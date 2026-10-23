"use strict";
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {spawnSync} = require("node:child_process");
const {test} = require("node:test");

const ROOT = path.join(__dirname, "..", "..");
const PYTHON = process.env.PYTHON || "python3";

function lockEntry() {
  const lock = JSON.parse(fs.readFileSync(path.join(ROOT, "vendor.lock.json"), "utf8"));
  const entry = lock.files.find((item) => item.destination === "vendor/py_launch.cjs");
  assert.ok(entry, "vendor.lock.json must list vendor/py_launch.cjs");
  return entry;
}

function writeFakePython(dir) {
  const marker = path.join(dir, "marker.txt");
  const fake = path.join(dir, "fake-python");
  fs.writeFileSync(
    fake,
    `#!/usr/bin/env python3
import sys
marker = ${JSON.stringify(marker)}
if "-c" in sys.argv:
    i = sys.argv.index("-c")
    if i + 1 < len(sys.argv) and "version_info" in sys.argv[i + 1]:
        print("3.12")
        raise SystemExit(0)
open(marker, "w", encoding="utf-8").write("ran")
raise SystemExit(0)
`,
    {encoding: "utf8", mode: 0o755},
  );
  return {fake, marker};
}

test("vendored py_launch.cjs matches vendor.lock.json", () => {
  const entry = lockEntry();
  const data = fs.readFileSync(path.join(ROOT, "vendor/py_launch.cjs"));
  assert.equal(crypto.createHash("sha256").update(data).digest("hex"), entry.sha256);
  assert.equal(
    crypto.createHash("sha1").update(Buffer.concat([Buffer.from(`blob ${data.length}\0`), data])).digest("hex"),
    entry.blob_sha,
  );
  assert.equal(entry.commit, "2ea31034ca3caa60ed769806baf750d75e296552");
});

test("cli_args.cjs does not spawn node", () => {
  const src = fs.readFileSync(path.join(ROOT, "cli_args.cjs"), "utf8");
  assert.match(src, /require\("\.\/vendor\/py_launch\.cjs"\)/);
  assert.doesNotMatch(src, /\bnode\b.*spawn/i);
  assert.doesNotMatch(src, /spawn(?:Sync)?\([^)]*shell\s*:\s*true/);
});

test("runCommand roundtrip and child exit code", () => {
  const {runCommand} = require(path.join(ROOT, "cli_args.cjs"));
  const body = runCommand([PYTHON, "-S", "-c", "import sys; sys.exit(4)"]);
  assert.equal(body.returncode, 4);
  assert.equal(body.executed, true);
  assert.ok(typeof body.stdout_b64 === "string");
});

test("runCommand preserves Japanese output", () => {
  const {runCommand} = require(path.join(ROOT, "cli_args.cjs"));
  const body = runCommand([PYTHON, "-S", "-c", "print('日本語')"]);
  assert.equal(body.stdout, "日本語\n");
  assert.equal(body.returncode, 0);
});

test("render text and json", () => {
  const {render} = require(path.join(ROOT, "cli_args.cjs"));
  const value = {title: "日本語", n: 1};
  assert.equal(render(value, "text"), "{'title': '日本語', 'n': 1}\n");
  assert.deepEqual(JSON.parse(render(value, "json")), value);
});

test("CLI_ARGS_PYTHON is used when set explicitly", (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cli-args-fake-py-"));
  t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
  const {fake, marker} = writeFakePython(dir);
  const {runCommand} = require(path.join(ROOT, "cli_args.cjs"));
  try {
    runCommand([PYTHON, "-S", "-c", "print(1)"], {python: fake});
  } catch {
    // interpreter ran even if the script failed afterward
  }
  assert.equal(fs.readFileSync(marker, "utf8"), "ran");
});

test("invalid run request maps Python exit 2 to CliArgsRequestError", () => {
  const {runCommand, CliArgsRequestError} = require(path.join(ROOT, "cli_args.cjs"));
  assert.throws(
    () => runCommand([PYTHON], {dry_run: "yes"}),
    (err) => err instanceof CliArgsRequestError && /dry_run/.test(err.message),
  );
});

test("missing interpreter uses cli_args Python process failed prefix", () => {
  const {runCommand} = require(path.join(ROOT, "cli_args.cjs"));
  assert.throws(
    () => runCommand([PYTHON, "-S", "-c", "print(1)"], {python: "/missing/cli-args-python"}),
    (err) => err.message.startsWith("cli_args Python process failed: ") && /ENOENT|spawnSync/.test(err.message),
  );
});

test("cli_args.cjs CLI exits 2 when CLI_ARGS_PYTHON is unusable", () => {
  const result = spawnSync(process.execPath, [path.join(ROOT, "cli_args.cjs"), "run"], {
    env: {...process.env, CLI_ARGS_PYTHON: "/missing/cli-args-python"},
    input: JSON.stringify({argv: [PYTHON, "-S", "-c", "print(1)"]}),
  });
  assert.equal(result.status, 2);
});

test("runCommand applies default max_output and fits derived maxBuffer", () => {
  const {
    runCommand,
    CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES,
    cliRunResponseMaxBufferBytes,
  } = require(path.join(ROOT, "cli_args.cjs"));
  const limit = CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES;
  const code = `import sys; sys.stdout.buffer.write(b"z" * ${limit})`;
  const body = runCommand([PYTHON, "-S", "-c", code]);
  assert.equal(body.output_limited, undefined);
  assert.equal(Buffer.from(body.stdout_b64, "base64").length, limit);
  assert.ok(cliRunResponseMaxBufferBytes(limit) > limit);
});

test("runCommand max_output boundary under and over", () => {
  const {runCommand} = require(path.join(ROOT, "cli_args.cjs"));
  const limit = 48 * 1024;
  const under = limit - 1;
  const ok = runCommand(
    [PYTHON, "-S", "-c", `import sys; sys.stdout.buffer.write(b"x" * ${under})`],
    {max_output: limit},
  );
  assert.notEqual(ok.output_limited, true);
  assert.equal(Buffer.from(ok.stdout_b64, "base64").length, under);

  const limited = runCommand(
    [PYTHON, "-S", "-c", `import sys; sys.stdout.buffer.write(b"x" * ${limit + 1})`],
    {max_output: limit},
  );
  assert.equal(limited.output_limited, true);
  assert.equal(limited.returncode, null);
  assert.equal(Buffer.from(limited.stdout_b64, "base64").length, limit);
});

test("runCommand rejects max_output above CLI_RUN_MAX_OUTPUT_BYTES", () => {
  const {runCommand, CliArgsRequestError, CLI_RUN_MAX_OUTPUT_BYTES} = require(path.join(
    ROOT,
    "cli_args.cjs",
  ));
  assert.throws(
    () => runCommand([PYTHON, "-S", "-c", "print(1)"], {max_output: CLI_RUN_MAX_OUTPUT_BYTES + 1}),
    (err) => err instanceof CliArgsRequestError && /max_output exceeds limit/.test(err.message),
  );
});

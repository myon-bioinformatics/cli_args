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

function normalizeNewlines(text) {
  return String(text).replace(/\r\n/g, "\n");
}

function lockEntry() {
  const lock = JSON.parse(fs.readFileSync(path.join(ROOT, "vendor.lock.json"), "utf8"));
  const entry = lock.files.find((item) => item.destination === "vendor/py_launch.cjs");
  assert.ok(entry, "vendor.lock.json must list vendor/py_launch.cjs");
  return entry;
}

function resolvedPythonExecutable() {
  const result = spawnSync(PYTHON, ["-c", "import sys; print(sys.executable)"], {encoding: "utf8"});
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
}

function withCliArgsPython(value, fn) {
  const prior = process.env.CLI_ARGS_PYTHON;
  if (value === undefined) {
    delete process.env.CLI_ARGS_PYTHON;
  } else {
    process.env.CLI_ARGS_PYTHON = value;
  }
  try {
    fn();
  } finally {
    if (prior === undefined) {
      delete process.env.CLI_ARGS_PYTHON;
    } else {
      process.env.CLI_ARGS_PYTHON = prior;
    }
  }
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
  const body = runCommand([PYTHON, "-S", "-c", "print('日本語')"], {
    env: {PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8"},
  });
  assert.equal(normalizeNewlines(body.stdout), "日本語\n");
  assert.equal(body.returncode, 0);
});

test("runCommand does not inject PYTHONUTF8 into wrapped env", () => {
  const {runCommand} = require(path.join(ROOT, "cli_args.cjs"));
  const code = [
    "import os, json",
    "print(json.dumps({",
    "  'PYTHONUTF8': os.environ.get('PYTHONUTF8'),",
    "  'PYTHONIOENCODING': os.environ.get('PYTHONIOENCODING'),",
    "}))",
  ].join("\n");
  const body = runCommand([PYTHON, "-S", "-c", code], {
    env: {PYTHONUTF8: "0", PYTHONIOENCODING: "cp1252"},
  });
  const seen = JSON.parse(normalizeNewlines(body.stdout));
  assert.equal(seen.PYTHONUTF8, "0");
  assert.equal(seen.PYTHONIOENCODING, "cp1252");
});

test("render text and json", () => {
  const {render} = require(path.join(ROOT, "cli_args.cjs"));
  const value = {title: "日本語", n: 1};
  assert.equal(render(value, "text"), "{'title': '日本語', 'n': 1}\n");
  assert.deepEqual(JSON.parse(render(value, "json")), value);
});

test("CLI_ARGS_PYTHON env is honored without silent fallback", () => {
  const {runCommand} = require(path.join(ROOT, "cli_args.cjs"));
  const resolved = resolvedPythonExecutable();
  const missing = path.join(os.tmpdir(), `cli-args-missing-python-${process.pid}`);
  withCliArgsPython(missing, () => {
    assert.throws(
      () => runCommand([PYTHON, "-S", "-c", "print(1)"]),
      (err) => err.message.startsWith("cli_args Python process failed: "),
    );
  });
  withCliArgsPython(resolved, () => {
    const body = runCommand([PYTHON, "-S", "-c", "print(9)"]);
    assert.equal(body.returncode, 0);
    assert.equal(normalizeNewlines(body.stdout), "9\n");
  });
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

test("runCommand default max_output is 4 MiB with output_limited false", () => {
  const {runCommand, CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES, cliHostMaxBufferBytes, CLI_RUN_RESPONSE_MAX_BYTES} =
    require(path.join(ROOT, "cli_args.cjs"));
  const limit = CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES;
  const code = `import sys; sys.stdout.buffer.write(b"z" * ${limit})`;
  const body = runCommand([PYTHON, "-S", "-c", code]);
  assert.equal(body.output_limited, false);
  assert.equal(Buffer.from(body.stdout_b64, "base64").length, limit);
  assert.equal(cliHostMaxBufferBytes(CLI_RUN_RESPONSE_MAX_BYTES), CLI_RUN_RESPONSE_MAX_BYTES + 512);
});

test("runCommand max_output exactly at limit", () => {
  const {runCommand} = require(path.join(ROOT, "cli_args.cjs"));
  const limit = 512;
  const code = `import sys; sys.stdout.buffer.write(bytes(i % 256 for i in range(${limit})))`;
  const body = runCommand([PYTHON, "-S", "-c", code], {max_output: limit});
  const expected = Buffer.from(Array.from({length: limit}, (_, i) => i % 256));
  assert.equal(body.output_limited, false);
  assert.equal(Buffer.from(body.stdout_b64, "base64").compare(expected), 0);
});

test("runCommand max_output boundary under and over", () => {
  const {runCommand} = require(path.join(ROOT, "cli_args.cjs"));
  const limit = 48 * 1024;
  const under = limit - 1;
  const ok = runCommand(
    [PYTHON, "-S", "-c", `import sys; sys.stdout.buffer.write(b"x" * ${under})`],
    {max_output: limit},
  );
  assert.equal(ok.output_limited, false);
  assert.equal(Buffer.from(ok.stdout_b64, "base64").length, under);

  const limited = runCommand(
    [PYTHON, "-S", "-c", `import sys; sys.stdout.buffer.write(b"x" * ${limit + 1})`],
    {max_output: limit},
  );
  assert.equal(limited.output_limited, true);
  assert.equal(limited.returncode, null);
  assert.equal(Buffer.from(limited.stdout_b64, "base64").length, limit);
});

test("runCommand binary control bytes under response cap", () => {
  const {runCommand} = require(path.join(ROOT, "cli_args.cjs"));
  const limit = 96 * 1024;
  const code = `import sys; sys.stdout.buffer.write(bytes(i % 256 for i in range(${limit})))`;
  const body = runCommand([PYTHON, "-S", "-c", code], {max_output: limit});
  assert.equal(body.output_limited, false);
  assert.equal(Buffer.from(body.stdout_b64, "base64").length, limit);
});

test("runCommand long argv with small max_output", () => {
  const {runCommand} = require(path.join(ROOT, "cli_args.cjs"));
  const longArg = "y".repeat(20000);
  const body = runCommand(
    [PYTHON, "-S", "-c", "import sys; sys.stdout.buffer.write(b'b' * 900)", longArg],
    {max_output: 1000},
  );
  assert.equal(body.argv.at(-1), longArg);
  assert.equal(body.output_limited, false);
  assert.equal(Buffer.from(body.stdout_b64, "base64").length, 900);
});

test("render deep nesting stays within response cap", () => {
  const {render} = require(path.join(ROOT, "cli_args.cjs"));
  let value = Array.from({length: 3000}, (_, i) => i);
  for (let depth = 0; depth < 200; depth += 1) {
    value = [value];
  }
  const out = render(value, "json");
  assert.ok(out.length > 500_000);
  assert.deepEqual(JSON.parse(out), value);
});

test("runCommand rejects stdin larger than CLI_STDIN_MAX_BYTES", () => {
  const {runCommand, CliArgsRequestError, CLI_STDIN_MAX_BYTES, STDIN_EXCEEDS_MSG} = require(path.join(
    ROOT,
    "cli_args.cjs",
  ));
  const padding = "a".repeat(CLI_STDIN_MAX_BYTES);
  assert.throws(
    () => runCommand([PYTHON, "-S", "-c", "print(1)", padding]),
    (err) => err instanceof CliArgsRequestError && err.message === STDIN_EXCEEDS_MSG,
  );
});

test("render rejects stdin larger than CLI_STDIN_MAX_BYTES", () => {
  const {render, CliArgsRequestError, STDIN_EXCEEDS_MSG} = require(path.join(ROOT, "cli_args.cjs"));
  const huge = {data: "x".repeat(4 * 1024 * 1024 + 64)};
  assert.throws(
    () => render(huge, "json"),
    (err) => err instanceof CliArgsRequestError && err.message === STDIN_EXCEEDS_MSG,
  );
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

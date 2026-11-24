"use strict";
// Node-side tests for cli_args.py through the shared vendor/py_launch.cjs (no cli_args.cjs wrapper).
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {spawnSync} = require("node:child_process");
const {test} = require("node:test");

const ROOT = path.join(__dirname, "..");
const LAUNCHER = path.join(ROOT, "vendor", "py_launch.cjs");
const SCRIPT = path.join(ROOT, "cli_args.py");
const {
  run,
  call,
  assertNodeVersion,
  hostMaxBufferBytes,
  HOST_RESPONSE_MARGIN_BYTES,
  MIN_NODE,
} = require(LAUNCHER);

const PY_LAUNCH = {envVar: "CLI_ARGS_PYTHON", noSite: true};
const PYTHON =
  process.env.CLI_ARGS_PYTHON || process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");

const CLI_STDIN_MAX_BYTES = 4 * 1024 * 1024;
const CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES = 4 * 1024 * 1024;
const CLI_RUN_RESPONSE_MAX_BYTES = 96 * 1024 * 1024;
const CLI_RENDER_RESPONSE_MAX_BYTES = 96 * 1024 * 1024;

function normalizeNewlines(text) {
  return String(text).replace(/\r\n/g, "\n");
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

function runCliArgs(request, opts = {}) {
  const input = `${JSON.stringify(request)}\n`;
  const result = run(SCRIPT, ["run"], {
    ...PY_LAUNCH,
    python: opts.python,
    input,
    maxInputBytes: CLI_STDIN_MAX_BYTES,
    responseMaxBytes: CLI_RUN_RESPONSE_MAX_BYTES,
  });
  return JSON.parse(String(result.stdout));
}

function renderCliArgs(value, format = "text", opts = {}) {
  const input = `${JSON.stringify(value)}\n`;
  const result = run(
    SCRIPT,
    ["render", "--format", format, "--response-max-bytes", String(CLI_RENDER_RESPONSE_MAX_BYTES)],
    {
      ...PY_LAUNCH,
      python: opts.python,
      input,
      maxInputBytes: CLI_STDIN_MAX_BYTES,
      responseMaxBytes: CLI_RENDER_RESPONSE_MAX_BYTES,
    },
  );
  return String(result.stdout);
}

test("vendored py_launch.cjs matches vendor.lock.json", () => {
  const lock = JSON.parse(fs.readFileSync(path.join(ROOT, "vendor.lock.json"), "utf8"));
  const entry = lock.files.find((item) => item.destination === "vendor/py_launch.cjs");
  assert.ok(entry, "vendor.lock.json must list vendor/py_launch.cjs");
  const digest = crypto.createHash("sha256").update(fs.readFileSync(LAUNCHER)).digest("hex");
  assert.equal(digest, entry.sha256);
});

test("no per-tool Node wrapper is left at the repository root", () => {
  const wrappers = fs.readdirSync(ROOT).filter((name) => /\.(cjs|d\.cts)$/.test(name));
  assert.deepEqual(wrappers, []);
});

test("py_launch CLI --help runs on this Node and names run and render", () => {
  const result = spawnSync(
    process.execPath,
    [LAUNCHER, "--env-var", "CLI_ARGS_PYTHON", "--", SCRIPT, "--help"],
    {encoding: "utf8"},
  );
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /\brun\b/);
  assert.match(result.stdout, /\brender\b/);
  assert.match(result.stdout, /exit 2/);
});

test("py_launch CLI exits 2 when CLI_ARGS_PYTHON is unusable", () => {
  const result = spawnSync(
    process.execPath,
    [LAUNCHER, "--env-var", "CLI_ARGS_PYTHON", "--", SCRIPT, "run"],
    {
      env: {...process.env, CLI_ARGS_PYTHON: "/missing/cli-args-python"},
      input: JSON.stringify({argv: [PYTHON, "-S", "-c", "print(1)"]}),
      encoding: "utf8",
    },
  );
  assert.equal(result.status, 2);
});

test("run roundtrip and child exit code", () => {
  const body = runCliArgs({
    argv: [PYTHON, "-S", "-c", "import sys; sys.exit(4)"],
    max_output: CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES,
    response_max_bytes: CLI_RUN_RESPONSE_MAX_BYTES,
  });
  assert.equal(body.returncode, 4);
  assert.equal(body.executed, true);
  assert.ok(typeof body.stdout_b64 === "string");
});

test("run preserves Japanese output", () => {
  const body = runCliArgs({
    argv: [PYTHON, "-S", "-c", "print('日本語')"],
    env: {PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8"},
    max_output: CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES,
    response_max_bytes: CLI_RUN_RESPONSE_MAX_BYTES,
  });
  assert.equal(normalizeNewlines(body.stdout), "日本語\n");
  assert.equal(body.returncode, 0);
});

test("run does not inject PYTHONUTF8 into wrapped env", () => {
  const code = [
    "import os, json",
    "print(json.dumps({",
    "  'PYTHONUTF8': os.environ.get('PYTHONUTF8'),",
    "  'PYTHONIOENCODING': os.environ.get('PYTHONIOENCODING'),",
    "}))",
  ].join("\n");
  const body = runCliArgs({
    argv: [PYTHON, "-S", "-c", code],
    env: {PYTHONUTF8: "0", PYTHONIOENCODING: "cp1252"},
    max_output: CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES,
    response_max_bytes: CLI_RUN_RESPONSE_MAX_BYTES,
  });
  const seen = JSON.parse(normalizeNewlines(body.stdout));
  assert.equal(seen.PYTHONUTF8, "0");
  assert.equal(seen.PYTHONIOENCODING, "cp1252");
});

test("render text and json", () => {
  const value = {title: "日本語", n: 1};
  assert.equal(renderCliArgs(value, "text"), "{'title': '日本語', 'n': 1}\n");
  assert.deepEqual(JSON.parse(renderCliArgs(value, "json")), value);
});

test("call invokes cli_args.py functions by name and preserves non-ASCII text", () => {
  const value = {title: "日本語 & é 🌱", n: 2};
  const rendered = call(SCRIPT, "render_output", {args: [value], kwargs: {format: "json"}}, PY_LAUNCH);
  assert.deepEqual(JSON.parse(rendered), value);
  const trimmed = call(SCRIPT, "trim_output", ["a\nb\nc\nd\ne", 1, 1], PY_LAUNCH);
  assert.equal(trimmed, "a\n... 3 line(s) omitted ...\ne");
});

test("py_launch CLI --call runs cli_args.py functions by name", () => {
  const result = spawnSync(
    process.execPath,
    [LAUNCHER, "--env-var", "CLI_ARGS_PYTHON", "--call", "trim_output", "--", SCRIPT, "a\nb\nc\nd", "1", "1"],
    {encoding: "utf8"},
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout), "a\n... 2 line(s) omitted ...\nd");
});

test("CLI_ARGS_PYTHON env is honored without silent fallback", () => {
  const resolved = resolvedPythonExecutable();
  const missing = path.join(os.tmpdir(), `cli-args-missing-python-${process.pid}`);
  withCliArgsPython(missing, () => {
    assert.throws(
      () => runCliArgs({argv: [PYTHON, "-S", "-c", "print(1)"]}),
      (err) => err.code === "ENOINTERPRETER" && /CLI_ARGS_PYTHON/.test(err.message),
    );
  });
  withCliArgsPython(resolved, () => {
    const body = runCliArgs({argv: [PYTHON, "-S", "-c", "print(9)"]});
    assert.equal(body.returncode, 0);
    assert.equal(normalizeNewlines(body.stdout), "9\n");
  });
});

test("invalid run request exits 2 from cli_args.py", () => {
  assert.throws(
    () => runCliArgs({argv: [PYTHON], dry_run: "yes"}),
    (err) => err.status === 2 && /dry_run/.test(String(err.stderr)),
  );
});

test("missing explicit python fails without fallback", () => {
  assert.throws(
    () => runCliArgs({argv: [PYTHON, "-S", "-c", "print(1)"]}, {python: "/missing/cli-args-python"}),
    (err) => err.code === "ENOINTERPRETER" && /ENOENT|spawnSync/.test(err.message),
  );
});

test("run default max_output is 4 MiB with output_limited false", () => {
  const limit = CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES;
  const code = `import sys; sys.stdout.buffer.write(b"z" * ${limit})`;
  const body = runCliArgs({
    argv: [PYTHON, "-S", "-c", code],
    max_output: limit,
    response_max_bytes: CLI_RUN_RESPONSE_MAX_BYTES,
  });
  assert.equal(body.output_limited, false);
  assert.equal(Buffer.from(body.stdout_b64, "base64").length, limit);
  assert.equal(hostMaxBufferBytes(CLI_RUN_RESPONSE_MAX_BYTES), CLI_RUN_RESPONSE_MAX_BYTES + HOST_RESPONSE_MARGIN_BYTES);
});

test("run max_output exactly at limit", () => {
  const limit = 512;
  const code = `import sys; sys.stdout.buffer.write(bytes(i % 256 for i in range(${limit})))`;
  const body = runCliArgs({
    argv: [PYTHON, "-S", "-c", code],
    max_output: limit,
    response_max_bytes: CLI_RUN_RESPONSE_MAX_BYTES,
  });
  const expected = Buffer.from(Array.from({length: limit}, (_, i) => i % 256));
  assert.equal(body.output_limited, false);
  assert.equal(Buffer.from(body.stdout_b64, "base64").compare(expected), 0);
});

test("run max_output boundary under and over", () => {
  const limit = 48 * 1024;
  const under = limit - 1;
  const ok = runCliArgs({
    argv: [PYTHON, "-S", "-c", `import sys; sys.stdout.buffer.write(b"x" * ${under})`],
    max_output: limit,
    response_max_bytes: CLI_RUN_RESPONSE_MAX_BYTES,
  });
  assert.equal(ok.output_limited, false);
  assert.equal(Buffer.from(ok.stdout_b64, "base64").length, under);

  const limited = runCliArgs({
    argv: [PYTHON, "-S", "-c", `import sys; sys.stdout.buffer.write(b"x" * ${limit + 1})`],
    max_output: limit,
    response_max_bytes: CLI_RUN_RESPONSE_MAX_BYTES,
  });
  assert.equal(limited.output_limited, true);
  assert.equal(limited.returncode, null);
  assert.equal(Buffer.from(limited.stdout_b64, "base64").length, limit);
});

test("run binary control bytes under response cap", () => {
  const limit = 96 * 1024;
  const code = `import sys; sys.stdout.buffer.write(bytes(i % 256 for i in range(${limit})))`;
  const body = runCliArgs({
    argv: [PYTHON, "-S", "-c", code],
    max_output: limit,
    response_max_bytes: CLI_RUN_RESPONSE_MAX_BYTES,
  });
  assert.equal(body.output_limited, false);
  assert.equal(Buffer.from(body.stdout_b64, "base64").length, limit);
});

test("run long argv with small max_output", () => {
  const longArg = "y".repeat(20000);
  const body = runCliArgs({
    argv: [PYTHON, "-S", "-c", "import sys; sys.stdout.buffer.write(b'b' * 900)", longArg],
    max_output: 1000,
    response_max_bytes: CLI_RUN_RESPONSE_MAX_BYTES,
  });
  assert.equal(body.argv.at(-1), longArg);
  assert.equal(body.output_limited, false);
  assert.equal(Buffer.from(body.stdout_b64, "base64").length, 900);
});

test("render deep nesting stays within response cap", () => {
  let value = Array.from({length: 3000}, (_, i) => i);
  for (let depth = 0; depth < 200; depth += 1) {
    value = [value];
  }
  const out = renderCliArgs(value, "json");
  assert.ok(out.length > 500_000);
  assert.deepEqual(JSON.parse(out), value);
});

test("run rejects stdin larger than CLI_STDIN_MAX_BYTES via py_launch maxInputBytes", () => {
  const padding = "a".repeat(CLI_STDIN_MAX_BYTES);
  assert.throws(
    () => runCliArgs({argv: [PYTHON, "-S", "-c", "print(1)", padding]}),
    (err) => err.code === "EINPUTTOOLARGE",
  );
});

test("render rejects stdin larger than CLI_STDIN_MAX_BYTES via py_launch maxInputBytes", () => {
  const huge = {data: "x".repeat(4 * 1024 * 1024 + 64)};
  assert.throws(
    () => renderCliArgs(huge, "json"),
    (err) => err.code === "EINPUTTOOLARGE",
  );
});

test("assertNodeVersion rejects Node 22/24 and accepts Node 26+", () => {
  assert.equal(MIN_NODE[0], 26);
  assert.throws(() => assertNodeVersion("22.14.0"), (e) => e.code === "ENODEVERSION" && /Node 26\+/.test(e.message));
  assert.throws(() => assertNodeVersion("24.0.0"), (e) => e.code === "ENODEVERSION" && /Node 26\+/.test(e.message));
  assert.doesNotThrow(() => assertNodeVersion("26.0.0"));
  const major = Number.parseInt(String(process.versions.node).split(".")[0], 10);
  assert.ok(major >= MIN_NODE[0], process.versions.node);
});

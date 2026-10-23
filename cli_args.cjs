"use strict";
/** Thin Node API (Node 24+): Python owns run_command/render_output via cli_args.py run/render. */
const path = require("node:path");
const {run, main} = require("./vendor/py_launch.cjs");

const PY_SCRIPT = path.join(__dirname, "cli_args.py");
const PY_LAUNCH = {envVar: "CLI_ARGS_PYTHON", noSite: true};
const ERR_PREFIX = "cli_args Python process failed: ";

/** Keep in sync with cli_args.CLI_STDIN_MAX_BYTES */
const CLI_STDIN_MAX_BYTES = 4 * 1024 * 1024;
/** Keep in sync with cli_args.CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES */
const CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES = 4 * 1024 * 1024;
/** Keep in sync with cli_args.CLI_RUN_MAX_OUTPUT_BYTES */
const CLI_RUN_MAX_OUTPUT_BYTES = 8 * 1024 * 1024;
/** Keep in sync with cli_args.CLI_RUN_RESPONSE_MAX_BYTES */
const CLI_RUN_RESPONSE_MAX_BYTES = 96 * 1024 * 1024;
/** Keep in sync with cli_args.CLI_RENDER_RESPONSE_MAX_BYTES */
const CLI_RENDER_RESPONSE_MAX_BYTES = 96 * 1024 * 1024;
/** Keep in sync with cli_args.CLI_HOST_RESPONSE_MARGIN_BYTES */
const CLI_HOST_RESPONSE_MARGIN_BYTES = 512;
/** Keep in sync with cli_args._NODE_MIN_MAJOR */
const NODE_MIN_MAJOR = 24;

class CliArgsRequestError extends Error {
  constructor(message) {
    super(message);
    this.name = "CliArgsRequestError";
  }
}

/** @param {number} responseMaxBytes */
function cliHostMaxBufferBytes(responseMaxBytes) {
  if (!Number.isInteger(responseMaxBytes) || responseMaxBytes < 0) {
    throw new CliArgsRequestError("response_max_bytes must be a nonnegative integer");
  }
  return responseMaxBytes + CLI_HOST_RESPONSE_MARGIN_BYTES;
}

const STDIN_EXCEEDS_MSG = "stdin exceeds size limit";

/** Reject Node hosts older than NODE_MIN_MAJOR. Pass a version string in tests. */
function assertNodeFloor(version = process.versions.node) {
  const match = /(?:^|\s)v?(\d+)/i.exec(String(version).trim());
  const major = match ? Number.parseInt(match[1], 10) : NaN;
  if (!Number.isInteger(major) || major < NODE_MIN_MAJOR) {
    throw new Error(`cli_args.cjs requires Node ${NODE_MIN_MAJOR}+ (found ${version})`);
  }
}

/**
 * @param {string} input
 */
function assertStdinWithinLimit(input) {
  if (Buffer.byteLength(input, "utf8") > CLI_STDIN_MAX_BYTES) {
    throw new CliArgsRequestError(STDIN_EXCEEDS_MSG);
  }
}

/**
 * @param {object} opts
 */
function resolveRunMaxOutput(opts) {
  const value = opts.max_output !== undefined ? opts.max_output : CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES;
  if (!Number.isInteger(value) || value < 0) {
    throw new CliArgsRequestError("max_output must be a nonnegative integer");
  }
  if (value > CLI_RUN_MAX_OUTPUT_BYTES) {
    throw new CliArgsRequestError(
      `max_output exceeds limit (${CLI_RUN_MAX_OUTPUT_BYTES} bytes); see CLI_RUN_MAX_OUTPUT_BYTES in cli_args.py`,
    );
  }
  return value;
}

/**
 * @param {unknown} err
 * @param {string} failureFallback
 * @param {{stdinPrechecked?: boolean}} [context]
 */
function mapLaunchError(err, failureFallback, context = {}) {
  const msg = String(err && err.message ? err.message : err);
  const code = err && err.code ? String(err.code) : "";
  const causeCode = err && err.cause && err.cause.code ? String(err.cause.code) : "";
  if (code === "EPIPE" || causeCode === "EPIPE" || /\bEPIPE\b/.test(msg)) {
    if (context.stdinPrechecked) {
      throw new Error(ERR_PREFIX + "Python stdin pipe closed unexpectedly");
    }
    throw new CliArgsRequestError(STDIN_EXCEEDS_MSG);
  }
  if (code === "ENOBUFS" || /\bENOBUFS\b/.test(msg)) {
    throw new Error(
      ERR_PREFIX +
        "internal error: Python stdout exceeded the Node capture buffer despite response_max_bytes " +
        "(report as a cli_args bug)",
    );
  }
  if (msg.startsWith("py_launch: Python process failed: ")) {
    throw new Error(ERR_PREFIX + msg.slice("py_launch: Python process failed: ".length));
  }
  const spawn = msg.match(/^py_launch: ([^:]+): (spawnSync .+)$/);
  if (spawn) throw new Error(ERR_PREFIX + spawn[2]);
  if (msg.startsWith("py_launch: ")) {
    throw new Error(ERR_PREFIX + msg.slice("py_launch: ".length));
  }
  if (err && Object.hasOwn(err, "status")) {
    if (err.status === 2) {
      const detail = (err.stderr && err.stderr.toString("utf8").trim()) || failureFallback;
      throw new CliArgsRequestError(detail);
    }
    if (err.status !== 0) {
      const detail = (err.stderr && err.stderr.toString("utf8").trim()) || failureFallback;
      if (/response exceeds response_max_bytes/.test(detail)) {
        throw new Error(ERR_PREFIX + detail);
      }
      throw new Error(detail);
    }
  }
  throw err;
}

/**
 * @param {string[]} argv
 * @param {object} [opts]
 */
function runCommand(argv, opts = {}) {
  assertNodeFloor();
  const maxOutput = resolveRunMaxOutput(opts);
  const request = {
    argv,
    max_output: maxOutput,
    response_max_bytes: CLI_RUN_RESPONSE_MAX_BYTES,
  };
  if (opts.cwd !== undefined) request.cwd = opts.cwd;
  if (opts.timeout !== undefined) request.timeout = opts.timeout;
  if (opts.env !== undefined) request.env = opts.env;
  if (opts.input !== undefined) request.input = opts.input;
  if (opts.dry_run !== undefined) request.dry_run = opts.dry_run;
  const input = `${JSON.stringify(request)}\n`;
  assertStdinWithinLimit(input);
  try {
    const result = run(PY_SCRIPT, ["run"], {
      ...PY_LAUNCH,
      python: opts.python,
      input,
      maxBuffer: cliHostMaxBufferBytes(CLI_RUN_RESPONSE_MAX_BYTES),
    });
    return JSON.parse(String(result.stdout));
  } catch (err) {
    mapLaunchError(err, "cli_args run failed", {stdinPrechecked: true});
  }
}

/**
 * @param {unknown} value
 * @param {"text"|"json"} [format]
 * @param {object} [opts]
 */
function render(value, format = "text", opts = {}) {
  assertNodeFloor();
  if (format !== "text" && format !== "json") {
    throw new Error("format must be text or json");
  }
  const input = `${JSON.stringify(value)}\n`;
  assertStdinWithinLimit(input);
  try {
    const result = run(
      PY_SCRIPT,
      ["render", "--format", format, "--response-max-bytes", String(CLI_RENDER_RESPONSE_MAX_BYTES)],
      {
        ...PY_LAUNCH,
        python: opts.python,
        input,
        maxBuffer: cliHostMaxBufferBytes(CLI_RENDER_RESPONSE_MAX_BYTES),
      },
    );
    return String(result.stdout);
  } catch (err) {
    mapLaunchError(err, "cli_args render failed", {stdinPrechecked: true});
  }
}

if (require.main === module) {
  try {
    assertNodeFloor();
  } catch (err) {
    process.stderr.write(`${err && err.message ? err.message : err}\n`);
    process.exit(1);
  }
  main(PY_SCRIPT, PY_LAUNCH);
}

module.exports = {
  runCommand,
  render,
  assertNodeFloor,
  NODE_MIN_MAJOR,
  CliArgsRequestError,
  CLI_STDIN_MAX_BYTES,
  CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES,
  CLI_RUN_MAX_OUTPUT_BYTES,
  CLI_RUN_RESPONSE_MAX_BYTES,
  CLI_RENDER_RESPONSE_MAX_BYTES,
  CLI_HOST_RESPONSE_MARGIN_BYTES,
  cliHostMaxBufferBytes,
  assertStdinWithinLimit,
  STDIN_EXCEEDS_MSG,
};

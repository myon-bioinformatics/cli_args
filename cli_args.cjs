"use strict";
/** Thin Node API: Python owns run_command/render_output via cli_args.py run/render. */
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

class CliArgsRequestError extends Error {
  constructor(message) {
    super(message);
    this.name = "CliArgsRequestError";
  }
}

/** @param {number} maxOutputBytes */
function cliRunResponseMaxBufferBytes(maxOutputBytes) {
  if (!Number.isInteger(maxOutputBytes) || maxOutputBytes < 0) {
    throw new CliArgsRequestError("max_output must be a nonnegative integer");
  }
  return Math.floor(maxOutputBytes * 14 / 3) + 8192;
}

function cliRenderResponseMaxBufferBytes() {
  return CLI_STDIN_MAX_BYTES * 4 + 8192;
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
 */
function mapLaunchError(err, failureFallback) {
  const msg = String(err && err.message ? err.message : err);
  const code = err && err.code ? String(err.code) : "";
  if (code === "ENOBUFS" || /\bENOBUFS\b/.test(msg)) {
    throw new Error(
      ERR_PREFIX +
        "Python response exceeded the Node capture buffer; reduce child output, set a lower max_output, " +
        "or call cli_args.py directly without the Node wrapper",
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
      throw new Error((err.stderr && err.stderr.toString("utf8").trim()) || failureFallback);
    }
  }
  throw err;
}

/**
 * @param {string[]} argv
 * @param {object} [opts]
 */
function runCommand(argv, opts = {}) {
  const maxOutput = resolveRunMaxOutput(opts);
  const request = {argv, max_output: maxOutput};
  if (opts.cwd !== undefined) request.cwd = opts.cwd;
  if (opts.timeout !== undefined) request.timeout = opts.timeout;
  if (opts.env !== undefined) request.env = opts.env;
  if (opts.input !== undefined) request.input = opts.input;
  if (opts.dry_run !== undefined) request.dry_run = opts.dry_run;
  const input = `${JSON.stringify(request)}\n`;
  try {
    const result = run(PY_SCRIPT, ["run"], {
      ...PY_LAUNCH,
      python: opts.python,
      input,
      maxBuffer: cliRunResponseMaxBufferBytes(maxOutput),
    });
    return JSON.parse(String(result.stdout));
  } catch (err) {
    mapLaunchError(err, "cli_args run failed");
  }
}

/**
 * @param {unknown} value
 * @param {"text"|"json"} [format]
 * @param {object} [opts]
 */
function render(value, format = "text", opts = {}) {
  if (format !== "text" && format !== "json") {
    throw new Error("format must be text or json");
  }
  const input = `${JSON.stringify(value)}\n`;
  try {
    const result = run(PY_SCRIPT, ["render", "--format", format], {
      ...PY_LAUNCH,
      python: opts.python,
      input,
      maxBuffer: cliRenderResponseMaxBufferBytes(),
    });
    return String(result.stdout);
  } catch (err) {
    mapLaunchError(err, "cli_args render failed");
  }
}

if (require.main === module) {
  main(PY_SCRIPT, PY_LAUNCH);
}

module.exports = {
  runCommand,
  render,
  CliArgsRequestError,
  CLI_STDIN_MAX_BYTES,
  CLI_RUN_DEFAULT_MAX_OUTPUT_BYTES,
  CLI_RUN_MAX_OUTPUT_BYTES,
  cliRunResponseMaxBufferBytes,
  cliRenderResponseMaxBufferBytes,
};

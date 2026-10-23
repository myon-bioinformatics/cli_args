"use strict";
/** Thin Node API: Python owns run_command/render_output via cli_args.py run/render. */
const path = require("node:path");
const {run, main} = require("./vendor/py_launch.cjs");

const PY_SCRIPT = path.join(__dirname, "cli_args.py");
const PY_LAUNCH = {envVar: "CLI_ARGS_PYTHON", noSite: true};
const ERR_PREFIX = "cli_args Python process failed: ";
const MAX_RUN_BUFFER = 16 * 1024 * 1024;

class CliArgsRequestError extends Error {
  constructor(message) {
    super(message);
    this.name = "CliArgsRequestError";
  }
}

/**
 * @param {unknown} err
 * @param {string} failureFallback
 */
function mapLaunchError(err, failureFallback) {
  const msg = String(err && err.message ? err.message : err);
  if (msg.startsWith("py_launch: Python process failed: ")) {
    throw Error(ERR_PREFIX + msg.slice("py_launch: Python process failed: ".length));
  }
  const spawn = msg.match(/^py_launch: ([^:]+): (spawnSync .+)$/);
  if (spawn) throw Error(ERR_PREFIX + spawn[2]);
  if (msg.startsWith("py_launch: ")) {
    throw Error(ERR_PREFIX + msg.slice("py_launch: ".length));
  }
  if (err && Object.hasOwn(err, "status")) {
    if (err.status === 2) {
      const detail = (err.stderr && err.stderr.toString("utf8").trim()) || failureFallback;
      throw new CliArgsRequestError(detail);
    }
    if (err.status !== 0) {
      throw Error((err.stderr && err.stderr.toString("utf8").trim()) || failureFallback);
    }
  }
  throw err;
}

/**
 * @param {string[]} argv
 * @param {object} [opts]
 */
function runCommand(argv, opts = {}) {
  const request = {argv};
  if (opts.cwd !== undefined) request.cwd = opts.cwd;
  if (opts.timeout !== undefined) request.timeout = opts.timeout;
  if (opts.env !== undefined) request.env = opts.env;
  if (opts.input !== undefined) request.input = opts.input;
  if (opts.max_output !== undefined) request.max_output = opts.max_output;
  if (opts.dry_run !== undefined) request.dry_run = opts.dry_run;
  const input = `${JSON.stringify(request)}\n`;
  try {
    const result = run(PY_SCRIPT, ["run"], {
      ...PY_LAUNCH,
      python: opts.python,
      input,
      maxBuffer: MAX_RUN_BUFFER,
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
    throw Error("format must be text or json");
  }
  const input = `${JSON.stringify(value)}\n`;
  try {
    const result = run(PY_SCRIPT, ["render", "--format", format], {
      ...PY_LAUNCH,
      python: opts.python,
      input,
      maxBuffer: MAX_RUN_BUFFER,
    });
    return String(result.stdout);
  } catch (err) {
    mapLaunchError(err, "cli_args render failed");
  }
}

if (require.main === module) {
  main(PY_SCRIPT, PY_LAUNCH);
}

module.exports = {runCommand, render, CliArgsRequestError};

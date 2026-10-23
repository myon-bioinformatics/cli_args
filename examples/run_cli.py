"""Run an external command. Wrapper options precede the mandatory -- boundary.

--format json writes one JSON result document; text writes the child stdout.
exit 124: timeout.
exit 125: captured output cap was hit.
exit 127: executable was not found.
exit 1: another launch or output failure.
any other status is the child exit code.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cli_args import (Command, add_execution_arguments, add_output_arguments,
                      build_env, make_parser, run_command, write_output)


def main(argv=None):
    parser = make_parser(
        description=__doc__,
        suggest_unknown=True,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_execution_arguments(parser)
    parser.add_argument("--max-output-bytes", type=int, metavar="N",
                        help="stop child if captured stdout+stderr exceeds N bytes")
    parser.add_argument("--no-overwrite", action="store_true",
                        help="refuse existing output file or symlink")
    stdin_group = parser.add_mutually_exclusive_group()
    stdin_group.add_argument("--stdin", help="string input to pass as stdin to the process")
    stdin_group.add_argument("--stdin-file", type=Path, help="path to file whose contents are passed as stdin")
    parser.add_argument("--env", action="append", metavar="KEY=VALUE",
                        help="environment variable setting for the process (can be repeated; values may be visible in process listings)")
    add_output_arguments(parser)
    tokens = list(sys.argv[1:] if argv is None else argv)
    if "--" not in tokens:
        # --help must work before the child boundary; flags after -- belong to the child.
        if "-h" in tokens or "--help" in tokens:
            parser.parse_args(tokens)
        parser.error("use -- before the executable and its arguments")
    boundary = tokens.index("--")
    args = parser.parse_args(tokens[:boundary])
    try:
        command = Command(tuple(tokens[boundary + 1:]))
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    if args.max_output_bytes is not None and args.max_output_bytes < 0:
        parser.error("--max-output-bytes must be nonnegative")
    stdin_data = None
    if args.stdin is not None:
        stdin_data = args.stdin
    elif args.stdin_file is not None:
        try:
            stdin_data = args.stdin_file.read_bytes()
        except OSError as exc:
            print("failed to read stdin file: " + str(exc), file=sys.stderr)
            return 1
    env_map = None
    if args.env is not None:
        try:
            env_map = build_env(args.env, inherit=True)
        except (TypeError, ValueError) as exc:
            parser.error(str(exc))
    try:
        result = run_command(command, cwd=args.cwd, timeout=args.timeout,
                             dry_run=args.dry_run, max_output_bytes=args.max_output_bytes,
                             stdin=stdin_data, env=env_map)
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 127 if isinstance(exc, FileNotFoundError) else 1
    try:
        write_output(result, format=args.format, output=args.output,
                     overwrite=not args.no_overwrite)
    except OSError as exc:
        print("failed to write output: " + str(exc), file=sys.stderr)
        return 1
    if args.format == "text" and result.stderr:
        sys.stderr.write(result.stderr)
    if result.output_limited:
        print("command output limit exceeded", file=sys.stderr)
        return 125
    if result.timed_out:
        print("command timed out", file=sys.stderr)
        return 124
    code = result.returncode or 0
    return 128 - code if code < 0 else code


if __name__ == "__main__":
    raise SystemExit(main())

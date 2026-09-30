"""Run an external command. Wrapper options precede the mandatory -- boundary."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cli_args import (Command, add_execution_arguments, add_output_arguments,
                      make_parser, run_command, write_output)


def main(argv=None):
    parser = make_parser(description=__doc__)
    add_execution_arguments(parser)
    add_output_arguments(parser)
    tokens = list(sys.argv[1:] if argv is None else argv)
    if "--" not in tokens:
        parser.error("use -- before the executable and its arguments")
    boundary = tokens.index("--")
    args = parser.parse_args(tokens[:boundary])
    try:
        command = Command(tuple(tokens[boundary + 1:]))
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    try:
        result = run_command(command, cwd=args.cwd, timeout=args.timeout, dry_run=args.dry_run)
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 127 if isinstance(exc, FileNotFoundError) else 1
    write_output(result, format=args.format, output=args.output)
    if args.format == "text" and result.stderr:
        sys.stderr.write(result.stderr)
    if result.timed_out:
        print("command timed out", file=sys.stderr)
        return 124
    code = result.returncode or 0
    return 128 - code if code < 0 else code


if __name__ == "__main__":
    raise SystemExit(main())

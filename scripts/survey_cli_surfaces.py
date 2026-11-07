"""Measure the argparse CLI surfaces of sibling repositories (stdlib only).

python -S scripts/survey_cli_surfaces.py CLONES_DIR [--format text|json] [--output FILE]

CLONES_DIR holds one checkout per repository. For every ``.py`` file that
builds an ``ArgumentParser`` the survey records its long options, which of them
carry ``help=``, whether ``--format`` / ``--json`` / ``--timeout`` exist, the
exit codes written as literals, and the test commands found in its workflows.
The text report is the org-wide option vocabulary; the JSON report keeps the
per-file facts behind it. Nothing is executed and no file is modified.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cli_args import (EXIT_FAILURE, EXIT_OK, add_output_arguments, make_parser,  # noqa: E402
                      write_error, write_output)

SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "vendor", "__pycache__",
                       "build", "dist", ".dart_tool"})
EXIT_LITERAL_RE = re.compile(r"sys\.exit\((\d+)\)|SystemExit\((\d+)\)|\breturn (\d)\b")
TEST_COMMAND_RE = re.compile(
    r"(uv run[^\n]*?\b(?:pytest|unittest)\b[^\n]*|python3? (?:-[A-Za-z] )*-m (?:pytest|unittest)[^\n]*"
    r"|\bpytest\b[^\n]*|node --test[^\n]*|flutter test[^\n]*|npm (?:test|run test)[^\n]*"
    r"|npx playwright test[^\n]*|bun test[^\n]*)"
)
SHARED_OPTIONS = ("--format", "--json", "--output", "--out", "--timeout", "--dry-run", "--root")


def _python_files(repo: Path):
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath) / name


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def scan_cli_file(path: Path, repo: Path) -> dict[str, Any] | None:
    """Return the surface of one file, or None when it builds no parser."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if "ArgumentParser" not in source and "add_parser(" not in source:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    parsers = 0
    subcommands: list[str] = []
    options: list[tuple[list[str], bool, list[str] | None]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == "ArgumentParser":
            parsers += 1
        elif name == "add_parser" and node.args and isinstance(node.args[0], ast.Constant):
            subcommands.append(str(node.args[0].value))
        elif name == "add_argument":
            names = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if not names:
                continue
            keywords = {k.arg: k.value for k in node.keywords if k.arg}
            choices = None
            value = keywords.get("choices")
            if isinstance(value, (ast.Tuple, ast.List)):
                choices = [str(e.value) for e in value.elts if isinstance(e, ast.Constant)]
            options.append((names, "help" in keywords, choices))
    if parsers == 0 and not subcommands:
        return None
    long_options = sorted({n for names, _, _ in options for n in names if n.startswith("--")})
    without_help = sorted({n for names, has_help, _ in options if not has_help
                           for n in names if n.startswith("--")})
    format_choices = next((c for names, _, c in options if "--format" in names), None)
    exit_codes = sorted({int(x) for m in EXIT_LITERAL_RE.finditer(source) for x in m.groups() if x})
    return {
        "file": path.relative_to(repo).as_posix(),
        "parsers": parsers,
        "subcommands": subcommands,
        "long_options": long_options,
        "options_without_help": without_help,
        "format_choices": format_choices,
        "exit_codes": exit_codes,
    }


def scan_workflows(repo: Path) -> list[str]:
    workflows = repo / ".github" / "workflows"
    found: set[str] = set()
    if not workflows.is_dir():
        return []
    for workflow in sorted(list(workflows.glob("*.yml")) + list(workflows.glob("*.yaml"))):
        for line in workflow.read_text(encoding="utf-8", errors="replace").splitlines():
            match = TEST_COMMAND_RE.search(line)
            if match:
                found.add(f"{workflow.name}: {match.group(0).strip()[:120]}")
    return sorted(found)


def survey(clones: Path) -> dict[str, Any]:
    repos: dict[str, Any] = {}
    for repo in sorted(p for p in clones.iterdir() if (p / ".git").exists()):
        files = [f for f in (scan_cli_file(p, repo) for p in _python_files(repo)) if f]
        repos[repo.name] = {"clis": files, "ci_test_commands": scan_workflows(repo)}
    return {"schema": "cli-surface-survey/1", "repos": repos, "summary": summarize(repos)}


def summarize(repos: dict[str, Any]) -> dict[str, Any]:
    option_files: Counter[str] = Counter()
    option_repos: defaultdict[str, set[str]] = defaultdict(set)
    without_help: Counter[str] = Counter()
    format_choices: Counter[str] = Counter()
    exit_codes: Counter[int] = Counter()
    cli_files = 0
    for name, info in repos.items():
        for cli in info["clis"]:
            cli_files += 1
            for option in cli["long_options"]:
                option_files[option] += 1
                option_repos[option].add(name)
            for option in cli["options_without_help"]:
                without_help[option] += 1
            if cli["format_choices"] is not None:
                format_choices["|".join(cli["format_choices"])] += 1
            for code in cli["exit_codes"]:
                exit_codes[code] += 1
    vocabulary = [
        {"option": option, "files": files, "repos": len(option_repos[option]),
         "files_without_help": without_help[option]}
        for option, files in option_files.most_common()
    ]
    return {
        "repositories": len(repos),
        "cli_files": cli_files,
        "vocabulary": vocabulary,
        "shared_options": {o: option_files[o] for o in SHARED_OPTIONS},
        "format_choices": dict(format_choices.most_common()),
        "exit_codes": {str(code): count for code, count in sorted(exit_codes.items())},
    }


def render_text(report: dict[str, Any], top: int) -> str:
    summary = report["summary"]
    lines = [
        f"repositories: {summary['repositories']}  cli files: {summary['cli_files']}",
        "shared options (files): " + " ".join(f"{k}={v}" for k, v in summary["shared_options"].items()),
        "exit codes (files): " + " ".join(f"{k}={v}" for k, v in summary["exit_codes"].items()),
        "--format choices: " + "; ".join(f"{k} ({v})" for k, v in summary["format_choices"].items()),
        "",
        f"{'option':24} {'files':>5} {'repos':>5} {'no-help':>7}",
    ]
    for row in summary["vocabulary"][:top]:
        lines.append(f"{row['option']:24} {row['files']:5d} {row['repos']:5d} {row['files_without_help']:7d}")
    lines.append("")
    lines.append(f"{'repository':30} {'clis':>4} {'opts':>5} {'no-help':>7}  ci test commands")
    for name, info in report["repos"].items():
        clis = info["clis"]
        lines.append(
            f"{name:30} {len(clis):4d} {sum(len(c['long_options']) for c in clis):5d} "
            f"{sum(len(c['options_without_help']) for c in clis):7d}  {len(info['ci_test_commands'])}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = make_parser(
        json_errors=True,
        prog="survey_cli_surfaces.py",
        description=__doc__.split("\n\n")[1],
        epilog="exit 0: report written; 1: CLONES_DIR unreadable; 2: usage (JSON record with --format json)",
    )
    parser.add_argument("clones", type=Path, help="directory holding one git checkout per repository")
    parser.add_argument("--top", type=int, default=40, help="vocabulary rows in the text report (default: 40)")
    add_output_arguments(parser, json_flag=True)
    args = parser.parse_args(argv)
    if args.top < 0:
        parser.error("--top must be >= 0")
    if not args.clones.is_dir():
        return write_error(f"not a directory: {args.clones}", error="io_error",
                           exit_code=EXIT_FAILURE, format=args.format)
    report = survey(args.clones)
    value: Any = report if args.format == "json" else render_text(report, args.top)
    write_output(value, format=args.format, output=args.output)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

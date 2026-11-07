"""Executable contract for scripts/survey_cli_surfaces.py (the cross-repo CLI survey)."""
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "survey_cli_surfaces.py"
survey_module = runpy.run_path(str(SCRIPT), run_name="survey_cli_surfaces")

CLI_WITH_FORMAT = '''
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--format", choices=("text", "json"), default="text", help="output")
parser.add_argument("--output", help="file")
parser.add_argument("--timeout", type=float)
sub = parser.add_subparsers(dest="cmd")
sub.add_parser("status")
args = parser.parse_args()
raise SystemExit(2)
'''
CLI_WITH_JSON = '''
from argparse import ArgumentParser
p = ArgumentParser()
p.add_argument("--json", action="store_true")
p.add_argument("--out", "-o")
p.add_argument("--root", help="repository root")
def main():
    return 0
sys_exit = main
'''
NOT_A_CLI = "import json\nprint(json.dumps({}))\n"
WORKFLOW = """
jobs:
  test:
    steps:
      - run: uv run --locked pytest -q
      - run: node --test tests/x.test.cjs
      - run: echo not a test command
"""


def _make_clones(tmp_path: Path) -> Path:
    clones = tmp_path / "clones"
    alpha = clones / "alpha"
    (alpha / ".git").mkdir(parents=True)
    (alpha / "alpha.py").write_text(CLI_WITH_FORMAT, encoding="utf-8")
    (alpha / "lib.py").write_text(NOT_A_CLI, encoding="utf-8")
    (alpha / "vendor").mkdir()
    (alpha / "vendor" / "copied.py").write_text(CLI_WITH_JSON, encoding="utf-8")
    (alpha / ".github" / "workflows").mkdir(parents=True)
    (alpha / ".github" / "workflows" / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
    beta = clones / "beta"
    (beta / ".git").mkdir(parents=True)
    (beta / "scripts").mkdir()
    (beta / "scripts" / "tool.py").write_text(CLI_WITH_JSON, encoding="utf-8")
    (beta / "broken.py").write_text("def (:\n", encoding="utf-8")
    (clones / "not-a-repo").mkdir()
    (clones / "not-a-repo" / "x.py").write_text(CLI_WITH_JSON, encoding="utf-8")
    return clones


def test_survey_counts_options_help_and_ci_commands(tmp_path):
    report = survey_module["survey"](_make_clones(tmp_path))
    assert report["schema"] == "cli-surface-survey/1"
    assert sorted(report["repos"]) == ["alpha", "beta"]  # vendor/ and non-repos are skipped
    alpha = report["repos"]["alpha"]
    assert [c["file"] for c in alpha["clis"]] == ["alpha.py"]
    cli = alpha["clis"][0]
    assert cli["long_options"] == ["--format", "--output", "--timeout"]
    assert cli["options_without_help"] == ["--timeout"]
    assert cli["format_choices"] == ["text", "json"]
    assert cli["subcommands"] == ["status"] and cli["exit_codes"] == [2]
    assert alpha["ci_test_commands"] == ["ci.yml: node --test tests/x.test.cjs", "ci.yml: uv run --locked pytest -q"]
    beta = report["repos"]["beta"]["clis"]
    assert [c["file"] for c in beta] == ["scripts/tool.py"]
    assert beta[0]["options_without_help"] == ["--json", "--out"]
    assert beta[0]["exit_codes"] == [0]
    summary = report["summary"]
    assert (summary["repositories"], summary["cli_files"]) == (2, 2)
    assert summary["shared_options"] == {"--format": 1, "--json": 1, "--output": 1, "--out": 1,
                                         "--timeout": 1, "--dry-run": 0, "--root": 1}
    assert summary["format_choices"] == {"text|json": 1}
    assert summary["exit_codes"] == {"0": 1, "2": 1}
    assert summary["vocabulary"][0] == {"option": "--format", "files": 1, "repos": 1, "files_without_help": 0}
    text = survey_module["render_text"](report, top=3)
    assert "repositories: 2  cli files: 2" in text and text.count("\n") > 8


def test_cli_uses_the_shared_contract(tmp_path):
    clones = _make_clones(tmp_path)
    out = tmp_path / "survey.json"
    run = subprocess.run([sys.executable, "-S", str(SCRIPT), str(clones), "--json", "--output", str(out)],
                         cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert (run.returncode, run.stdout, run.stderr) == (0, "", "")
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["cli_files"] == 2
    usage = subprocess.run([sys.executable, "-S", str(SCRIPT), str(clones), "--format=json", "--top", "x"],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert usage.returncode == 2 and usage.stdout == ""
    assert json.loads(usage.stderr) == {"ok": False, "error": "usage", "exit_code": 2,
                                        "message": "argument --top: invalid int value: 'x'"}
    missing = subprocess.run([sys.executable, "-S", str(SCRIPT), str(tmp_path / "nope"), "--json"],
                             cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert missing.returncode == 1 and json.loads(missing.stderr)["error"] == "io_error"
    text_usage = subprocess.run([sys.executable, "-S", str(SCRIPT), str(clones), "--top", "-1"],
                                cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert text_usage.returncode == 2 and text_usage.stderr.startswith("usage: survey_cli_surfaces.py")


@pytest.mark.parametrize("flag", ["--format", "--json", "--output", "--top"])
def test_every_flag_has_help(flag):
    run = subprocess.run([sys.executable, "-S", str(SCRIPT), "--help"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0 and flag in run.stdout and "exit 0: report written" in run.stdout

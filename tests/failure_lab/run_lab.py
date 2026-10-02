"""Run intentionally failing pytest cases and verify their raw JUnit evidence.

This script exits 0 only when the child pytest run fails in the expected ways.
It is a test-harness tool, not part of the stdlib-only runtime artifact.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CASE_FILE = ROOT / "tests" / "failure_lab" / "intentional_cases.py"
OUTPUT_DIR = ROOT / "test-results" / "negative-evidence"
JUNIT = OUTPUT_DIR / "intentional-failure.xml"
STDOUT = OUTPUT_DIR / "child-stdout.txt"
STDERR = OUTPUT_DIR / "child-stderr.txt"
RECEIPT = OUTPUT_DIR / "receipt.json"


def classify_testcase(case: ET.Element) -> str:
    for tag in ("failure", "error", "skipped"):
        if case.find(tag) is not None:
            return tag
    return "passed"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-ra",
        "--tb=short",
        str(CASE_FILE),
        f"--junitxml={JUNIT}",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    STDOUT.write_text(completed.stdout, encoding="utf-8", newline="\n")
    STDERR.write_text(completed.stderr, encoding="utf-8", newline="\n")

    if not JUNIT.exists():
        raise SystemExit("intentional failure run did not produce JUnit")

    tree = ET.parse(JUNIT)
    cases = {}
    for testcase in tree.getroot().iter("testcase"):
        name = testcase.attrib.get("name", "")
        cases[name] = classify_testcase(testcase)

    expected = {
        "test_expected_pass": "passed",
        "test_assertion_failure": "failure",
        "test_setup_error": "error",
        "test_known_antipattern_xfail": "skipped",
        "test_unexpected_pass_is_failure": "failure",
    }
    receipt = {
        "schema": "cli_args/negative-evidence/1",
        "command": command,
        "child_returncode": completed.returncode,
        "expected_child_returncode": 1,
        "cases": cases,
        "expected_cases": expected,
        "junit": str(JUNIT.relative_to(ROOT)),
        "stdout": str(STDOUT.relative_to(ROOT)),
        "stderr": str(STDERR.relative_to(ROOT)),
    }
    RECEIPT.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    problems = []
    if completed.returncode != 1:
        problems.append(f"child pytest return code {completed.returncode}, expected 1")
    if cases != expected:
        problems.append(f"JUnit classifications {cases!r}, expected {expected!r}")

    if problems:
        for problem in problems:
            print("negative-evidence mismatch:", problem, file=sys.stderr)
        return 1

    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

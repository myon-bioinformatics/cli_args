"""Run intentionally failing pytest cases and verify their raw JUnit evidence.

This script exits 0 only when the child pytest run fails in the expected ways.
It is a test-harness tool, not part of the stdlib-only runtime artifact.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import logging
import os
import platform
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CASE_FILE = ROOT / "tests" / "failure_lab" / "intentional_cases.py"
OUTPUT_DIR = ROOT / "test-results" / "negative-evidence"
JUNIT = OUTPUT_DIR / "intentional-failure.xml"
STDOUT = OUTPUT_DIR / "child-stdout.txt"
STDERR = OUTPUT_DIR / "child-stderr.txt"
RECEIPT = OUTPUT_DIR / "receipt.json"
DIAGNOSTICS = OUTPUT_DIR / "diagnostics.log"
LOGGER = logging.getLogger("cli_args.failure_lab")


def classify_testcase(case: ET.Element) -> str:
    for tag in ("failure", "error", "skipped"):
        if case.find(tag) is not None:
            return tag
    return "passed"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # A failed launch must never reuse evidence from a previous local run.
    for artifact in (JUNIT, STDOUT, STDERR, RECEIPT):
        artifact.unlink(missing_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
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
    LOGGER.info("child_start executable=%s", sys.executable)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )
    LOGGER.info("child_complete returncode=%s", completed.returncode)
    STDOUT.write_text(completed.stdout, encoding="utf-8", newline="\n")
    STDERR.write_text(completed.stderr, encoding="utf-8", newline="\n")

    if not JUNIT.exists():
        raise RuntimeError("intentional failure run did not produce fresh JUnit")

    tree = ET.parse(JUNIT)
    cases = {}
    for testcase in tree.getroot().iter("testcase"):
        name = testcase.attrib.get("name", "")
        if name in cases:
            raise ValueError(f"duplicate JUnit testcase: {name}")
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
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": time.monotonic() - started,
        "environment": {
            "python": platform.python_version(),
            "executable": sys.executable,
            "platform": platform.platform(),
            "github_sha": os.environ.get("GITHUB_SHA"),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        },
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
            LOGGER.error("negative-evidence mismatch: %s", problem)
        return 1

    LOGGER.info("evidence_validated cases=%s", len(cases))
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


def entrypoint() -> int:
    # Only the executable harness configures logging; imports stay inert.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    previous = (LOGGER.handlers[:], LOGGER.level, LOGGER.propagate)
    with closing(logging.FileHandler(DIAGNOSTICS, mode="w", encoding="utf-8")) as file_handler:
        console = logging.StreamHandler(sys.stderr)
        for handler in (file_handler, console):
            handler.setFormatter(formatter)
        LOGGER.handlers = [file_handler, console]
        LOGGER.setLevel(logging.INFO)
        LOGGER.propagate = False
        try:
            return main()
        except Exception:
            LOGGER.exception("evidence_harness_failed")
            return 1
        finally:
            LOGGER.handlers, LOGGER.level, LOGGER.propagate = previous
            console.close()


if __name__ == "__main__":
    raise SystemExit(entrypoint())


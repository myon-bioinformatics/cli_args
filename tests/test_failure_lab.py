import importlib.util
from datetime import datetime
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def lab(tmp_path, monkeypatch):
    path = Path(__file__).parent / "failure_lab" / "run_lab.py"
    spec = importlib.util.spec_from_file_location("failure_lab_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)
    for name in ("JUNIT", "STDOUT", "STDERR", "RECEIPT", "DIAGNOSTICS"):
        monkeypatch.setattr(module, name, tmp_path / getattr(module, name).name)
    return module


def test_failed_launch_cannot_reuse_previous_evidence(lab, monkeypatch):
    for artifact in (lab.JUNIT, lab.STDOUT, lab.STDERR, lab.RECEIPT):
        artifact.write_text("stale evidence", encoding="utf-8")

    def fail(*args, **kwargs):
        raise OSError("launch evidence probe")

    monkeypatch.setattr(lab.subprocess, "run", fail)
    assert lab.entrypoint() == 1
    assert not any(p.exists() for p in (lab.JUNIT, lab.STDOUT, lab.STDERR, lab.RECEIPT))
    diagnostics = lab.DIAGNOSTICS.read_text(encoding="utf-8")
    datetime.strptime(diagnostics.split()[0], "%Y-%m-%dT%H:%M:%SZ")
    assert "ERROR cli_args.failure_lab evidence_harness_failed" in diagnostics
    assert "Traceback (most recent call last):" in diagnostics
    assert "OSError: launch evidence probe" in diagnostics


def test_missing_fresh_junit_is_rejected(lab, monkeypatch):
    lab.JUNIT.write_text("<testsuite/>", encoding="utf-8")
    monkeypatch.setattr(lab.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a[0], 1, "child output", ""))
    assert lab.entrypoint() == 1
    assert not lab.JUNIT.exists()
    assert "did not produce fresh JUnit" in lab.DIAGNOSTICS.read_text()


def test_duplicate_case_cannot_hide_an_unknown_failure(lab, monkeypatch):
    def child(command, **kwargs):
        lab.JUNIT.write_text(
            '<testsuite><testcase name="same"><failure/></testcase>'
            '<testcase name="same"/></testsuite>', encoding="utf-8")
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(lab.subprocess, "run", child)
    assert lab.entrypoint() == 1
    assert "duplicate JUnit testcase: same" in lab.DIAGNOSTICS.read_text()
    assert not lab.RECEIPT.exists()

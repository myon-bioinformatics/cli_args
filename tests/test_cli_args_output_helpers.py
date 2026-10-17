"""trim_output (explicit omission marker) and pytest_summary (deciding lines of a pytest run)."""
import pytest

import cli_args

FAILING = """\
============================= test session starts ==============================
collected 5 items

test_mod.py .FEF.                                                        [100%]

==================================== ERRORS ====================================
_________________________ ERROR at setup of test_err __________________________
E   RuntimeError: fixture boom
E   second line
=================================== FAILURES ===================================
___________________________________ test_bad ___________________________________
E   assert 1 == 3
E    +  where 1 = f(1)
___________________________________ test_xp ____________________________________
[XPASS(strict)]
================================ tests coverage ================================
Name     Stmts   Miss  Cover
TOTAL        4      1    75%
FAIL Required test coverage of 90% not reached. Total coverage: 75.00%
ERROR: Coverage failure: total of 75 is less than fail-under=90
=========================== short test summary info ============================
ERROR test_mod.py::test_err - RuntimeError: fixture boom
FAILED test_mod.py::test_bad - assert 1 == 3
FAILED test_mod.py::test_xp - [XPASS(strict)]
==== 2 failed, 2 passed, 1 warning, 1 error in 0.03s ====
"""


def test_trim_output_marks_the_gap():
    text = "".join(f"line {i}\n" for i in range(10))
    assert cli_args.trim_output(text, head=2, tail=3) == "line 0\nline 1\n... 5 line(s) omitted ...\nline 7\nline 8\nline 9\n"
    assert cli_args.trim_output(text, head=0, tail=1) == "... 9 line(s) omitted ...\nline 9\n"
    assert cli_args.trim_output(text, head=1, tail=0) == "line 0\n... 9 line(s) omitted ...\n"
    assert cli_args.trim_output(text, head=5, tail=5) is text
    assert cli_args.trim_output("a\r\nb\r\nc", head=1, tail=1) == "a\r\n... 1 line(s) omitted ...\nc"
    assert cli_args.trim_output("", head=0, tail=0) == ""


@pytest.mark.parametrize("kwargs, error", [({"head": -1}, ValueError), ({"tail": 1.5}, ValueError),
                                            ({"head": True}, ValueError)])
def test_trim_output_validation(kwargs, error):
    with pytest.raises(error):
        cli_args.trim_output("x", **kwargs)
    with pytest.raises(TypeError):
        cli_args.trim_output(b"x")


def test_pytest_summary_failing_run_with_coverage():
    out = cli_args.pytest_summary(FAILING)
    assert out["summary"] == "2 failed, 2 passed, 1 warning, 1 error in 0.03s"
    assert out["counts"] == {"failed": 2, "passed": 2, "warnings": 1, "errors": 1}
    assert out["failed"] == ["test_mod.py::test_bad - assert 1 == 3", "test_mod.py::test_xp - [XPASS(strict)]"]
    assert out["errors"] == ["test_mod.py::test_err - RuntimeError: fixture boom"]
    assert out["coverage"] == {"total": "TOTAL 4 1 75%",
                               "required": "Required test coverage of 90% not reached. Total coverage: 75.00%",
                               "required_met": False}
    assert out["deciding_lines"] == [
        "E   RuntimeError: fixture boom", "E   assert 1 == 3", "TOTAL        4      1    75%",
        "FAIL Required test coverage of 90% not reached. Total coverage: 75.00%",
        "ERROR: Coverage failure: total of 75 is less than fail-under=90",
        "ERROR test_mod.py::test_err - RuntimeError: fixture boom",
        "FAILED test_mod.py::test_bad - assert 1 == 3", "FAILED test_mod.py::test_xp - [XPASS(strict)]",
        "==== 2 failed, 2 passed, 1 warning, 1 error in 0.03s ===="]
    assert not out["truncated"]
    capped = cli_args.pytest_summary(FAILING, max_lines=2)
    assert len(capped["deciding_lines"]) == 2 and capped["truncated"]


def test_pytest_summary_quiet_pass_collection_error_and_nothing():
    quiet = cli_args.pytest_summary("....\nRequired test coverage of 90% reached. Total coverage: 97.10%\n"
                                    "4 passed, 1 deselected in 0.40s (0:00:00)\n")
    assert quiet["summary"] == "4 passed, 1 deselected in 0.40s (0:00:00)"
    assert quiet["counts"] == {"passed": 4, "deselected": 1} and quiet["coverage"]["required_met"] is True
    collect = cli_args.pytest_summary("ERROR collecting tests/test_x.py\nINTERNALERROR> boom\n"
                                      "!!! Interrupted: 1 error during collection !!!\n1 error in 0.10s\n")
    assert collect["counts"] == {"errors": 1} and collect["errors"] == []
    assert collect["deciding_lines"] == ["ERROR collecting tests/test_x.py", "INTERNALERROR> boom", "1 error in 0.10s"]
    none = cli_args.pytest_summary("no tests ran in 0.01s\n")
    assert none["summary"] == "no tests ran in 0.01s" and none["counts"] == {}
    empty = cli_args.pytest_summary("")
    assert empty["summary"] is None and empty["coverage"] == {"total": None, "required": None, "required_met": None}
    for bad in (b"x", None):
        with pytest.raises(TypeError):
            cli_args.pytest_summary(bad)
    for limit in (0, True):
        with pytest.raises(ValueError):
            cli_args.pytest_summary("", max_lines=limit)


def test_pytest_summary_on_a_real_run(tmp_path):
    (tmp_path / "test_x.py").write_text("def test_ok():\n    pass\n\ndef test_no():\n    assert 1 == 2\n",
                                        encoding="utf-8")
    result = cli_args.run_command(cli_args.pytest_command(["test_x.py"], quiet=True, summary=True,
                                                         extra=["-p", "no:cacheprovider"]),
                                  cwd=tmp_path, timeout=120)
    out = cli_args.pytest_summary(result.stdout)
    assert out["counts"] == {"failed": 1, "passed": 1}
    assert out["failed"] and out["failed"][0].startswith("test_x.py::test_no")
    assert "E       assert 1 == 2" in out["deciding_lines"]

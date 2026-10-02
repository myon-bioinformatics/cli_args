import pytest


def test_expected_pass():
    assert True


def test_assertion_failure():
    expected = {"mode": "machine", "separator": "nul"}
    actual = {"mode": "human", "separator": "newline"}
    assert actual == expected


@pytest.fixture
def broken_fixture():
    raise RuntimeError("intentional setup error for JUnit evidence")


def test_setup_error(broken_fixture):
    assert broken_fixture


@pytest.mark.xfail(reason="known antipattern kept as evidence", strict=True)
def test_known_antipattern_xfail():
    assert "unsafe newline parsing" == "nul-safe parsing"


@pytest.mark.xfail(reason="strict XPASS must stay visible", strict=True)
def test_unexpected_pass_is_failure():
    assert True

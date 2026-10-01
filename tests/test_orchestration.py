import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from cli_args import Command, run_command


def _py(code, *args):
    return Command((sys.executable, "-S", "-c", code)).positional(*args)


def test_ordered_steps_stop_on_first_failure(tmp_path):
    markers = [tmp_path / f"step-{index}.txt" for index in range(1, 5)]
    steps = [
        _py("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('1');", markers[0]),
        _py("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('2'); sys.exit(7)", markers[1]),
        _py("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('3');", markers[2]),
        _py("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('4');", markers[3]),
    ]

    results = []
    for command in steps:
        result = run_command(command)
        results.append(result.returncode)
        if result.returncode != 0:
            break

    assert results == [0, 7]
    assert markers[0].exists()
    assert markers[1].exists()
    assert not markers[2].exists()
    assert not markers[3].exists()


def test_exit_codes_are_structured_signals():
    observed = {}
    for code in (0, 1, 2):
        result = run_command(_py("import sys; sys.exit(int(sys.argv[1]))", str(code)))
        observed[code] = result.returncode
    assert observed == {0: 0, 1: 1, 2: 2}


def test_explicit_environment_handoff_does_not_mutate_parent():
    key = "CLI_ARGS_ORCHESTRATION_VALUE"
    before = os.environ.get(key)
    env = {**os.environ, key: "parent-provided"}

    result = run_command(
        _py(
            "import os; "
            "print(os.environ['CLI_ARGS_ORCHESTRATION_VALUE']); "
            "os.environ['CLI_ARGS_ORCHESTRATION_VALUE']='child-only'; "
            "print(os.environ['CLI_ARGS_ORCHESTRATION_VALUE'])"
        ),
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["parent-provided", "child-only"]
    assert os.environ.get(key) == before


def test_stdout_value_can_drive_next_command():
    first = run_command(_py("import json; print(json.dumps({'count': 3}))"))
    assert first.returncode == 0
    payload = json.loads(first.stdout)

    second = run_command(
        _py("import sys; print(int(sys.argv[1]) * 2)", str(payload["count"]))
    )
    assert (second.returncode, second.stdout.strip()) == (0, "6")


def test_temporary_file_handoff_is_explicit_and_cleaned():
    with TemporaryDirectory() as raw:
        root = Path(raw)
        artifact = root / "handoff.json"

        produced = run_command(
            _py(
                "from pathlib import Path; import json,sys; "
                "Path(sys.argv[1]).write_text(json.dumps({'ok': True}), encoding='utf-8')",
                artifact,
            )
        )
        assert produced.returncode == 0

        consumed = run_command(
            _py(
                "from pathlib import Path; import json,sys; "
                "print(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['ok'])",
                artifact,
            )
        )
        assert (consumed.returncode, consumed.stdout.strip()) == (0, "True")
        assert artifact.is_file()

    assert not root.exists()


def test_conditional_fallback_without_shell():
    primary = run_command(_py("import sys; sys.exit(1)"))
    assert primary.returncode == 1

    fallback = None
    if primary.returncode != 0:
        fallback = run_command(_py("print('fallback')"))

    assert fallback is not None
    assert (fallback.returncode, fallback.stdout.strip()) == (0, "fallback")

import json
import os
import shutil

import pytest

from cli_args import Command, run_command


def test_docker_transports_exact_argv_and_runs_container_suite():
    docker = shutil.which("docker")
    image = os.environ.get("CLI_ARGS_TEST_IMAGE")
    if docker is None or not image:
        pytest.skip("Docker integration image is not configured")

    values = ["", "-leading", "space value", "日本語"]
    transported = ["--", *values]
    probe = (
        Command((docker,))
        .positional("run", "--rm", image, "python", "-S", "-c",
                    "import json,sys; print(json.dumps(sys.argv[1:], ensure_ascii=False))")
        .passthrough(transported)
    )
    result = run_command(probe, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == transported

    suite = run_command(
        Command((docker,)).positional(
            "run", "--rm", image,
            "python", "-m", "pytest", "-q", "tests/test_container_commands.py",
        ),
        timeout=120,
    )
    assert suite.returncode == 0, suite.stdout + suite.stderr
    assert "passed" in suite.stdout

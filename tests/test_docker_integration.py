import json
import os
import shutil
import uuid

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

    inspected = run_command(
        Command((docker,))
        .positional("inspect")
        .option("--format", "{{.Config.WorkingDir}}")
        .positional(image),
        timeout=30,
    )
    assert (inspected.returncode, inspected.stdout.strip()) == (0, "/workspace")

    name = "cli-args-" + uuid.uuid4().hex[:12]
    started = run_command(
        Command((docker,)).positional("run", "-d", "--rm", "--name", name, image, "sleep", "60"),
        timeout=30,
    )
    assert started.returncode == 0, started.stderr
    try:
        executed = run_command(
            Command((docker,)).positional(
                "exec", name, "python", "-S", "-c",
                "import json,sys; print(json.dumps(sys.argv[1:], ensure_ascii=False))",
            ).passthrough(["exec space", "実行"]),
            timeout=30,
        )
        assert executed.returncode == 0, executed.stderr
        assert json.loads(executed.stdout) == ["exec space", "実行"]
    finally:
        run_command(Command((docker,)).positional("rm", "-f", name), timeout=30)

    suite = run_command(
        Command((docker,)).positional(
            "run", "--rm", image,
            "python", "-m", "pytest", "-q", "tests/test_container_commands.py",
        ),
        timeout=120,
    )
    assert suite.returncode == 0, suite.stdout + suite.stderr
    assert "passed" in suite.stdout

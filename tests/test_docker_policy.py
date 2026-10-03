import json
import os
import shutil

import pytest

from cli_args import Command, run_command


def test_docker_local_only_networkless_read_only_policy():
    docker = shutil.which("docker")
    image = os.environ.get("CLI_ARGS_TEST_IMAGE")
    if docker is None or not image:
        pytest.skip("Docker integration image is not configured")

    script = (
        "from pathlib import Path; import json; "
        "Path('/tmp/probe').write_text('ok'); "
        "print(json.dumps({'tmp':Path('/tmp/probe').read_text()}))"
    )
    command = (
        Command((docker,))
        .positional("run", "--rm")
        .option("--pull", "never", attached=True)
        .option("--network", "none", attached=True)
        .flag("--read-only")
        .option("--tmpfs", "/tmp:rw,noexec,nosuid,size=16m")
        .positional(image, "python", "-S", "-c", script)
    )
    result = run_command(command, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"tmp": "ok"}

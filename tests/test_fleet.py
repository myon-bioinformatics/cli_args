"""Fleet contracts through the parent's shared checks (vendor/fleet_check.py): locks, pins, CI setup, benchmark."""
import json, re, tomllib, unittest

from vendor import fleet_check as fleet

ROOT = fleet.repo_root(__file__)
PARENT_WORKFLOW_PIN = "9e3da7ae1846e9604ebc24bb5178f7de094a4e77"
ACCEPTED = {"vendor/fleet_check.py": "45ed741f7e1f60179934cee6fa1e16a887f97cb0"}
SETUP_UV = "astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2"
JOBS = {
    "ci.yml": {
        "vendor-locked": "3.15",
        "test": "${{ matrix.python }}",
        "node-runtime": "3.15",
        "docker-integration": "3.15",
        "portability": "3.15",
        "negative-evidence": "3.15"
    },
    "runtime-compatibility.yml": {
        "runtime": "${{ matrix.python }}"
    }
}
EXPECTED_REPORTS = [
    "junit-py3.11/pytest-3.11.xml",
    "junit-py3.12/pytest-3.12.xml",
    "junit-py3.14/pytest-3.14.xml",
    "junit-node-ubuntu-latest-26/node-ubuntu-latest-26.xml",
    "junit-node-ubuntu-latest-latest/node-ubuntu-latest-latest.xml",
    "junit-node-windows-latest-26/node-windows-latest-26.xml",
    "junit-node-windows-latest-latest/node-windows-latest-latest.xml",
    "junit-node-macos-latest-26/node-macos-latest-26.xml",
    "junit-node-macos-latest-latest/node-macos-latest-latest.xml",
    "junit-docker-integration/docker-integration.xml",
    "junit-container-real/container-real.xml",
    "junit-core-windows/core-windows.xml",
    "junit-core-macos/core-macos.xml"
]



def job(workflow, name):
    return fleet.workflow_job(ROOT, name, workflow)


def test_vendor_lock_matches_checked_in_bytes():
    fleet.check_lock(ROOT, commits=ACCEPTED)


def test_parent_workflow_references_use_reviewed_rollout_commit():
    # Refs resolved at runtime (``${{ … }}``) are not pins and stay outside this contract.
    pins = [ref for ref in fleet.parent_refs(ROOT) if "${{" not in (ref or "")]
    assert set(pins) == {PARENT_WORKFLOW_PIN}, pins


def test_vendor_locked_job_resolves_parent_main_at_runtime():
    path = ROOT / ".github/workflows/ci.yml"
    text = path.read_text(encoding="utf-8")
    assert PARENT_WORKFLOW_PIN in text
    assert "parent_vendor_tools_resolve.py" in text
    assert "GITHUB_TOKEN" in text
    assert "steps.parent-vendor-tools.outputs.sha" in text
    script = (ROOT / "scripts/parent_vendor_tools_resolve.py").read_text(encoding="utf-8")
    assert "api.github.com/repos/" in script
    assert "ls-remote" in script and "--symref" in script
    assert "638801160" in script
    assert "shell=True" not in script


def test_vendor_locked_job_runs_network_parent_vendor_resolve_regressions():
    path = ROOT / ".github/workflows/ci.yml"
    text = path.read_text(encoding="utf-8")
    assert "Network parent vendor tools resolve regressions" in text
    assert (
        "uv run --locked pytest -q -m network tests/test_parent_vendor_tools_resolve.py"
        in text
    )
    marker = "Network parent vendor tools resolve regressions"
    block = text.split(marker, 1)[1].split("- name:", 1)[0]
    assert "GITHUB_TOKEN: ${{ github.token }}" in block


def test_pytest_jobs_run_through_uv_and_node_tests_stay():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python -m pytest" not in text
    assert text.count("uv run --locked pytest") >= 6
    assert "node --test tests/node/cli_args.test.cjs" in text
    dockerfile = (ROOT / "tests/docker/Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["uv", "run", "--locked", "pytest"' in dockerfile
    assert "python -m pytest" not in dockerfile


class OptimizedBenchmarkTests(unittest.TestCase):
    def test_wrong_trim_result_stops_without_success_json(self):
        patch = """
g['subprocess'].check_output = lambda *a, **kw: b'def trim_output(text): return "reference"'
g['cli_args'].trim_output = lambda *a, **kw: 'incorrect'
"""
        result = fleet.run_main(ROOT, "scripts/benchmark_trim_memory.py", patch, optimized=True, timeout=30)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("trim output mismatch", result.stderr)
        self.assertEqual(result.stdout, "")


class CiPythonSetupTests(unittest.TestCase):
    def test_project_and_lock_declare_python311_without_runtime_dependencies(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["requires-python"], ">=3.11")
        self.assertEqual(lock["requires-python"], project["project"]["requires-python"])
        self.assertEqual(project["project"]["dependencies"], [])
        self.assertIsNot(project["tool"]["uv"].get("package"), False)
        self.assertEqual(project["tool"]["uv"]["dependency-groups"]["dev"]["requires-python"], ">=3.11")

    def test_supported_runtime_versions_keep_existing_os_coverage(self):
        block = job("runtime-compatibility.yml", "runtime")
        matrix = re.search(r"(?ms)^      matrix:\n(.*?)(?=^    steps:)", block)
        self.assertIsNotNone(matrix)
        self.assertEqual(matrix.group(1), '''        os: [ubuntu-latest]
        python: ["3.11", "3.12", "3.13", "3.14"]
        include:
          - os: windows-latest
            python: "3.11"
          - os: windows-latest
            python: "3.14"
          - os: macos-latest
            python: "3.11"
          - os: macos-latest
            python: "3.14"
''')
        self.assertIn("runs-on: ${{ matrix.os }}", block)
        self.assertIn("fail-fast: false", block)
        self.assertIn("python -S -m unittest discover -s tests -p test_runtime_compatibility.py -v", block)
        self.assertNotIn("continue-on-error", block)

    def test_selected_python_is_ready_before_any_python_or_uv_command(self):
        for workflow, jobs in JOBS.items():
            for name, version in jobs.items():
                with self.subTest(workflow=workflow, job=name):
                    block = job(workflow, name)
                    self.assertEqual(block.count("uses: " + SETUP_UV), 1)
                    setup = block.index("uses: " + SETUP_UV)
                    command = re.search(
                        r"(?m)^\s*(?:-\s+)?(?:run:\s*)?(?:python(?:3)?|uv)\s+",
                        block,
                    )
                    self.assertIsNotNone(command, "No interpreter consumer was checked")
                    self.assertLess(setup, command.start(), "Python ran before setup-uv")
                    setup_inputs = block[setup:].split("\n", 10)[:9]
                    inputs = "\n".join(setup_inputs)
                    self.assertIn('version: "latest"', inputs)
                    self.assertIn(f'python-version: "{version}"', inputs)
                    self.assertIn("activate-environment: true", inputs)
                    self.assertIn("enable-cache: true", inputs)
                    self.assertIn("save-cache: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}", inputs)  # only main writes
                    self.assertIn("prune-cache: true", inputs)

    def test_compatibility_matrix_and_required_report_identities_are_preserved(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("python: ['3.11', '3.12', '3.14']", text)
        match = re.search(r"expected-reports: '([^']+)'", job("ci.yml", "failure-identity"))
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1)), EXPECTED_REPORTS)

    def test_frozen_container_baseline_and_locked_commands_are_preserved(self):
        dockerfile = (ROOT / "tests/docker/Dockerfile").read_text(encoding="utf-8")
        self.assertEqual(dockerfile.splitlines()[0], "FROM python:3.14.0-slim-bookworm")
        self.assertIn('CMD ["uv", "run", "--locked", "pytest"', dockerfile)
        self.assertIn("uv sync --locked", dockerfile)
        # uv comes from its own image, not from pip, and the lock decides every package.
        self.assertIn("COPY --from=ghcr.io/astral-sh/uv:", dockerfile)
        self.assertNotIn("pip install", dockerfile)
        self.assertIn("python:3.14.0-slim-bookworm", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("uv run --locked pytest", job("ci.yml", "test"))



if __name__ == "__main__":
    unittest.main()

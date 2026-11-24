"""Fleet contracts through the parent's shared checks (vendor/fleet_check.py): locks, pins, CI setup, benchmark."""
import json, re, tomllib, unittest

from vendor import fleet_check as fleet

ROOT = fleet.repo_root(__file__)
PARENT_WORKFLOW_PIN = "1368174821fb03be258ecf3312ce0ea809f6ea22"
ACCEPTED = {
    "vendor/fleet_check.py": "20de01921e50e9339aa9271b0547a5be7649b3b3",
    "vendor/py_launch.cjs": "de63762d8485e4d398a651715d34ebf4a04c23f2"
}
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
    # Every parent row is listed, so a new or renamed vendored file has to be reviewed here.
    sources = {where: (fleet.PARENT, where.rpartition("/")[2]) for where in ACCEPTED}
    sources["vendor/myon-bioinformatics-LICENSE"] = (fleet.PARENT, "LICENSE")
    fleet.check_lock(ROOT, commits=ACCEPTED, sources=sources)


def test_every_action_is_pinned_by_full_sha_with_version_comment():
    assert SETUP_UV in {f"{action}@{sha}" for action, sha, _ in fleet.check_actions(ROOT)}


def test_parent_workflow_references_use_reviewed_rollout_commit():
    # The .vendor-sync-tools checkout is resolved at runtime (``${{ … }}``): not a pin, checked on its own.
    pins = fleet.parent_refs(ROOT, skip=(".vendor-sync-tools",))
    assert set(pins) == {PARENT_WORKFLOW_PIN}, pins
    assert fleet.parent_refs(ROOT, only=(".vendor-sync-tools",)) == ["${{ steps.parent-vendor-tools.outputs.sha }}"]


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
    assert "node --test tests/cli_args.test.cjs" in text
    dockerfile = (ROOT / "tests/docker/Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["uv", "run", "--locked", "pytest"' in dockerfile
    assert "python -m pytest" not in dockerfile


def test_no_per_tool_wrapper_and_readme_documents_the_direct_command():
    assert not (ROOT / "cli_args.cjs").exists()
    assert not (ROOT / "cli_args.d.cts").exists()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "node vendor/py_launch.cjs --env-var CLI_ARGS_PYTHON -- cli_args.py" in readme
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert pkg["engines"]["node"] == ">=26"


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
        # pyproject and uv.lock agree on the floor, and the runtime job starts at it: the parent's check.
        self.assertEqual(fleet.python_floor(ROOT), ("3.11", ["3.11", "3.12", "3.13", "3.14"]))
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
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

    def test_selected_python_is_ready_before_any_python_or_uv_command(self):
        for workflow, jobs in JOBS.items():
            for name, version in jobs.items():
                with self.subTest(workflow=workflow, job=name):
                    fleet.workflow_job(ROOT, name, workflow, setup=SETUP_UV, inputs=(
                        'version: "latest"', f'python-version: "{version}"', "activate-environment: true", "enable-cache: true",
                        "save-cache: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}",  # only main writes
                        "prune-cache: true"))

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


# 🧰 Scripts: 📝 each one describes itself and ⌨️ one that reads sys.argv declares its arguments (argparse /
# cli_args). Read with ast, never run; the portfolio's script catalog reads the same facts.

class ScriptsDescribeThemselves(unittest.TestCase):
    def test_every_script_has_a_description_and_declared_arguments(self):
        fleet.check_scripts(fleet.repo_root(__file__))

    def test_pull_request_ci_stays_quick(self):
        # ⏱ push limited to branches, superseded PR runs cancelled, every job timed (fleet_check.check_ci)
        fleet.check_ci(fleet.repo_root(__file__))

    def test_root_scripts_import_only_the_standard_library(self):
        root = fleet.repo_root(__file__)
        for path in sorted(root.glob("*.py")):
            if path.name != "conftest.py":
                fleet.check_imports(root, path.name)

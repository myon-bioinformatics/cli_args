"""Live resolution of parent vendor tooling (opt-in via network marker)."""
import importlib.util
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_resolve():
    spec = importlib.util.spec_from_file_location(
        "parent_vendor_tools_resolve",
        ROOT / "scripts/parent_vendor_tools_resolve.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.network
def test_resolve_parent_vendor_tools_head_matches_github_api():
    resolve = _load_resolve()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    resolved = resolve.resolve_parent_vendor_tools_head(token=token)
    assert resolved["repository"] == resolve.PARENT_REPOSITORY
    assert resolved["repository_id"] == resolve.EXPECTED_REPOSITORY_ID
    assert re.fullmatch(r"[0-9a-f]{40}", str(resolved["sha"]))

"""Guards for the release/CI wiring: one version source, semver, and workflow safety properties."""
from __future__ import annotations

import re
from pathlib import Path

import app

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_version_is_plain_semver_and_distinct_from_the_api_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", app.__version__)
    assert app.API_VERSION == "1.3.3" and app.__version__ != app.API_VERSION
    # The release workflow reads the very same line.
    assert re.search(rf'^__version__\s*=\s*"{re.escape(app.__version__)}"', _read("app/__init__.py"), re.M)


def test_docs_name_the_api_version_the_code_targets():
    assert f"Customer API {app.API_VERSION}" in _read("README.md")
    assert "1.3.3" in _read("docs/ENDPOINT_MATRIX.md")


def test_ci_triggers_permissions_and_no_secrets():
    ci = _read(".github/workflows/ci.yml")
    assert "pull_request:" in ci and "push:" in ci and "branches: [main]" in ci
    assert re.search(r"^permissions:\n  contents: read$", ci, re.M)
    assert "secrets." not in ci and "pull_request_target" not in ci
    assert "python -m pytest" in ci and "docker build" in ci


def test_release_runs_only_after_successful_main_push_ci():
    rel = _read(".github/workflows/release.yml")
    assert "workflow_run:" in rel and 'workflows: ["CI"]' in rel
    for guard in ("conclusion == 'success'", "event == 'push'", "head_branch == 'main'"):
        assert guard in rel
    assert re.search(r"^permissions:\n  contents: write\b", rel, re.M)
    assert "secrets." not in rel and "cancel-in-progress: false" in rel
    assert "--verify-tag" in rel and "git rev-parse -q --verify" in rel and "gh release view" in rel

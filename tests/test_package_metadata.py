from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from link2context import __version__

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 CI.
    import tomli as tomllib


def project_metadata() -> dict:
    return tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_package_version_matches_pyproject() -> None:
    assert project_metadata()["version"] == __version__


def test_pyproject_declares_open_source_package_metadata() -> None:
    project = project_metadata()

    assert project["name"] == "link2context"
    assert project["license"] == "MIT"
    assert project["readme"] == "README.md"
    assert project["requires-python"] == ">=3.10"
    assert project["scripts"] == {
        "link2context": "link2context.cli:main",
        "link2context-store": "link2context.store:main",
    }
    assert project["optional-dependencies"]["dev"] == [
        "build>=1",
        "pytest>=8",
        "tomli>=2; python_version < '3.11'",
    ]


def test_open_source_repository_files_are_present() -> None:
    required_paths = [
        "README.md",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "LICENSE",
        "MANIFEST.in",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "docs/architecture.md",
        "docs/export-contracts.md",
        "docs/github-publish.md",
        "docs/index.md",
        "docs/quickstart.md",
        "docs/roadmap.md",
        "docs/release-checklist.md",
        ".github/dependabot.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
        ".github/pull_request_template.md",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
    ]

    missing = [path for path in required_paths if not Path(path).exists()]
    assert missing == []


def test_public_example_url_lists_are_sanitized() -> None:
    forbidden_fragments = [
        "C:\\Users\\",
        "id_token=",
        "web_session=",
        "sec_poison_id=",
        "shareRedId=",
        "share_id=",
        "xsec_token=C",
        "xsec_token=Y",
    ]
    leaked = []
    for path in Path("examples").glob("*urls*.txt"):
        content = path.read_text(encoding="utf-8")
        if any(fragment in content for fragment in forbidden_fragments):
            leaked.append(str(path))

    assert leaked == []


def test_sdist_contains_public_docs_and_excludes_local_artifacts() -> None:
    sdists = sorted(Path("dist").glob("link2context-*.tar.gz"))
    if not sdists:
        pytest.skip("Run python -m build to validate sdist contents.")

    with tarfile.open(sdists[-1], "r:gz") as archive:
        names = archive.getnames()

    required = [
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "MANIFEST.in",
        "docs/index.md",
        "docs/architecture.md",
        "docs/export-contracts.md",
        "docs/github-publish.md",
        "docs/quickstart.md",
        "docs/roadmap.md",
        "docs/release-checklist.md",
        "examples/wechat_sample.html",
        "examples/xiaohongshu_sample.html",
        "examples/media-pipeline/fake_ocr.py",
    ]
    forbidden_parts = [
        "/.secrets/",
        "/build/",
        "/data/",
        "/dist/",
        "/graphify-out/",
        "/outputs/",
        "/work/",
        "/examples/wechat_urls_ian.txt",
    ]

    missing = [path for path in required if not any(name.endswith(f"/{path}") for name in names)]
    leaked = [name for name in names if any(part in name for part in forbidden_parts)]

    assert missing == []
    assert leaked == []

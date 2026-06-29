from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote


LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in Path(".").rglob("*.md")
        if not any(part in {".git", ".pytest_cache", "outputs", "graphify-out"} for part in path.parts)
    )


def local_link_target(markdown_path: Path, raw_target: str) -> Path | None:
    target = raw_target.strip()
    if not target or target.startswith("#"):
        return None
    if "://" in target or target.startswith("mailto:"):
        return None
    target = target.split("#", 1)[0]
    if not target:
        return None
    return (markdown_path.parent / unquote(target)).resolve()


def test_local_markdown_links_point_to_existing_files() -> None:
    missing: list[str] = []
    root = Path(".").resolve()

    for markdown_path in markdown_files():
        content = markdown_path.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(content):
            target = local_link_target(markdown_path, match.group(1))
            if target is None:
                continue
            try:
                display_target = target.relative_to(root)
            except ValueError:
                missing.append(f"{markdown_path}: {match.group(1)} escapes repository")
                continue
            if not target.exists():
                missing.append(f"{markdown_path}: {display_target}")

    assert missing == []

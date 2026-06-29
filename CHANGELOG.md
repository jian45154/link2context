# Changelog

All notable project changes should be recorded here once the repository starts using tagged releases.

## 0.1.1 - Alpha

### Added

- English README entry point for the public repository.
- GitHub Pages landing page with bilingual copy, platform adapter cards, and HTML documentation entry points.
- HTML documentation hub at `docs/index.html` with links back to Markdown source documents.

### Changed

- Updated release template structure for clearer highlights, change categories, verification, compatibility, and release notes.
- Included the root landing page and HTML docs in source distributions.

## 0.1.0 - Alpha

Initial open-source baseline.

### Added

- WeChat Official Account article extraction to `context.json` and `context.md`.
- Xiaohongshu note extraction with conservative public HTML parsing and optional operator-provided cookies.
- Batch URL processing, retry manifests, and batch verification.
- Local SQLite context store with import, ingest, search, tags, notes, statuses, citations, and quality reports.
- Graph, JSONL, Markdown, Neo4j Cypher, snapshot, and agent handoff exports.
- OCR/ASR media workflow commands for cache, queue, external command execution, verification, and write-back.
- CLI `--version` and `--help` coverage for both `link2context` and `link2context-store`.
- GitHub CI, issue templates, MIT license, contributing guide, security policy, and release checklist.

### Notes

- The project is alpha software.
- Platform adapters are read-only.
- Tests prefer offline fixtures; live platform behavior depends on the operator's local access and platform responses.

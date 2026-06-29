# Documentation Index

Link2Context is an open-source, local-first CLI and Python library for turning saved links and social content into agent-ready context and local knowledge-graph inputs.

## Start here

- [README](../README.md): Chinese project overview, install command, core CLI workflows.
- [English README](../README.en.md): English entry point and core workflow summary.
- [Quickstart](quickstart.md): offline fixture workflow from context files to store query and handoff export.
- [Changelog](../CHANGELOG.md): release notes and notable project changes.
- [Roadmap](roadmap.md): near-term and later open-source direction.
- [Open Source Project Goal](project-goal.md): project scope, non-goals, and milestones.
- [GitHub Publishing](github-publish.md): remote setup and final public repository checks.
- [Release Checklist](release-checklist.md): local checks before publishing or tagging.
- [Security Policy](../SECURITY.md): secret handling, platform boundaries, and vulnerability reporting.
- [Contributing](../CONTRIBUTING.md): local setup, PR checks, and contribution principles.
- [Code of Conduct](../CODE_OF_CONDUCT.md): expectations for public collaboration.

## Technical notes

- [Architecture](architecture.md): modules, data flow, contracts, and boundaries.
- [Import And Export Contracts](export-contracts.md): stable files, optional fields, and verification commands for external tools.
- [Media OCR And ASR Workflows](media-ocr-asr.md): fake, Tesseract, Sona/Vibe, and custom command-template examples.
- [Graph MVP](graph-mvp.md): entity, relationship, graph export, and profile scope.
- [Agent Query MVP](agent-query-mvp.md): keyword query package and retrieval sources.
- [Open Source Landscape Scan](competitive-scan.md): adjacent public projects and positioning.

## Local verification

```powershell
python -m pip install -e ".[dev]" --dry-run
python -m compileall -q link2context tests
python -m pytest tests -q
```

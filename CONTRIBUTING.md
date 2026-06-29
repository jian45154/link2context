# Contributing

Link2Context is an open-source, local-first CLI and Python library. Keep changes small, testable, and compatible with local/offline workflows.

## Local setup

```powershell
python -m pip install -e ".[dev]"
python -m pytest tests -q
```

Before opening a pull request, run:

```powershell
python -m pip install -e ".[dev]" --dry-run
python -m pytest tests -q
```

## Principles

- Prefer local fixtures and deterministic tests over live platform calls.
- Keep platform adapters read-only.
- Do not commit cookies, tokens, private exports, or downloaded media.
- Do not add platform bypass logic, automated writes, likes, comments, or posting features.
- Preserve `context.json`, `context.md`, SQLite, Markdown, JSONL, and graph export compatibility unless a migration is explicit.

## Good first changes

- Add or improve offline HTML fixtures.
- Improve extraction quality with tests.
- Add conservative OCR/ASR adapters behind explicit local commands.
- Improve documentation for self-hosted workflows.

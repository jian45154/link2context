# Architecture

Link2Context is a local-first pipeline. It turns operator-supplied links or saved HTML into context files, then optionally imports those files into a local SQLite store for graph, query, media, and export workflows.

## Data Flow

```text
URL / local HTML
  -> platform parser
  -> context.json + context.md
  -> SQLite store
  -> graph/query/media/export commands
  -> agent handoff or external tools
```

## Modules

- `link2context.cli`: main link-to-context CLI, batch manifests, retry flow, and batch verification.
- `link2context.wechat`: WeChat Official Account HTML extraction.
- `link2context.xiaohongshu`: Xiaohongshu HTML extraction and public-page cleanup.
- `link2context.fetch`: HTTP fetch helper used by live URL workflows.
- `link2context.agent_reach`: optional Agent Reach backend status integration.
- `link2context.graph`: rule-based entity and relationship extraction from context packages.
- `link2context.store`: SQLite schema, import/export, query, graph, media OCR/ASR, verification, and agent handoff commands.

## Context Contract

The first durable output is a directory with:

- `context.json`: structured source, article, content, media, agent package, and quality fields.
- `context.md`: a human-readable Markdown rendering for direct agent handoff.

Platform adapters should preserve this contract. If extraction is partial, they should report missing fields and warnings through `quality` instead of hiding uncertainty.

## Store Contract

The local store is SQLite. It imports `context.json` files into tables for:

- documents
- media
- citations
- entities
- document-entity links
- user tags, notes, and statuses
- relationships

Store commands should remain deterministic and usable offline. Live platform behavior belongs in fetch/parser layers, not in store commands.

## Media Contract

Images and videos are not processed by a bundled OCR/ASR engine. Link2Context prepares queues and command templates for external local tools, then verifies and applies result JSON/JSONL back into the store.

Execution boundaries:

- `cache-media` may download operator-selected media into local ignored output paths.
- `run-media-text` executes explicit operator-provided commands or built-in presets.
- `apply-media-text` writes recognized text to the media table.
- `reindex-media-text` turns recognized text into graph evidence.

Commands that execute external tools should keep dry-run or explicit review behavior where possible.

## Boundaries

- Platform adapters are read-only.
- Cookies and headers are operator-supplied and must not be persisted into context files.
- Generated stores, outputs, media caches, build artifacts, and secrets stay out of the repository.
- Hosted service, account automation, and platform bypass logic are non-goals.

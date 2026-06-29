# Import And Export Contracts

This page documents the current file contracts for external tools. These contracts are local-first and conservative: generated files should be verified before another agent, graph database, Markdown knowledge base, or backup workflow consumes them.

## Stability Levels

- Stable: deterministic structure used by tests and intended for external consumers.
- Optional: field may be absent, empty, or null when source content does not provide it.
- Experimental: useful today, but schema or ranking may change before 1.0.

## Context Directory

Command:

```powershell
python -m link2context --html examples/wechat_sample.html --url "https://mp.weixin.qq.com/s/example" --out outputs/sample
```

Files:

- `context.json`: stable structured extraction result.
- `context.md`: stable Markdown rendering for human or agent handoff.

Stable `context.json` top-level keys:

- `project`: project name.
- `source`: platform, URL, fetch time, and identifiers.
- `article`: title, account or author metadata, publication time, summary, and canonical URL.
- `content`: source HTML, Markdown, and plain text.
- `media`: cover image, images, and videos.
- `agent_package`: brief, key points, claims, entities, links, and citations.
- `quality`: status, warnings, and missing fields.

Optional fields include `article.author`, `article.published_at`, `article.summary`, media URLs, and extracted citations. Partial extraction should be represented through `quality.warnings` and `quality.missing_fields` rather than silently hidden.

## Batch Directory

Command:

```powershell
python -m link2context --url-list examples/wechat_urls.txt --out outputs/batch
python -m link2context --verify-batch outputs/batch
```

Stable files:

- `manifest.json`
- one subdirectory per successful URL, each containing `context.json` and `context.md`
- `error.json` for failed items

Stable manifest fields include `project`, `format`, `version`, `generated_at`, `count`, `succeeded`, `failed`, `ok`, `items`, `failures`, and `recommended_next`. Successful items include file details with size and `sha256` so external tools can verify that context files have not changed.

## SQLite Store

Command:

```powershell
python -m link2context.store --db data/link2context.db ingest outputs/sample
python -m link2context.store --db data/link2context.db doctor
```

The SQLite database is a local working store, not a public interchange artifact. External tools should prefer verified exports below unless they intentionally depend on Link2Context internals.

Stable table families:

- `documents`
- `media`
- `citations`
- `entities`
- `document_entities`
- `relationships`
- user annotations: tags, notes, statuses

## JSONL Dump

Commands:

```powershell
python -m link2context.store --db data/link2context.db dump-jsonl --out outputs/jsonl-dump
python -m link2context.store --db data/link2context.db verify-jsonl outputs/jsonl-dump
python -m link2context.store --db data/link2context.db import-jsonl outputs/jsonl-dump
```

Stable files:

- `documents.jsonl`
- `media.jsonl`
- `citations.jsonl`
- `entities.jsonl`
- `document_entities.jsonl`
- `document_tags.jsonl`
- `document_notes.jsonl`
- `document_status.jsonl`
- `relationships.jsonl`
- `manifest.json`

Each JSONL file is line-oriented UTF-8 JSON. The manifest stores expected files, row counts, byte sizes, and `sha256` hashes. Consumers should run `verify-jsonl` before import or downstream processing.

## Markdown Document Export

Commands:

```powershell
python -m link2context.store --db data/link2context.db dump-docs --out outputs/markdown-docs
python -m link2context.store --db data/link2context.db verify-docs outputs/markdown-docs
```

Stable files:

- one Markdown file per exported document
- `manifest.json`

Markdown exports are intended for Markdown-first knowledge bases and human review. They preserve source metadata, media records, citations, entities, relationships, and content in a readable format. Consumers should treat Markdown text as presentation, not as the canonical structured schema.

## Graph CSV

Commands:

```powershell
python -m link2context.store --db data/link2context.db dump-graph --out outputs/graph-csv
python -m link2context.store --db data/link2context.db verify-graph outputs/graph-csv
```

Stable files:

- `nodes.csv`
- `edges.csv`
- `manifest.json`

Stable node columns include `id`, `kind`, `label`, `entity_type`, `url`, `platform`, `account_name`, and `quality_status`.

Stable edge columns include `source`, `target`, `predicate`, `confidence`, and `evidence`.

Graph CSV is designed for tools such as graph databases, Gephi, notebooks, and custom import scripts. Entity extraction and ranking are experimental, but file shape and verification behavior are intended to remain deterministic.

## Neo4j Cypher

Commands:

```powershell
python -m link2context.store --db data/link2context.db dump-neo4j --out outputs/graph.cypher
python -m link2context.store --db data/link2context.db verify-neo4j outputs/graph.cypher
```

Stable files:

- `graph.cypher`
- `graph.cypher.manifest.json`

The Cypher output creates a unique node id constraint, then merges `Document`, `Entity`, and `Literal` nodes plus relationships derived from Link2Context predicates. The manifest records file detail and graph counts for verification.

## Agent Handoff Export

Commands:

```powershell
python -m link2context.store --db data/link2context.db export --out outputs/agent-handoff
python -m link2context.store --db data/link2context.db verify-export outputs/agent-handoff
```

Stable core files:

- `handoff.md`
- `manifest.json`
- `brief.md` / `brief.json`
- `doctor.md` / `doctor.json`
- `quality.md` / `quality.json`
- `evidence.md` / `evidence.json`
- `actions.md` / `actions.json`
- `agent-tasks.md` / `agent-tasks.json`
- `graph.json` / `graph.mmd`

Additional files may be added as new store commands mature. Consumers should read `manifest.json` and run `verify-export` rather than assuming a fixed exhaustive file list.

## Full Snapshot

Commands:

```powershell
python -m link2context.store --db data/link2context.db snapshot --out outputs/snapshot
python -m link2context.store --db data/link2context.db verify-snapshot outputs/snapshot
python -m link2context.store --db data/link2context.db import-snapshot outputs/snapshot
```

A snapshot combines agent handoff files, JSONL backup, Markdown docs, graph CSV, Neo4j Cypher, and root `snapshot.json`. Use this for portable backups or complete handoffs.

## Verification Rule

External consumers should follow this rule:

1. Generate the export.
2. Run the matching `verify-*` command.
3. Only consume files when verification reports OK.

This keeps downstream tools from ingesting partial, stale, or manually edited files without noticing.

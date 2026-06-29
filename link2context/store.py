from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from . import __version__
from .graph import extract_graph

PROFILE_TERM_STOP_NAMES = {
    "AI",
    "Agent",
    "Agents",
    "Article",
    "Articles",
    "Content",
    "Context",
    "File",
    "Files",
    "HTML",
    "HTTP",
    "HTTPS",
    "Image",
    "Images",
    "JSON",
    "Link",
    "Links",
    "Markdown",
    "Model",
    "Models",
    "Page",
    "Pages",
    "Post",
    "Posts",
    "Skill",
    "Skills",
    "Text",
    "Texts",
    "Tool",
    "Tools",
    "URL",
    "URLs",
    "Video",
    "Videos",
    "Web",
    "Website",
    "Websites",
}
PROFILE_ENTITY_STOP_NAMES = PROFILE_TERM_STOP_NAMES
MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD = 0.70
MEDIA_TEXT_PRESETS = {
    "tesseract": {
        "kind": "image",
        "template": 'tesseract "{input_source}" stdout -l {language}',
        "model": "tesseract",
        "language": "chi_sim+eng",
        "confidence": None,
        "description": "Run Tesseract against a local image path and print OCR text to stdout.",
    },
    "sona": {
        "kind": "video",
        "template": '"{tool_path}" transcribe "{preset_model}" "{input_source}" --language {language}',
        "tool_path": "sona",
        "model": "sona",
        "language": "zh",
        "confidence": None,
        "description": "Run Vibe/Sona whisper.cpp transcription against a local audio/video path.",
    },
    "vibe": {
        "kind": "video",
        "template": '"{tool_path}" transcribe "{preset_model}" "{input_source}" --language {language}',
        "tool_path": "vibe",
        "model": "vibe",
        "language": "zh",
        "confidence": None,
        "description": "Run Vibe whisper.cpp-style transcription against a local audio/video path.",
    },
}


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL UNIQUE,
  platform TEXT NOT NULL,
  title TEXT,
  account_name TEXT,
  author TEXT,
  published_at TEXT,
  fetched_at TEXT,
  summary TEXT,
  plain_text TEXT,
  markdown TEXT,
  quality_status TEXT,
  context_json TEXT NOT NULL,
  imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS media (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  media_index INTEGER NOT NULL,
  url TEXT,
  local_path TEXT,
  cache_status TEXT,
  cache_error TEXT,
  cache_sha256 TEXT,
  cache_bytes INTEGER,
  cache_checked_at TEXT,
  status TEXT,
  text TEXT,
  text_model TEXT,
  text_language TEXT,
  text_confidence REAL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS citations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL,
  ref TEXT NOT NULL,
  text TEXT NOT NULL,
  source TEXT,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  normalized_name TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS document_entities (
  document_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  confidence REAL NOT NULL,
  evidence TEXT,
  PRIMARY KEY(document_id, entity_id, role),
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relationships (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object TEXT NOT NULL,
  confidence REAL NOT NULL,
  evidence TEXT,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS document_tags (
  document_id INTEGER NOT NULL,
  tag TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(document_id, tag),
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS document_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL,
  note TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS document_status (
  document_id INTEGER PRIMARY KEY,
  status TEXT NOT NULL,
  note TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_documents_platform ON documents(platform);
CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(title);
CREATE INDEX IF NOT EXISTS idx_documents_quality ON documents(quality_status);
CREATE INDEX IF NOT EXISTS idx_media_document ON media(document_id);
CREATE INDEX IF NOT EXISTS idx_citations_document ON citations(document_id);
CREATE INDEX IF NOT EXISTS idx_entities_normalized_name ON entities(normalized_name);
CREATE INDEX IF NOT EXISTS idx_document_entities_entity ON document_entities(entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_document ON relationships(document_id);
CREATE INDEX IF NOT EXISTS idx_document_tags_tag ON document_tags(tag);
CREATE INDEX IF NOT EXISTS idx_document_notes_document ON document_notes(document_id);
CREATE INDEX IF NOT EXISTS idx_document_status_status ON document_status(status);
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="link2context-store",
        description="Import Link2Context context.json files into a local SQLite knowledge store.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--db", default="data/link2context.db", help="SQLite database path.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="Import context.json files.")
    import_parser.add_argument("paths", nargs="+", help="Files or directories to import.")

    ingest_parser = subparsers.add_parser("ingest", help="Import contexts and print an agent-readiness check.")
    ingest_parser.add_argument("paths", nargs="+", help="Files or directories to ingest.")
    ingest_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    search_parser = subparsers.add_parser("search", help="Search imported documents.")
    search_parser.add_argument("query", help="Text to search in title, summary, and body.")
    search_parser.add_argument("--limit", type=int, default=10)

    doc_parser = subparsers.add_parser("doc", help="Open one imported document by id or URL.")
    doc_parser.add_argument("document", help="Document id or URL.")
    doc_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    tag_parser = subparsers.add_parser("tag", help="Add user tags to one imported document.")
    tag_parser.add_argument("document", help="Document id or URL.")
    tag_parser.add_argument("tags", nargs="+", help="One or more user tags to attach.")
    tag_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    tags_parser = subparsers.add_parser("tags", help="List user tags and tagged documents.")
    tags_parser.add_argument("--limit", type=int, default=20)
    tags_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    note_parser = subparsers.add_parser("note", help="Add a user note to one imported document.")
    note_parser.add_argument("document", help="Document id or URL.")
    note_parser.add_argument("note", nargs="+", help="Note text to attach to the document.")
    note_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    notes_parser = subparsers.add_parser("notes", help="List user notes across imported documents.")
    notes_parser.add_argument("--limit", type=int, default=20)
    notes_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    mark_parser = subparsers.add_parser("mark", help="Set a user workflow status for one imported document.")
    mark_parser.add_argument("document", help="Document id or URL.")
    mark_parser.add_argument("status", choices=("inbox", "later", "reading", "read", "archived"))
    mark_parser.add_argument("--note", help="Optional status note.")
    mark_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    statuses_parser = subparsers.add_parser("statuses", help="List user workflow statuses.")
    statuses_parser.add_argument("--status", choices=("inbox", "later", "reading", "read", "archived"))
    statuses_parser.add_argument("--limit", type=int, default=20)
    statuses_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    annotations_parser = subparsers.add_parser("annotations", help="List documents with user tags, notes, or workflow status.")
    annotations_parser.add_argument("--limit", type=int, default=20)
    annotations_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    citation_parser = subparsers.add_parser("citation", help="Open citations for one document by id/URL and optional ref.")
    citation_parser.add_argument("document", help="Document id or URL.")
    citation_parser.add_argument("ref", nargs="?", help="Optional citation ref, such as paragraph_12.")
    citation_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    evidence_parser = subparsers.add_parser("evidence", help="Search citation evidence across the local store.")
    evidence_parser.add_argument(
        "query",
        nargs="?",
        help="Optional text to search in citation text, refs, sources, titles, and URLs.",
    )
    evidence_parser.add_argument("--limit", type=int, default=50)
    evidence_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    related_parser = subparsers.add_parser("related", help="Find documents related to one imported document.")
    related_parser.add_argument("document", help="Source document id or URL.")
    related_parser.add_argument("--limit", type=int, default=5)
    related_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    duplicates_parser = subparsers.add_parser("duplicates", help="Find duplicate or near-duplicate imported documents.")
    duplicates_parser.add_argument("--limit", type=int, default=20)
    duplicates_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    query_parser = subparsers.add_parser("query", help="Return an agent-ready evidence package for a query.")
    query_parser.add_argument("query", help="Question or keyword to retrieve from the local store.")
    query_parser.add_argument("--limit", type=int, default=5)
    query_parser.add_argument("--format", choices=("json", "markdown"), default="json")

    entities_parser = subparsers.add_parser("entities", help="List extracted entities.")
    entities_parser.add_argument("--limit", type=int, default=20)

    explain_parser = subparsers.add_parser("explain", help="Explain an entity with documents, citations, and relations.")
    explain_parser.add_argument("entity", help="Entity name to explain.")
    explain_parser.add_argument("--limit", type=int, default=5)
    explain_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    profile_parser = subparsers.add_parser("profile", help="Print a conservative interest profile.")
    profile_parser.add_argument("--limit", type=int, default=20)
    profile_parser.add_argument("--format", choices=("json", "markdown"), default="json")

    brief_parser = subparsers.add_parser("brief", help="Print an agent-ready external brain brief.")
    brief_parser.add_argument("--limit", type=int, default=10)
    brief_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    export_parser = subparsers.add_parser("export", help="Export an agent handoff bundle.")
    export_parser.add_argument("--out", required=True, help="Output directory for the handoff bundle.")
    export_parser.add_argument("--limit", type=int, default=20)

    snapshot_parser = subparsers.add_parser("snapshot", help="Export a complete handoff plus JSONL backup snapshot.")
    snapshot_parser.add_argument("--out", required=True, help="Output directory for the snapshot.")
    snapshot_parser.add_argument("--limit", type=int, default=20)

    verify_snapshot_parser = subparsers.add_parser("verify-snapshot", help="Verify a complete Link2Context snapshot.")
    verify_snapshot_parser.add_argument("path", help="Snapshot directory containing snapshot.json.")
    verify_snapshot_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    import_snapshot_parser = subparsers.add_parser(
        "import-snapshot",
        help="Import a verified Link2Context snapshot into the local store.",
    )
    import_snapshot_parser.add_argument("path", help="Snapshot directory containing snapshot.json.")
    import_snapshot_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    dump_parser = subparsers.add_parser("dump-jsonl", help="Export portable JSONL tables for external tools.")
    dump_parser.add_argument("--out", required=True, help="Output directory for JSONL files.")

    dump_docs_parser = subparsers.add_parser("dump-docs", help="Export imported documents as Markdown files.")
    dump_docs_parser.add_argument("--out", required=True, help="Output directory for Markdown files.")
    dump_docs_parser.add_argument("--limit", type=int, default=100)

    verify_docs_parser = subparsers.add_parser("verify-docs", help="Verify a Markdown document export.")
    verify_docs_parser.add_argument("path", help="Markdown document export directory containing manifest.json.")
    verify_docs_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    import_jsonl_parser = subparsers.add_parser("import-jsonl", help="Import a verified JSONL dump into the local store.")
    import_jsonl_parser.add_argument("path", help="JSONL dump directory containing manifest.json.")
    import_jsonl_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    verify_jsonl_parser = subparsers.add_parser("verify-jsonl", help="Verify a JSONL dump manifest and row counts.")
    verify_jsonl_parser.add_argument("path", help="JSONL dump directory containing manifest.json.")
    verify_jsonl_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    verify_graph_parser = subparsers.add_parser("verify-graph", help="Verify a graph CSV export manifest and row counts.")
    verify_graph_parser.add_argument("path", help="Graph CSV directory containing manifest.json.")
    verify_graph_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    verify_neo4j_parser = subparsers.add_parser("verify-neo4j", help="Verify a Neo4j Cypher graph export.")
    verify_neo4j_parser.add_argument("path", help="Neo4j .cypher file.")
    verify_neo4j_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    verify_export_parser = subparsers.add_parser("verify-export", help="Verify an exported agent handoff bundle.")
    verify_export_parser.add_argument("path", help="Export directory containing manifest.json.")
    verify_export_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    verify_auto_queue_parser = subparsers.add_parser("verify-auto-queue", help="Verify exported auto-queue command files before execution.")
    verify_auto_queue_parser.add_argument("path", help="Export directory containing auto-queue.commands.txt and auto-queue.jsonl.")
    verify_auto_queue_parser.add_argument("--base-dir", default=".", help="Base directory for relative media local_path checks.")
    verify_auto_queue_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    verify_auto_queue_next_parser = subparsers.add_parser(
        "verify-auto-queue-next",
        help="Verify generated auto-queue next OCR/ASR command files before manual execution.",
    )
    verify_auto_queue_next_parser.add_argument(
        "path",
        help="Export directory containing auto-queue-next.commands.txt and auto-queue-next.jsonl.",
    )
    verify_auto_queue_next_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    run_auto_queue_next_parser = subparsers.add_parser(
        "run-auto-queue-next",
        help="Run verified OCR/ASR next commands, dry-run by default.",
    )
    run_auto_queue_next_parser.add_argument(
        "path",
        help="Export directory containing auto-queue-next.commands.txt and auto-queue-next.jsonl.",
    )
    run_auto_queue_next_parser.add_argument("--execute", action="store_true", help="Actually execute commands after verification passes.")
    run_auto_queue_next_parser.add_argument("--timeout", type=int, default=120, help="Timeout seconds per command when --execute is used.")
    run_auto_queue_next_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    run_auto_queue_parser = subparsers.add_parser("run-auto-queue", help="Run verified auto-queue commands, dry-run by default.")
    run_auto_queue_parser.add_argument("path", help="Export directory containing auto-queue.commands.txt and auto-queue.jsonl.")
    run_auto_queue_parser.add_argument("--base-dir", default=".", help="Base directory for relative media local_path checks.")
    run_auto_queue_parser.add_argument("--execute", action="store_true", help="Actually execute commands after verification passes.")
    run_auto_queue_parser.add_argument("--timeout", type=int, default=120, help="Timeout seconds per command when --execute is used.")
    run_auto_queue_parser.add_argument("--next-preset", choices=tuple(MEDIA_TEXT_PRESETS), help="Use a run-media-text preset in generated next commands.")
    run_auto_queue_parser.add_argument("--next-preset-model", help="Preset model file/name for generated next commands.")
    run_auto_queue_parser.add_argument("--next-tool-path", help="Preset executable override for generated next commands.")
    run_auto_queue_parser.add_argument("--next-command-template", help="Custom run-media-text command template for generated next commands.")
    run_auto_queue_parser.add_argument("--next-model", default="external-command", help="Model metadata for generated next commands.")
    run_auto_queue_parser.add_argument("--next-language", default="", help="Language metadata for generated next commands.")
    run_auto_queue_parser.add_argument("--next-confidence", type=float, help="Confidence metadata for generated next commands.")
    run_auto_queue_parser.add_argument("--next-out-dir", default="outputs", help="Output directory for generated run-media-text result files.")
    run_auto_queue_parser.add_argument(
        "--write-next",
        action="store_true",
        help="Write generated next commands to auto-queue-next.commands.txt and auto-queue-next.jsonl.",
    )
    run_auto_queue_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    doctor_parser = subparsers.add_parser("doctor", help="Check whether the local store is useful for agents.")
    doctor_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    timeline_parser = subparsers.add_parser("timeline", help="List imported documents by published/imported time.")
    timeline_parser.add_argument("--limit", type=int, default=20)
    timeline_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    media_parser = subparsers.add_parser("media", help="List imported media items and processing status.")
    media_parser.add_argument("--kind", choices=("all", "image", "video"), default="all")
    media_parser.add_argument("--status", help="Filter by media processing status.")
    media_parser.add_argument("--limit", type=int, default=50)
    media_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    media_pipeline_parser = subparsers.add_parser("media-pipeline", help="Summarize OCR/ASR media processing pipeline status.")
    media_pipeline_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    media_text_presets_parser = subparsers.add_parser(
        "media-text-presets",
        help="List built-in OCR/ASR presets and local executable availability.",
    )
    media_text_presets_parser.add_argument("--preset-model", help="Model path/name to validate for presets that require one.")
    media_text_presets_parser.add_argument(
        "--model-dir",
        action="append",
        default=[],
        help="Additional directory to scan for local Sona/Whisper model files. Can be repeated.",
    )
    media_text_presets_parser.add_argument("--tool-path", help="Override preset executable path for availability checks.")
    media_text_presets_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    prepare_media_model_parser = subparsers.add_parser(
        "prepare-media-model",
        help="Download and verify a local OCR/ASR model file, dry-run by default.",
    )
    prepare_media_model_parser.add_argument("--url", required=True, help="Model download URL.")
    prepare_media_model_parser.add_argument("--out", default="models/ggml-small.bin", help="Output model path.")
    prepare_media_model_parser.add_argument("--sha256", help="Expected SHA-256 checksum.")
    prepare_media_model_parser.add_argument("--execute", action="store_true", help="Actually download and write the model file.")
    prepare_media_model_parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing model file.")
    prepare_media_model_parser.add_argument("--timeout", type=int, default=120, help="Download timeout in seconds.")
    prepare_media_model_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    cache_media_parser = subparsers.add_parser("cache-media", help="Download queued media and store local_path.")
    cache_media_parser.add_argument("--kind", choices=("all", "image", "video"), default="all")
    cache_media_parser.add_argument("--status", default="not_processed", help="Media status to cache.")
    cache_media_parser.add_argument("--limit", type=int, default=50)
    cache_media_parser.add_argument("--out-dir", default="outputs/media-cache", help="Directory for cached media files.")
    cache_media_parser.add_argument("--overwrite", action="store_true", help="Redownload items that already have local_path.")
    cache_media_parser.add_argument("--timeout", type=int, default=30)
    cache_media_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    export_media_fixes_parser = subparsers.add_parser(
        "export-media-fixes",
        help="Export failed media cache items as an editable JSONL repair manifest.",
    )
    export_media_fixes_parser.add_argument("--out", required=True, help="Output JSONL path for media fixes.")
    export_media_fixes_parser.add_argument("--kind", choices=("all", "image", "video"), default="all")
    export_media_fixes_parser.add_argument("--status", default="not_processed", help="Media status to export.")
    export_media_fixes_parser.add_argument(
        "--cache-status",
        default="failed",
        help="Cache status to export, or failed for missing_url/download_failed/empty_response.",
    )
    export_media_fixes_parser.add_argument("--limit", type=int, default=50)
    export_media_fixes_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    apply_media_fixes_parser = subparsers.add_parser(
        "apply-media-fixes",
        help="Apply fixed_url/fixed_local_path values from a media repair JSONL manifest.",
    )
    apply_media_fixes_parser.add_argument("path", help="JSONL file created by export-media-fixes.")
    apply_media_fixes_parser.add_argument("--force", action="store_true", help="Apply even when verify-media-fixes reports errors.")
    apply_media_fixes_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    verify_media_fixes_parser = subparsers.add_parser(
        "verify-media-fixes",
        help="Verify a media repair JSONL manifest before applying it.",
    )
    verify_media_fixes_parser.add_argument("path", help="JSONL file created by export-media-fixes.")
    verify_media_fixes_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    queue_parser = subparsers.add_parser("queue", help="Print an OCR/ASR processing queue for imported media.")
    queue_parser.add_argument("--kind", choices=("all", "image", "video"), default="all")
    queue_parser.add_argument("--status", default="not_processed", help="Media status to queue.")
    queue_parser.add_argument("--limit", type=int, default=50)
    queue_parser.add_argument(
        "--low-confidence",
        action="store_true",
        help="Queue media whose existing OCR/ASR text confidence is below the review threshold.",
    )
    queue_parser.add_argument("--format", choices=("json", "markdown", "jsonl"), default="markdown")

    run_media_parser = subparsers.add_parser(
        "run-media-text",
        help="Run an external OCR/ASR command over the media queue and write apply-media-text results.",
    )
    run_media_parser.add_argument("--kind", choices=("all", "image", "video"), default="all")
    run_media_parser.add_argument("--status", default="not_processed", help="Media status to queue.")
    run_media_parser.add_argument("--limit", type=int, default=50)
    run_media_parser.add_argument(
        "--low-confidence",
        action="store_true",
        help="Run against low-confidence media text instead of unprocessed media.",
    )
    run_media_parser.add_argument("--out", required=True, help="Output JSONL path for OCR/ASR results.")
    run_media_parser.add_argument(
        "--preset",
        choices=tuple(MEDIA_TEXT_PRESETS),
        help="Use a built-in command template preset instead of writing --command-template.",
    )
    run_media_parser.add_argument("--preset-model", help="Model file/name required by some presets, such as sona.")
    run_media_parser.add_argument("--tool-path", help="Override the executable path used by a preset.")
    run_media_parser.add_argument(
        "--command-template",
        help=(
            "Shell command template. Available fields: {input_url}, {kind}, "
            "{document_id}, {media_index}, {document_title}."
        ),
    )
    run_media_parser.add_argument("--model", default="external-command")
    run_media_parser.add_argument("--language", default="")
    run_media_parser.add_argument("--confidence", type=float)
    run_media_parser.add_argument("--timeout", type=int, default=120)
    run_media_parser.add_argument("--apply", action="store_true", help="Apply generated results after writing them.")
    run_media_parser.add_argument(
        "--reindex",
        action="store_true",
        help="When used with --apply, rebuild media.text graph signals for touched documents.",
    )
    run_media_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    apply_media_parser = subparsers.add_parser("apply-media-text", help="Apply OCR/ASR text results to media records.")
    apply_media_parser.add_argument("path", help="JSON or JSONL file with OCR/ASR results.")
    apply_media_parser.add_argument("--status", default="processed", help="Status to set when text is applied.")
    apply_media_parser.add_argument(
        "--reindex",
        action="store_true",
        help="Rebuild media.text graph signals after applying OCR/ASR results.",
    )
    apply_media_parser.add_argument("--reindex-limit", type=int, default=200)
    apply_media_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    verify_media_text_parser = subparsers.add_parser(
        "verify-media-text",
        help="Verify OCR/ASR result JSONL has been applied to media rows.",
    )
    verify_media_text_parser.add_argument("path", help="JSON or JSONL file with OCR/ASR results.")
    verify_media_text_parser.add_argument("--status", default="processed", help="Expected media status after apply-media-text.")
    verify_media_text_parser.add_argument(
        "--require-reindex",
        action="store_true",
        help="Require media.text graph signals for touched documents.",
    )
    verify_media_text_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    reindex_media_parser = subparsers.add_parser("reindex-media-text", help="Extract graph entities from media text.")
    reindex_media_parser.add_argument("--limit", type=int, default=200)
    reindex_media_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    quality_parser = subparsers.add_parser("quality", help="List document quality status, warnings, and missing fields.")
    quality_parser.add_argument("--status", help="Filter by quality status, such as ok or partial.")
    quality_parser.add_argument("--limit", type=int, default=50)
    quality_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    actions_parser = subparsers.add_parser("actions", help="Print prioritized next actions for improving the store.")
    actions_parser.add_argument("--limit", type=int, default=20)
    actions_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    tasks_parser = subparsers.add_parser("tasks", help="Print a machine-readable agent handoff task checklist.")
    tasks_parser.add_argument("--limit", type=int, default=20)
    tasks_parser.add_argument("--kind", help="Filter tasks by kind, such as query, media, read_now, or handoff.")
    tasks_parser.add_argument("--source", help="Filter tasks by source, such as actions, curate, or starter_query.")
    tasks_parser.add_argument("--contains", help="Filter tasks by text in title, detail, source, kind, or command.")
    tasks_parser.add_argument("--max-priority", type=int, help="Only include tasks with priority at or below this value.")
    tasks_parser.add_argument("--retry-mode", help="Filter media cache tasks by retry mode, such as retry_download.")
    tasks_parser.add_argument("--cache-status", help="Filter media cache tasks by cache status, such as download_failed.")
    tasks_parser.add_argument("--format", choices=("json", "markdown", "jsonl", "commands"), default="markdown")

    sources_parser = subparsers.add_parser("sources", help="Summarize source accounts and platforms.")
    sources_parser.add_argument("--limit", type=int, default=20)
    sources_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    coverage_parser = subparsers.add_parser("coverage", help="Summarize platform, source, graph, and media coverage.")
    coverage_parser.add_argument("--limit", type=int, default=20)
    coverage_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    topics_parser = subparsers.add_parser("topics", help="Summarize topic/entity signals with evidence.")
    topics_parser.add_argument("--type", dest="entity_type", help="Filter by entity type, such as topic or term.")
    topics_parser.add_argument("--limit", type=int, default=20)
    topics_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    clusters_parser = subparsers.add_parser("clusters", help="Group documents into topic clusters by shared entities.")
    clusters_parser.add_argument("--min-docs", type=int, default=2, help="Minimum documents required for a cluster.")
    clusters_parser.add_argument("--limit", type=int, default=20)
    clusters_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    questions_parser = subparsers.add_parser("questions", help="Generate follow-up questions from topic clusters.")
    questions_parser.add_argument("--limit", type=int, default=20)
    questions_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    relations_parser = subparsers.add_parser("relations", help="List graph relationships by entity or predicate.")
    relations_parser.add_argument("entity", nargs="?", help="Optional subject/object entity to filter.")
    relations_parser.add_argument("--predicate", help="Filter by relationship predicate.")
    relations_parser.add_argument("--limit", type=int, default=50)
    relations_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    digest_parser = subparsers.add_parser("digest", help="Print a compact review of recent store activity.")
    digest_parser.add_argument("--limit", type=int, default=10)
    digest_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    review_parser = subparsers.add_parser("review", help="Print a one-page agent review of the local store.")
    review_parser.add_argument("--limit", type=int, default=10)
    review_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    inbox_parser = subparsers.add_parser("inbox", help="Print a daily triage view for the external brain store.")
    inbox_parser.add_argument("--limit", type=int, default=10)
    inbox_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    curate_parser = subparsers.add_parser("curate", help="Print action lanes for keeping collected links useful.")
    curate_parser.add_argument("--limit", type=int, default=10)
    curate_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")

    graph_parser = subparsers.add_parser("graph", help="Export documents and entities as graph JSON.")
    graph_parser.add_argument("--limit", type=int, default=100)
    graph_parser.add_argument("--include-terms", action="store_true", help="Include noisy term entities in graph export.")
    graph_parser.add_argument("--format", choices=("json", "mermaid"), default="json")

    dump_graph_parser = subparsers.add_parser("dump-graph", help="Export graph nodes and edges as CSV files.")
    dump_graph_parser.add_argument("--out", required=True, help="Output directory for graph CSV files.")
    dump_graph_parser.add_argument("--limit", type=int, default=100)
    dump_graph_parser.add_argument("--include-terms", action="store_true", help="Include noisy term entities in graph CSV.")

    dump_neo4j_parser = subparsers.add_parser("dump-neo4j", help="Export graph as a Neo4j Cypher import script.")
    dump_neo4j_parser.add_argument("--out", required=True, help="Output .cypher file.")
    dump_neo4j_parser.add_argument("--limit", type=int, default=100)
    dump_neo4j_parser.add_argument("--include-terms", action="store_true", help="Include noisy term entities in Cypher.")

    subparsers.add_parser("stats", help="Print document counts.")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with connect(db_path) as conn:
        init_db(conn)
        if args.command == "import":
            imported = import_paths(conn, [Path(path) for path in args.paths])
            print(f"Imported {imported} context file(s) into {db_path}")
        elif args.command == "ingest":
            result = ingest_paths(conn, [Path(path) for path in args.paths])
            if args.format == "markdown":
                print(render_ingest_markdown(result, db_path))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "search":
            for row in search(conn, args.query, args.limit):
                print(f"[{row['id']}] [{row['platform']}] {row['title'] or 'Untitled'}")
                print(f"  url: {row['url']}")
                print(f"  status: {row['quality_status']}")
        elif args.command == "doc":
            document = get_document(conn, args.document)
            if args.format == "markdown":
                print(render_document_markdown(document))
            else:
                print(json.dumps(document, ensure_ascii=False, indent=2))
        elif args.command == "tag":
            result = add_document_tags(conn, args.document, args.tags)
            if args.format == "markdown":
                print(render_tag_result_markdown(result))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "tags":
            report = tag_report(conn, args.limit)
            if args.format == "markdown":
                print(render_tags_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "note":
            result = add_document_note(conn, args.document, " ".join(args.note))
            if args.format == "markdown":
                print(render_note_result_markdown(result))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "notes":
            report = notes_report(conn, args.limit)
            if args.format == "markdown":
                print(render_notes_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "mark":
            result = mark_document_status(conn, args.document, args.status, args.note)
            if args.format == "markdown":
                print(render_mark_result_markdown(result))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "statuses":
            report = status_report(conn, args.status, args.limit)
            if args.format == "markdown":
                print(render_statuses_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "annotations":
            report = annotations_report(conn, args.limit)
            if args.format == "markdown":
                print(render_annotations_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "citation":
            citation = citation_lookup(conn, args.document, args.ref)
            if args.format == "markdown":
                print(render_citation_markdown(citation))
            else:
                print(json.dumps(citation, ensure_ascii=False, indent=2))
        elif args.command == "evidence":
            report = evidence_report(conn, args.query, args.limit)
            if args.format == "markdown":
                print(render_evidence_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "related":
            related = related_documents(conn, args.document, args.limit)
            if args.format == "markdown":
                print(render_related_markdown(related))
            else:
                print(json.dumps(related, ensure_ascii=False, indent=2))
        elif args.command == "duplicates":
            report = duplicate_report(conn, args.limit)
            if args.format == "markdown":
                print(render_duplicate_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "query":
            package = agent_query(conn, args.query, args.limit)
            if args.format == "markdown":
                print(render_query_markdown(package))
            else:
                print(json.dumps(package, ensure_ascii=False, indent=2))
        elif args.command == "entities":
            for row in list_entities(conn, args.limit):
                print(f"{row['name']} ({row['type']}): {row['documents']} document(s)")
        elif args.command == "explain":
            explanation = explain_entity(conn, args.entity, args.limit)
            if args.format == "markdown":
                print(render_entity_explanation_markdown(explanation))
            else:
                print(json.dumps(explanation, ensure_ascii=False, indent=2))
        elif args.command == "profile":
            profile = interest_profile(conn, args.limit)
            if args.format == "markdown":
                print(render_profile_markdown(profile))
            else:
                print(json.dumps(profile, ensure_ascii=False, indent=2))
        elif args.command == "brief":
            brief = external_brain_brief(conn, args.limit)
            if args.format == "markdown":
                print(render_brief_markdown(brief))
            else:
                print(json.dumps(brief, ensure_ascii=False, indent=2))
        elif args.command == "export":
            manifest = export_agent_handoff(conn, Path(args.out), args.limit)
            print(f"Exported agent handoff bundle to {args.out}")
            for file_name in manifest["files"]:
                print(f"  {file_name}")
        elif args.command == "snapshot":
            manifest = export_snapshot(conn, Path(args.out), args.limit)
            print(f"Exported Link2Context snapshot to {args.out}")
            print(f"  {manifest['handoff']['path']}")
            print(f"  {manifest['jsonl']['path']}")
            print(f"  {manifest['markdown_docs']['path']}")
            print(f"  {manifest['graph_csv']['path']}")
            print(f"  {manifest['neo4j']['path']}")
            print("  snapshot.json")
        elif args.command == "verify-snapshot":
            report = verify_snapshot(Path(args.path))
            if args.format == "markdown":
                print(render_verify_snapshot_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "import-snapshot":
            report = import_snapshot(conn, Path(args.path))
            if args.format == "markdown":
                print(render_import_snapshot_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "dump-jsonl":
            manifest = dump_jsonl(conn, Path(args.out))
            print(f"Exported JSONL dump to {args.out}")
            for file_name in manifest["files"]:
                print(f"  {file_name}")
        elif args.command == "dump-docs":
            manifest = dump_docs_markdown(conn, Path(args.out), args.limit)
            print(f"Exported Markdown documents to {args.out}")
            for file_name in manifest["files"]:
                print(f"  {file_name}")
        elif args.command == "verify-docs":
            report = verify_docs_markdown(Path(args.path))
            if args.format == "markdown":
                print(render_verify_docs_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "import-jsonl":
            report = import_jsonl_dump(conn, Path(args.path))
            if args.format == "markdown":
                print(render_import_jsonl_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "verify-jsonl":
            report = verify_jsonl_dump(Path(args.path))
            if args.format == "markdown":
                print(render_verify_jsonl_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "verify-graph":
            report = verify_graph_csv(Path(args.path))
            if args.format == "markdown":
                print(render_verify_graph_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "verify-neo4j":
            report = verify_neo4j_cypher(Path(args.path))
            if args.format == "markdown":
                print(render_verify_neo4j_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "verify-export":
            report = verify_export_bundle(Path(args.path))
            if args.format == "markdown":
                print(render_verify_export_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "verify-auto-queue":
            report = verify_auto_queue(Path(args.path), Path(args.base_dir))
            if args.format == "markdown":
                print(render_verify_auto_queue_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "verify-auto-queue-next":
            report = verify_auto_queue_next(Path(args.path))
            if args.format == "markdown":
                print(render_verify_auto_queue_next_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "run-auto-queue-next":
            report = run_auto_queue_next(Path(args.path), execute=args.execute, timeout=args.timeout)
            if args.format == "markdown":
                print(render_run_auto_queue_next_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "run-auto-queue":
            next_plan = {
                "preset": args.next_preset,
                "preset_model": args.next_preset_model,
                "tool_path": args.next_tool_path,
                "command_template": args.next_command_template,
                "model": args.next_model,
                "language": args.next_language,
                "confidence": args.next_confidence,
                "out_dir": args.next_out_dir,
            }
            report = run_auto_queue(
                Path(args.path),
                Path(args.base_dir),
                execute=args.execute,
                timeout=args.timeout,
                next_plan=next_plan,
                write_next=args.write_next,
            )
            if args.format == "markdown":
                print(render_run_auto_queue_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "doctor":
            report = store_doctor(conn)
            if args.format == "markdown":
                print(render_doctor_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "timeline":
            timeline = document_timeline(conn, args.limit)
            if args.format == "markdown":
                print(render_timeline_markdown(timeline))
            else:
                print(json.dumps(timeline, ensure_ascii=False, indent=2))
        elif args.command == "media":
            inventory = media_inventory(conn, args.kind, args.status, args.limit)
            if args.format == "markdown":
                print(render_media_markdown(inventory))
            else:
                print(json.dumps(inventory, ensure_ascii=False, indent=2))
        elif args.command == "media-pipeline":
            report = media_pipeline_status(conn)
            if args.format == "markdown":
                print(render_media_pipeline_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "media-text-presets":
            report = media_text_presets_report(
                preset_model=args.preset_model,
                model_dirs=[Path(value) for value in args.model_dir],
                tool_path=args.tool_path,
            )
            if args.format == "markdown":
                print(render_media_text_presets_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "prepare-media-model":
            report = prepare_media_model(
                args.url,
                Path(args.out),
                sha256=args.sha256,
                execute=args.execute,
                overwrite=args.overwrite,
                timeout=args.timeout,
            )
            if args.format == "markdown":
                print(render_prepare_media_model_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "cache-media":
            report = cache_media(conn, args.kind, args.status, args.limit, Path(args.out_dir), args.overwrite, args.timeout)
            if args.format == "markdown":
                print(render_cache_media_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "export-media-fixes":
            report = export_media_fixes(conn, Path(args.out), args.kind, args.status, args.cache_status, args.limit)
            if args.format == "markdown":
                print(render_export_media_fixes_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "apply-media-fixes":
            report = apply_media_fixes(conn, Path(args.path), force=args.force)
            if args.format == "markdown":
                print(render_apply_media_fixes_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "verify-media-fixes":
            report = verify_media_fixes(conn, Path(args.path))
            if args.format == "markdown":
                print(render_verify_media_fixes_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "queue":
            queue = media_queue(conn, args.kind, args.status, args.limit, args.low_confidence)
            if args.format == "markdown":
                print(render_media_queue_markdown(queue))
            elif args.format == "jsonl":
                for item in queue["items"]:
                    print(json.dumps(item, ensure_ascii=False))
            else:
                print(json.dumps(queue, ensure_ascii=False, indent=2))
        elif args.command == "run-media-text":
            report = run_media_text(
                conn,
                kind=args.kind,
                status=args.status,
                limit=args.limit,
                low_confidence=args.low_confidence,
                out_path=Path(args.out),
                command_template=args.command_template,
                preset=args.preset,
                preset_model=args.preset_model,
                tool_path=args.tool_path,
                model=args.model,
                language=args.language,
                confidence=args.confidence,
                timeout=args.timeout,
                apply=args.apply,
                reindex=args.reindex,
            )
            if args.format == "markdown":
                print(render_run_media_text_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "apply-media-text":
            report = apply_media_text(conn, Path(args.path), args.status, args.reindex, args.reindex_limit)
            if args.format == "markdown":
                print(render_apply_media_text_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "verify-media-text":
            report = verify_media_text(conn, Path(args.path), args.status, args.require_reindex)
            if args.format == "markdown":
                print(render_verify_media_text_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "reindex-media-text":
            report = reindex_media_text(conn, args.limit)
            if args.format == "markdown":
                print(render_reindex_media_text_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "quality":
            report = quality_report(conn, args.status, args.limit)
            if args.format == "markdown":
                print(render_quality_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "actions":
            plan = action_plan(conn, args.limit)
            if args.format == "markdown":
                print(render_action_plan_markdown(plan))
            else:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
        elif args.command == "tasks":
            report = agent_task_report(
                conn,
                args.limit,
                args.kind,
                args.source,
                args.max_priority,
                args.contains,
                args.retry_mode,
                args.cache_status,
            )
            if args.format == "markdown":
                print(render_agent_tasks_markdown(report))
            elif args.format == "jsonl":
                for task in report["tasks"]:
                    print(json.dumps(task, ensure_ascii=False))
            elif args.format == "commands":
                for command in agent_task_commands(report):
                    print(command)
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "sources":
            report = source_report(conn, args.limit)
            if args.format == "markdown":
                print(render_sources_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "coverage":
            report = coverage_report(conn, args.limit)
            if args.format == "markdown":
                print(render_coverage_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "topics":
            report = topics_report(conn, args.entity_type, args.limit)
            if args.format == "markdown":
                print(render_topics_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "clusters":
            report = clusters_report(conn, args.min_docs, args.limit)
            if args.format == "markdown":
                print(render_clusters_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "questions":
            report = questions_report(conn, args.limit)
            if args.format == "markdown":
                print(render_questions_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "relations":
            report = relations_report(conn, args.entity, args.predicate, args.limit)
            if args.format == "markdown":
                print(render_relations_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "digest":
            report = digest_report(conn, args.limit)
            if args.format == "markdown":
                print(render_digest_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "review":
            report = review_report(conn, args.limit)
            if args.format == "markdown":
                print(render_review_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "inbox":
            report = inbox_report(conn, args.limit)
            if args.format == "markdown":
                print(render_inbox_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "curate":
            report = curate_report(conn, args.limit)
            if args.format == "markdown":
                print(render_curate_markdown(report))
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "graph":
            graph = export_graph(conn, args.limit, args.include_terms)
            if args.format == "mermaid":
                print(render_graph_mermaid(graph))
            else:
                print(json.dumps(graph, ensure_ascii=False, indent=2))
        elif args.command == "dump-graph":
            manifest = dump_graph_csv(conn, Path(args.out), args.limit, args.include_terms)
            print(f"Exported graph CSV to {args.out}")
            for file_name in manifest["files"]:
                print(f"  {file_name}")
        elif args.command == "dump-neo4j":
            manifest = dump_neo4j_cypher(conn, Path(args.out), args.limit, args.include_terms)
            print(f"Exported Neo4j Cypher to {args.out}")
            print(f"  nodes: {manifest['nodes']}")
            print(f"  edges: {manifest['edges']}")
        elif args.command == "stats":
            print(json.dumps(stats(conn), ensure_ascii=False, indent=2))


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    ensure_column(conn, "media", "text_model", "TEXT")
    ensure_column(conn, "media", "text_language", "TEXT")
    ensure_column(conn, "media", "text_confidence", "REAL")
    ensure_column(conn, "media", "local_path", "TEXT")
    ensure_column(conn, "media", "cache_status", "TEXT")
    ensure_column(conn, "media", "cache_error", "TEXT")
    ensure_column(conn, "media", "cache_sha256", "TEXT")
    ensure_column(conn, "media", "cache_bytes", "INTEGER")
    ensure_column(conn, "media", "cache_checked_at", "TEXT")


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def import_paths(conn: sqlite3.Connection, paths: list[Path]) -> int:
    count = 0
    for path in paths:
        for context_path in iter_context_files(path):
            context = json.loads(context_path.read_text(encoding="utf-8"))
            import_context(conn, context)
            count += 1
    conn.commit()
    return count


def ingest_paths(conn: sqlite3.Connection, paths: list[Path]) -> dict:
    batch_checks = batch_manifest_checks(paths)
    batch_warnings = [check for check in batch_checks if not check.get("ok") or check.get("failed", 0)]
    imported = import_paths(conn, paths)
    report = store_doctor(conn)
    return {
        "imported": imported,
        "batch_checks": batch_checks,
        "batch_warnings": batch_warnings,
        "doctor": report,
        "recommended_next": [
            "python -m link2context.store --db data/link2context.db brief",
            "python -m link2context.store --db data/link2context.db timeline",
            "python -m link2context.store --db data/link2context.db export --out outputs/agent-handoff",
        ],
    }


def render_ingest_markdown(result: dict, db_path: Path) -> str:
    doctor = result["doctor"]
    parts = [
        "# Link2Context Ingest",
        "",
        f"- Imported: {result.get('imported', 0)} context file(s)",
        f"- Database: {db_path}",
        f"- Store status: {doctor.get('status')}",
        f"- Ready for agent: {str(doctor.get('ready_for_agent')).lower()}",
        "",
        "## Store Doctor",
        "",
    ]
    for check in doctor.get("checks", []):
        marker = "ok" if check.get("ok") else "warn"
        parts.append(f"- {marker} {check['name']}: {check['detail']}")
    if result.get("batch_checks"):
        parts.extend(["", "## Batch Checks", ""])
        for check in result["batch_checks"]:
            marker = "ok" if check.get("ok") else "warn"
            parts.append(f"- {marker} {check['path']}: {check['summary']}")
    if result.get("batch_warnings"):
        parts.extend(["", "## Batch Warnings", ""])
        for warning in result["batch_warnings"]:
            parts.append(f"- {warning['path']}: {warning['summary']}")
            for error in warning.get("errors", [])[:5]:
                parts.append(f"  - {error}")
    if result.get("recommended_next"):
        parts.extend(["", "## Recommended Next", ""])
        for command in result["recommended_next"]:
            parts.append(f"- `{command}`")
    return "\n".join(parts).strip() + "\n"


def batch_manifest_warnings(paths: list[Path]) -> list[dict]:
    return [check for check in batch_manifest_checks(paths) if not check.get("ok") or check.get("failed", 0)]


def batch_manifest_checks(paths: list[Path]) -> list[dict]:
    warnings: list[dict] = []
    for path in batch_manifest_dirs(paths):
        from .cli import verify_batch

        report = verify_batch(path)
        failed = report.get("summary", {}).get("failed", 0)
        errors = list(report.get("errors") or [])
        summary = (
            f"{failed} failed item(s)"
            if not errors
            else f"{failed} failed item(s), {len(errors)} verification error(s)"
        )
        warnings.append(
            {
                "path": str(path),
                "ok": bool(report.get("ok")),
                "summary": summary,
                "count": report.get("summary", {}).get("count", 0),
                "succeeded": report.get("summary", {}).get("succeeded", 0),
                "failed": failed,
                "errors": errors,
            }
        )
    return warnings


def batch_manifest_dirs(paths: list[Path]) -> list[Path]:
    dirs: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        candidates = [path] if path.is_dir() else []
        if path.is_dir():
            candidates.extend(manifest.parent for manifest in path.rglob("manifest.json"))
        for candidate in candidates:
            manifest_path = candidate / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(manifest.get("items"), list) or "succeeded" not in manifest:
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            dirs.append(candidate)
    return dirs


def iter_context_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        if path.name == "context.json":
            yield path
        return
    if path.is_dir():
        yield from path.rglob("context.json")


def import_context(conn: sqlite3.Connection, context: dict) -> int:
    source = context.get("source", {})
    article = context.get("article", {})
    content = context.get("content", {})
    quality = context.get("quality", {})
    media = context.get("media", {})
    agent_package = context.get("agent_package", {})

    url = source.get("url")
    platform = source.get("platform")
    if not url or not platform:
        raise ValueError("context.json is missing source.url or source.platform")

    conn.execute(
        """
        INSERT INTO documents (
          url, platform, title, account_name, author, published_at, fetched_at,
          summary, plain_text, markdown, quality_status, context_json, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(url) DO UPDATE SET
          platform=excluded.platform,
          title=excluded.title,
          account_name=excluded.account_name,
          author=excluded.author,
          published_at=excluded.published_at,
          fetched_at=excluded.fetched_at,
          summary=excluded.summary,
          plain_text=excluded.plain_text,
          markdown=excluded.markdown,
          quality_status=excluded.quality_status,
          context_json=excluded.context_json,
          imported_at=CURRENT_TIMESTAMP
        """,
        (
            url,
            platform,
            article.get("title"),
            article.get("account_name"),
            article.get("author"),
            article.get("published_at"),
            source.get("fetched_at"),
            article.get("summary"),
            content.get("plain_text"),
            content.get("markdown"),
            quality.get("status"),
            json.dumps(context, ensure_ascii=False),
        ),
    )
    document_id = int(conn.execute("SELECT id FROM documents WHERE url = ?", (url,)).fetchone()["id"])

    conn.execute("DELETE FROM media WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM citations WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM document_entities WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM relationships WHERE document_id = ?", (document_id,))

    for image in media.get("images", []) or []:
        insert_media(
            conn,
            document_id,
            "image",
            image.get("index"),
            image.get("url"),
            media_local_path(image),
            image.get("ocr", {}).get("status"),
            image.get("ocr", {}).get("text"),
        )
    for video in media.get("videos", []) or []:
        insert_media(
            conn,
            document_id,
            "video",
            video.get("index"),
            video.get("embed_url"),
            media_local_path(video),
            video.get("status"),
            None,
        )

    for citation in agent_package.get("citations", []) or []:
        conn.execute(
            "INSERT INTO citations (document_id, ref, text, source) VALUES (?, ?, ?, ?)",
            (document_id, citation.get("ref"), citation.get("text"), citation.get("source")),
        )

    graph = extract_graph(context)
    for entity in graph["entities"]:
        entity_id = upsert_entity(conn, entity)
        conn.execute(
            """
            INSERT OR REPLACE INTO document_entities (
              document_id, entity_id, role, confidence, evidence
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                document_id,
                entity_id,
                entity["type"],
                entity["confidence"],
                entity["source"],
            ),
        )
    for relation in graph["relations"]:
        conn.execute(
            """
            INSERT INTO relationships (
              document_id, subject, predicate, object, confidence, evidence
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                relation["subject"],
                relation["predicate"],
                relation["object"],
                relation["confidence"],
                relation["evidence"],
            ),
        )
    sync_document_tags_to_graph(conn, document_id)
    sync_document_notes_to_graph(conn, document_id)

    return document_id


def add_document_tags(conn: sqlite3.Connection, identifier: str, tags: list[str]) -> dict:
    row = find_document(conn, identifier)
    if row is None:
        return {
            "query": identifier,
            "ok": False,
            "document": None,
            "added": [],
            "tags": [],
            "note": "No matching document found by id or URL.",
        }
    document_id = row["id"]
    cleaned_tags = normalize_user_tags(tags)
    for tag in cleaned_tags:
        conn.execute(
            "INSERT OR IGNORE INTO document_tags (document_id, tag) VALUES (?, ?)",
            (document_id, tag),
        )
    sync_document_tags_to_graph(conn, document_id)
    conn.commit()
    all_tags = document_user_tags(conn, document_id)
    return {
        "query": identifier,
        "ok": True,
        "document": {
            "id": document_id,
            "title": row["title"],
            "url": row["url"],
            "platform": row["platform"],
        },
        "added": cleaned_tags,
        "tags": all_tags,
        "note": "User tags were stored and mirrored into graph entities with evidence=user.tag.",
    }


def normalize_user_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        tag = re.sub(r"\s+", " ", raw_tag).strip().strip("#")
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(tag)
    return cleaned


def normalize_entity_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def sql_string_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sync_document_tags_to_graph(conn: sqlite3.Connection, document_id: int) -> None:
    row = conn.execute(
        "SELECT title, url FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute(
        "DELETE FROM document_entities WHERE document_id = ? AND evidence = 'user.tag'",
        (document_id,),
    )
    conn.execute(
        "DELETE FROM relationships WHERE document_id = ? AND evidence = 'user.tag'",
        (document_id,),
    )
    subject = row["title"] or row["url"] or f"document:{document_id}"
    for tag in document_user_tags(conn, document_id):
        entity_id = upsert_entity(
            conn,
            {
                "normalized_name": f"user_tag:{normalize_entity_name(tag)}",
                "name": tag,
                "type": "user_tag",
            },
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO document_entities (
              document_id, entity_id, role, confidence, evidence
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (document_id, entity_id, "user_tag", 1.0, "user.tag"),
        )
        conn.execute(
            """
            INSERT INTO relationships (
              document_id, subject, predicate, object, confidence, evidence
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (document_id, subject, "user_tagged_as", tag, 1.0, "user.tag"),
        )


def sync_all_document_tags_to_graph(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT DISTINCT document_id FROM document_tags ORDER BY document_id ASC"
    ).fetchall()
    for row in rows:
        sync_document_tags_to_graph(conn, row["document_id"])


def document_user_tags(conn: sqlite3.Connection, document_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT tag
        FROM document_tags
        WHERE document_id = ?
        ORDER BY tag ASC
        """,
        (document_id,),
    ).fetchall()
    return [row["tag"] for row in rows]


def add_document_note(conn: sqlite3.Connection, identifier: str, note: str) -> dict:
    row = find_document(conn, identifier)
    cleaned_note = normalize_note_text(note)
    if row is None:
        return {
            "query": identifier,
            "ok": False,
            "document": None,
            "note_added": None,
            "notes": [],
            "note": "No matching document found by id or URL.",
        }
    if not cleaned_note:
        return {
            "query": identifier,
            "ok": False,
            "document": {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "platform": row["platform"],
            },
            "note_added": None,
            "notes": document_user_notes(conn, row["id"]),
            "note": "Note text is empty.",
        }
    document_id = row["id"]
    cursor = conn.execute(
        "INSERT INTO document_notes (document_id, note) VALUES (?, ?)",
        (document_id, cleaned_note),
    )
    sync_document_notes_to_graph(conn, document_id)
    conn.commit()
    return {
        "query": identifier,
        "ok": True,
        "document": {
            "id": document_id,
            "title": row["title"],
            "url": row["url"],
            "platform": row["platform"],
        },
        "note_added": {
            "id": cursor.lastrowid,
            "note": cleaned_note,
        },
        "notes": document_user_notes(conn, document_id),
        "note": "User note was stored and mirrored into graph relationships with evidence=user.note.",
    }


def normalize_note_text(note: str) -> str:
    return re.sub(r"\s+", " ", note).strip()


def sync_document_notes_to_graph(conn: sqlite3.Connection, document_id: int) -> None:
    row = conn.execute(
        "SELECT title, url FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute(
        "DELETE FROM relationships WHERE document_id = ? AND evidence = 'user.note'",
        (document_id,),
    )
    subject = row["title"] or row["url"] or f"document:{document_id}"
    for note in document_user_notes(conn, document_id):
        conn.execute(
            """
            INSERT INTO relationships (
              document_id, subject, predicate, object, confidence, evidence
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (document_id, subject, "user_note", note_summary(note["note"]), 1.0, "user.note"),
        )


def sync_all_document_notes_to_graph(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT DISTINCT document_id FROM document_notes ORDER BY document_id ASC"
    ).fetchall()
    for row in rows:
        sync_document_notes_to_graph(conn, row["document_id"])


def note_summary(note: str, limit: int = 120) -> str:
    value = normalize_note_text(note)
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def document_user_notes(conn: sqlite3.Connection, document_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, note, created_at
        FROM document_notes
        WHERE document_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def mark_document_status(conn: sqlite3.Connection, identifier: str, status: str, note: str | None = None) -> dict:
    row = find_document(conn, identifier)
    if row is None:
        return {
            "query": identifier,
            "ok": False,
            "document": None,
            "user_status": None,
            "note": "No matching document found by id or URL.",
        }
    clean_note = normalize_note_text(note or "") or None
    conn.execute(
        """
        INSERT INTO document_status (document_id, status, note, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(document_id) DO UPDATE SET
          status=excluded.status,
          note=excluded.note,
          updated_at=CURRENT_TIMESTAMP
        """,
        (row["id"], status, clean_note),
    )
    conn.commit()
    return {
        "query": identifier,
        "ok": True,
        "document": {
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "platform": row["platform"],
        },
        "user_status": document_user_status(conn, row["id"]),
        "note": "User workflow status was stored locally.",
    }


def document_user_status(conn: sqlite3.Connection, document_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT status, note, updated_at
        FROM document_status
        WHERE document_id = ?
        """,
        (document_id,),
    ).fetchone()
    return None if row is None else dict(row)


def status_report(conn: sqlite3.Connection, status: str | None = None, limit: int = 20) -> dict:
    limit = max(1, limit)
    conditions = []
    params: list[str | int] = []
    if status:
        conditions.append("s.status = ?")
        params.append(status)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""
        SELECT
          s.status, s.note, s.updated_at,
          d.id AS document_id, d.title, d.url, d.platform, d.account_name, d.quality_status
        FROM document_status s
        JOIN documents d ON d.id = s.document_id
        {where_clause}
        ORDER BY s.updated_at DESC, d.imported_at DESC, d.id DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    summary_rows = conn.execute(
        """
        SELECT status, COUNT(*) AS documents
        FROM document_status
        GROUP BY status
        ORDER BY documents DESC, status ASC
        """
    ).fetchall()
    return {
        "filters": {
            "status": status,
            "limit": limit,
        },
        "summary": [dict(row) for row in summary_rows],
        "documents": [
            {
                "status": row["status"],
                "note": row["note"],
                "updated_at": row["updated_at"],
                "document": {
                    "id": row["document_id"],
                    "title": row["title"],
                    "url": row["url"],
                    "platform": row["platform"],
                    "account_name": row["account_name"],
                    "quality_status": row["quality_status"],
                },
            }
            for row in rows
        ],
        "note": "User workflow statuses are independent from extraction quality_status.",
    }


def render_mark_result_markdown(result: dict) -> str:
    parts = [
        "# Link2Context Mark",
        "",
        f"- OK: {str(result.get('ok')).lower()}",
    ]
    document = result.get("document")
    if document:
        parts.append(f"- Document: [{document['id']}] {document.get('title') or 'Untitled'}")
        parts.append(f"- URL: {document.get('url')}")
    status = result.get("user_status")
    if status:
        parts.append(f"- Status: {status.get('status')}")
        if status.get("note"):
            parts.append(f"- Status note: {status.get('note')}")
        parts.append(f"- Updated: {status.get('updated_at')}")
    if result.get("note"):
        parts.extend(["", "## Note", "", result["note"]])
    return "\n".join(parts).strip() + "\n"


def render_statuses_markdown(report: dict) -> str:
    filters = report.get("filters", {})
    parts = [
        "# Link2Context Statuses",
        "",
        f"- Status filter: {filters.get('status') or 'all'}",
        f"- Limit: {filters.get('limit')}",
        "",
    ]
    if report.get("summary"):
        parts.extend(["## Summary", ""])
        for row in report["summary"]:
            parts.append(f"- {row['status']}: {row['documents']}")
        parts.append("")
    if not report.get("documents"):
        parts.extend(["No marked documents.", ""])
        return "\n".join(parts).strip() + "\n"
    parts.extend(["## Documents", ""])
    for item in report["documents"]:
        document = item["document"]
        parts.append(f"- [{document['id']}] {document.get('title') or 'Untitled'} ({item['status']})")
        parts.append(f"  - URL: {document.get('url')}")
        if item.get("note"):
            parts.append(f"  - Note: {item['note']}")
        parts.append(f"  - Updated: {item.get('updated_at')}")
    parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def annotations_report(conn: sqlite3.Connection, limit: int = 20) -> dict:
    limit = max(1, limit)
    rows = conn.execute(
        """
        SELECT id, title, url, platform, account_name, quality_status, imported_at
        FROM documents d
        WHERE EXISTS (SELECT 1 FROM document_tags t WHERE t.document_id = d.id)
           OR EXISTS (SELECT 1 FROM document_notes n WHERE n.document_id = d.id)
           OR EXISTS (SELECT 1 FROM document_status s WHERE s.document_id = d.id)
        ORDER BY imported_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    documents = []
    for row in rows:
        documents.append(
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "platform": row["platform"],
                "account_name": row["account_name"],
                "quality_status": row["quality_status"],
                "user_status": document_user_status(conn, row["id"]),
                "tags": document_user_tags(conn, row["id"]),
                "notes": document_user_notes(conn, row["id"]),
                "commands": {
                    "doc": f"python -m link2context.store --db data/link2context.db doc {row['id']}",
                    "mark_read": f"python -m link2context.store --db data/link2context.db mark {row['id']} read",
                },
            }
        )
    return {
        "documents": documents,
        "summary": {
            "documents": len(documents),
            "with_tags": sum(1 for document in documents if document["tags"]),
            "with_notes": sum(1 for document in documents if document["notes"]),
            "with_status": sum(1 for document in documents if document["user_status"]),
        },
        "limit": limit,
        "note": "Annotations combine user tags, notes, and workflow status into one agent-readable view.",
    }


def render_annotations_markdown(report: dict) -> str:
    summary = report.get("summary", {})
    parts = [
        "# Link2Context Annotations",
        "",
        f"- Documents: {summary.get('documents', 0)}",
        f"- With tags: {summary.get('with_tags', 0)}",
        f"- With notes: {summary.get('with_notes', 0)}",
        f"- With status: {summary.get('with_status', 0)}",
        f"- Limit: {report.get('limit')}",
        "",
    ]
    if not report.get("documents"):
        parts.extend(["No annotated documents.", ""])
        return "\n".join(parts).strip() + "\n"
    for document in report["documents"]:
        parts.append(f"## [{document['id']}] {document.get('title') or 'Untitled'}")
        parts.append("")
        parts.append(f"- URL: {document.get('url')}")
        parts.append(f"- Platform: {document.get('platform')}")
        parts.append(f"- Quality: {document.get('quality_status') or 'unknown'}")
        if document.get("user_status"):
            status = document["user_status"]
            parts.append(f"- User status: {status.get('status')}")
            if status.get("note"):
                parts.append(f"- Status note: {status.get('note')}")
        if document.get("tags"):
            parts.append(f"- Tags: {', '.join(document['tags'])}")
        if document.get("notes"):
            parts.append("- Notes:")
            for note in document["notes"][:3]:
                parts.append(f"  - [{note['id']}] {note.get('note')}")
        commands = document.get("commands", {})
        if commands.get("doc"):
            parts.append(f"- Command: `{commands.get('doc')}`")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def upsert_entity(conn: sqlite3.Connection, entity: dict) -> int:
    conn.execute(
        """
        INSERT INTO entities (normalized_name, name, type)
        VALUES (?, ?, ?)
        ON CONFLICT(normalized_name) DO UPDATE SET
          name=excluded.name,
          type=excluded.type
        """,
        (entity["normalized_name"], entity["name"], entity["type"]),
    )
    return int(
        conn.execute(
            "SELECT id FROM entities WHERE normalized_name = ?",
            (entity["normalized_name"],),
        ).fetchone()["id"]
    )


def insert_media(
    conn: sqlite3.Connection,
    document_id: int,
    kind: str,
    media_index: int | None,
    url: str | None,
    local_path: str | None,
    status: str | None,
    text: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO media (document_id, kind, media_index, url, local_path, status, text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (document_id, kind, media_index or 0, url, local_path, status, text),
    )


def media_local_path(item: dict) -> str | None:
    return item.get("local_path") or item.get("path") or item.get("file_path")


def search(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[sqlite3.Row]:
    pattern = f"%{query}%"
    return list(
        conn.execute(
            """
            SELECT id, platform, title, url, quality_status
            FROM documents
            WHERE title LIKE ? OR summary LIKE ? OR plain_text LIKE ?
               OR EXISTS (
                   SELECT 1 FROM media m
                   WHERE m.document_id = documents.id
                     AND m.text LIKE ?
               )
            ORDER BY imported_at DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, pattern, limit),
        )
    )


def get_document(conn: sqlite3.Connection, identifier: str) -> dict:
    identifier = identifier.strip()
    if not identifier:
        raise ValueError("document identifier must not be empty")
    row = find_document(conn, identifier)
    if row is None:
        return {
            "query": identifier,
            "found": False,
            "document": None,
            "tags": [],
            "notes": [],
            "user_status": None,
            "media": [],
            "citations": [],
            "entities": [],
            "note": "No matching document found by id or URL.",
        }
    document_id = row["id"]
    return {
        "query": identifier,
        "found": True,
        "document": {
            "id": document_id,
            "url": row["url"],
            "platform": row["platform"],
            "title": row["title"],
            "account_name": row["account_name"],
            "author": row["author"],
            "published_at": row["published_at"],
            "fetched_at": row["fetched_at"],
            "summary": row["summary"],
            "quality_status": row["quality_status"],
            "markdown": row["markdown"],
        },
        "tags": document_user_tags(conn, document_id),
        "notes": document_user_notes(conn, document_id),
        "user_status": document_user_status(conn, document_id),
        "media": document_media(conn, document_id),
        "citations": document_citations(conn, document_id),
        "entities": document_entities_for_id(conn, document_id),
        "note": "Full imported document context from the local store.",
    }


def find_document(conn: sqlite3.Connection, identifier: str) -> sqlite3.Row | None:
    if identifier.isdigit():
        row = conn.execute(
            """
            SELECT id, url, platform, title, account_name, author, published_at, fetched_at,
                   summary, markdown, quality_status
            FROM documents
            WHERE id = ?
            """,
            (int(identifier),),
        ).fetchone()
        if row is not None:
            return row
    return conn.execute(
        """
        SELECT id, url, platform, title, account_name, author, published_at, fetched_at,
               summary, markdown, quality_status
        FROM documents
        WHERE url = ?
        """,
        (identifier,),
    ).fetchone()


def document_media(conn: sqlite3.Connection, document_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
          kind, media_index, url, local_path,
          cache_status, cache_error, cache_sha256, cache_bytes, cache_checked_at,
          status, text
        FROM media
        WHERE document_id = ?
        ORDER BY kind ASC, media_index ASC, id ASC
        """,
        (document_id,),
    ).fetchall()
    return [
        {
            "kind": row["kind"],
            "index": row["media_index"],
            "url": row["url"],
            "local_path": row["local_path"],
            "cache_status": row["cache_status"],
            "cache_error": row["cache_error"],
            "cache_sha256": row["cache_sha256"],
            "cache_bytes": row["cache_bytes"],
            "cache_checked_at": row["cache_checked_at"],
            "status": row["status"],
            "text": row["text"],
        }
        for row in rows
    ]


def document_citations(conn: sqlite3.Connection, document_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT ref, text, source
        FROM citations
        WHERE document_id = ?
        ORDER BY id ASC
        """,
        (document_id,),
    ).fetchall()
    return [
        {
            "ref": row["ref"],
            "text": row["text"],
            "source": row["source"],
        }
        for row in rows
    ]


def citation_lookup(conn: sqlite3.Connection, identifier: str, ref: str | None = None) -> dict:
    identifier = identifier.strip()
    if not identifier:
        raise ValueError("document identifier must not be empty")
    document = find_document(conn, identifier)
    if document is None:
        return {
            "query": identifier,
            "found": False,
            "document": None,
            "citations": [],
            "note": "No matching document found by id or URL.",
        }
    if ref:
        rows = conn.execute(
            """
            SELECT ref, text, source
            FROM citations
            WHERE document_id = ? AND ref = ?
            ORDER BY id ASC
            """,
            (document["id"], ref),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT ref, text, source
            FROM citations
            WHERE document_id = ?
            ORDER BY id ASC
            """,
            (document["id"],),
        ).fetchall()
    return {
        "query": identifier,
        "ref": ref,
        "found": bool(rows),
        "document": {
            "id": document["id"],
            "title": document["title"],
            "url": document["url"],
            "platform": document["platform"],
            "account_name": document["account_name"],
            "quality_status": document["quality_status"],
        },
        "citations": [
            {
                "ref": row["ref"],
                "text": row["text"],
                "source": row["source"],
            }
            for row in rows
        ],
        "note": "Citation evidence from the local imported context store.",
    }


def render_citation_markdown(package: dict) -> str:
    if package.get("document") is None:
        return "\n".join(
            [
                f"# Link2Context Citation: {package.get('query')}",
                "",
                package.get("note", "No matching document found."),
                "",
            ]
        ).strip() + "\n"
    document = package["document"]
    parts = [
        f"# Link2Context Citation Evidence",
        "",
        f"- Document: [{document['id']}] {document.get('title') or 'Untitled'}",
        f"- URL: {document.get('url')}",
        f"- Ref filter: {package.get('ref') or 'all'}",
        "",
    ]
    if not package.get("citations"):
        parts.extend(["No matching citations.", ""])
        return "\n".join(parts).strip() + "\n"
    for citation in package["citations"]:
        parts.append(f"## {citation.get('ref')}")
        parts.append("")
        parts.append(f"- Source: {citation.get('source')}")
        parts.append("")
        parts.append(citation.get("text") or "")
        parts.append("")
    if package.get("note"):
        parts.extend(["## Note", "", package["note"], ""])
    return "\n".join(parts).strip() + "\n"


def evidence_report(conn: sqlite3.Connection, query: str | None = None, limit: int = 50) -> dict:
    normalized_query = query.strip() if query else None
    params: list[object] = []
    where_clause = ""
    if normalized_query:
        pattern = f"%{normalized_query}%"
        where_clause = """
        WHERE c.text LIKE ?
           OR c.ref LIKE ?
           OR c.source LIKE ?
           OR d.title LIKE ?
           OR d.url LIKE ?
           OR d.account_name LIKE ?
        """
        params.extend([pattern, pattern, pattern, pattern, pattern, pattern])
    rows = conn.execute(
        f"""
        SELECT
            c.ref,
            c.text,
            c.source,
            d.id AS document_id,
            d.title,
            d.url,
            d.platform,
            d.account_name,
            d.quality_status
        FROM citations c
        JOIN documents d ON d.id = c.document_id
        {where_clause}
        ORDER BY d.imported_at DESC, d.id DESC, c.id ASC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return {
        "query": normalized_query,
        "limit": limit,
        "items": [
            {
                "ref": row["ref"],
                "text": row["text"],
                "source": row["source"],
                "document": {
                    "id": row["document_id"],
                    "title": row["title"],
                    "url": row["url"],
                    "platform": row["platform"],
                    "account_name": row["account_name"],
                    "quality_status": row["quality_status"],
                },
            }
            for row in rows
        ],
        "note": "Citation evidence from imported context packages. Use citation <id> <ref> to inspect a specific item.",
    }


def render_evidence_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Evidence",
        "",
        f"- Query: {report.get('query') or 'all'}",
        f"- Limit: {report.get('limit')}",
        "",
    ]
    if not report.get("items"):
        parts.extend(["No matching evidence.", ""])
        return "\n".join(parts).strip() + "\n"
    for item in report["items"]:
        document = item["document"]
        parts.append(f"## [{document['id']}] {document.get('title') or 'Untitled'} | {item.get('ref')}")
        parts.append("")
        parts.append(f"- URL: {document.get('url')}")
        parts.append(f"- Platform: {document.get('platform')}")
        parts.append(f"- Account: {document.get('account_name') or 'unknown'}")
        parts.append(f"- Source: {item.get('source')}")
        parts.append(f"- Quality: {document.get('quality_status')}")
        parts.append(
            "- Command: "
            f"`python -m link2context.store --db data/link2context.db citation {document['id']} {item.get('ref')}`"
        )
        parts.append("")
        parts.append(item.get("text") or "")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def document_entities_for_id(conn: sqlite3.Connection, document_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT e.name, e.type, de.role, de.confidence, de.evidence
        FROM document_entities de
        JOIN entities e ON e.id = de.entity_id
        WHERE de.document_id = ?
        ORDER BY de.confidence DESC, e.name ASC
        """,
        (document_id,),
    ).fetchall()
    return [
        {
            "name": row["name"],
            "type": row["type"],
            "role": row["role"],
            "confidence": row["confidence"],
            "evidence": row["evidence"],
        }
        for row in rows
    ]


def render_document_markdown(package: dict) -> str:
    if not package.get("found"):
        return "\n".join(
            [
                f"# Link2Context Document: {package.get('query')}",
                "",
                package.get("note", "No matching document found."),
                "",
            ]
        ).strip() + "\n"

    document = package["document"]
    parts = [
        f"# {document.get('title') or 'Untitled'}",
        "",
        f"- ID: {document.get('id')}",
        f"- URL: {document.get('url')}",
        f"- Platform: {document.get('platform')}",
        f"- Account: {document.get('account_name') or 'Unknown'}",
        f"- Author: {document.get('author') or 'Unknown'}",
        f"- Published: {document.get('published_at') or 'unknown'}",
        f"- Quality: {document.get('quality_status') or 'unknown'}",
    ]
    user_status = package.get("user_status")
    if user_status:
        parts.append(f"- User status: {user_status.get('status')}")
        if user_status.get("note"):
            parts.append(f"- Status note: {user_status.get('note')}")
        parts.append(f"- Status updated: {user_status.get('updated_at')}")
    parts.append("")
    if document.get("summary"):
        parts.extend(["## Summary", "", document["summary"], ""])
    if package.get("tags"):
        parts.extend(["## User Tags", ""])
        for tag in package["tags"]:
            parts.append(f"- {tag}")
        parts.append("")
    if package.get("notes"):
        parts.extend(["## User Notes", ""])
        for note in package["notes"]:
            parts.append(f"- [{note['id']}] {note.get('created_at') or 'unknown'}")
            parts.append(f"  {note.get('note')}")
        parts.append("")
    if package.get("entities"):
        parts.extend(["## Entities", ""])
        for entity in package["entities"][:20]:
            parts.append(
                f"- {entity['name']} ({entity['type']}, role={entity['role']}, confidence={entity['confidence']})"
            )
        parts.append("")
    if package.get("media"):
        parts.extend(["## Media", ""])
        for item in package["media"]:
            parts.append(f"- {item['kind']}[{item['index']}]: {item.get('url') or 'no-url'} ({item.get('status') or 'unknown'})")
        parts.append("")
    if package.get("citations"):
        parts.extend(["## Citations", ""])
        for citation in package["citations"][:20]:
            parts.append(f"- {citation.get('ref')} ({citation.get('source')})")
            parts.append(f"  {citation.get('text')}")
        parts.append("")
    if document.get("markdown"):
        parts.extend(["## Content", "", document["markdown"], ""])
    if package.get("note"):
        parts.extend(["## Note", "", package["note"], ""])
    return "\n".join(parts).strip() + "\n"


def tag_report(conn: sqlite3.Connection, limit: int = 20) -> dict:
    limit = max(1, limit)
    tag_rows = conn.execute(
        """
        SELECT tag, COUNT(*) AS documents, MAX(dt.created_at) AS latest_at
        FROM document_tags dt
        GROUP BY tag
        ORDER BY documents DESC, latest_at DESC, tag ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return {
        "tags": [
            {
                "tag": row["tag"],
                "documents": row["documents"],
                "latest_at": row["latest_at"],
                "recent_documents": tagged_documents(conn, row["tag"], 3),
            }
            for row in tag_rows
        ],
        "limit": limit,
        "note": "User tags are stored locally and mirrored into graph entities with type=user_tag.",
    }


def tagged_documents(conn: sqlite3.Connection, tag: str, limit: int = 3) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.id, d.title, d.url, d.platform, d.account_name, dt.created_at
        FROM document_tags dt
        JOIN documents d ON d.id = dt.document_id
        WHERE dt.tag = ?
        ORDER BY dt.created_at DESC, d.imported_at DESC, d.id DESC
        LIMIT ?
        """,
        (tag, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def render_tag_result_markdown(result: dict) -> str:
    parts = [
        "# Link2Context Tag",
        "",
        f"- OK: {str(result.get('ok')).lower()}",
    ]
    document = result.get("document")
    if document:
        parts.append(f"- Document: [{document['id']}] {document.get('title') or 'Untitled'}")
        parts.append(f"- URL: {document.get('url')}")
    if result.get("added"):
        parts.extend(["", "## Added", ""])
        for tag in result["added"]:
            parts.append(f"- {tag}")
    if result.get("tags"):
        parts.extend(["", "## Current Tags", ""])
        for tag in result["tags"]:
            parts.append(f"- {tag}")
    if result.get("note"):
        parts.extend(["", "## Note", "", result["note"]])
    return "\n".join(parts).strip() + "\n"


def render_tags_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Tags",
        "",
        f"- Limit: {report.get('limit')}",
        "",
    ]
    if not report.get("tags"):
        parts.extend(["No user tags found.", ""])
        return "\n".join(parts).strip() + "\n"
    for tag in report["tags"]:
        parts.append(f"## {tag['tag']}")
        parts.append("")
        parts.append(f"- Documents: {tag['documents']}")
        parts.append(f"- Latest: {tag.get('latest_at') or 'unknown'}")
        for document in tag.get("recent_documents", []):
            parts.append(f"- [{document['id']}] {document.get('title') or 'Untitled'}")
            parts.append(f"  - URL: {document.get('url')}")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def notes_report(conn: sqlite3.Connection, limit: int = 20) -> dict:
    limit = max(1, limit)
    rows = conn.execute(
        """
        SELECT
          n.id, n.note, n.created_at,
          d.id AS document_id, d.title, d.url, d.platform, d.account_name
        FROM document_notes n
        JOIN documents d ON d.id = n.document_id
        ORDER BY n.created_at DESC, n.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return {
        "notes": [
            {
                "id": row["id"],
                "note": row["note"],
                "created_at": row["created_at"],
                "document": {
                    "id": row["document_id"],
                    "title": row["title"],
                    "url": row["url"],
                    "platform": row["platform"],
                    "account_name": row["account_name"],
                },
            }
            for row in rows
        ],
        "limit": limit,
        "note": "User notes are stored locally and mirrored into graph relationships with evidence=user.note.",
    }


def render_note_result_markdown(result: dict) -> str:
    parts = [
        "# Link2Context Note",
        "",
        f"- OK: {str(result.get('ok')).lower()}",
    ]
    document = result.get("document")
    if document:
        parts.append(f"- Document: [{document['id']}] {document.get('title') or 'Untitled'}")
        parts.append(f"- URL: {document.get('url')}")
    if result.get("note_added"):
        parts.extend(["", "## Added", ""])
        parts.append(f"- [{result['note_added']['id']}] {result['note_added']['note']}")
    if result.get("notes"):
        parts.extend(["", "## Current Notes", ""])
        for note in result["notes"]:
            parts.append(f"- [{note['id']}] {note.get('note')}")
    if result.get("note"):
        parts.extend(["", "## Note", "", result["note"]])
    return "\n".join(parts).strip() + "\n"


def render_notes_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Notes",
        "",
        f"- Limit: {report.get('limit')}",
        "",
    ]
    if not report.get("notes"):
        parts.extend(["No user notes found.", ""])
        return "\n".join(parts).strip() + "\n"
    for note in report["notes"]:
        document = note.get("document", {})
        parts.append(f"## Note {note['id']}")
        parts.append("")
        parts.append(f"- Document: [{document.get('id')}] {document.get('title') or 'Untitled'}")
        parts.append(f"- URL: {document.get('url')}")
        parts.append(f"- Created: {note.get('created_at') or 'unknown'}")
        parts.append("")
        parts.append(note.get("note") or "")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def dump_docs_markdown(conn: sqlite3.Connection, out_dir: Path, limit: int = 100) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        """
        SELECT id, title, url, platform, imported_at
        FROM documents
        ORDER BY imported_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    files: list[str] = []
    documents: list[dict] = []
    for row in rows:
        file_name = document_markdown_filename(row["id"], row["title"] or row["url"])
        package = get_document(conn, str(row["id"]))
        (out_dir / file_name).write_text(render_document_markdown(package), encoding="utf-8")
        files.append(file_name)
        documents.append(
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "platform": row["platform"],
                "file": file_name,
            }
        )
    file_details = {
        file_name: export_file_detail(out_dir / file_name)
        for file_name in files
    }
    manifest = {
        "project": "Link2Context",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "format": "markdown-documents",
        "limit": limit,
        "files": files,
        "documents": documents,
        "file_details": file_details,
        "stats": stats(conn),
        "note": "One Markdown file per imported document, suitable for file-based knowledge bases.",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def document_markdown_filename(document_id: int, title: str | None) -> str:
    base = re.sub(r"\s+", " ", str(title or "untitled")).strip()
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base)
    base = base.strip(" ._") or "untitled"
    if len(base) > 80:
        base = base[:80].rstrip(" ._")
    return f"{document_id:04d}-{base}.md"


def verify_docs_markdown(path: Path) -> dict:
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return {
            "path": str(path),
            "ok": False,
            "errors": ["manifest.json is missing"],
            "files": {},
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    files: dict[str, dict] = {}
    expected_files = manifest.get("files", [])
    details = manifest.get("file_details", {})
    if manifest.get("format") != "markdown-documents":
        errors.append("manifest format is not markdown-documents")
    for file_name in expected_files:
        file_path = path / file_name
        if not file_path.exists():
            errors.append(f"{file_name} is missing")
            files[file_name] = {"ok": False, "error": "missing"}
            continue
        actual = export_file_detail(file_path)
        expected = details.get(file_name)
        if expected is None:
            errors.append(f"{file_name} has no manifest detail")
            files[file_name] = {"ok": False, "actual": actual, "error": "missing_detail"}
            continue
        ok = actual == expected
        if not ok:
            errors.append(f"{file_name} does not match manifest detail")
        files[file_name] = {
            "ok": ok,
            "expected": expected,
            "actual": actual,
        }
    extra_files = sorted(
        file.name
        for file in path.iterdir()
        if file.is_file() and file.name != "manifest.json" and file.name not in expected_files
    )
    return {
        "path": str(path),
        "ok": not errors,
        "errors": errors,
        "extra_files": extra_files,
        "files": files,
        "manifest": {
            "project": manifest.get("project"),
            "exported_at": manifest.get("exported_at"),
            "format": manifest.get("format"),
            "limit": manifest.get("limit"),
            "documents": len(manifest.get("documents", [])),
        },
    }


def render_verify_docs_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Markdown Docs Verification",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        "",
    ]
    manifest = report.get("manifest") or {}
    if manifest:
        parts.append(f"- Documents: {manifest.get('documents', 0)}")
        parts.append("")
    if report.get("errors"):
        parts.extend(["## Errors", ""])
        for error in report["errors"]:
            parts.append(f"- {error}")
        parts.append("")
    if report.get("extra_files"):
        parts.extend(["## Extra Files", ""])
        for file_name in report["extra_files"]:
            parts.append(f"- {file_name}")
        parts.append("")
    if report.get("files"):
        parts.extend(["## Files", ""])
        for file_name, detail in report["files"].items():
            marker = "ok" if detail.get("ok") else "fail"
            parts.append(f"- {marker} {file_name}")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def related_documents(conn: sqlite3.Connection, identifier: str, limit: int = 5) -> dict:
    identifier = identifier.strip()
    if not identifier:
        raise ValueError("document identifier must not be empty")
    source = find_document(conn, identifier)
    if source is None:
        return {
            "query": identifier,
            "found": False,
            "source": None,
            "results": [],
            "note": "No matching source document found by id or URL.",
        }
    source_entities = source_document_entities(conn, source["id"])
    rows = conn.execute(
        """
        SELECT
          d.id, d.title, d.url, d.platform, d.account_name, d.published_at, d.quality_status,
          COUNT(DISTINCT e.id) AS shared_entities,
          SUM(de.confidence) AS score,
          GROUP_CONCAT(DISTINCT e.name) AS entity_names
        FROM document_entities sde
        JOIN document_entities de ON de.entity_id = sde.entity_id AND de.document_id != sde.document_id
        JOIN entities e ON e.id = de.entity_id
        JOIN documents d ON d.id = de.document_id
        WHERE sde.document_id = ?
          AND NOT (e.type = 'term' AND (length(e.name) <= 2 OR e.name IN ('AI', 'Agent', 'Agents', 'Skill', 'Skills')))
        GROUP BY d.id
        ORDER BY shared_entities DESC, score DESC, d.imported_at DESC, d.id DESC
        LIMIT ?
        """,
        (source["id"], limit),
    ).fetchall()
    return {
        "query": identifier,
        "found": True,
        "source": {
            "id": source["id"],
            "title": source["title"],
            "url": source["url"],
            "platform": source["platform"],
            "account_name": source["account_name"],
            "quality_status": source["quality_status"],
            "entities": source_entities,
        },
        "results": [
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "platform": row["platform"],
                "account_name": row["account_name"],
                "published_at": row["published_at"],
                "quality_status": row["quality_status"],
                "shared_entities": row["shared_entities"],
                "score": row["score"],
                "entities": sorted((row["entity_names"] or "").split(",")),
            }
            for row in rows
        ],
        "note": "Related documents are ranked by shared extracted entities. This is rule-based, not semantic similarity.",
    }


def source_document_entities(conn: sqlite3.Connection, document_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT e.name, e.type, de.confidence
        FROM document_entities de
        JOIN entities e ON e.id = de.entity_id
        WHERE de.document_id = ?
        ORDER BY de.confidence DESC, e.name ASC
        """,
        (document_id,),
    ).fetchall()
    return [
        {
            "name": row["name"],
            "type": row["type"],
            "confidence": row["confidence"],
        }
        for row in rows
    ]


def render_related_markdown(package: dict) -> str:
    if not package.get("found"):
        return "\n".join(
            [
                f"# Link2Context Related: {package.get('query')}",
                "",
                package.get("note", "No matching source document found."),
                "",
            ]
        ).strip() + "\n"

    source = package["source"]
    parts = [
        f"# Link2Context Related Documents",
        "",
        f"- Source: {source.get('title') or 'Untitled'}",
        f"- URL: {source.get('url')}",
        f"- Method: shared extracted entities",
        "",
    ]
    if not package.get("results"):
        parts.extend(["No related documents found.", ""])
        return "\n".join(parts).strip() + "\n"
    for index, result in enumerate(package["results"], start=1):
        entities = ", ".join(result.get("entities", [])[:10]) or "none"
        parts.append(f"## {index}. {result.get('title') or 'Untitled'}")
        parts.append("")
        parts.append(f"- URL: {result.get('url')}")
        parts.append(f"- Platform: {result.get('platform')}")
        if result.get("account_name"):
            parts.append(f"- Account: {result.get('account_name')}")
        parts.append(f"- Shared entities: {result.get('shared_entities')}")
        parts.append(f"- Score: {result.get('score')}")
        parts.append(f"- Entities: {entities}")
        parts.append("")
    if package.get("note"):
        parts.extend(["## Note", "", package["note"], ""])
    return "\n".join(parts).strip() + "\n"


def duplicate_report(conn: sqlite3.Connection, limit: int = 20) -> dict:
    rows = conn.execute(
        """
        SELECT id, title, url, platform, account_name, published_at, imported_at, quality_status
        FROM documents
        ORDER BY imported_at DESC, id DESC
        """
    ).fetchall()
    documents = [dict(row) for row in rows]
    groups: list[dict] = []
    groups.extend(duplicate_groups(documents, "canonical_url", canonical_url_key, "same_canonical_url"))
    groups.extend(duplicate_groups(documents, "title", normalized_title_key, "same_normalized_title"))
    groups = sorted(
        groups,
        key=lambda group: (-len(group["documents"]), group["kind"], group["key"]),
    )[:limit]
    duplicate_document_ids = {
        document["id"]
        for group in groups
        for document in group["documents"]
    }
    return {
        "groups": groups,
        "summary": {
            "groups": len(groups),
            "documents": len(duplicate_document_ids),
        },
        "limit": limit,
        "note": "Duplicate candidates are rule-based, using canonical URLs and normalized titles. Review before deleting or merging.",
    }


def duplicate_groups(documents: list[dict], key_name: str, key_func: Callable[[dict], str], kind: str) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for document in documents:
        key = key_func(document)
        if not key:
            continue
        buckets.setdefault(key, []).append(document)
    return [
        {
            "kind": kind,
            "key": key,
            "documents": sorted(bucket, key=lambda item: item["id"]),
        }
        for key, bucket in buckets.items()
        if len(bucket) > 1
    ]


def normalized_title_key(document: dict) -> str:
    title = re.sub(r"\s+", " ", str(document.get("title") or "")).strip().casefold()
    return title if len(title) >= 4 else ""


def canonical_url_key(document: dict) -> str:
    raw_url = str(document.get("url") or "").strip()
    if not raw_url:
        return ""
    parsed = urlsplit(raw_url)
    host = parsed.netloc.casefold()
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
    if host.endswith("xiaohongshu.com"):
        query = ""
    elif host == "mp.weixin.qq.com" and path.startswith("/s/"):
        query = ""
    elif host == "mp.weixin.qq.com":
        keep = {"__biz", "mid", "idx", "sn"}
        query = urlencode(sorted((key, value) for key, value in parse_qsl(parsed.query) if key in keep))
    else:
        ignored_prefixes = ("utm_",)
        ignored = {"fbclid", "gclid", "share_id", "share_from_user_hidden"}
        query = urlencode(
            sorted(
                (key, value)
                for key, value in parse_qsl(parsed.query)
                if key not in ignored and not key.startswith(ignored_prefixes)
            )
        )
    return urlunsplit((parsed.scheme.casefold() or "https", host, path, query, ""))


def render_duplicate_markdown(report: dict) -> str:
    summary = report.get("summary", {})
    parts = [
        "# Link2Context Duplicates",
        "",
        f"- Groups: {summary.get('groups', 0)}",
        f"- Documents involved: {summary.get('documents', 0)}",
        f"- Limit: {report.get('limit')}",
        "",
    ]
    if not report.get("groups"):
        parts.extend(["No duplicate candidates found.", ""])
        return "\n".join(parts).strip() + "\n"
    for index, group in enumerate(report["groups"], start=1):
        parts.append(f"## {index}. {group['kind']}")
        parts.append("")
        parts.append(f"- Key: {group['key']}")
        parts.append("- Documents:")
        for document in group["documents"]:
            parts.append(f"  - [{document['id']}] {document.get('title') or 'Untitled'}")
            parts.append(f"    - URL: {document.get('url')}")
            parts.append(f"    - Platform: {document.get('platform')}")
            if document.get("account_name"):
                parts.append(f"    - Account: {document.get('account_name')}")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def agent_query(conn: sqlite3.Connection, query: str, limit: int = 5) -> dict:
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    terms = query_terms(query)
    clauses = " OR ".join(
        [
            "d.title LIKE ?",
            "d.summary LIKE ?",
            "d.plain_text LIKE ?",
            "e.name LIKE ?",
            "c.text LIKE ?",
            "EXISTS (SELECT 1 FROM media m WHERE m.document_id = d.id AND m.text LIKE ?)",
            "EXISTS (SELECT 1 FROM document_tags dt WHERE dt.document_id = d.id AND dt.tag LIKE ?)",
            "EXISTS (SELECT 1 FROM document_notes dn WHERE dn.document_id = d.id AND dn.note LIKE ?)",
            "EXISTS (SELECT 1 FROM document_status ds WHERE ds.document_id = d.id AND ds.status LIKE ?)",
            "EXISTS (SELECT 1 FROM document_status ds_note WHERE ds_note.document_id = d.id AND ds_note.note LIKE ?)",
        ]
    )
    where_clause = " OR ".join(f"({clauses})" for _ in terms)
    params = [pattern for term in terms for pattern in [f"%{term}%"] * 10]
    rows = conn.execute(
        f"""
        SELECT
          d.id, d.platform, d.title, d.url, d.account_name, d.published_at,
          d.summary, d.quality_status,
          CASE WHEN d.title LIKE ? THEN 30 ELSE 0 END
          + CASE WHEN d.summary LIKE ? THEN 20 ELSE 0 END
          + CASE WHEN d.plain_text LIKE ? THEN 10 ELSE 0 END
          + MAX(CASE WHEN e.name LIKE ? THEN 8 ELSE 0 END)
          + MAX(CASE WHEN c.text LIKE ? THEN 5 ELSE 0 END)
          + CASE WHEN EXISTS (
              SELECT 1 FROM media m_score
              WHERE m_score.document_id = d.id
                AND m_score.text LIKE ?
            ) THEN 5 ELSE 0 END
          + CASE WHEN EXISTS (
              SELECT 1 FROM document_tags dt_score
              WHERE dt_score.document_id = d.id
                AND dt_score.tag LIKE ?
            ) THEN 6 ELSE 0 END
          + CASE WHEN EXISTS (
              SELECT 1 FROM document_notes dn_score
              WHERE dn_score.document_id = d.id
                AND dn_score.note LIKE ?
            ) THEN 6 ELSE 0 END
          + CASE WHEN EXISTS (
              SELECT 1 FROM document_status ds_score
              WHERE ds_score.document_id = d.id
                AND (ds_score.status LIKE ? OR ds_score.note LIKE ?)
            ) THEN 4 ELSE 0 END AS score
        FROM documents d
        LEFT JOIN document_entities de ON de.document_id = d.id
        LEFT JOIN entities e ON e.id = de.entity_id
        LEFT JOIN citations c ON c.document_id = d.id
        WHERE {where_clause}
        GROUP BY
          d.id, d.platform, d.title, d.url, d.account_name, d.published_at,
          d.summary, d.quality_status, d.plain_text, d.imported_at
        ORDER BY score DESC, d.imported_at DESC, d.id DESC
        LIMIT ?
        """,
        (
            f"%{terms[0]}%",
            f"%{terms[0]}%",
            f"%{terms[0]}%",
            f"%{terms[0]}%",
            f"%{terms[0]}%",
            f"%{terms[0]}%",
            f"%{terms[0]}%",
            f"%{terms[0]}%",
            f"%{terms[0]}%",
            f"%{terms[0]}%",
            *params,
            limit,
        ),
    ).fetchall()
    return {
        "query": query,
        "terms": terms,
        "results": [agent_query_result(conn, row, terms) for row in rows],
        "note": "Keyword retrieval over imported documents, entities, citations, media text, and user annotations. Not semantic search.",
    }


def query_terms(query: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9+._-]*|[\u4e00-\u9fff]{2,}", query)
    if not tokens:
        tokens = [query]
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(token)
    return terms


def agent_query_result(conn: sqlite3.Connection, row: sqlite3.Row, terms: list[str]) -> dict:
    document_id = row["id"]
    user_annotations = document_user_annotation_summary(conn, document_id)
    return {
        "title": row["title"],
        "url": row["url"],
        "platform": row["platform"],
        "account_name": row["account_name"],
        "published_at": row["published_at"],
        "summary": row["summary"],
        "quality_status": row["quality_status"],
        "score": row["score"],
        "matched_terms": matched_terms(row, terms),
        "annotation_matched_terms": annotation_matched_terms(user_annotations, terms),
        "user_annotations": user_annotations,
        "matched_entities": [
            {"name": entity["name"], "type": entity["type"], "evidence": entity["evidence"]}
            for entity in document_entities(conn, document_id, terms, 5)
        ],
        "citations": ranked_citations(conn, document_id, terms, 5),
        "media_evidence": ranked_media_text(conn, document_id, terms, 5),
    }


def document_user_annotation_summary(conn: sqlite3.Connection, document_id: int, note_limit: int = 3) -> dict:
    return {
        "tags": document_user_tags(conn, document_id),
        "notes": document_user_notes(conn, document_id)[:note_limit],
        "user_status": document_user_status(conn, document_id),
    }


def annotation_matched_terms(annotations: dict, terms: list[str]) -> list[str]:
    status = annotations.get("user_status") or {}
    notes = annotations.get("notes") or []
    haystack = "\n".join(
        [
            " ".join(annotations.get("tags") or []),
            " ".join(note.get("note", "") for note in notes),
            str(status.get("status") or ""),
            str(status.get("note") or ""),
        ]
    )
    return [term for term in terms if term.casefold() in haystack.casefold()]


def matched_terms(row: sqlite3.Row, terms: list[str]) -> list[str]:
    haystack = "\n".join(str(row[key] or "") for key in ("title", "summary"))
    return [term for term in terms if term.casefold() in haystack.casefold()]


def document_entities(
    conn: sqlite3.Connection,
    document_id: int,
    terms: list[str],
    limit: int = 5,
) -> list[sqlite3.Row]:
    where_clause = " OR ".join("(e.name LIKE ? OR e.type LIKE ?)" for _ in terms)
    params = [pattern for term in terms for pattern in [f"%{term}%"] * 2]
    return list(
        conn.execute(
            f"""
            SELECT e.name, e.type, de.evidence
            FROM document_entities de
            JOIN entities e ON e.id = de.entity_id
            WHERE de.document_id = ?
              AND ({where_clause})
            ORDER BY de.confidence DESC, e.name ASC
            LIMIT ?
            """,
            (document_id, *params, limit),
        )
    )


def ranked_citations(
    conn: sqlite3.Connection,
    document_id: int,
    terms: list[str],
    limit: int = 5,
) -> list[dict]:
    where_clause = " OR ".join("text LIKE ?" for _ in terms)
    rows = conn.execute(
        f"""
        SELECT ref, text, source
        FROM citations
        WHERE document_id = ?
          AND ({where_clause})
        LIMIT ?
        """,
        (document_id, *(f"%{term}%" for term in terms), 200),
    ).fetchall()
    ranked = sorted(
        (citation_result(row, terms) for row in rows),
        key=lambda item: (-item["score"], citation_ref_sort_key(item["ref"])),
    )
    return ranked[:limit]


def citation_result(row: sqlite3.Row, terms: list[str]) -> dict:
    text = row["text"] or ""
    matched = [term for term in terms if term.casefold() in text.casefold()]
    score = sum(text.casefold().count(term.casefold()) for term in matched) + len(matched) * 3
    return {
        "ref": row["ref"],
        "text": text,
        "source": row["source"],
        "matched_terms": matched,
        "score": score,
    }


def ranked_media_text(
    conn: sqlite3.Connection,
    document_id: int,
    terms: list[str],
    limit: int = 5,
) -> list[dict]:
    where_clause = " OR ".join("text LIKE ?" for _ in terms)
    rows = conn.execute(
        f"""
        SELECT kind, media_index, url, local_path, status, text
        FROM media
        WHERE document_id = ?
          AND text IS NOT NULL
          AND ({where_clause})
        LIMIT ?
        """,
        (document_id, *(f"%{term}%" for term in terms), 200),
    ).fetchall()
    ranked = sorted(
        (media_text_result(row, terms) for row in rows),
        key=lambda item: (-item["score"], item["kind"], item["index"]),
    )
    return ranked[:limit]


def media_text_result(row: sqlite3.Row, terms: list[str]) -> dict:
    text = row["text"] or ""
    matched = [term for term in terms if term.casefold() in text.casefold()]
    score = sum(text.casefold().count(term.casefold()) for term in matched) + len(matched) * 3
    return {
        "kind": row["kind"],
        "index": row["media_index"],
        "url": row["url"],
        "local_path": row["local_path"],
        "status": row["status"],
        "text": text,
        "matched_terms": matched,
        "score": score,
    }


def citation_ref_sort_key(ref: str | None) -> tuple[int, int, str]:
    value = ref or ""
    match = re.search(r"(\d+)$", value)
    if match:
        return (0, int(match.group(1)), value)
    return (1, 0, value)


def render_query_markdown(package: dict) -> str:
    parts = [
        f"# Link2Context Query: {package['query']}",
        "",
        f"- Terms: {', '.join(package.get('terms', [])) or 'None'}",
        "- Retrieval: keyword search over imported documents, entities, citations, media text, and user annotations",
        "",
    ]
    results = package.get("results", [])
    if not results:
        parts.extend(["No matching evidence found.", ""])
        return "\n".join(parts).strip() + "\n"

    for index, result in enumerate(results, start=1):
        parts.extend(
            [
                f"## {index}. {result.get('title') or 'Untitled'}",
                "",
                f"- URL: {result.get('url')}",
                f"- Platform: {result.get('platform')}",
                f"- Account: {result.get('account_name') or 'Unknown'}",
                f"- Quality: {result.get('quality_status') or 'unknown'}",
                f"- Score: {result.get('score')}",
                "",
            ]
        )
        if result.get("summary"):
            parts.extend(["### Summary", "", result["summary"], ""])
        annotations = result.get("user_annotations") or {}
        if annotations.get("tags") or annotations.get("notes") or annotations.get("user_status"):
            parts.extend(["### User Annotations", ""])
            if annotations.get("user_status"):
                status = annotations["user_status"]
                parts.append(f"- Status: {status.get('status')}")
                if status.get("note"):
                    parts.append(f"  {status['note']}")
            if annotations.get("tags"):
                parts.append(f"- Tags: {', '.join(annotations['tags'])}")
            if annotations.get("notes"):
                parts.append("- Notes:")
                for note in annotations["notes"]:
                    parts.append(f"  - {note['note']}")
            if result.get("annotation_matched_terms"):
                matched = ", ".join(result["annotation_matched_terms"])
                parts.append(f"- Annotation matched terms: {matched}")
            parts.append("")
        if result.get("matched_entities"):
            parts.extend(["### Matched Entities", ""])
            for entity in result["matched_entities"]:
                parts.append(f"- {entity['name']} ({entity['type']}, evidence={entity['evidence']})")
            parts.append("")
        if result.get("citations"):
            parts.extend(["### Evidence", ""])
            for citation in result["citations"]:
                matched = ", ".join(citation.get("matched_terms", [])) or "none"
                parts.extend(
                    [
                        f"- {citation['ref']} | score={citation['score']} | matched={matched}",
                        f"  {citation['text']}",
                    ]
                )
            parts.append("")
        if result.get("media_evidence"):
            parts.extend(["### Media Evidence", ""])
            for media in result["media_evidence"]:
                matched = ", ".join(media.get("matched_terms", [])) or "none"
                parts.extend(
                    [
                        f"- {media['kind']}[{media['index']}] | score={media['score']} | matched={matched}",
                        f"  {media['text']}",
                    ]
                )
            parts.append("")
    return "\n".join(parts).strip() + "\n"


def list_entities(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT e.name, e.type, COUNT(de.document_id) AS documents
            FROM entities e
            JOIN document_entities de ON de.entity_id = e.id
            GROUP BY e.id
            ORDER BY documents DESC, e.name ASC
            LIMIT ?
            """,
            (limit,),
        )
    )


def explain_entity(conn: sqlite3.Connection, name: str, limit: int = 5) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("entity name must not be empty")
    entity = find_entity(conn, name)
    if entity is None:
        return {
            "query": name,
            "found": False,
            "entity": None,
            "documents": [],
            "citations": [],
            "relations": [],
            "note": "No matching entity found in the local store.",
        }
    documents = explain_entity_documents(conn, entity["id"], limit)
    citations = explain_entity_citations(conn, entity["id"], entity["name"], limit)
    relations = explain_entity_relations(conn, entity["name"], limit)
    return {
        "query": name,
        "found": True,
        "entity": {
            "name": entity["name"],
            "type": entity["type"],
            "normalized_name": entity["normalized_name"],
        },
        "documents": documents,
        "citations": citations,
        "relations": relations,
        "note": "Entity explanation is based on imported documents, extracted entities, citations, and rule-based relationships.",
    }


def find_entity(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    normalized = normalize_graph_key(name)
    row = conn.execute(
        """
        SELECT id, normalized_name, name, type
        FROM entities
        WHERE normalized_name = ?
        """,
        (normalized,),
    ).fetchone()
    if row is not None:
        return row
    return conn.execute(
        """
        SELECT id, normalized_name, name, type
        FROM entities
        WHERE name LIKE ?
        ORDER BY length(name) ASC, name ASC
        LIMIT 1
        """,
        (f"%{name}%",),
    ).fetchone()


def explain_entity_documents(conn: sqlite3.Connection, entity_id: int, limit: int = 5) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.title, d.url, d.platform, d.account_name, d.published_at, d.quality_status, de.role, de.evidence
        FROM document_entities de
        JOIN documents d ON d.id = de.document_id
        WHERE de.entity_id = ?
        ORDER BY d.imported_at DESC, d.id DESC
        LIMIT ?
        """,
        (entity_id, limit),
    ).fetchall()
    return [
        {
            "title": row["title"],
            "url": row["url"],
            "platform": row["platform"],
            "account_name": row["account_name"],
            "published_at": row["published_at"],
            "quality_status": row["quality_status"],
            "role": row["role"],
            "evidence": row["evidence"],
        }
        for row in rows
    ]


def explain_entity_citations(
    conn: sqlite3.Connection,
    entity_id: int,
    entity_name: str,
    limit: int = 5,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.ref, c.text, c.source, d.title, d.url, d.platform
        FROM document_entities de
        JOIN documents d ON d.id = de.document_id
        JOIN citations c ON c.document_id = d.id
        WHERE de.entity_id = ?
          AND c.text LIKE ?
        ORDER BY d.imported_at DESC, d.id DESC, c.id ASC
        LIMIT ?
        """,
        (entity_id, f"%{entity_name}%", limit),
    ).fetchall()
    return [
        {
            "ref": row["ref"],
            "text": row["text"],
            "source": row["source"],
            "title": row["title"],
            "url": row["url"],
            "platform": row["platform"],
        }
        for row in rows
    ]


def explain_entity_relations(conn: sqlite3.Connection, entity_name: str, limit: int = 5) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.subject, r.predicate, r.object, r.confidence, r.evidence, d.title, d.url
        FROM relationships r
        JOIN documents d ON d.id = r.document_id
        WHERE r.subject = ? OR r.object = ?
        ORDER BY r.confidence DESC, d.imported_at DESC, r.id ASC
        LIMIT ?
        """,
        (entity_name, entity_name, limit),
    ).fetchall()
    return [
        {
            "subject": row["subject"],
            "predicate": row["predicate"],
            "object": row["object"],
            "confidence": row["confidence"],
            "evidence": row["evidence"],
            "title": row["title"],
            "url": row["url"],
        }
        for row in rows
    ]


def render_entity_explanation_markdown(explanation: dict) -> str:
    if not explanation.get("found"):
        return "\n".join(
            [
                f"# Link2Context Entity: {explanation.get('query')}",
                "",
                explanation.get("note", "No matching entity found."),
                "",
            ]
        ).strip() + "\n"

    entity = explanation["entity"]
    parts = [
        f"# Link2Context Entity: {entity['name']}",
        "",
        f"- Type: {entity['type']}",
        f"- Normalized: {entity['normalized_name']}",
        "",
    ]
    if explanation.get("documents"):
        parts.extend(["## Documents", ""])
        for document in explanation["documents"]:
            parts.append(f"- {document.get('title') or 'Untitled'}")
            parts.append(f"  - URL: {document.get('url')}")
            parts.append(f"  - Platform: {document.get('platform')}")
            if document.get("account_name"):
                parts.append(f"  - Account: {document.get('account_name')}")
            parts.append(f"  - Role: {document.get('role')}")
            parts.append(f"  - Evidence: {document.get('evidence')}")
        parts.append("")
    if explanation.get("citations"):
        parts.extend(["## Citations", ""])
        for citation in explanation["citations"]:
            parts.append(f"- {citation.get('ref')} | {citation.get('title') or 'Untitled'}")
            parts.append(f"  {citation.get('text')}")
        parts.append("")
    if explanation.get("relations"):
        parts.extend(["## Relations", ""])
        for relation in explanation["relations"]:
            parts.append(
                f"- {relation['subject']} --{relation['predicate']}--> {relation['object']} "
                f"(confidence={relation['confidence']})"
            )
            parts.append(f"  - Evidence: {relation.get('evidence')}")
            parts.append(f"  - Source: {relation.get('title') or relation.get('url')}")
        parts.append("")
    if explanation.get("note"):
        parts.extend(["## Note", "", explanation["note"], ""])
    return "\n".join(parts).strip() + "\n"


def interest_profile(conn: sqlite3.Connection, limit: int = 20) -> dict:
    candidate_limit = max(limit * 4, limit)
    stop_names_sql = ", ".join(sql_string_literal(name) for name in sorted(PROFILE_TERM_STOP_NAMES))
    entity_filter = """
        e.type NOT IN ('source_account', 'person_or_author')
        AND NOT (e.type = 'term' AND (length(e.name) <= 2 OR e.name IN ({stop_names})))
    """.format(stop_names=stop_names_sql)
    entity_rows = conn.execute(
        f"""
        SELECT e.id, e.name, e.type,
               COUNT(DISTINCT de.document_id) AS documents,
               AVG(de.confidence) AS avg_confidence,
               COUNT(DISTINCT CASE WHEN de.evidence = 'media.text' THEN de.document_id END) AS media_documents
        FROM entities e
        JOIN document_entities de ON de.entity_id = e.id
        WHERE {entity_filter}
        GROUP BY e.id
        ORDER BY documents DESC, avg_confidence DESC, e.name ASC
        LIMIT ?
        """,
        (candidate_limit,),
    ).fetchall()
    account_rows = conn.execute(
        """
        SELECT account_name, COUNT(*) AS documents
        FROM documents
        WHERE account_name IS NOT NULL AND account_name != ''
        GROUP BY account_name
        ORDER BY documents DESC, account_name ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    platform_rows = conn.execute(
        "SELECT platform, COUNT(*) AS documents FROM documents GROUP BY platform ORDER BY documents DESC"
    ).fetchall()
    recent_document_rows = conn.execute(
        """
        SELECT id, title, url, platform, account_name, published_at, imported_at, quality_status
        FROM documents
        ORDER BY COALESCE(published_at, imported_at) DESC, imported_at DESC, id DESC
        LIMIT ?
        """,
        (min(limit, 10),),
    ).fetchall()
    recent_entity_rows = conn.execute(
        f"""
        SELECT e.id, e.name, e.type, COUNT(DISTINCT d.id) AS documents,
               AVG(de.confidence) AS avg_confidence,
               COUNT(DISTINCT CASE WHEN de.evidence = 'media.text' THEN d.id END) AS media_documents,
               MAX(COALESCE(d.published_at, d.imported_at)) AS latest_at
        FROM entities e
        JOIN document_entities de ON de.entity_id = e.id
        JOIN documents d ON d.id = de.document_id
        WHERE {entity_filter}
        GROUP BY e.id
        ORDER BY latest_at DESC, documents DESC, avg_confidence DESC, e.name ASC
        LIMIT ?
        """,
        (max(min(limit, 10) * 4, min(limit, 10)),),
    ).fetchall()
    top_entities = profile_entity_entries(conn, entity_rows, 3, limit, sort_entries=True)
    recent_entities = profile_entity_entries(conn, recent_entity_rows, 2, min(limit, 10), sort_entries=False)
    recent_account_rows = conn.execute(
        """
        SELECT account_name, COUNT(*) AS documents,
               MAX(COALESCE(published_at, imported_at)) AS latest_at
        FROM documents
        WHERE account_name IS NOT NULL AND account_name != ''
        GROUP BY account_name
        ORDER BY latest_at DESC, documents DESC, account_name ASC
        LIMIT ?
        """,
        (min(limit, 10),),
    ).fetchall()
    return {
        "documents": conn.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"],
        "top_entities": [
            entity
            for entity in top_entities
        ],
        "top_accounts": [
            {
                "name": row["account_name"],
                "documents": row["documents"],
                "evidence_documents": account_evidence(conn, row["account_name"], 3),
            }
            for row in account_rows
        ],
        "by_platform": {
            row["platform"]: row["documents"]
            for row in platform_rows
        },
        "recent_documents": [
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "platform": row["platform"],
                "account_name": row["account_name"],
                "published_at": row["published_at"],
                "imported_at": row["imported_at"],
                "quality_status": row["quality_status"],
            }
            for row in recent_document_rows
        ],
        "recent_entities": [
            entity
            for entity in recent_entities
        ],
        "recent_accounts": [
            {
                "name": row["account_name"],
                "documents": row["documents"],
                "latest_at": row["latest_at"],
                "evidence_documents": account_evidence(conn, row["account_name"], 2),
            }
            for row in recent_account_rows
        ],
        "note": "Conservative profile based only on imported context entities, source metadata, and document chronology.",
    }


def profile_entity_entries(
    conn: sqlite3.Connection,
    rows: Iterable[sqlite3.Row],
    evidence_limit: int,
    limit: int,
    *,
    sort_entries: bool,
) -> list[dict]:
    entries: list[dict] = []
    for row in rows:
        if is_profile_noise_entity(row["name"], row["type"]):
            continue
        evidence_citations = entity_citation_evidence(conn, row["id"], row["name"], evidence_limit)
        entry = {
            "name": row["name"],
            "type": row["type"],
            "documents": row["documents"],
            "avg_confidence": row["avg_confidence"],
            "media_documents": row["media_documents"],
            "evidence_documents": entity_evidence(conn, row["id"], evidence_limit),
            "evidence_citations": evidence_citations,
            "evidence_citation_count": len(evidence_citations),
        }
        if "latest_at" in row.keys():
            entry["latest_at"] = row["latest_at"]
        entries.append(entry)
    if sort_entries:
        entries.sort(key=profile_entity_sort_key)
    return entries[:limit]


def profile_entity_sort_key(entity: dict) -> tuple:
    return (
        -int(entity.get("documents") or 0),
        -int(entity.get("evidence_citation_count") or 0),
        -float(entity.get("avg_confidence") or 0),
        str(entity.get("name") or "").casefold(),
    )


def is_profile_noise_entity(name: str, entity_type: str | None = None) -> bool:
    cleaned = str(name or "").strip()
    if not cleaned:
        return True
    if cleaned in PROFILE_ENTITY_STOP_NAMES:
        return True
    if entity_type == "term" and cleaned.casefold() in {item.casefold() for item in PROFILE_TERM_STOP_NAMES}:
        return True
    return False


def render_profile_markdown(profile: dict) -> str:
    parts = [
        "# Link2Context Interest Profile",
        "",
        f"- Documents: {profile.get('documents', 0)}",
        "- Basis: imported contexts, extracted entities, and source metadata",
        "",
    ]
    if profile.get("by_platform"):
        parts.extend(["## Platforms", ""])
        for platform, count in profile["by_platform"].items():
            parts.append(f"- {platform}: {count}")
        parts.append("")

    if profile.get("top_entities"):
        parts.extend(["## Top Entities", ""])
        for entity in profile["top_entities"]:
            confidence = entity.get("avg_confidence")
            confidence_text = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "unknown"
            media_text = (
                f", {entity.get('media_documents', 0)} media-text document(s)"
                if entity.get("media_documents")
                else ""
            )
            parts.append(
                f"- {entity['name']} ({entity['type']}): {entity['documents']} document(s), "
                f"avg confidence {confidence_text}{media_text}"
            )
            for evidence in entity.get("evidence_documents", [])[:2]:
                parts.append(f"  - {evidence.get('title') or 'Untitled'}: {evidence.get('url')}")
            for citation in entity.get("evidence_citations", [])[:2]:
                parts.append(f"  - Citation {citation.get('ref')}: {citation.get('text')}")
        parts.append("")

    if profile.get("top_accounts"):
        parts.extend(["## Top Accounts", ""])
        for account in profile["top_accounts"]:
            parts.append(f"- {account['name']}: {account['documents']} document(s)")
            for evidence in account.get("evidence_documents", [])[:2]:
                parts.append(f"  - {evidence.get('title') or 'Untitled'}: {evidence.get('url')}")
        parts.append("")

    if profile.get("recent_documents"):
        parts.extend(["## Recent Documents", ""])
        for document in profile["recent_documents"][:5]:
            date = document.get("published_at") or document.get("imported_at") or "unknown"
            parts.append(f"- {date}: {document.get('title') or 'Untitled'}")
            parts.append(f"  - {document.get('url')}")
        parts.append("")

    if profile.get("recent_entities"):
        parts.extend(["## Recent Entities", ""])
        for entity in profile["recent_entities"][:5]:
            confidence = entity.get("avg_confidence")
            confidence_text = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "unknown"
            media_text = (
                f", {entity.get('media_documents', 0)} media-text document(s)"
                if entity.get("media_documents")
                else ""
            )
            parts.append(
                f"- {entity['name']} ({entity['type']}): latest {entity.get('latest_at') or 'unknown'}, "
                f"{entity['documents']} document(s), avg confidence {confidence_text}{media_text}"
            )
        parts.append("")

    if profile.get("recent_accounts"):
        parts.extend(["## Recent Accounts", ""])
        for account in profile["recent_accounts"][:5]:
            parts.append(
                f"- {account['name']}: latest {account.get('latest_at') or 'unknown'}, {account['documents']} document(s)"
            )
        parts.append("")

    if profile.get("note"):
        parts.extend(["## Note", "", profile["note"], ""])
    return "\n".join(parts).strip() + "\n"


def external_brain_brief(conn: sqlite3.Connection, limit: int = 10) -> dict:
    return {
        "project": "Link2Context",
        "purpose": "Agent-ready brief of the user's imported external brain store.",
        "stats": stats(conn),
        "profile": interest_profile(conn, limit),
        "annotations": annotations_report(conn, min(limit, 5)),
        "starter_queries": starter_queries(conn, min(limit, 8)),
        "clusters": clusters_report(conn, 2, min(limit, 5))["clusters"],
        "recent_documents": recent_documents(conn, limit),
        "agent_usage": {
            "query_command": "python -m link2context.store --db data/link2context.db query \"<question>\" --format markdown",
            "clusters_command": "python -m link2context.store --db data/link2context.db clusters",
            "questions_command": "python -m link2context.store --db data/link2context.db questions",
            "annotations_command": "python -m link2context.store --db data/link2context.db annotations",
            "graph_command": "python -m link2context.store --db data/link2context.db graph --format mermaid",
            "profile_command": "python -m link2context.store --db data/link2context.db profile --format markdown",
            "caution": "Use citations and URLs as evidence. Treat profile and graph as conservative rule-based MVP outputs.",
        },
        "note": "This brief summarizes imported contexts only; it is not a complete semantic memory.",
    }


def starter_queries(conn: sqlite3.Connection, limit: int = 8) -> list[dict]:
    limit = max(1, limit)
    suggestions: list[dict] = []
    seen: set[str] = set()

    def add(query: str | None, source: str, reason: str, documents: int | None = None) -> None:
        if len(suggestions) >= limit:
            return
        value = normalize_query_suggestion(query)
        if not value:
            return
        key = value.casefold()
        if key in seen:
            return
        seen.add(key)
        item = {
            "query": value,
            "source": source,
            "reason": reason,
            "command": f'python -m link2context.store --db data/link2context.db query "{escape_command_query(value)}" --format markdown',
        }
        if documents is not None:
            item["documents"] = documents
        suggestions.append(item)

    tag_rows = conn.execute(
        """
        SELECT tag, COUNT(DISTINCT document_id) AS documents
        FROM document_tags
        GROUP BY tag
        ORDER BY documents DESC, tag ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    for row in tag_rows:
        add(row["tag"], "user_tag", f"User tag on {row['documents']} document(s).", row["documents"])

    note_rows = conn.execute(
        """
        SELECT note, COUNT(*) AS documents
        FROM document_notes
        GROUP BY note
        ORDER BY documents DESC, MAX(created_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    for row in note_rows:
        add(row["note"], "user_note", "User note text matched by query.", row["documents"])

    status_rows = conn.execute(
        """
        SELECT status, note, COUNT(*) AS documents
        FROM document_status
        GROUP BY status, note
        ORDER BY documents DESC, MAX(updated_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    for row in status_rows:
        add(row["note"] or row["status"], "user_status", f"Workflow status: {row['status']}.", row["documents"])

    entity_rows = conn.execute(
        """
        SELECT e.name, e.type, COUNT(DISTINCT de.document_id) AS documents
        FROM entities e
        JOIN document_entities de ON de.entity_id = e.id
        WHERE e.type NOT IN ('source_account', 'person_or_author')
          AND NOT (e.type = 'term' AND (length(e.name) <= 2 OR e.name IN ('AI', 'Agent', 'Agents', 'Skill', 'Skills')))
        GROUP BY e.id
        ORDER BY documents DESC, e.name ASC
        LIMIT ?
        """,
        (limit * 2,),
    ).fetchall()
    for row in entity_rows:
        if row["name"] in PROFILE_ENTITY_STOP_NAMES:
            continue
        add(
            row["name"],
            f"entity:{row['type']}",
            f"Repeated extracted signal across {row['documents']} document(s).",
            row["documents"],
        )

    account_rows = conn.execute(
        """
        SELECT account_name, COUNT(*) AS documents
        FROM documents
        WHERE account_name IS NOT NULL AND account_name != ''
        GROUP BY account_name
        ORDER BY documents DESC, account_name ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    for row in account_rows:
        add(
            row["account_name"],
            "source_account",
            f"Source account with {row['documents']} imported document(s).",
            row["documents"],
        )

    return suggestions


def normalize_query_suggestion(query: str | None, limit: int = 80) -> str:
    value = re.sub(r"\s+", " ", query or "").strip()
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[:limit].rstrip()


def escape_command_query(query: str) -> str:
    return query.replace('"', '\\"')


def recent_documents(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, title, url, platform, account_name, published_at, quality_status
        FROM documents
        ORDER BY imported_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "platform": row["platform"],
            "account_name": row["account_name"],
            "published_at": row["published_at"],
            "quality_status": row["quality_status"],
        }
        for row in rows
    ]


def render_brief_markdown(brief: dict) -> str:
    profile = brief.get("profile", {})
    store_stats = brief.get("stats", {})
    parts = [
        "# Link2Context External Brain Brief",
        "",
        brief.get("purpose", ""),
        "",
        "## Store Stats",
        "",
        f"- Documents: {store_stats.get('documents', 0)}",
        f"- Citations: {store_stats.get('citations', 0)}",
        f"- Entities: {store_stats.get('entities', 0)}",
        f"- Relationships: {store_stats.get('relationships', 0)}",
        "",
    ]
    if store_stats.get("by_platform"):
        parts.extend(["## Platforms", ""])
        for platform, count in store_stats["by_platform"].items():
            parts.append(f"- {platform}: {count}")
        parts.append("")

    if profile.get("top_entities"):
        parts.extend(["## Interest Signals", ""])
        for entity in profile["top_entities"][:5]:
            parts.append(f"- {entity['name']} ({entity['type']}): {entity['documents']} document(s)")
        parts.append("")

    if profile.get("top_accounts"):
        parts.extend(["## Source Accounts", ""])
        for account in profile["top_accounts"][:5]:
            parts.append(f"- {account['name']}: {account['documents']} document(s)")
        parts.append("")

    annotations = brief.get("annotations", {})
    if annotations.get("documents"):
        parts.extend(["## User Annotations", ""])
        summary = annotations.get("summary", {})
        parts.append(
            f"- Annotated documents: {summary.get('documents', 0)} "
            f"(tags={summary.get('with_tags', 0)}, notes={summary.get('with_notes', 0)}, "
            f"status={summary.get('with_status', 0)})"
        )
        for document in annotations["documents"][:5]:
            parts.append(f"- [{document['id']}] {document.get('title') or 'Untitled'}")
            if document.get("user_status"):
                parts.append(f"  - Status: {document['user_status'].get('status')}")
            if document.get("tags"):
                parts.append(f"  - Tags: {', '.join(document['tags'])}")
            if document.get("notes"):
                parts.append(f"  - Note: {document['notes'][0].get('note')}")
        parts.append("")

    if brief.get("clusters"):
        parts.extend(["## Topic Clusters", ""])
        for cluster in brief["clusters"][:5]:
            parts.append(f"- {cluster['name']} ({cluster['type']}): {cluster['documents']} document(s)")
            commands = cluster.get("commands", {})
            if commands.get("explain"):
                parts.append(f"  - Explain: `{commands.get('explain')}`")
            if commands.get("evidence"):
                parts.append(f"  - Evidence: `{commands.get('evidence')}`")
        parts.append("")

    if brief.get("starter_queries"):
        parts.extend(["## Starter Queries", ""])
        for item in brief["starter_queries"][:8]:
            documents = item.get("documents")
            documents_text = f", documents={documents}" if documents is not None else ""
            parts.append(f"- {item['query']} ({item['source']}{documents_text})")
            parts.append(f"  - Reason: {item['reason']}")
            parts.append(f"  - `{item['command']}`")
        parts.append("")

    if brief.get("recent_documents"):
        parts.extend(["## Recent Documents", ""])
        for document in brief["recent_documents"]:
            title = document.get("title") or "Untitled"
            parts.append(f"- {title}")
            if document.get("id") is not None:
                parts.append(f"  - ID: {document.get('id')}")
            parts.append(f"  - URL: {document.get('url')}")
            parts.append(f"  - Platform: {document.get('platform')}")
            if document.get("account_name"):
                parts.append(f"  - Account: {document.get('account_name')}")
        parts.append("")

    agent_usage = brief.get("agent_usage", {})
    if agent_usage:
        parts.extend(["## Agent Usage", ""])
        parts.append(f"- Query: `{agent_usage.get('query_command')}`")
        parts.append(f"- Clusters: `{agent_usage.get('clusters_command')}`")
        parts.append(f"- Questions: `{agent_usage.get('questions_command')}`")
        parts.append(f"- Annotations: `{agent_usage.get('annotations_command')}`")
        parts.append(f"- Graph: `{agent_usage.get('graph_command')}`")
        parts.append(f"- Profile: `{agent_usage.get('profile_command')}`")
        parts.append(f"- Caution: {agent_usage.get('caution')}")
        parts.append("")

    if brief.get("note"):
        parts.extend(["## Note", "", brief["note"], ""])
    return "\n".join(part for part in parts if part is not None).strip() + "\n"


def render_starter_queries_markdown(queries: list[dict]) -> str:
    parts = [
        "# Link2Context Starter Queries",
        "",
        "Suggested first queries for an agent taking over this external brain store.",
        "",
    ]
    if not queries:
        parts.extend(["No starter queries available.", ""])
        return "\n".join(parts).strip() + "\n"
    for index, item in enumerate(queries, start=1):
        documents = item.get("documents")
        documents_text = f", documents={documents}" if documents is not None else ""
        parts.append(f"## {index}. {item.get('query')}")
        parts.append("")
        parts.append(f"- Source: {item.get('source')}{documents_text}")
        parts.append(f"- Reason: {item.get('reason')}")
        parts.append(f"- Command: `{item.get('command')}`")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def agent_tasks(
    actions: dict,
    curate: dict,
    starter_query_items: list[dict],
    limit: int = 20,
    kind: str | None = None,
    source: str | None = None,
    max_priority: int | None = None,
    contains: str | None = None,
    retry_mode: str | None = None,
    cache_status: str | None = None,
) -> dict:
    limit = max(1, limit)
    tasks: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(task: dict) -> None:
        task = enrich_agent_task(task)
        command = task.get("command") or ""
        title = task.get("title") or command
        key = (command, title)
        if key in seen:
            return
        seen.add(key)
        tasks.append(task)

    for action in actions.get("actions", []):
        add(
            {
                "priority": action.get("priority", 9),
                "kind": action.get("kind"),
                "source": "actions",
                "title": action.get("title"),
                "detail": action.get("detail"),
                "command": action.get("command"),
            }
        )

    for query in starter_query_items:
        add(
            {
                "priority": 2,
                "kind": "query",
                "source": f"starter_query:{query.get('source')}",
                "title": f"Query: {query.get('query')}",
                "detail": query.get("reason"),
                "command": query.get("command"),
                "documents": query.get("documents"),
            }
        )

    lane_priorities = {
        "read_now": 2,
        "continue_marked": 2,
        "fix_quality": 2,
        "process_media": 3,
        "review_duplicates": 3,
        "agent_handoff": 4,
    }
    for lane in curate.get("lanes", []):
        lane_name = lane.get("name")
        for item in lane.get("items", []):
            title = item.get("title") or lane.get("title") or lane_name
            add(
                {
                    "priority": lane_priorities.get(lane_name, 6),
                    "kind": lane_name,
                    "source": "curate",
                    "title": title,
                    "detail": item.get("detail") or lane.get("purpose"),
                    "command": item.get("command"),
                    "document_id": item.get("id") or item.get("document_id"),
                }
            )

    normalized_kind = normalize_task_kind(kind)
    if normalized_kind:
        tasks = [task for task in tasks if normalize_task_kind(task.get("kind")) == normalized_kind]
    normalized_source = normalize_task_source(source)
    if normalized_source:
        tasks = [task for task in tasks if task_source_matches(task.get("source"), normalized_source)]
    normalized_max_priority = normalize_task_max_priority(max_priority)
    if normalized_max_priority is not None:
        tasks = [task for task in tasks if int(task.get("priority", 9)) <= normalized_max_priority]
    normalized_contains = normalize_task_contains(contains)
    if normalized_contains:
        tasks = [task for task in tasks if task_contains_text(task, normalized_contains)]
    normalized_retry_mode = normalize_task_contains(retry_mode)
    if normalized_retry_mode:
        tasks = [task for task in tasks if normalize_task_contains(task.get("retry_mode")) == normalized_retry_mode]
    normalized_cache_status = normalize_task_contains(cache_status)
    if normalized_cache_status:
        tasks = [task for task in tasks if normalize_task_contains(task.get("cache_status")) == normalized_cache_status]
    tasks = sorted(tasks, key=agent_task_sort_key)[:limit]
    return {
        "status": curate.get("status") or actions.get("status"),
        "ready_for_agent": curate.get("ready_for_agent", actions.get("ready_for_agent")),
        "filters": {
            "kind": normalized_kind,
            "source": normalized_source,
            "max_priority": normalized_max_priority,
            "contains": normalized_contains,
            "retry_mode": normalized_retry_mode,
            "cache_status": normalized_cache_status,
        },
        "tasks": tasks,
        "limit": limit,
        "note": "Agent tasks combine action priorities, starter queries, and curate lanes into a machine-readable handoff checklist.",
    }


def normalize_task_kind(kind: str | None) -> str | None:
    value = (kind or "").strip()
    return value or None


def normalize_task_source(source: str | None) -> str | None:
    value = (source or "").strip()
    return value or None


def normalize_task_max_priority(max_priority: int | None) -> int | None:
    if max_priority is None:
        return None
    return max(1, max_priority)


def normalize_task_contains(contains: str | None) -> str | None:
    value = re.sub(r"\s+", " ", contains or "").strip()
    return value.casefold() if value else None


def enrich_agent_task(task: dict) -> dict:
    detail = task.get("detail") or ""
    fields = task_detail_fields(detail)
    enriched = dict(task)
    for key in ("retry_mode", "cache_status", "cache_error"):
        if key in fields and key not in enriched:
            enriched[key] = fields[key]
    return enriched


def task_detail_fields(detail: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in detail.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            fields[key] = value
    return fields


def task_contains_text(task: dict, contains: str) -> bool:
    haystack = "\n".join(
        str(task.get(key) or "")
        for key in ("title", "detail", "command", "source", "kind", "retry_mode", "cache_status", "cache_error")
    )
    return contains in haystack.casefold()


def task_source_matches(task_source: str | None, filter_source: str) -> bool:
    value = task_source or ""
    return value == filter_source or value.startswith(f"{filter_source}:")


def agent_task_sort_key(item: dict) -> tuple[int, int, str, str]:
    kind = item.get("kind") or ""
    kind_rank = {
        "query": 0,
        "read_now": 1,
        "media_cache": 2,
        "media_review": 3,
        "media": 4,
        "process_media": 4,
        "handoff": 8,
    }.get(kind, 5)
    return (item.get("priority", 9), kind_rank, kind, item.get("title") or "")


def agent_task_report(
    conn: sqlite3.Connection,
    limit: int = 20,
    kind: str | None = None,
    source: str | None = None,
    max_priority: int | None = None,
    contains: str | None = None,
    retry_mode: str | None = None,
    cache_status: str | None = None,
) -> dict:
    actions = action_plan(conn, limit)
    curate = curate_report(conn, min(limit, 10))
    queries = starter_queries(conn, min(limit, 8))
    return agent_tasks(actions, curate, queries, limit, kind, source, max_priority, contains, retry_mode, cache_status)


def render_agent_tasks_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Agent Tasks",
        "",
        f"- Status: {report.get('status')}",
        f"- Ready for agent: {str(report.get('ready_for_agent')).lower()}",
        f"- Kind filter: {(report.get('filters') or {}).get('kind') or 'all'}",
        f"- Source filter: {(report.get('filters') or {}).get('source') or 'all'}",
        f"- Max priority: {(report.get('filters') or {}).get('max_priority') or 'all'}",
        f"- Contains: {(report.get('filters') or {}).get('contains') or 'all'}",
        f"- Retry mode: {(report.get('filters') or {}).get('retry_mode') or 'all'}",
        f"- Cache status: {(report.get('filters') or {}).get('cache_status') or 'all'}",
        "",
    ]
    if not report.get("tasks"):
        parts.extend(["No agent tasks available.", ""])
        return "\n".join(parts).strip() + "\n"
    parts.extend(["## Tasks", ""])
    for task in report["tasks"]:
        parts.append(f"- P{task.get('priority')} [{task.get('kind')}] {task.get('title')}")
        if task.get("detail"):
            parts.append(f"  - Detail: {task.get('detail')}")
        if task.get("documents") is not None:
            parts.append(f"  - Documents: {task.get('documents')}")
        if task.get("document_id") is not None:
            parts.append(f"  - Document: {task.get('document_id')}")
        if task.get("retry_mode"):
            parts.append(f"  - Retry mode: {task.get('retry_mode')}")
        if task.get("cache_status"):
            parts.append(f"  - Cache status: {task.get('cache_status')}")
        if task.get("command"):
            parts.append(f"  - Command: `{task.get('command')}`")
    parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def agent_task_commands(report: dict) -> list[str]:
    commands = []
    seen = set()
    for task in report.get("tasks", []):
        command = task.get("command")
        if command and command not in seen:
            seen.add(command)
            commands.append(command)
    return commands


def export_agent_handoff(conn: sqlite3.Connection, out_dir: Path, limit: int = 20) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    brief = external_brain_brief(conn, limit)
    profile = brief["profile"]
    graph = export_graph(conn, limit)
    doctor = store_doctor(conn)
    timeline = document_timeline(conn, limit)
    media = media_inventory(conn, "all", None, limit)
    media_pipeline = media_pipeline_status(conn)
    queue = media_queue(conn, "all", "not_processed", limit)
    quality = quality_report(conn, None, limit)
    actions = action_plan(conn, limit)
    sources = source_report(conn, limit)
    tags = tag_report(conn, limit)
    notes = notes_report(conn, limit)
    statuses = status_report(conn, None, limit)
    annotations = annotations_report(conn, limit)
    topics = topics_report(conn, None, limit)
    clusters = clusters_report(conn, 2, limit)
    questions = questions_report(conn, limit)
    relations = relations_report(conn, None, None, limit)
    digest = digest_report(conn, limit)
    evidence = evidence_report(conn, None, limit)
    review = review_report(conn, limit)
    inbox = inbox_report(conn, limit)
    curate = curate_report(conn, limit)
    duplicates = duplicate_report(conn, limit)
    coverage = coverage_report(conn, limit)
    tasks = agent_task_report(conn, limit)
    hot_tasks = agent_task_report(conn, max(limit, 10))
    hot_commands = handoff_hot_commands(hot_tasks)
    hot_command_groups = group_hot_commands(hot_commands)
    exported_at = datetime.now(timezone.utc).isoformat()
    files = {
        "handoff.md": render_handoff_markdown(brief, doctor, media, limit, hot_tasks, media_pipeline),
        "auto-queue.commands.txt": render_hot_command_commands(hot_command_groups["auto_queue"]),
        "auto-queue.jsonl": render_hot_command_jsonl(hot_command_groups["auto_queue"]),
        "inbox.md": render_inbox_markdown(inbox),
        "inbox.json": json.dumps(inbox, ensure_ascii=False, indent=2) + "\n",
        "curate.md": render_curate_markdown(curate),
        "curate.json": json.dumps(curate, ensure_ascii=False, indent=2) + "\n",
        "duplicates.md": render_duplicate_markdown(duplicates),
        "duplicates.json": json.dumps(duplicates, ensure_ascii=False, indent=2) + "\n",
        "coverage.md": render_coverage_markdown(coverage),
        "coverage.json": json.dumps(coverage, ensure_ascii=False, indent=2) + "\n",
        "review.md": render_review_markdown(review),
        "review.json": json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        "brief.md": render_brief_markdown(brief),
        "brief.json": json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
        "starter-queries.md": render_starter_queries_markdown(brief.get("starter_queries", [])),
        "starter-queries.json": json.dumps(brief.get("starter_queries", []), ensure_ascii=False, indent=2) + "\n",
        "doctor.md": render_doctor_markdown(doctor),
        "doctor.json": json.dumps(doctor, ensure_ascii=False, indent=2) + "\n",
        "quality.md": render_quality_markdown(quality),
        "quality.json": json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        "evidence.md": render_evidence_markdown(evidence),
        "evidence.json": json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        "actions.md": render_action_plan_markdown(actions),
        "actions.json": json.dumps(actions, ensure_ascii=False, indent=2) + "\n",
        "agent-tasks.md": render_agent_tasks_markdown(tasks),
        "agent-tasks.json": json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
        "digest.md": render_digest_markdown(digest),
        "digest.json": json.dumps(digest, ensure_ascii=False, indent=2) + "\n",
        "sources.md": render_sources_markdown(sources),
        "sources.json": json.dumps(sources, ensure_ascii=False, indent=2) + "\n",
        "tags.md": render_tags_markdown(tags),
        "tags.json": json.dumps(tags, ensure_ascii=False, indent=2) + "\n",
        "notes.md": render_notes_markdown(notes),
        "notes.json": json.dumps(notes, ensure_ascii=False, indent=2) + "\n",
        "statuses.md": render_statuses_markdown(statuses),
        "statuses.json": json.dumps(statuses, ensure_ascii=False, indent=2) + "\n",
        "annotations.md": render_annotations_markdown(annotations),
        "annotations.json": json.dumps(annotations, ensure_ascii=False, indent=2) + "\n",
        "topics.md": render_topics_markdown(topics),
        "topics.json": json.dumps(topics, ensure_ascii=False, indent=2) + "\n",
        "clusters.md": render_clusters_markdown(clusters),
        "clusters.json": json.dumps(clusters, ensure_ascii=False, indent=2) + "\n",
        "questions.md": render_questions_markdown(questions),
        "questions.json": json.dumps(questions, ensure_ascii=False, indent=2) + "\n",
        "relations.md": render_relations_markdown(relations),
        "relations.json": json.dumps(relations, ensure_ascii=False, indent=2) + "\n",
        "profile.md": render_profile_markdown(profile),
        "profile.json": json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        "timeline.md": render_timeline_markdown(timeline),
        "timeline.json": json.dumps(timeline, ensure_ascii=False, indent=2) + "\n",
        "media-pipeline.md": render_media_pipeline_markdown(media_pipeline),
        "media-pipeline.json": json.dumps(media_pipeline, ensure_ascii=False, indent=2) + "\n",
        "queue.md": render_media_queue_markdown(queue),
        "queue.json": json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        "media.md": render_media_markdown(media),
        "media.json": json.dumps(media, ensure_ascii=False, indent=2) + "\n",
        "graph.json": json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
        "graph.mmd": render_graph_mermaid(graph),
    }
    for file_name, content in files.items():
        (out_dir / file_name).write_text(content, encoding="utf-8")
    file_details = {
        file_name: export_file_detail(out_dir / file_name)
        for file_name in files
    }
    manifest = {
        "project": "Link2Context",
        "exported_at": exported_at,
        "limit": limit,
        "files": list(files.keys()),
        "file_details": file_details,
        "hot_commands": hot_commands,
        "hot_command_groups": hot_command_groups,
        "media_pipeline": media_pipeline,
        "stats": brief["stats"],
        "note": "Agent handoff bundle generated from the local Link2Context SQLite store.",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def export_file_detail(path: Path) -> dict:
    content = path.read_bytes()
    return {
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def render_hot_command_commands(commands: list[dict]) -> str:
    lines = [entry["command"] for entry in commands if entry.get("command")]
    return "\n".join(lines).strip() + ("\n" if lines else "")


def render_hot_command_jsonl(commands: list[dict]) -> str:
    if not commands:
        return ""
    return "\n".join(json.dumps(entry, ensure_ascii=False) for entry in commands) + "\n"


def verify_auto_queue(path: Path, base_dir: Path | None = None) -> dict:
    base_dir = base_dir or Path(".")
    commands_path = path / "auto-queue.commands.txt"
    jsonl_path = path / "auto-queue.jsonl"
    errors: list[str] = []
    warnings: list[str] = []
    command_lines: list[str] = []
    entries: list[dict] = []

    if not commands_path.exists():
        errors.append("auto-queue.commands.txt is missing")
    else:
        command_lines = [line.strip() for line in commands_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not jsonl_path.exists():
        errors.append("auto-queue.jsonl is missing")
    else:
        for line_number, line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"auto-queue.jsonl line {line_number} invalid JSON: {exc.msg}")
                continue
            if not isinstance(entry, dict):
                errors.append(f"auto-queue.jsonl line {line_number} must be an object")
                continue
            entries.append(entry)

    if not command_lines:
        errors.append("auto-queue.commands.txt has no executable commands")
    if not entries:
        errors.append("auto-queue.jsonl has no command entries")

    jsonl_commands = [str(entry.get("command") or "").strip() for entry in entries if entry.get("command")]
    if command_lines and jsonl_commands and command_lines != jsonl_commands:
        errors.append("auto-queue.commands.txt commands do not match auto-queue.jsonl command order")

    for index, entry in enumerate(entries, start=1):
        if entry.get("automation") != "auto_queue":
            errors.append(f"auto-queue.jsonl entry {index} automation is not auto_queue")
        if entry.get("requires_review") is not False:
            errors.append(f"auto-queue.jsonl entry {index} requires_review must be false")
        local_path = task_detail_fields(str(entry.get("reason") or "")).get("local_path")
        if not local_path:
            warnings.append(f"auto-queue.jsonl entry {index} has no local_path in reason")
            continue
        candidate = Path(local_path)
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        if not candidate.exists():
            errors.append(f"auto-queue.jsonl entry {index} local_path does not exist: {local_path}")

    return {
        "path": str(path),
        "base_dir": str(base_dir),
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "commands": len(command_lines),
        "entries": len(entries),
        "files": {
            "auto-queue.commands.txt": commands_path.exists(),
            "auto-queue.jsonl": jsonl_path.exists(),
        },
        "note": "Run auto-queue.commands.txt only when this preflight report is ok.",
    }


def render_verify_auto_queue_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Auto Queue Verification",
        "",
        f"- Path: {report.get('path')}",
        f"- Base dir: {report.get('base_dir')}",
        f"- OK: {str(report.get('ok')).lower()}",
        f"- Commands: {report.get('commands', 0)}",
        f"- Entries: {report.get('entries', 0)}",
        "",
    ]
    if report.get("errors"):
        parts.extend(["## Errors", ""])
        for error in report["errors"]:
            parts.append(f"- {error}")
        parts.append("")
    if report.get("warnings"):
        parts.extend(["## Warnings", ""])
        for warning in report["warnings"]:
            parts.append(f"- {warning}")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def verify_auto_queue_next(path: Path) -> dict:
    commands_path = path / "auto-queue-next.commands.txt"
    jsonl_path = path / "auto-queue-next.jsonl"
    manifest_path = path / "manifest.json"
    errors: list[str] = []
    warnings: list[str] = []
    command_lines: list[str] = []
    entries: list[dict] = []

    if not commands_path.exists():
        errors.append("auto-queue-next.commands.txt is missing")
    else:
        command_lines = [line.strip() for line in commands_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not jsonl_path.exists():
        errors.append("auto-queue-next.jsonl is missing")
    else:
        for line_number, line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"auto-queue-next.jsonl line {line_number} invalid JSON: {exc.msg}")
                continue
            if not isinstance(entry, dict):
                errors.append(f"auto-queue-next.jsonl line {line_number} must be an object")
                continue
            entries.append(entry)

    if not command_lines:
        errors.append("auto-queue-next.commands.txt has no executable commands")
    if not entries:
        errors.append("auto-queue-next.jsonl has no command entries")

    jsonl_commands = [str(entry.get("command") or "").strip() for entry in entries if entry.get("command")]
    if command_lines and jsonl_commands and command_lines != jsonl_commands:
        errors.append("auto-queue-next.commands.txt commands do not match auto-queue-next.jsonl command order")
    if command_lines and entries and len(command_lines) != len(entries):
        errors.append("auto-queue-next command count does not match JSONL entry count")

    out_paths: list[str] = []
    for index, entry in enumerate(entries, start=1):
        command = str(entry.get("command") or "").strip()
        if entry.get("automation") != "manual_review":
            errors.append(f"auto-queue-next.jsonl entry {index} automation is not manual_review")
        if entry.get("requires_review") is not True:
            errors.append(f"auto-queue-next.jsonl entry {index} requires_review must be true")
        if entry.get("stage") != "run_media_text":
            errors.append(f"auto-queue-next.jsonl entry {index} stage is not run_media_text")
        if not entry.get("source_command"):
            warnings.append(f"auto-queue-next.jsonl entry {index} has no source_command")
        if " run-media-text" not in f" {command}":
            errors.append(f"auto-queue-next.jsonl entry {index} command is not run-media-text")
        if not command_has_flag(command, "--apply"):
            errors.append(f"auto-queue-next.jsonl entry {index} command is missing --apply")
        if not command_has_flag(command, "--reindex"):
            errors.append(f"auto-queue-next.jsonl entry {index} command is missing --reindex")
        out_path = command_option_value(command, "--out")
        if not out_path:
            errors.append(f"auto-queue-next.jsonl entry {index} command is missing --out")
        else:
            out_paths.append(out_path)
            if not out_path.endswith(".jsonl"):
                errors.append(f"auto-queue-next.jsonl entry {index} --out is not a JSONL file: {out_path}")

    duplicate_out_paths = sorted({value for value in out_paths if out_paths.count(value) > 1})
    for out_path in duplicate_out_paths:
        errors.append(f"auto-queue-next output path is duplicated: {out_path}")

    manifest_summary = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"manifest.json invalid JSON: {exc.msg}")
            manifest = {}
        manifest_files = manifest.get("files", [])
        manifest_details = manifest.get("file_details", {})
        auto_queue_next = manifest.get("auto_queue_next")
        for file_name, file_path in (
            ("auto-queue-next.commands.txt", commands_path),
            ("auto-queue-next.jsonl", jsonl_path),
        ):
            if file_name not in manifest_files:
                errors.append(f"manifest files missing {file_name}")
            expected = manifest_details.get(file_name)
            if expected is None:
                errors.append(f"{file_name} has no manifest detail")
            elif file_path.exists() and export_file_detail(file_path) != expected:
                errors.append(f"{file_name} does not match manifest detail")
        if not isinstance(auto_queue_next, dict):
            errors.append("manifest auto_queue_next must be an object")
        else:
            if auto_queue_next.get("files") != ["auto-queue-next.commands.txt", "auto-queue-next.jsonl"]:
                errors.append("manifest auto_queue_next files do not match expected next files")
            if auto_queue_next.get("entries") != len(entries):
                errors.append("manifest auto_queue_next entries does not match JSONL entry count")
            if auto_queue_next.get("requires_review") is not True:
                errors.append("manifest auto_queue_next requires_review must be true")
        manifest_summary = {
            "present": True,
            "auto_queue_next": auto_queue_next,
        }
    else:
        warnings.append("manifest.json is missing; file details were not checked")
        manifest_summary = {"present": False}

    return {
        "path": str(path),
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "commands": len(command_lines),
        "entries": len(entries),
        "out_paths": out_paths,
        "files": {
            "auto-queue-next.commands.txt": commands_path.exists(),
            "auto-queue-next.jsonl": jsonl_path.exists(),
            "manifest.json": manifest_path.exists(),
        },
        "manifest": manifest_summary,
        "note": "Review auto-queue-next.commands.txt before executing OCR/ASR write-back commands.",
    }


def render_verify_auto_queue_next_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Auto Queue Next Verification",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        f"- Commands: {report.get('commands', 0)}",
        f"- Entries: {report.get('entries', 0)}",
        "",
    ]
    if report.get("errors"):
        parts.extend(["## Errors", ""])
        for error in report["errors"]:
            parts.append(f"- {error}")
        parts.append("")
    if report.get("warnings"):
        parts.extend(["## Warnings", ""])
        for warning in report["warnings"]:
            parts.append(f"- {warning}")
        parts.append("")
    if report.get("out_paths"):
        parts.extend(["## Output Paths", ""])
        for out_path in report["out_paths"]:
            parts.append(f"- `{out_path}`")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def run_auto_queue(
    path: Path,
    base_dir: Path | None = None,
    execute: bool = False,
    timeout: int = 120,
    next_plan: dict | None = None,
    write_next: bool = False,
    runner=None,
) -> dict:
    verification = verify_auto_queue(path, base_dir)
    command_path = path / "auto-queue.commands.txt"
    commands = []
    if command_path.exists():
        commands = [line.strip() for line in command_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    normalized_next_plan = normalize_auto_queue_next_plan(next_plan)
    next_commands = auto_queue_next_commands(commands, normalized_next_plan)
    next_entries = auto_queue_next_entries(commands, next_commands, normalized_next_plan)
    report = {
        "path": str(path),
        "base_dir": str(base_dir or Path(".")),
        "ok": False,
        "execute": bool(execute),
        "write_next": bool(write_next),
        "verification": verification,
        "commands": commands,
        "next_plan": normalized_next_plan,
        "next_commands": next_commands,
        "next_entries": next_entries,
        "next_files": {},
        "results": [],
        "note": "Dry run only. Re-run with --execute after reviewing commands." if not execute else "",
    }
    if not verification.get("ok"):
        report["note"] = "Auto-queue was not run because preflight verification failed."
        return report
    if write_next:
        report["next_files"] = write_auto_queue_next_files(path, next_entries)
    if not execute:
        report["ok"] = True
        return report

    command_runner = runner or run_shell_command
    results = []
    for command in commands:
        result = command_runner(command, timeout)
        results.append(result)
    report["results"] = results
    report["ok"] = all(result.get("returncode") == 0 for result in results)
    if not report["ok"]:
        report["note"] = "One or more auto-queue commands failed."
    return report


def run_auto_queue_next(
    path: Path,
    execute: bool = False,
    timeout: int = 120,
    runner=None,
) -> dict:
    verification = verify_auto_queue_next(path)
    command_path = path / "auto-queue-next.commands.txt"
    commands = []
    if command_path.exists():
        commands = [line.strip() for line in command_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = {
        "path": str(path),
        "ok": False,
        "execute": bool(execute),
        "verification": verification,
        "commands": commands,
        "results": [],
        "note": "Dry run only. Re-run with --execute after reviewing OCR/ASR write-back commands."
        if not execute
        else "",
    }
    if not verification.get("ok"):
        report["note"] = "Auto-queue next commands were not run because preflight verification failed."
        return report
    if not execute:
        report["ok"] = True
        return report

    command_runner = runner or run_shell_command
    results = []
    for command in commands:
        result = command_runner(command, timeout)
        results.append(result)
    report["results"] = results
    report["ok"] = all(result.get("returncode") == 0 for result in results)
    if not report["ok"]:
        report["note"] = "One or more auto-queue next commands failed."
    return report


def write_auto_queue_next_files(path: Path, entries: list[dict]) -> dict:
    path.mkdir(parents=True, exist_ok=True)
    files = {
        "auto-queue-next.commands.txt": render_hot_command_commands(entries),
        "auto-queue-next.jsonl": render_hot_command_jsonl(entries),
    }
    details = {}
    for file_name, content in files.items():
        file_path = path / file_name
        file_path.write_text(content, encoding="utf-8")
        details[file_name] = export_file_detail(file_path)
    report = {
        "files": list(files.keys()),
        "file_details": details,
        "entries": len(entries),
        "note": "Review generated run-media-text commands before executing them.",
    }
    manifest_path = path / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_files = list(manifest.get("files", []))
        for file_name in files:
            if file_name not in manifest_files:
                manifest_files.append(file_name)
        manifest["files"] = manifest_files
        manifest.setdefault("file_details", {}).update(details)
        manifest["auto_queue_next"] = {
            "files": list(files.keys()),
            "entries": len(entries),
            "requires_review": True,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["manifest_updated"] = True
    else:
        report["manifest_updated"] = False
    return report


def normalize_auto_queue_next_plan(next_plan: dict | None = None) -> dict:
    plan = dict(next_plan or {})
    return {
        "preset": plan.get("preset"),
        "preset_model": plan.get("preset_model"),
        "tool_path": plan.get("tool_path"),
        "command_template": plan.get("command_template"),
        "model": plan.get("model") or "external-command",
        "language": plan.get("language") or "",
        "confidence": plan.get("confidence"),
        "out_dir": plan.get("out_dir") or "outputs",
    }


def auto_queue_next_entries(commands: list[str], next_commands: list[str], next_plan: dict | None = None) -> list[dict]:
    plan = normalize_auto_queue_next_plan(next_plan)
    entries = []
    for source_command, next_command in zip(commands, next_commands, strict=False):
        entries.append(
            {
                "command": next_command,
                "kind": command_option_value(source_command, "--kind") or "all",
                "stage": "run_media_text",
                "source_command": source_command,
                "automation": "manual_review",
                "requires_review": True,
                "plan": {key: value for key, value in plan.items() if value not in (None, "")},
                "reason": "generated by run-auto-queue after verified media queue handoff",
            }
        )
    return entries


def auto_queue_next_commands(commands: list[str], next_plan: dict | None = None) -> list[str]:
    plan = normalize_auto_queue_next_plan(next_plan)
    if plan["preset"] and plan["command_template"]:
        raise ValueError("Use either next preset or next command template, not both")
    next_commands = []
    seen = set()
    for command in commands:
        kind = command_option_value(command, "--kind") or "all"
        status = command_option_value(command, "--status") or "not_processed"
        limit = command_option_value(command, "--limit")
        low_confidence = command_has_flag(command, "--low-confidence")
        suffix = f"{kind}-low-confidence" if low_confidence else f"{kind}-{status}"
        output = f"{plan['out_dir'].rstrip('/')}/auto-queue-media-text-{suffix}.jsonl"
        effective_plan = auto_queue_next_effective_plan_for_kind(plan, kind)
        pieces = [
            "python -m link2context.store --db data/link2context.db run-media-text",
            f"--kind {kind}",
            f"--out {output}",
            *auto_queue_next_runner_args(effective_plan),
            "--apply --reindex",
        ]
        if low_confidence:
            pieces.insert(2, "--low-confidence")
        else:
            pieces.insert(2, f"--status {status}")
        if limit:
            pieces.insert(3, f"--limit {limit}")
        next_command = " ".join(pieces)
        if next_command not in seen:
            seen.add(next_command)
            next_commands.append(next_command)
    return next_commands


def auto_queue_next_effective_plan_for_kind(plan: dict, kind: str) -> dict:
    preset = plan.get("preset")
    if not preset:
        return plan
    preset_config = MEDIA_TEXT_PRESETS.get(preset) or {}
    preset_kind = preset_config.get("kind")
    if preset_kind in (None, "all", kind):
        return plan
    fallback = dict(plan)
    fallback["preset"] = None
    fallback["preset_model"] = None
    fallback["tool_path"] = None
    fallback["command_template"] = None
    fallback["model"] = "external-command"
    return fallback


def auto_queue_next_runner_args(plan: dict) -> list[str]:
    pieces = []
    if plan["preset"]:
        pieces.append(f"--preset {plan['preset']}")
        if plan["preset_model"]:
            pieces.append(f"--preset-model {quote_cli_value(plan['preset_model'])}")
        if plan["tool_path"]:
            pieces.append(f"--tool-path {quote_cli_value(plan['tool_path'])}")
    elif plan["command_template"]:
        pieces.append(f"--command-template {quote_cli_value(plan['command_template'])}")
    else:
        pieces.append('--command-template "<ocr-or-asr-command> {input_source}"')
    if plan["model"] and (plan["model"] != "external-command" or not plan["preset"]):
        pieces.append(f"--model {quote_cli_value(plan['model'])}")
    if plan["language"]:
        pieces.append(f"--language {quote_cli_value(plan['language'])}")
    if plan["confidence"] is not None:
        pieces.append(f"--confidence {plan['confidence']}")
    return pieces


def command_option_value(command: str, option: str) -> str | None:
    parts = command.split()
    for index, part in enumerate(parts):
        if part == option and index + 1 < len(parts):
            return parts[index + 1]
        if part.startswith(f"{option}="):
            return part.split("=", 1)[1]
    return None


def command_has_flag(command: str, flag: str) -> bool:
    return flag in command.split()


def quote_cli_value(value: object) -> str:
    text = str(value)
    escaped = text.replace('"', '\\"')
    return f'"{escaped}"'


def run_shell_command(command: str, timeout: int) -> dict:
    completed = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def render_run_auto_queue_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Auto Queue Run",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        f"- Execute: {str(report.get('execute')).lower()}",
        f"- Write next: {str(report.get('write_next')).lower()}",
        f"- Commands: {len(report.get('commands', []))}",
        "",
    ]
    verification = report.get("verification", {})
    if not verification.get("ok"):
        parts.extend(["## Verification Errors", ""])
        for error in verification.get("errors", []):
            parts.append(f"- {error}")
        parts.append("")
    if report.get("commands"):
        parts.extend(["## Commands", ""])
        for command in report["commands"]:
            parts.append(f"- `{command}`")
        parts.append("")
    if report.get("results"):
        parts.extend(["## Results", ""])
        for result in report["results"]:
            marker = "ok" if result.get("returncode") == 0 else "fail"
            parts.append(f"- {marker} `{result.get('command')}`")
        parts.append("")
    if report.get("next_commands"):
        parts.extend(["## Next Commands", ""])
        for command in report["next_commands"]:
            parts.append(f"- `{command}`")
        parts.append("")
    if report.get("next_files"):
        parts.extend(["## Next Files", ""])
        next_files = report["next_files"]
        for file_name in next_files.get("files", []):
            parts.append(f"- `{file_name}`")
        if next_files.get("note"):
            parts.append(f"- Note: {next_files['note']}")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def render_run_auto_queue_next_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Auto Queue Next Run",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        f"- Execute: {str(report.get('execute')).lower()}",
        f"- Commands: {len(report.get('commands', []))}",
        "",
    ]
    verification = report.get("verification", {})
    if not verification.get("ok"):
        parts.extend(["## Verification Errors", ""])
        for error in verification.get("errors", []):
            parts.append(f"- {error}")
        parts.append("")
    if report.get("commands"):
        parts.extend(["## Commands", ""])
        for command in report["commands"]:
            parts.append(f"- `{command}`")
        parts.append("")
    if report.get("results"):
        parts.extend(["## Results", ""])
        for result in report["results"]:
            marker = "ok" if result.get("returncode") == 0 else "fail"
            parts.append(f"- {marker} `{result.get('command')}`")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def export_snapshot(conn: sqlite3.Connection, out_dir: Path, limit: int = 20) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    handoff_dir = out_dir / "agent-handoff"
    jsonl_dir = out_dir / "jsonl-dump"
    docs_dir = out_dir / "markdown-docs"
    graph_dir = out_dir / "graph-csv"
    neo4j_path = out_dir / "graph.cypher"
    handoff_manifest = export_agent_handoff(conn, handoff_dir, limit)
    jsonl_manifest = dump_jsonl(conn, jsonl_dir)
    docs_manifest = dump_docs_markdown(conn, docs_dir, limit)
    graph_manifest = dump_graph_csv(conn, graph_dir, limit)
    neo4j_manifest = dump_neo4j_cypher(conn, neo4j_path, limit)
    handoff_verification = verify_export_bundle(handoff_dir)
    jsonl_verification = verify_jsonl_dump(jsonl_dir)
    docs_verification = verify_docs_markdown(docs_dir)
    graph_verification = verify_graph_csv(graph_dir)
    neo4j_verification = verify_neo4j_cypher(neo4j_path)
    manifest = {
        "project": "Link2Context",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "limit": limit,
        "stats": stats(conn),
        "handoff": {
            "path": "agent-handoff",
            "ok": handoff_verification["ok"],
            "files": handoff_manifest["files"],
            "manifest": "agent-handoff/manifest.json",
        },
        "jsonl": {
            "path": "jsonl-dump",
            "ok": jsonl_verification["ok"],
            "files": jsonl_manifest["files"],
            "manifest": "jsonl-dump/manifest.json",
        },
        "markdown_docs": {
            "path": "markdown-docs",
            "ok": docs_verification["ok"],
            "files": docs_manifest["files"],
            "manifest": "markdown-docs/manifest.json",
        },
        "graph_csv": {
            "path": "graph-csv",
            "ok": graph_verification["ok"],
            "files": graph_manifest["files"],
            "manifest": "graph-csv/manifest.json",
        },
        "neo4j": {
            "path": "graph.cypher",
            "ok": neo4j_verification["ok"],
            "manifest": "graph.cypher.manifest.json",
        },
        "ok": (
            handoff_verification["ok"]
            and jsonl_verification["ok"]
            and docs_verification["ok"]
            and graph_verification["ok"]
            and neo4j_verification["ok"]
        ),
        "note": "Complete snapshot containing an agent handoff bundle, portable backup, Markdown documents, and graph exports.",
    }
    (out_dir / "snapshot.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_snapshot(path: Path) -> dict:
    snapshot_path = path / "snapshot.json"
    if not snapshot_path.exists():
        return {
            "path": str(path),
            "ok": False,
            "errors": ["snapshot.json is missing"],
            "handoff": None,
            "jsonl": None,
            "markdown_docs": None,
            "graph_csv": None,
            "neo4j": None,
        }
    manifest = json.loads(snapshot_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    handoff_path = path / manifest.get("handoff", {}).get("path", "agent-handoff")
    jsonl_path = path / manifest.get("jsonl", {}).get("path", "jsonl-dump")
    handoff_report = verify_export_bundle(handoff_path)
    jsonl_report = verify_jsonl_dump(jsonl_path)
    docs_path = None
    docs_report = None
    if manifest.get("markdown_docs") is not None:
        docs_path = path / manifest.get("markdown_docs", {}).get("path", "markdown-docs")
        docs_report = verify_docs_markdown(docs_path)
    graph_path = None
    graph_report = None
    if manifest.get("graph_csv") is not None:
        graph_path = path / manifest.get("graph_csv", {}).get("path", "graph-csv")
        graph_report = verify_graph_csv(graph_path)
    neo4j_path = None
    neo4j_report = None
    if manifest.get("neo4j") is not None:
        neo4j_path = path / manifest.get("neo4j", {}).get("path", "graph.cypher")
        neo4j_report = verify_neo4j_cypher(neo4j_path)
    if not handoff_report["ok"]:
        errors.append("agent-handoff verification failed")
    if not jsonl_report["ok"]:
        errors.append("jsonl-dump verification failed")
    if docs_report is not None and not docs_report["ok"]:
        errors.append("markdown-docs verification failed")
    if graph_report is not None and not graph_report["ok"]:
        errors.append("graph-csv verification failed")
    if neo4j_report is not None and not neo4j_report["ok"]:
        errors.append("neo4j verification failed")
    actual_ok = not errors
    if manifest.get("ok") is not actual_ok:
        errors.append("snapshot ok field does not match verification result")
    return {
        "path": str(path),
        "ok": not errors,
        "errors": errors,
        "manifest": {
            "project": manifest.get("project"),
            "exported_at": manifest.get("exported_at"),
            "limit": manifest.get("limit"),
            "ok": manifest.get("ok"),
        },
        "handoff": {
            "path": str(handoff_path),
            "ok": handoff_report["ok"],
            "errors": handoff_report.get("errors", []),
        },
        "jsonl": {
            "path": str(jsonl_path),
            "ok": jsonl_report["ok"],
            "errors": jsonl_report.get("errors", []),
        },
        "markdown_docs": (
            {
                "path": str(docs_path),
                "ok": docs_report["ok"],
                "errors": docs_report.get("errors", []),
            }
            if docs_report is not None
            else None
        ),
        "graph_csv": (
            {
                "path": str(graph_path),
                "ok": graph_report["ok"],
                "errors": graph_report.get("errors", []),
            }
            if graph_report is not None
            else None
        ),
        "neo4j": (
            {
                "path": str(neo4j_path),
                "ok": neo4j_report["ok"],
                "errors": neo4j_report.get("errors", []),
            }
            if neo4j_report is not None
            else None
        ),
    }


def render_verify_snapshot_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Snapshot Verification",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        "",
    ]
    if report.get("errors"):
        parts.extend(["## Errors", ""])
        for error in report["errors"]:
            parts.append(f"- {error}")
        parts.append("")
    for section_name in ("handoff", "jsonl", "markdown_docs", "graph_csv", "neo4j"):
        section = report.get(section_name)
        if not section:
            continue
        parts.extend([f"## {section_name}", ""])
        parts.append(f"- Path: {section.get('path')}")
        parts.append(f"- OK: {str(section.get('ok')).lower()}")
        if section.get("errors"):
            for error in section["errors"]:
                parts.append(f"- Error: {error}")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def import_snapshot(conn: sqlite3.Connection, path: Path) -> dict:
    verification = verify_snapshot(path)
    if not verification["ok"]:
        return {
            "path": str(path),
            "ok": False,
            "imported": {},
            "verification": verification,
            "note": "Snapshot was not imported because verification failed.",
        }
    snapshot_path = path / "snapshot.json"
    manifest = json.loads(snapshot_path.read_text(encoding="utf-8"))
    jsonl_path = path / manifest.get("jsonl", {}).get("path", "jsonl-dump")
    import_report = import_jsonl_dump(conn, jsonl_path)
    return {
        "path": str(path),
        "ok": bool(import_report.get("ok")),
        "jsonl_path": str(jsonl_path),
        "imported": import_report.get("imported", {}),
        "verification": verification,
        "jsonl_import": import_report,
        "stats": import_report.get("stats", stats(conn)),
        "note": (
            "Imported snapshot JSONL backup into the local SQLite store."
            if import_report.get("ok")
            else "Snapshot JSONL import failed."
        ),
    }


def render_import_snapshot_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Snapshot Import",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        "",
    ]
    if report.get("jsonl_path"):
        parts.extend([f"- JSONL path: {report.get('jsonl_path')}", ""])
    if not report.get("ok"):
        verification = report.get("verification", {})
        if verification.get("errors"):
            parts.extend(["## Verification Errors", ""])
            for error in verification["errors"]:
                parts.append(f"- {error}")
            parts.append("")
        jsonl_import = report.get("jsonl_import", {})
        jsonl_verification = jsonl_import.get("verification", {})
        if jsonl_verification.get("errors"):
            parts.extend(["## JSONL Import Errors", ""])
            for error in jsonl_verification["errors"]:
                parts.append(f"- {error}")
            parts.append("")
        if report.get("note"):
            parts.extend(["## Note", "", report["note"], ""])
        return "\n".join(parts).strip() + "\n"
    if report.get("imported"):
        parts.extend(["## Imported", ""])
        for table, count in report["imported"].items():
            parts.append(f"- {table}: {count}")
        parts.append("")
    stats_value = report.get("stats", {})
    if stats_value:
        parts.extend(["## Store Stats", ""])
        parts.append(f"- Documents: {stats_value.get('documents', 0)}")
        parts.append(f"- Citations: {stats_value.get('citations', 0)}")
        parts.append(f"- Entities: {stats_value.get('entities', 0)}")
        parts.append(f"- Relationships: {stats_value.get('relationships', 0)}")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def dump_jsonl(conn: sqlite3.Connection, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        (
            "documents.jsonl",
            """
            SELECT id, url, platform, title, account_name, author, published_at, fetched_at,
                   summary, plain_text, markdown, quality_status, imported_at
            FROM documents
            ORDER BY id ASC
            """,
        ),
        (
            "media.jsonl",
            """
            SELECT id, document_id, kind, media_index, url, local_path,
                   cache_status, cache_error, cache_sha256, cache_bytes, cache_checked_at,
                   status, text
            FROM media
            ORDER BY document_id ASC, media_index ASC, id ASC
            """,
        ),
        (
            "citations.jsonl",
            """
            SELECT id, document_id, ref, text, source
            FROM citations
            ORDER BY document_id ASC, id ASC
            """,
        ),
        (
            "entities.jsonl",
            """
            SELECT id, normalized_name, name, type, first_seen_at
            FROM entities
            ORDER BY id ASC
            """,
        ),
        (
            "document_entities.jsonl",
            """
            SELECT document_id, entity_id, role, confidence, evidence
            FROM document_entities
            ORDER BY document_id ASC, entity_id ASC, role ASC
            """,
        ),
        (
            "document_tags.jsonl",
            """
            SELECT document_id, tag, created_at
            FROM document_tags
            ORDER BY document_id ASC, tag ASC
            """,
        ),
        (
            "document_notes.jsonl",
            """
            SELECT id, document_id, note, created_at
            FROM document_notes
            ORDER BY document_id ASC, id ASC
            """,
        ),
        (
            "document_status.jsonl",
            """
            SELECT document_id, status, note, updated_at
            FROM document_status
            ORDER BY document_id ASC
            """,
        ),
        (
            "relationships.jsonl",
            """
            SELECT id, document_id, subject, predicate, object, confidence, evidence
            FROM relationships
            ORDER BY document_id ASC, id ASC
            """,
        ),
    ]
    row_counts: dict[str, int] = {}
    files: list[str] = []
    for file_name, query in specs:
        path = out_dir / file_name
        rows = conn.execute(query).fetchall()
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
        row_counts[file_name] = len(rows)
        files.append(file_name)
    file_details = {
        file_name: export_file_detail(out_dir / file_name)
        for file_name in files
    }
    manifest = {
        "project": "Link2Context",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "format": "jsonl",
        "files": files,
        "row_counts": row_counts,
        "file_details": file_details,
        "stats": stats(conn),
        "note": "Portable JSONL dump for external vector stores, graph databases, or agent tools.",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def import_jsonl_dump(conn: sqlite3.Connection, path: Path) -> dict:
    verification = verify_jsonl_dump(path)
    if not verification["ok"]:
        return {
            "path": str(path),
            "ok": False,
            "imported": {},
            "verification": verification,
            "note": "JSONL dump was not imported because verification failed.",
        }
    imported = {
        "documents": import_jsonl_table(conn, path / "documents.jsonl", import_jsonl_document),
        "entities": import_jsonl_table(conn, path / "entities.jsonl", import_jsonl_entity),
        "media": import_jsonl_table(conn, path / "media.jsonl", import_jsonl_media),
        "citations": import_jsonl_table(conn, path / "citations.jsonl", import_jsonl_citation),
        "document_entities": import_jsonl_table(
            conn,
            path / "document_entities.jsonl",
            import_jsonl_document_entity,
        ),
        "document_tags": import_jsonl_table(conn, path / "document_tags.jsonl", import_jsonl_document_tag),
        "document_notes": import_jsonl_table(conn, path / "document_notes.jsonl", import_jsonl_document_note),
        "document_status": import_jsonl_table(conn, path / "document_status.jsonl", import_jsonl_document_status),
        "relationships": import_jsonl_table(conn, path / "relationships.jsonl", import_jsonl_relationship),
    }
    sync_all_document_tags_to_graph(conn)
    sync_all_document_notes_to_graph(conn)
    conn.commit()
    return {
        "path": str(path),
        "ok": True,
        "imported": imported,
        "verification": verification,
        "stats": stats(conn),
        "note": "Imported JSONL dump into the local SQLite store.",
    }


def import_jsonl_table(conn: sqlite3.Connection, path: Path, importer: Callable[[sqlite3.Connection, dict], None]) -> int:
    count = 0
    for row in read_jsonl_file(path):
        importer(conn, row)
        count += 1
    return count


def read_jsonl_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def import_jsonl_document(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO documents (
          id, url, platform, title, account_name, author, published_at, fetched_at,
          summary, plain_text, markdown, quality_status, context_json, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("id"),
            row.get("url"),
            row.get("platform"),
            row.get("title"),
            row.get("account_name"),
            row.get("author"),
            row.get("published_at"),
            row.get("fetched_at"),
            row.get("summary"),
            row.get("plain_text"),
            row.get("markdown"),
            row.get("quality_status"),
            json.dumps(
                {
                    "source": {"url": row.get("url"), "platform": row.get("platform")},
                    "article": {"title": row.get("title"), "account_name": row.get("account_name")},
                    "content": {"plain_text": row.get("plain_text"), "markdown": row.get("markdown")},
                    "quality": {"status": row.get("quality_status")},
                    "restored_from": "jsonl",
                },
                ensure_ascii=False,
            ),
            row.get("imported_at"),
        ),
    )


def import_jsonl_entity(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO entities (id, normalized_name, name, type, first_seen_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (row.get("id"), row.get("normalized_name"), row.get("name"), row.get("type"), row.get("first_seen_at")),
    )


def import_jsonl_media(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO media (
          id, document_id, kind, media_index, url, local_path,
          cache_status, cache_error, cache_sha256, cache_bytes, cache_checked_at,
          status, text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("id"),
            row.get("document_id"),
            row.get("kind"),
            row.get("media_index"),
            row.get("url"),
            row.get("local_path"),
            row.get("cache_status"),
            row.get("cache_error"),
            row.get("cache_sha256"),
            row.get("cache_bytes"),
            row.get("cache_checked_at"),
            row.get("status"),
            row.get("text"),
        ),
    )


def import_jsonl_citation(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO citations (id, document_id, ref, text, source)
        VALUES (?, ?, ?, ?, ?)
        """,
        (row.get("id"), row.get("document_id"), row.get("ref"), row.get("text"), row.get("source")),
    )


def import_jsonl_document_entity(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO document_entities (document_id, entity_id, role, confidence, evidence)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            row.get("document_id"),
            row.get("entity_id"),
            row.get("role"),
            row.get("confidence"),
            row.get("evidence"),
        ),
    )


def import_jsonl_document_tag(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO document_tags (document_id, tag, created_at)
        VALUES (?, ?, ?)
        """,
        (row.get("document_id"), row.get("tag"), row.get("created_at")),
    )


def import_jsonl_document_note(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO document_notes (id, document_id, note, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (row.get("id"), row.get("document_id"), row.get("note"), row.get("created_at")),
    )


def import_jsonl_document_status(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO document_status (document_id, status, note, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (row.get("document_id"), row.get("status"), row.get("note"), row.get("updated_at")),
    )


def import_jsonl_relationship(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO relationships (id, document_id, subject, predicate, object, confidence, evidence)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("id"),
            row.get("document_id"),
            row.get("subject"),
            row.get("predicate"),
            row.get("object"),
            row.get("confidence"),
            row.get("evidence"),
        ),
    )


def render_import_jsonl_markdown(report: dict) -> str:
    parts = [
        "# Link2Context JSONL Import",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        "",
    ]
    if not report.get("ok"):
        verification = report.get("verification", {})
        if verification.get("errors"):
            parts.extend(["## Verification Errors", ""])
            for error in verification["errors"]:
                parts.append(f"- {error}")
            parts.append("")
        if report.get("note"):
            parts.extend(["## Note", "", report["note"], ""])
        return "\n".join(parts).strip() + "\n"
    if report.get("imported"):
        parts.extend(["## Imported", ""])
        for table, count in report["imported"].items():
            parts.append(f"- {table}: {count}")
        parts.append("")
    stats_value = report.get("stats", {})
    if stats_value:
        parts.extend(["## Store Stats", ""])
        parts.append(f"- Documents: {stats_value.get('documents', 0)}")
        parts.append(f"- Citations: {stats_value.get('citations', 0)}")
        parts.append(f"- Entities: {stats_value.get('entities', 0)}")
        parts.append(f"- Relationships: {stats_value.get('relationships', 0)}")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def verify_jsonl_dump(path: Path) -> dict:
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return {
            "path": str(path),
            "ok": False,
            "errors": ["manifest.json is missing"],
            "files": {},
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    files: dict[str, dict] = {}
    expected_files = manifest.get("files", [])
    details = manifest.get("file_details", {})
    row_counts = manifest.get("row_counts", {})
    if manifest.get("format") != "jsonl":
        errors.append("manifest format is not jsonl")
    for file_name in expected_files:
        file_path = path / file_name
        if not file_path.exists():
            errors.append(f"{file_name} is missing")
            files[file_name] = {"ok": False, "error": "missing"}
            continue
        actual = export_file_detail(file_path)
        expected = details.get(file_name)
        actual_rows = count_jsonl_rows(file_path)
        expected_rows = row_counts.get(file_name)
        file_errors = []
        if expected is None:
            file_errors.append("missing_detail")
            errors.append(f"{file_name} has no manifest detail")
        elif actual != expected:
            file_errors.append("detail_mismatch")
            errors.append(f"{file_name} does not match manifest detail")
        if expected_rows is None:
            file_errors.append("missing_row_count")
            errors.append(f"{file_name} has no manifest row count")
        elif actual_rows != expected_rows:
            file_errors.append("row_count_mismatch")
            errors.append(f"{file_name} row count does not match manifest")
        files[file_name] = {
            "ok": not file_errors,
            "expected": expected,
            "actual": actual,
            "expected_rows": expected_rows,
            "actual_rows": actual_rows,
            "errors": file_errors,
        }
    extra_files = sorted(
        file.name
        for file in path.iterdir()
        if file.is_file() and file.name != "manifest.json" and file.name not in expected_files
    )
    return {
        "path": str(path),
        "ok": not errors,
        "errors": errors,
        "extra_files": extra_files,
        "files": files,
        "manifest": {
            "project": manifest.get("project"),
            "exported_at": manifest.get("exported_at"),
            "format": manifest.get("format"),
        },
    }


def count_jsonl_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _line in handle)


def render_verify_jsonl_markdown(report: dict) -> str:
    parts = [
        "# Link2Context JSONL Verification",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        "",
    ]
    if report.get("errors"):
        parts.extend(["## Errors", ""])
        for error in report["errors"]:
            parts.append(f"- {error}")
        parts.append("")
    if report.get("extra_files"):
        parts.extend(["## Extra Files", ""])
        for file_name in report["extra_files"]:
            parts.append(f"- {file_name}")
        parts.append("")
    if report.get("files"):
        parts.extend(["## Files", ""])
        for file_name, detail in report["files"].items():
            marker = "ok" if detail.get("ok") else "fail"
            parts.append(
                f"- {marker} {file_name}: "
                f"{detail.get('actual_rows')} row(s)"
            )
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def verify_export_bundle(path: Path) -> dict:
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return {
            "path": str(path),
            "ok": False,
            "errors": ["manifest.json is missing"],
            "files": {},
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    files: dict[str, dict] = {}
    hot_commands = manifest.get("hot_commands")
    if hot_commands is not None:
        if not isinstance(hot_commands, list):
            errors.append("hot_commands must be a list")
        else:
            for index, entry in enumerate(hot_commands, start=1):
                if not isinstance(entry, dict):
                    errors.append(f"hot_commands[{index}] must be an object")
                    continue
                for key in ("command", "kind", "priority", "source", "reason", "automation", "requires_review"):
                    if key not in entry:
                        errors.append(f"hot_commands[{index}] missing {key}")
    hot_command_groups = manifest.get("hot_command_groups")
    if hot_command_groups is not None:
        if not isinstance(hot_command_groups, dict):
            errors.append("hot_command_groups must be an object")
        else:
            for key in ("auto_queue", "manual_review"):
                if not isinstance(hot_command_groups.get(key), list):
                    errors.append(f"hot_command_groups.{key} must be a list")
    media_pipeline = manifest.get("media_pipeline")
    if not isinstance(media_pipeline, dict):
        errors.append("media_pipeline must be an object")
    else:
        recommended_commands = media_pipeline.get("recommended_commands")
        if not isinstance(recommended_commands, list):
            errors.append("media_pipeline.recommended_commands must be a list")
        else:
            required_fragments = (
                "media-text-presets",
                "prepare-media-model",
                "verify-auto-queue",
                "verify-auto-queue-next",
            )
            for fragment in required_fragments:
                if not any(fragment in str(command) for command in recommended_commands):
                    errors.append(f"media_pipeline.recommended_commands missing {fragment}")
    expected_files = manifest.get("files", [])
    details = manifest.get("file_details", {})
    for file_name in expected_files:
        file_path = path / file_name
        if not file_path.exists():
            errors.append(f"{file_name} is missing")
            files[file_name] = {"ok": False, "error": "missing"}
            continue
        actual = export_file_detail(file_path)
        expected = details.get(file_name)
        if expected is None:
            errors.append(f"{file_name} has no manifest detail")
            files[file_name] = {"ok": False, "actual": actual, "error": "missing_detail"}
            continue
        ok = actual == expected
        if not ok:
            errors.append(f"{file_name} does not match manifest detail")
        files[file_name] = {
            "ok": ok,
            "expected": expected,
            "actual": actual,
        }
    extra_files = sorted(
        file.name
        for file in path.iterdir()
        if file.is_file() and file.name != "manifest.json" and file.name not in expected_files
    )
    return {
        "path": str(path),
        "ok": not errors,
        "errors": errors,
        "extra_files": extra_files,
        "files": files,
        "manifest": {
            "project": manifest.get("project"),
            "exported_at": manifest.get("exported_at"),
            "limit": manifest.get("limit"),
            "media_pipeline": {
                "present": isinstance(media_pipeline, dict),
                "recommended_commands": len(media_pipeline.get("recommended_commands", []))
                if isinstance(media_pipeline, dict) and isinstance(media_pipeline.get("recommended_commands"), list)
                else 0,
            },
        },
    }


def render_verify_export_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Export Verification",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        "",
    ]
    if report.get("errors"):
        parts.extend(["## Errors", ""])
        for error in report["errors"]:
            parts.append(f"- {error}")
        parts.append("")
    if report.get("extra_files"):
        parts.extend(["## Extra Files", ""])
        for file_name in report["extra_files"]:
            parts.append(f"- {file_name}")
        parts.append("")
    if report.get("files"):
        parts.extend(["## Files", ""])
        for file_name, detail in report["files"].items():
            marker = "ok" if detail.get("ok") else "fail"
            parts.append(f"- {marker} {file_name}")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def render_handoff_markdown(
    brief: dict,
    doctor: dict,
    media: dict,
    limit: int,
    tasks: dict | None = None,
    media_pipeline: dict | None = None,
) -> str:
    stats_value = brief.get("stats", {})
    media_summary = media.get("summary", [])
    parts = [
        "# Link2Context Agent Handoff",
        "",
        "This bundle is an agent-readable snapshot of the local Link2Context store.",
        "",
        "## Read Order",
        "",
        "1. `inbox.md` - start with daily triage and next actions.",
        "2. `curate.md` - choose the next action lane: read, fix, process media, or hand off.",
        "3. `review.md` - read the one-page agent review.",
        "4. `doctor.md` - check whether the store is ready for agent use.",
        "5. `duplicates.md` - inspect repeated or near-duplicate documents.",
        "6. `coverage.md` - inspect platform, source, graph, and media coverage gaps.",
        "7. `quality.md` - inspect low-quality or partial extractions.",
        "8. `evidence.md` - inspect citation evidence snippets and follow-up citation commands.",
        "9. `actions.md` - inspect prioritized next steps.",
        "10. `agent-tasks.md/json` - inspect the machine-readable handoff checklist.",
        "11. `digest.md` - review recent documents, topics, sources, quality, and actions together.",
        "12. `brief.md` - understand the collection at a high level.",
        "13. `starter-queries.md/json` - use machine-readable first queries for agent handoff.",
        "14. `sources.md` - inspect source accounts and platform distribution.",
        "15. `tags.md` - inspect user-added personal tags.",
        "16. `notes.md` - inspect user-written notes and judgments.",
        "17. `statuses.md` - inspect user workflow statuses.",
        "18. `annotations.md` - inspect combined user tags, notes, and statuses.",
        "19. `topics.md` - inspect topic/entity signals with evidence.",
        "20. `clusters.md` - inspect document clusters formed by shared entities.",
        "21. `questions.md` - inspect generated follow-up questions for agent exploration.",
        "22. `timeline.md` - inspect recency and source chronology.",
        "23. `profile.md` - inspect conservative interest signals.",
        "24. `media-pipeline.md/json` - inspect OCR/ASR pipeline status and blockers.",
        "25. `queue.md` - inspect OCR/ASR processing queue.",
        "26. `media.md` - inspect OCR/ASR backlog.",
        "27. `relations.md` - inspect relationship edges with source documents.",
        "28. `graph.mmd` or `graph.json` - inspect entity relationships.",
        "",
        "## Snapshot",
        "",
        f"- Documents: {stats_value.get('documents', 0)}",
        f"- Citations: {stats_value.get('citations', 0)}",
        f"- Entities: {stats_value.get('entities', 0)}",
        f"- Relationships: {stats_value.get('relationships', 0)}",
        f"- Export limit per section: {limit}",
        f"- Store status: {doctor.get('status')}",
        f"- Ready for agent: {str(doctor.get('ready_for_agent')).lower()}",
        "",
    ]
    if media_summary:
        parts.extend(["## Media Backlog", ""])
        for row in media_summary:
            parts.append(f"- {row['kind']} / {row['status']}: {row['count']}")
        parts.append("")
    if media_pipeline:
        counts = media_pipeline.get("counts", {})
        parts.extend(["## Media Pipeline", ""])
        parts.append(f"- Status: {media_pipeline.get('status')}")
        parts.append(f"- Local ready: {counts.get('local_ready', 0)}")
        parts.append(f"- With text: {counts.get('with_text', 0)}")
        parts.append(f"- Low confidence: {counts.get('low_confidence', 0)}")
        parts.append(f"- Indexed documents: {counts.get('indexed_documents', 0)}")
        if media_pipeline.get("blockers"):
            parts.append(f"- Blockers: {', '.join(media_pipeline['blockers'])}")
        parts.append("- Details: `media-pipeline.md`")
        if media_pipeline.get("recommended_commands"):
            parts.append("- Next commands:")
            for command in media_pipeline["recommended_commands"][:3]:
                parts.append(f"  - `{command}`")
        parts.append("")
    hot_commands = handoff_hot_commands(tasks or {})
    if hot_commands:
        parts.extend(["## Hot Commands", ""])
        for entry in hot_commands:
            parts.append(f"- `{entry['command']}`")
        parts.append("")
    parts.extend(
        [
            "## Useful Commands",
            "",
            "- `python -m link2context.store --db data/link2context.db query \"<question>\" --format markdown`",
            "- `python -m link2context.store --db data/link2context.db inbox`",
            "- `python -m link2context.store --db data/link2context.db curate`",
            "- `python -m link2context.store --db data/link2context.db review`",
            "- `python -m link2context.store --db data/link2context.db coverage`",
            "- `python -m link2context.store --db data/link2context.db doc <id>`",
            "- `python -m link2context.store --db data/link2context.db tag <id> <tag>`",
            "- `python -m link2context.store --db data/link2context.db note <id> \"<note>\"`",
            "- `python -m link2context.store --db data/link2context.db mark <id> later`",
            "- `python -m link2context.store --db data/link2context.db statuses`",
            "- `python -m link2context.store --db data/link2context.db annotations`",
            "- `python -m link2context.store --db data/link2context.db evidence \"<keyword>\"`",
            "- `python -m link2context.store --db data/link2context.db clusters`",
            "- `python -m link2context.store --db data/link2context.db questions`",
            "- `python -m link2context.store --db data/link2context.db related <id>`",
            "- `python -m link2context.store --db data/link2context.db duplicates`",
            "- `python -m link2context.store --db data/link2context.db explain \"<entity>\"`",
            "- `python -m link2context.store --db data/link2context.db queue`",
            "- `python -m link2context.store --db data/link2context.db media --status not_processed`",
            "",
            "## Caution",
            "",
            "- Entity extraction, graph edges, related documents, and profile are conservative rule-based MVP outputs.",
            "- Use citations and source URLs as evidence before making claims.",
            "- OCR and ASR are not executed by the current store commands; media status reflects imported context metadata.",
            "",
        ]
    )
    return "\n".join(parts).strip() + "\n"


def handoff_hot_commands(tasks: dict, limit: int = 5) -> list[dict]:
    commands: list[dict] = []
    seen: set[str] = set()
    hot_kinds = {"media", "media_cache", "media_review"}
    for task in tasks.get("tasks", []):
        command = task.get("command")
        if task.get("kind") not in hot_kinds or not command or command in seen:
            continue
        seen.add(command)
        policy = hot_command_policy(task, command)
        commands.append(
            {
                "command": command,
                "kind": task.get("kind"),
                "priority": task.get("priority", 9),
                "source": task.get("source") or "",
                "reason": task.get("detail") or task.get("title") or "",
                "automation": policy["automation"],
                "requires_review": policy["requires_review"],
            }
        )
        if len(commands) >= limit:
            break
    return commands


def group_hot_commands(commands: list[dict]) -> dict:
    return {
        "auto_queue": [entry for entry in commands if entry.get("automation") == "auto_queue" and not entry.get("requires_review")],
        "manual_review": [entry for entry in commands if entry.get("requires_review")],
    }


def hot_command_policy(task: dict, command: str) -> dict:
    kind = task.get("kind")
    if kind == "media" and " queue " in f" {command} ":
        return {
            "automation": "auto_queue",
            "requires_review": False,
        }
    return {
        "automation": "manual_review",
        "requires_review": True,
    }


def store_doctor(conn: sqlite3.Connection) -> dict:
    store_stats = stats(conn)
    checks = [
        doctor_check(
            "documents",
            store_stats["documents"] > 0,
            f"{store_stats['documents']} imported document(s)",
            "Import context.json files before querying or exporting.",
        ),
        doctor_check(
            "citations",
            store_stats["citations"] > 0,
            f"{store_stats['citations']} citation(s)",
            "Re-import richer contexts so agent answers can cite evidence.",
        ),
        doctor_check(
            "entities",
            store_stats["entities"] > 0,
            f"{store_stats['entities']} entity record(s)",
            "Entity extraction did not produce graph signals yet.",
        ),
        doctor_check(
            "relationships",
            store_stats["relationships"] > 0,
            f"{store_stats['relationships']} relationship(s)",
            "Relationship extraction did not produce graph edges yet.",
        ),
        doctor_check(
            "platforms",
            bool(store_stats["by_platform"]),
            ", ".join(f"{platform}={count}" for platform, count in store_stats["by_platform"].items()),
            "No source platform distribution is available.",
        ),
    ]
    ready = all(check["ok"] for check in checks)
    if store_stats["documents"] == 0:
        status = "empty"
    elif ready:
        status = "ok"
    else:
        status = "warn"
    return {
        "status": status,
        "ready_for_agent": ready,
        "stats": store_stats,
        "checks": checks,
        "recommended_next": doctor_recommendations(status, checks),
    }


def doctor_check(name: str, ok: bool, detail: str, fix: str) -> dict:
    return {
        "name": name,
        "ok": ok,
        "detail": detail if detail else "missing",
        "fix": None if ok else fix,
    }


def doctor_recommendations(status: str, checks: list[dict]) -> list[str]:
    if status == "empty":
        return [
            "Run: python -m link2context --url-list examples/wechat_urls.txt --out outputs/batch",
            "Run: python -m link2context.store --db data/link2context.db import outputs/batch",
        ]
    recommendations = [
        check["fix"]
        for check in checks
        if not check["ok"] and check.get("fix")
    ]
    if not recommendations:
        recommendations = [
            "Run: python -m link2context.store --db data/link2context.db brief",
            "Run: python -m link2context.store --db data/link2context.db export --out outputs/agent-handoff",
        ]
    return recommendations


def render_doctor_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Store Doctor",
        "",
        f"- Status: {report.get('status')}",
        f"- Ready for agent: {str(report.get('ready_for_agent')).lower()}",
        "",
        "## Checks",
        "",
    ]
    for check in report.get("checks", []):
        marker = "ok" if check.get("ok") else "warn"
        parts.append(f"- {marker} {check['name']}: {check['detail']}")
        if check.get("fix"):
            parts.append(f"  - Fix: {check['fix']}")
    parts.append("")
    if report.get("recommended_next"):
        parts.extend(["## Recommended Next", ""])
        for item in report["recommended_next"]:
            parts.append(f"- {item}")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def document_timeline(conn: sqlite3.Connection, limit: int = 20) -> dict:
    rows = conn.execute(
        """
        SELECT id, title, url, platform, account_name, author, published_at, imported_at, quality_status
        FROM documents
        ORDER BY COALESCE(published_at, imported_at) DESC, imported_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return {
        "documents": [
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "platform": row["platform"],
                "account_name": row["account_name"],
                "author": row["author"],
                "published_at": row["published_at"],
                "imported_at": row["imported_at"],
                "quality_status": row["quality_status"],
            }
            for row in rows
        ],
        "limit": limit,
        "note": "Ordered by published_at when available, otherwise imported_at.",
    }


def render_timeline_markdown(timeline: dict) -> str:
    parts = [
        "# Link2Context Timeline",
        "",
        timeline.get("note", ""),
        "",
    ]
    documents = timeline.get("documents", [])
    if not documents:
        parts.extend(["No imported documents.", ""])
        return "\n".join(parts).strip() + "\n"

    for document in documents:
        date = document.get("published_at") or document.get("imported_at") or "unknown"
        title = document.get("title") or "Untitled"
        parts.append(f"## {date}")
        parts.append("")
        parts.append(f"- {title}")
        if document.get("id") is not None:
            parts.append(f"  - ID: {document.get('id')}")
        parts.append(f"  - URL: {document.get('url')}")
        parts.append(f"  - Platform: {document.get('platform')}")
        if document.get("account_name"):
            parts.append(f"  - Account: {document.get('account_name')}")
        if document.get("author"):
            parts.append(f"  - Author: {document.get('author')}")
        parts.append(f"  - Quality: {document.get('quality_status') or 'unknown'}")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def media_inventory(
    conn: sqlite3.Connection,
    kind: str = "all",
    status: str | None = None,
    limit: int = 50,
) -> dict:
    conditions = []
    params: list[str | int] = []
    if kind != "all":
        conditions.append("m.kind = ?")
        params.append(kind)
    if status:
        conditions.append("m.status = ?")
        params.append(status)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""
        SELECT
          m.kind, m.media_index, m.url, m.local_path, m.status, m.text,
          m.cache_status, m.cache_error, m.cache_sha256, m.cache_bytes, m.cache_checked_at,
          m.text_model, m.text_language, m.text_confidence,
          d.id AS document_id, d.title, d.url AS document_url, d.platform, d.account_name
        FROM media m
        JOIN documents d ON d.id = m.document_id
        {where_clause}
        ORDER BY d.imported_at DESC, d.id DESC, m.kind ASC, m.media_index ASC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    summary_rows = conn.execute(
        f"""
        SELECT m.kind, COALESCE(m.status, 'unknown') AS status, COUNT(*) AS count
        FROM media m
        JOIN documents d ON d.id = m.document_id
        {where_clause}
        GROUP BY m.kind, COALESCE(m.status, 'unknown')
        ORDER BY m.kind ASC, status ASC
        """,
        params,
    ).fetchall()
    items = [
        {
            "kind": row["kind"],
            "index": row["media_index"],
            "url": row["url"],
            "local_path": row["local_path"],
            "cache_status": row["cache_status"],
            "cache_error": row["cache_error"],
            "cache_sha256": row["cache_sha256"],
            "cache_bytes": row["cache_bytes"],
            "cache_checked_at": row["cache_checked_at"],
            "status": row["status"],
            "text": row["text"],
            "text_model": row["text_model"],
            "text_language": row["text_language"],
            "text_confidence": row["text_confidence"],
            "document": {
                "id": row["document_id"],
                "title": row["title"],
                "url": row["document_url"],
                "platform": row["platform"],
                "account_name": row["account_name"],
            },
        }
        for row in rows
    ]
    low_confidence = [
        item
        for item in items
        if item.get("text_confidence") is not None
        and item["text_confidence"] < MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD
    ]
    return {
        "filters": {
            "kind": kind,
            "status": status,
            "limit": limit,
        },
        "quality": {
            "low_confidence_threshold": MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD,
            "low_confidence_count": len(low_confidence),
        },
        "summary": [
            {
                "kind": row["kind"],
                "status": row["status"],
                "count": row["count"],
            }
            for row in summary_rows
        ],
        "items": items,
        "low_confidence": low_confidence,
        "note": "Media status is imported from context.json. OCR/ASR execution is not performed by this command.",
    }


def media_pipeline_status(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN status = 'not_processed' THEN 1 ELSE 0 END) AS not_processed,
          SUM(CASE WHEN text IS NOT NULL AND trim(text) != '' THEN 1 ELSE 0 END) AS with_text,
          SUM(CASE WHEN local_path IS NOT NULL AND trim(local_path) != '' THEN 1 ELSE 0 END) AS with_local_path,
          SUM(CASE WHEN cache_status IS NOT NULL AND trim(cache_status) != '' THEN 1 ELSE 0 END) AS cache_touched,
          SUM(CASE WHEN cache_status = 'cached' THEN 1 ELSE 0 END) AS cached,
          SUM(CASE WHEN cache_status IS NOT NULL AND cache_status NOT IN ('cached', 'manual_local_path') THEN 1 ELSE 0 END) AS cache_attention,
          SUM(CASE WHEN text_confidence IS NOT NULL AND text_confidence < ? THEN 1 ELSE 0 END) AS low_confidence
        FROM media
        """,
        (MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD,),
    ).fetchone()
    indexed_documents = conn.execute(
        "SELECT COUNT(DISTINCT document_id) AS count FROM document_entities WHERE evidence = 'media.text'"
    ).fetchone()["count"]
    indexed_relations = conn.execute(
        "SELECT COUNT(*) AS count FROM relationships WHERE evidence = 'media.text'"
    ).fetchone()["count"]
    local_ready = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM media
        WHERE status = 'not_processed'
          AND local_path IS NOT NULL
          AND trim(local_path) != ''
        """
    ).fetchone()["count"]
    counts = {
        "total": int(row["total"] or 0),
        "not_processed": int(row["not_processed"] or 0),
        "with_text": int(row["with_text"] or 0),
        "with_local_path": int(row["with_local_path"] or 0),
        "cache_touched": int(row["cache_touched"] or 0),
        "cached": int(row["cached"] or 0),
        "cache_attention": int(row["cache_attention"] or 0),
        "low_confidence": int(row["low_confidence"] or 0),
        "local_ready": int(local_ready or 0),
        "indexed_documents": int(indexed_documents or 0),
        "indexed_relations": int(indexed_relations or 0),
    }
    checks = [
        {
            "name": "auto_queue",
            "ok": counts["local_ready"] > 0,
            "count": counts["local_ready"],
            "status": "ready" if counts["local_ready"] else "empty",
            "command": "python -m link2context.store --db data/link2context.db queue --kind all --status not_processed --format jsonl",
        },
        {
            "name": "cache_attention",
            "ok": counts["cache_attention"] == 0,
            "count": counts["cache_attention"],
            "status": "ok" if counts["cache_attention"] == 0 else "needs_review",
            "command": "python -m link2context.store --db data/link2context.db media --format markdown",
        },
        {
            "name": "media_text",
            "ok": counts["with_text"] > 0 or counts["not_processed"] == 0,
            "count": counts["with_text"],
            "status": "present" if counts["with_text"] else "missing",
            "command": "python -m link2context.store --db data/link2context.db run-auto-queue-next outputs/agent-handoff",
        },
        {
            "name": "low_confidence",
            "ok": counts["low_confidence"] == 0,
            "count": counts["low_confidence"],
            "status": "ok" if counts["low_confidence"] == 0 else "needs_review",
            "command": "python -m link2context.store --db data/link2context.db queue --low-confidence --format markdown",
        },
        {
            "name": "media_text_graph",
            "ok": counts["with_text"] == 0 or counts["indexed_documents"] > 0,
            "count": counts["indexed_documents"],
            "status": "indexed" if counts["indexed_documents"] else "missing",
            "command": "python -m link2context.store --db data/link2context.db verify-media-text <results.jsonl> --require-reindex",
        },
    ]
    blockers = [
        check["name"]
        for check in checks
        if not check["ok"] and check["name"] in {"cache_attention", "low_confidence", "media_text_graph"}
    ]
    return {
        "status": "needs_attention" if blockers else "ready",
        "counts": counts,
        "checks": checks,
        "blockers": blockers,
        "recommended_files": [
            "auto-queue.commands.txt",
            "auto-queue.jsonl",
            "auto-queue-next.commands.txt",
            "auto-queue-next.jsonl",
            "media.md",
            "queue.md",
        ],
        "recommended_commands": [
            "python -m link2context.store --db data/link2context.db media-text-presets --format markdown",
            "python -m link2context.store --db data/link2context.db prepare-media-model --url <model-url> --out models/ggml-small.bin",
            "python -m link2context.store --db data/link2context.db verify-auto-queue outputs/agent-handoff --base-dir .",
            "python -m link2context.store --db data/link2context.db run-auto-queue outputs/agent-handoff --base-dir . --write-next",
            "python -m link2context.store --db data/link2context.db verify-auto-queue-next outputs/agent-handoff",
        ],
        "note": "Pipeline status is derived from current media rows and media.text graph evidence.",
    }


def render_media_pipeline_markdown(report: dict) -> str:
    counts = report.get("counts", {})
    parts = [
        "# Link2Context Media Pipeline",
        "",
        f"- Status: {report.get('status')}",
        f"- Total media: {counts.get('total', 0)}",
        f"- Not processed: {counts.get('not_processed', 0)}",
        f"- Local ready: {counts.get('local_ready', 0)}",
        f"- With text: {counts.get('with_text', 0)}",
        f"- Low confidence: {counts.get('low_confidence', 0)}",
        f"- Indexed documents: {counts.get('indexed_documents', 0)}",
        f"- Indexed relations: {counts.get('indexed_relations', 0)}",
        "",
    ]
    if report.get("checks"):
        parts.extend(["## Checks", ""])
        for check in report["checks"]:
            marker = "ok" if check.get("ok") else "attention"
            parts.append(f"- {marker} {check.get('name')}: {check.get('status')} ({check.get('count')})")
            if check.get("command"):
                parts.append(f"  - Command: `{check['command']}`")
        parts.append("")
    if report.get("recommended_files"):
        parts.extend(["## Handoff Files", ""])
        for file_name in report["recommended_files"]:
            parts.append(f"- `{file_name}`")
        parts.append("")
    if report.get("recommended_commands"):
        parts.extend(["## Recommended Commands", ""])
        for command in report["recommended_commands"]:
            parts.append(f"- `{command}`")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def media_text_presets_report(
    preset_model: str | None = None,
    model_dirs: list[Path] | None = None,
    tool_path: str | None = None,
) -> dict:
    discovered_models = discover_media_text_models(model_dirs)
    presets = []
    for name, config in MEDIA_TEXT_PRESETS.items():
        configured_tool_path = tool_path if tool_path and config.get("tool_path") else config.get("tool_path")
        if configured_tool_path:
            configured_path = Path(configured_tool_path)
            executable = configured_tool_path
            resolved = str(configured_path) if configured_path.exists() else shutil.which(configured_path.name)
        else:
            executable = name
            resolved = shutil.which(name)
        requires_model = name in {"sona", "vibe"}
        resolved_preset_model = preset_model
        if requires_model and not resolved_preset_model and discovered_models:
            resolved_preset_model = discovered_models[0]["path"]
        model_status = media_text_model_status(resolved_preset_model if requires_model else None)
        ready = bool(resolved) and (not requires_model or model_status["available"])
        presets.append(
            {
                "name": name,
                "kind": config.get("kind"),
                "model": config.get("model"),
                "language": config.get("language", ""),
                "confidence": config.get("confidence"),
                "requires_model": requires_model,
                "preset_model": resolved_preset_model if requires_model else None,
                "model_available": model_status["available"] if requires_model else None,
                "model_resolved_path": model_status["resolved_path"] if requires_model else None,
                "model_note": model_status["note"] if requires_model else "",
                "tool_path": configured_tool_path,
                "executable": executable,
                "available": bool(resolved),
                "ready": ready,
                "resolved_path": resolved,
                "template": config.get("template"),
                "description": config.get("description"),
                "example": media_text_preset_example(
                    name,
                    config,
                    preset_model=resolved_preset_model,
                    tool_path=tool_path if config.get("tool_path") else None,
                ),
            }
        )
    return {
        "presets": presets,
        "available": [preset["name"] for preset in presets if preset["available"]],
        "ready": [preset["name"] for preset in presets if preset["ready"]],
        "missing": [preset["name"] for preset in presets if not preset["available"]],
        "discovered_models": discovered_models,
        "note": "Presets only define command templates. Real OCR/ASR runs still need cached local media and any required model files.",
    }


def media_text_model_dirs(extra_dirs: list[Path] | None = None) -> list[Path]:
    dirs = [
        Path("models"),
        Path("outputs/models"),
        Path.home() / "AppData" / "Local" / "vibe" / "models",
        Path.home() / ".cache" / "whisper.cpp",
        Path.home() / ".cache" / "whisper",
    ]
    dirs.extend(extra_dirs or [])
    seen = set()
    unique = []
    for directory in dirs:
        key = str(directory)
        if key not in seen:
            seen.add(key)
            unique.append(directory)
    return unique


def discover_media_text_models(extra_dirs: list[Path] | None = None) -> list[dict]:
    models = []
    for directory in media_text_model_dirs(extra_dirs):
        if not directory.exists() or not directory.is_dir():
            continue
        for path in sorted(directory.glob("*")):
            if not path.is_file() or path.suffix.lower() not in {".bin", ".gguf"}:
                continue
            name = path.name.lower()
            if "ggml" not in name and "whisper" not in name and "q5" not in name and "q8" not in name:
                continue
            models.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "size_bytes": path.stat().st_size,
                }
            )
    return models


def media_text_model_status(preset_model: str | None) -> dict:
    if not preset_model:
        return {
            "available": False,
            "resolved_path": None,
            "note": "preset_model is required and was not provided.",
        }
    candidate = Path(preset_model)
    return {
        "available": candidate.exists(),
        "resolved_path": str(candidate) if candidate.exists() else None,
        "note": "" if candidate.exists() else "preset_model path does not exist.",
    }


def media_text_preset_example(
    name: str,
    config: dict,
    preset_model: str | None = None,
    tool_path: str | None = None,
) -> str:
    pieces = [
        "python -m link2context.store --db data/link2context.db run-media-text",
        f"--kind {config.get('kind', 'all')}",
        f"--out outputs/media-text/{name}.jsonl",
        f"--preset {name}",
    ]
    if name in {"sona", "vibe"}:
        pieces.append(f"--preset-model {quote_cli_value(preset_model or 'models/ggml-small.bin')}")
    if tool_path:
        pieces.append(f"--tool-path {quote_cli_value(tool_path)}")
    language = config.get("language")
    if language:
        pieces.append(f"--language {quote_cli_value(language)}")
    pieces.append("--apply --reindex")
    return " ".join(pieces)


def render_media_text_presets_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Media Text Presets",
        "",
        f"- Available: {len(report.get('available', []))}",
        f"- Ready: {len(report.get('ready', []))}",
        f"- Missing: {len(report.get('missing', []))}",
        f"- Discovered models: {len(report.get('discovered_models', []))}",
        "",
    ]
    if report.get("discovered_models"):
        parts.extend(["## Discovered Models", ""])
        for model in report["discovered_models"]:
            parts.append(f"- `{model['path']}` ({model.get('size_bytes', 0)} bytes)")
        parts.append("")
    for preset in report.get("presets", []):
        status = "available" if preset.get("available") else "missing"
        parts.extend(
            [
                f"## {preset.get('name')}",
                "",
                f"- Status: {status}",
                f"- Kind: {preset.get('kind')}",
                f"- Language: {preset.get('language') or 'default'}",
                f"- Requires model: {str(preset.get('requires_model')).lower()}",
                f"- Ready: {str(preset.get('ready')).lower()}",
                f"- Executable: `{preset.get('executable')}`",
            ]
        )
        if preset.get("resolved_path"):
            parts.append(f"- Resolved path: `{preset['resolved_path']}`")
        if preset.get("requires_model"):
            parts.append(f"- Preset model: `{preset.get('preset_model') or ''}`")
            parts.append(f"- Model available: {str(preset.get('model_available')).lower()}")
            if preset.get("model_resolved_path"):
                parts.append(f"- Model path: `{preset['model_resolved_path']}`")
            if preset.get("model_note"):
                parts.append(f"- Model note: {preset['model_note']}")
        if preset.get("description"):
            parts.append(f"- Description: {preset['description']}")
        parts.extend(
            [
                f"- Template: `{preset.get('template')}`",
                f"- Example: `{preset.get('example')}`",
                "",
            ]
        )
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def prepare_media_model(
    url: str,
    out_path: Path,
    sha256: str | None = None,
    execute: bool = False,
    overwrite: bool = False,
    timeout: int = 120,
    downloader=None,
) -> dict:
    report = {
        "url": url,
        "path": str(out_path),
        "execute": bool(execute),
        "overwrite": bool(overwrite),
        "exists_before": out_path.exists(),
        "downloaded": False,
        "bytes": 0,
        "sha256": None,
        "expected_sha256": sha256,
        "verified": False,
        "ok": False,
        "note": "",
    }
    if not execute:
        if out_path.exists():
            digest = file_sha256(out_path)
            report["bytes"] = out_path.stat().st_size
            report["sha256"] = digest
            report["verified"] = not sha256 or digest.lower() == sha256.lower()
            report["ok"] = report["verified"]
            report["note"] = (
                "Dry run only. Existing model file is valid."
                if report["ok"]
                else "Dry run only. Existing model file does not match expected SHA-256."
            )
            return report
        report["ok"] = True
        report["note"] = "Dry run only. Re-run with --execute to download the model file."
        return report

    if out_path.exists() and not overwrite:
        digest = file_sha256(out_path)
        report["bytes"] = out_path.stat().st_size
        report["sha256"] = digest
        report["verified"] = not sha256 or digest.lower() == sha256.lower()
        report["ok"] = report["verified"]
        report["note"] = (
            "Existing model file is valid; use --overwrite to redownload."
            if report["ok"]
            else "Existing model file does not match expected SHA-256; use --overwrite to replace it."
        )
        return report

    model_downloader = downloader or download_url_bytes
    data = model_downloader(url, max(1, timeout))
    digest = hashlib.sha256(data).hexdigest()
    report["bytes"] = len(data)
    report["sha256"] = digest
    if sha256 and digest.lower() != sha256.lower():
        report["ok"] = False
        report["note"] = "Downloaded model SHA-256 does not match expected value; file was not written."
        return report

    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_suffix(out_path.suffix + ".part")
    temp_path.write_bytes(data)
    temp_path.replace(out_path)
    report["downloaded"] = True
    report["verified"] = bool(sha256)
    report["ok"] = True
    report["note"] = "Model file downloaded successfully."
    return report


def download_url_bytes(url: str, timeout: int) -> bytes:
    request = Request(url, headers={"User-Agent": "Link2Context/0.1"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_prepare_media_model_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Media Model Preparation",
        "",
        f"- OK: {str(report.get('ok')).lower()}",
        f"- Execute: {str(report.get('execute')).lower()}",
        f"- Output: `{report.get('path')}`",
        f"- Exists before: {str(report.get('exists_before')).lower()}",
        f"- Downloaded: {str(report.get('downloaded')).lower()}",
        f"- Bytes: {report.get('bytes', 0)}",
    ]
    if report.get("sha256"):
        parts.append(f"- SHA-256: `{report['sha256']}`")
    if report.get("expected_sha256"):
        parts.append(f"- Expected SHA-256: `{report['expected_sha256']}`")
    parts.append(f"- Verified: {str(report.get('verified')).lower()}")
    parts.extend(["", "## Source", "", f"`{report.get('url')}`", ""])
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def render_media_markdown(inventory: dict) -> str:
    filters = inventory.get("filters", {})
    parts = [
        "# Link2Context Media Inventory",
        "",
        f"- Kind: {filters.get('kind', 'all')}",
        f"- Status filter: {filters.get('status') or 'all'}",
        f"- Limit: {filters.get('limit')}",
        "",
    ]
    if inventory.get("summary"):
        parts.extend(["## Summary", ""])
        for row in inventory["summary"]:
            parts.append(f"- {row['kind']} / {row['status']}: {row['count']}")
        parts.append("")
    quality = inventory.get("quality") or {}
    if quality.get("low_confidence_count"):
        threshold = quality.get("low_confidence_threshold", MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD)
        parts.extend(["## Low Confidence Text", ""])
        parts.append(f"- Threshold: {threshold:.2f}")
        for item in inventory.get("low_confidence", [])[:5]:
            document = item.get("document", {})
            parts.append(
                f"- {item.get('kind')}[{item.get('index')}] confidence={item.get('text_confidence'):.2f} "
                f"document=[{document.get('id')}] {document.get('title') or 'Untitled'}"
            )
        parts.append("")
    if not inventory.get("items"):
        parts.extend(["No matching media items.", ""])
        return "\n".join(parts).strip() + "\n"
    parts.extend(["## Items", ""])
    for item in inventory["items"]:
        document = item["document"]
        parts.append(f"- {item['kind']}[{item['index']}] ({item.get('status') or 'unknown'})")
        parts.append(f"  - URL: {item.get('url') or 'no-url'}")
        if item.get("local_path"):
            parts.append(f"  - Local path: {item['local_path']}")
        if item.get("cache_status"):
            cache_detail = f"status={item['cache_status']}"
            if item.get("cache_error"):
                cache_detail += f", error={item['cache_error']}"
            if item.get("cache_sha256"):
                cache_detail += f", sha256={item['cache_sha256']}"
            parts.append(f"  - Cache: {cache_detail}")
        parts.append(f"  - Document: [{document.get('id')}] {document.get('title') or 'Untitled'}")
        parts.append(f"  - Source: {document.get('url')}")
        if item.get("text"):
            parts.append(f"  - Text: {item['text']}")
        details = []
        if item.get("text_model"):
            details.append(f"model={item['text_model']}")
        if item.get("text_language"):
            details.append(f"language={item['text_language']}")
        if item.get("text_confidence") is not None:
            details.append(f"confidence={item['text_confidence']:.2f}")
        if details:
            parts.append(f"  - Text metadata: {', '.join(details)}")
    parts.append("")
    if inventory.get("note"):
        parts.extend(["## Note", "", inventory["note"], ""])
    return "\n".join(parts).strip() + "\n"


def cache_media(
    conn: sqlite3.Connection,
    kind: str = "all",
    status: str | None = "not_processed",
    limit: int = 50,
    out_dir: Path = Path("outputs/media-cache"),
    overwrite: bool = False,
    timeout: int = 30,
    fetcher: Callable[[str, int], tuple[bytes, str | None]] | None = None,
) -> dict:
    fetcher = fetcher or fetch_media_url
    out_dir.mkdir(parents=True, exist_ok=True)
    items = media_cache_candidates(conn, kind, status, limit)
    cached = []
    skipped = []
    for item in items:
        checked_at = datetime.now(timezone.utc).isoformat()
        if item.get("local_path") and not overwrite:
            skipped.append({**item, "reason": "already_cached"})
            continue
        if not item.get("url"):
            cache_media_failure(conn, item["media_id"], "missing_url", "missing media URL", checked_at)
            skipped.append({**item, "reason": "missing_url", "error": "missing media URL"})
            continue
        try:
            content, content_type = fetcher(item["url"], timeout)
        except Exception as exc:  # noqa: BLE001 - report external fetch errors, do not abort the batch.
            cache_media_failure(conn, item["media_id"], "download_failed", str(exc), checked_at)
            skipped.append({**item, "reason": "download_failed", "error": str(exc)})
            continue
        if not content:
            cache_media_failure(conn, item["media_id"], "empty_response", "empty response body", checked_at)
            skipped.append({**item, "reason": "empty_response", "error": "empty response body"})
            continue
        path = media_cache_path(out_dir, item, content_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        local_path = str(path)
        sha256 = hashlib.sha256(content).hexdigest()
        conn.execute(
            """
            UPDATE media
            SET local_path = ?, cache_status = ?, cache_error = NULL,
                cache_sha256 = ?, cache_bytes = ?, cache_checked_at = ?
            WHERE id = ?
            """,
            (local_path, "cached", sha256, len(content), checked_at, item["media_id"]),
        )
        cached.append(
            {
                **item,
                "local_path": local_path,
                "bytes": len(content),
                "sha256": sha256,
                "content_type": content_type,
                "cache_status": "cached",
                "cache_checked_at": checked_at,
            }
        )
    conn.commit()
    retry_command = media_cache_retry_command(kind, status, out_dir, overwrite, timeout)
    return {
        "out_dir": str(out_dir),
        "filters": {"kind": kind, "status": status, "limit": limit, "overwrite": overwrite},
        "cached": cached,
        "skipped": skipped,
        "retry": {
            "failed": len([item for item in skipped if item.get("reason") not in ("already_cached",)]),
            "command": retry_command,
        },
        "summary": {"candidates": len(items), "cached": len(cached), "skipped": len(skipped)},
        "note": "Cached media local_path is used by queue input_source and run-media-text presets.",
    }


def media_cache_candidates(
    conn: sqlite3.Connection,
    kind: str = "all",
    status: str | None = "not_processed",
    limit: int = 50,
) -> list[dict]:
    conditions = []
    params: list[str | int] = []
    if kind != "all":
        conditions.append("m.kind = ?")
        params.append(kind)
    if status:
        conditions.append("m.status = ?")
        params.append(status)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""
        SELECT
          m.id AS media_id, m.document_id, m.kind, m.media_index, m.url, m.local_path,
          m.cache_status, m.cache_error, m.cache_sha256, m.cache_bytes, m.cache_checked_at,
          m.status,
          d.title AS document_title, d.url AS document_url
        FROM media m
        JOIN documents d ON d.id = m.document_id
        {where_clause}
        ORDER BY d.imported_at DESC, d.id DESC, m.kind ASC, m.media_index ASC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def cache_media_failure(
    conn: sqlite3.Connection,
    media_id: int,
    cache_status: str,
    cache_error: str,
    checked_at: str,
) -> None:
    conn.execute(
        """
        UPDATE media
        SET cache_status = ?, cache_error = ?, cache_checked_at = ?
        WHERE id = ?
        """,
        (cache_status, cache_error, checked_at, media_id),
    )


def fetch_media_url(url: str, timeout: int = 30) -> tuple[bytes, str | None]:
    request = Request(url, headers={"User-Agent": "Link2Context/0.1"})
    with urlopen(request, timeout=max(1, timeout)) as response:
        content_type = response.headers.get("content-type")
        return response.read(), content_type


def media_cache_path(out_dir: Path, item: dict, content_type: str | None = None) -> Path:
    url = item.get("url") or ""
    suffix = media_cache_suffix(url, content_type)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    name = f"doc{item.get('document_id')}-{item.get('kind')}{item.get('media_index')}-{digest}{suffix}"
    return out_dir / name


def media_cache_suffix(url: str, content_type: str | None = None) -> str:
    path_suffix = Path(urlsplit(url).path).suffix
    if path_suffix and len(path_suffix) <= 8:
        return path_suffix
    if content_type:
        media_type = content_type.split(";", 1)[0].strip().lower()
        guessed = mimetypes.guess_extension(media_type)
        if guessed:
            return guessed
    return ".bin"


def media_cache_retry_command(
    kind: str,
    status: str | None,
    out_dir: Path,
    overwrite: bool,
    timeout: int,
) -> str:
    parts = [
        "python -m link2context.store --db data/link2context.db cache-media",
        f"--kind {kind}",
        f"--out-dir {out_dir}",
        f"--timeout {timeout}",
    ]
    if status:
        parts.append(f"--status {status}")
    if overwrite:
        parts.append("--overwrite")
    return " ".join(parts)


def export_media_fixes(
    conn: sqlite3.Connection,
    out_path: Path,
    kind: str = "all",
    status: str | None = "not_processed",
    cache_status: str = "failed",
    limit: int = 50,
) -> dict:
    items = media_cache_candidates(conn, kind, status, limit)
    exported = [media_fix_record(item) for item in items if should_export_media_fix(item, cache_status)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for item in exported:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return {
        "path": str(out_path),
        "filters": {"kind": kind, "status": status, "cache_status": cache_status, "limit": limit},
        "exported": len(exported),
        "items": exported,
        "next": f"Edit fixed_url/fixed_local_path, then run: python -m link2context.store --db data/link2context.db apply-media-fixes {out_path}",
        "note": "Only fixed_url and fixed_local_path are applied; current_* fields are context for review.",
    }


def should_export_media_fix(item: dict, cache_status: str) -> bool:
    current = item.get("cache_status")
    if cache_status == "all":
        return bool(current)
    if cache_status == "failed":
        return current in {"download_failed", "empty_response", "missing_url"}
    return current == cache_status


def media_fix_record(item: dict) -> dict:
    return {
        "media_id": item.get("media_id"),
        "document_id": item.get("document_id"),
        "kind": item.get("kind"),
        "media_index": item.get("media_index"),
        "cache_status": item.get("cache_status"),
        "cache_error": item.get("cache_error"),
        "current_url": item.get("url"),
        "current_local_path": item.get("local_path"),
        "fixed_url": "",
        "fixed_local_path": "",
        "document": {
            "title": item.get("document_title"),
            "url": item.get("document_url"),
        },
    }


def apply_media_fixes(conn: sqlite3.Connection, path: Path, force: bool = False) -> dict:
    verification = verify_media_fixes(conn, path)
    if not verification["ok"] and not force:
        return {
            "path": str(path),
            "ok": False,
            "applied": [],
            "skipped": [],
            "summary": {"rows": verification.get("rows", 0), "applied": 0, "skipped": verification.get("rows", 0)},
            "verification": verification,
            "note": "Media fixes were not applied because verification failed. Re-run with --force to override.",
        }
    rows = read_jsonl_file(path)
    applied = []
    skipped = []
    checked_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        media_id = row.get("media_id")
        if media_id is None:
            skipped.append({"row": row, "reason": "missing_media_id"})
            continue
        current = conn.execute("SELECT id, kind, status FROM media WHERE id = ?", (media_id,)).fetchone()
        if current is None:
            skipped.append({"row": row, "reason": "media_not_found"})
            continue
        fixed_url = clean_optional_string(row.get("fixed_url"))
        fixed_local_path = clean_optional_string(row.get("fixed_local_path"))
        if not fixed_url and not fixed_local_path:
            skipped.append({"media_id": media_id, "reason": "no_fixed_fields"})
            continue
        cache_status = "fix_applied"
        params: list[object] = []
        assignments = []
        if fixed_url:
            assignments.append("url = ?")
            params.append(fixed_url)
        if fixed_local_path:
            assignments.append("local_path = ?")
            params.append(fixed_local_path)
            cache_status = "manual_local_path"
            local_file = Path(fixed_local_path)
            if local_file.exists() and local_file.is_file():
                content = local_file.read_bytes()
                assignments.extend(["cache_sha256 = ?", "cache_bytes = ?"])
                params.extend([hashlib.sha256(content).hexdigest(), len(content)])
            else:
                assignments.extend(["cache_sha256 = NULL", "cache_bytes = NULL"])
        elif fixed_url:
            assignments.extend(["local_path = NULL", "cache_sha256 = NULL", "cache_bytes = NULL"])
        assignments.extend(["cache_status = ?", "cache_error = NULL", "cache_checked_at = ?"])
        params.extend([cache_status, checked_at, media_id])
        conn.execute(
            f"""
            UPDATE media
            SET {', '.join(assignments)}
            WHERE id = ?
            """,
            params,
        )
        applied.append(
            {
                "media_id": media_id,
                "kind": current["kind"],
                "status": current["status"],
                "fixed_url": fixed_url,
                "fixed_local_path": fixed_local_path,
                "cache_status": cache_status,
                "next_step": "queue_media_text" if fixed_local_path else "cache_media",
            }
        )
    conn.commit()
    next_commands = media_fix_next_commands(applied)
    return {
        "path": str(path),
        "ok": True,
        "forced": force,
        "applied": applied,
        "skipped": skipped,
        "summary": {"rows": len(rows), "applied": len(applied), "skipped": len(skipped)},
        "verification": verification,
        "next_commands": next_commands,
        "next": "Run next_commands in order to continue caching or OCR/ASR processing.",
    }


def media_fix_next_commands(applied: list[dict]) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    for item in applied:
        kind = item.get("kind") or "all"
        status = item.get("status") or "not_processed"
        if item.get("fixed_local_path"):
            command = (
                "python -m link2context.store --db data/link2context.db "
                f"queue --kind {kind} --status {status} --format jsonl"
            )
        else:
            command = (
                "python -m link2context.store --db data/link2context.db "
                f"cache-media --kind {kind} --status {status} --out-dir outputs/media-cache"
            )
        if command not in seen:
            seen.add(command)
            commands.append(command)
    return commands


def verify_media_fixes(conn: sqlite3.Connection, path: Path) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[dict] = []
    if not path.exists():
        return {
            "path": str(path),
            "ok": False,
            "rows": 0,
            "ready_to_apply": 0,
            "errors": [f"{path} does not exist"],
            "warnings": [],
        }
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(row, dict):
            errors.append(f"line {line_number}: row is not a JSON object")
            continue
        row_errors, row_warnings = verify_media_fix_row(conn, row, line_number)
        errors.extend(row_errors)
        warnings.extend(row_warnings)
        rows.append(row)
    ready = [
        row
        for row in rows
        if clean_optional_string(row.get("fixed_url")) or clean_optional_string(row.get("fixed_local_path"))
    ]
    if not rows:
        warnings.append("manifest has no editable rows")
    return {
        "path": str(path),
        "ok": not errors,
        "rows": len(rows),
        "ready_to_apply": len(ready),
        "errors": errors,
        "warnings": warnings,
        "next": f"python -m link2context.store --db data/link2context.db apply-media-fixes {path}",
    }


def verify_media_fix_row(conn: sqlite3.Connection, row: dict, line_number: int) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    media_id = row.get("media_id")
    if media_id is None:
        errors.append(f"line {line_number}: missing media_id")
    elif conn.execute("SELECT id FROM media WHERE id = ?", (media_id,)).fetchone() is None:
        errors.append(f"line {line_number}: media_id {media_id} does not exist")
    fixed_url = clean_optional_string(row.get("fixed_url"))
    fixed_local_path = clean_optional_string(row.get("fixed_local_path"))
    if not fixed_url and not fixed_local_path:
        warnings.append(f"line {line_number}: no fixed_url or fixed_local_path; apply will skip this row")
    if fixed_url:
        parsed = urlsplit(fixed_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"line {line_number}: fixed_url is not an http(s) URL")
    if fixed_local_path:
        local_path = Path(fixed_local_path)
        if not local_path.exists():
            errors.append(f"line {line_number}: fixed_local_path does not exist")
        elif not local_path.is_file():
            errors.append(f"line {line_number}: fixed_local_path is not a file")
    return errors, warnings


def render_verify_media_fixes_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Media Fix Verification",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        f"- Rows: {report.get('rows', 0)}",
        f"- Ready to apply: {report.get('ready_to_apply', 0)}",
        "",
    ]
    if report.get("errors"):
        parts.extend(["## Errors", ""])
        for error in report["errors"]:
            parts.append(f"- {error}")
        parts.append("")
    if report.get("warnings"):
        parts.extend(["## Warnings", ""])
        for warning in report["warnings"]:
            parts.append(f"- {warning}")
        parts.append("")
    if report.get("next") and report.get("ok"):
        parts.extend(["## Next", "", report["next"], ""])
    return "\n".join(parts).strip() + "\n"


def clean_optional_string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def render_export_media_fixes_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Media Fix Export",
        "",
        f"- Path: {report.get('path')}",
        f"- Exported: {report.get('exported', 0)}",
        "",
    ]
    for item in report.get("items", [])[:20]:
        parts.append(
            f"- media_id={item.get('media_id')} {item.get('kind')}[{item.get('media_index')}] "
            f"status={item.get('cache_status') or 'unknown'}"
        )
        if item.get("cache_error"):
            parts.append(f"  - Error: {item.get('cache_error')}")
        parts.append(f"  - Current URL: {item.get('current_url') or 'missing'}")
    if report.get("next"):
        parts.extend(["", "## Next", "", report["next"]])
    return "\n".join(parts).strip() + "\n"


def render_apply_media_fixes_markdown(report: dict) -> str:
    summary = report.get("summary", {})
    parts = [
        "# Link2Context Media Fix Apply",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok', True)).lower()}",
        f"- Rows: {summary.get('rows', 0)}",
        f"- Applied: {summary.get('applied', 0)}",
        f"- Skipped: {summary.get('skipped', 0)}",
        "",
    ]
    verification = report.get("verification") or {}
    if verification.get("errors"):
        parts.extend(["## Verification Errors", ""])
        for error in verification["errors"]:
            parts.append(f"- {error}")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    if report.get("applied"):
        parts.extend(["## Applied", ""])
        for item in report["applied"][:20]:
            parts.append(f"- media_id={item.get('media_id')} status={item.get('cache_status')}")
    if report.get("skipped"):
        parts.extend(["", "## Skipped", ""])
        for item in report["skipped"][:20]:
            parts.append(f"- {item.get('media_id') or 'row'}: {item.get('reason')}")
    if report.get("next_commands"):
        parts.extend(["", "## Next Commands", ""])
        for command in report["next_commands"]:
            parts.append(f"- `{command}`")
    if report.get("next"):
        parts.extend(["", "## Next", "", report["next"]])
    return "\n".join(parts).strip() + "\n"


def render_cache_media_markdown(report: dict) -> str:
    summary = report.get("summary", {})
    parts = [
        "# Link2Context Cache Media",
        "",
        f"- Output directory: {report.get('out_dir')}",
        f"- Candidates: {summary.get('candidates', 0)}",
        f"- Cached: {summary.get('cached', 0)}",
        f"- Skipped: {summary.get('skipped', 0)}",
        "",
    ]
    if report.get("cached"):
        parts.extend(["## Cached", ""])
        for item in report["cached"][:20]:
            parts.append(
                f"- document={item.get('document_id')} {item.get('kind')}[{item.get('media_index')}] "
                f"-> {item.get('local_path')} ({item.get('bytes', 0)} bytes, sha256={item.get('sha256')})"
            )
        parts.append("")
    if report.get("skipped"):
        parts.extend(["## Skipped", ""])
        for item in report["skipped"][:20]:
            parts.append(
                f"- document={item.get('document_id')} {item.get('kind')}[{item.get('media_index')}] "
                f"reason={item.get('reason')}"
            )
        parts.append("")
    retry = report.get("retry") or {}
    if retry.get("failed"):
        parts.extend(["## Retry", "", f"- Failed items: {retry.get('failed')}", f"- Command: `{retry.get('command')}`", ""])
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def media_queue(
    conn: sqlite3.Connection,
    kind: str = "all",
    status: str | None = "not_processed",
    limit: int = 50,
    low_confidence: bool = False,
) -> dict:
    inventory_status = None if low_confidence and status == "not_processed" else status
    inventory = media_inventory(conn, kind, inventory_status, limit)
    source_items = inventory.get("low_confidence", []) if low_confidence else inventory.get("items", [])
    items = []
    for item in source_items:
        task = media_task_for_kind(item.get("kind"))
        if low_confidence:
            task = f"{task}_review"
        document = item.get("document", {})
        items.append(
            {
                "task": task,
                "kind": item.get("kind"),
                "index": item.get("index"),
                "status": item.get("status"),
                "input_url": item.get("url"),
                "input_path": item.get("local_path"),
                "input_source": item.get("local_path") or item.get("url"),
                "document": document,
                "priority": 1 if low_confidence else media_queue_priority(item),
                "reason": "low_confidence_text" if low_confidence else "needs_text",
                "previous_text": item.get("text") if low_confidence else None,
                "previous_confidence": item.get("text_confidence") if low_confidence else None,
                "low_confidence_threshold": MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD if low_confidence else None,
                "output_hint": {
                    "document_id": document.get("id"),
                    "media_index": item.get("index"),
                    "field": "text",
                },
                "result_template": media_text_result_template(item),
            }
        )
    return {
        "filters": {
            **inventory.get("filters", {}),
            "status": status,
            "low_confidence": low_confidence,
        },
        "summary": inventory.get("summary", []),
        "quality": inventory.get("quality", {}),
        "items": items,
        "note": "Queue is for external OCR/ASR processors. Fill result_template.text/model/language/confidence and apply it with apply-media-text.",
    }


def media_task_for_kind(kind: str | None) -> str:
    if kind == "image":
        return "ocr"
    if kind == "video":
        return "asr"
    return "media_processing"


def media_text_result_template(item: dict) -> dict:
    document = item.get("document", {})
    return {
        "kind": item.get("kind"),
        "output_hint": {
            "document_id": document.get("id"),
            "media_index": item.get("index"),
        },
        "text": "",
        "model": "",
        "language": "",
        "confidence": None,
    }


def media_queue_priority(item: dict) -> int:
    document = item.get("document", {})
    if document.get("platform") == "xiaohongshu":
        return 1
    if item.get("kind") == "video":
        return 2
    return 3


def render_media_queue_markdown(queue: dict) -> str:
    filters = queue.get("filters", {})
    parts = [
        "# Link2Context Media Queue",
        "",
        f"- Kind: {filters.get('kind', 'all')}",
        f"- Status: {filters.get('status') or 'all'}",
        f"- Limit: {filters.get('limit')}",
        "",
    ]
    if queue.get("summary"):
        parts.extend(["## Summary", ""])
        for row in queue["summary"]:
            parts.append(f"- {row['kind']} / {row['status']}: {row['count']}")
        parts.append("")
    if not queue.get("items"):
        parts.extend(["No queued media items.", ""])
        return "\n".join(parts).strip() + "\n"
    parts.extend(["## Items", ""])
    for item in queue["items"]:
        document = item.get("document", {})
        parts.append(f"- P{item['priority']} {item['task']} {item['kind']}[{item['index']}]")
        if item.get("reason"):
            parts.append(f"  - Reason: {item['reason']}")
        if item.get("previous_confidence") is not None:
            parts.append(
                f"  - Previous confidence: {item['previous_confidence']:.2f} "
                f"(threshold {item.get('low_confidence_threshold', MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD):.2f})"
            )
        parts.append(f"  - Input: {item.get('input_url') or 'no-url'}")
        if item.get("input_path"):
            parts.append(f"  - Local input: {item['input_path']}")
        if item.get("input_source") and item.get("input_source") != item.get("input_url"):
            parts.append(f"  - Preferred input: {item['input_source']}")
        parts.append(f"  - Document: [{document.get('id')}] {document.get('title') or 'Untitled'}")
        parts.append(f"  - Source: {document.get('url')}")
        if item.get("result_template"):
            parts.append(f"  - Result template: {json.dumps(item['result_template'], ensure_ascii=False)}")
    parts.append("")
    if queue.get("note"):
        parts.extend(["## Note", "", queue["note"], ""])
    return "\n".join(parts).strip() + "\n"


def run_media_text(
    conn: sqlite3.Connection,
    kind: str = "all",
    status: str = "not_processed",
    limit: int = 50,
    low_confidence: bool = False,
    out_path: Path | None = None,
    command_template: str | None = None,
    preset: str | None = None,
    preset_model: str | None = None,
    tool_path: str | None = None,
    model: str = "external-command",
    language: str = "",
    confidence: float | None = None,
    timeout: int = 120,
    apply: bool = False,
    reindex: bool = False,
) -> dict:
    if out_path is None:
        raise ValueError("out_path is required")
    runner = resolve_media_text_runner(
        command_template=command_template,
        preset=preset,
        preset_model=preset_model,
        tool_path=tool_path,
        model=model,
        language=language,
        confidence=confidence,
    )
    queue = media_queue(conn, kind, status, limit, low_confidence)
    results = []
    skipped = []
    for item in queue.get("items", []):
        command = media_text_command(runner["command_template"], item, runner.get("format_values"))
        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                timeout=max(1, timeout),
            )
        except subprocess.TimeoutExpired:
            skipped.append(
                {
                    "document_id": item.get("output_hint", {}).get("document_id"),
                    "media_index": item.get("index"),
                    "kind": item.get("kind"),
                    "reason": "timeout",
                    "command": command,
                }
            )
            continue
        if completed.returncode != 0:
            skipped.append(
                {
                    "document_id": item.get("output_hint", {}).get("document_id"),
                    "media_index": item.get("index"),
                    "kind": item.get("kind"),
                    "reason": "command_failed",
                    "returncode": completed.returncode,
                    "stderr": completed.stderr.strip(),
                    "command": command,
                }
            )
            continue
        text = completed.stdout.strip()
        if not text:
            skipped.append(
                {
                    "document_id": item.get("output_hint", {}).get("document_id"),
                    "media_index": item.get("index"),
                    "kind": item.get("kind"),
                    "reason": "empty_output",
                    "command": command,
                }
            )
            continue
        result = {
            **item.get("result_template", {}),
            "text": text,
            "model": runner["model"],
            "language": runner["language"],
            "confidence": runner["confidence"],
        }
        results.append(result)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    apply_report = None
    if apply and results:
        apply_report = apply_media_text(conn, out_path, status="processed", reindex=reindex)
    return {
        "path": str(out_path),
        "runner": {
            "preset": runner.get("preset"),
            "model": runner.get("model"),
            "language": runner.get("language"),
            "confidence": runner.get("confidence"),
        },
        "queue": {
            "filters": queue.get("filters"),
            "items": len(queue.get("items", [])),
        },
        "results": results,
        "skipped": skipped,
        "apply": apply_report,
        "summary": {
            "queued": len(queue.get("items", [])),
            "written": len(results),
            "skipped": len(skipped),
            "applied": len(apply_report.get("applied", [])) if apply_report else 0,
        },
        "note": "run-media-text expects the external command to write recognized text to stdout.",
    }


def resolve_media_text_runner(
    command_template: str | None = None,
    preset: str | None = None,
    preset_model: str | None = None,
    tool_path: str | None = None,
    model: str = "external-command",
    language: str = "",
    confidence: float | None = None,
) -> dict:
    if preset and command_template:
        raise ValueError("Use either preset or command_template, not both")
    if preset:
        config = MEDIA_TEXT_PRESETS.get(preset)
        if not config:
            raise ValueError(f"Unknown media text preset: {preset}")
        if preset in {"sona", "vibe"} and not preset_model:
            raise ValueError(f"preset_model is required for {preset}")
        resolved_language = language or config.get("language", "")
        resolved_model = model if model != "external-command" else config.get("model", model)
        return {
            "preset": preset,
            "command_template": config["template"],
            "model": resolved_model,
            "language": resolved_language,
            "confidence": confidence if confidence is not None else config.get("confidence"),
            "format_values": {
                "language": resolved_language,
                "preset_model": preset_model or "",
                "tool_path": tool_path or config.get("tool_path", ""),
            },
        }
    if not command_template or not command_template.strip():
        raise ValueError("command_template is required")
    return {
        "preset": None,
        "command_template": command_template,
        "model": model,
        "language": language,
        "confidence": confidence,
        "format_values": {
            "language": language,
            "preset_model": preset_model or "",
            "tool_path": tool_path or "",
        },
    }


def media_text_command(command_template: str, item: dict, extra_values: dict | None = None) -> str:
    document = item.get("document", {})
    values = {
        "input_url": item.get("input_url") or "",
        "input_path": item.get("input_path") or "",
        "input_source": item.get("input_source") or item.get("input_path") or item.get("input_url") or "",
        "kind": item.get("kind") or "",
        "task": item.get("task") or "",
        "media_index": item.get("index") or "",
        "document_id": item.get("output_hint", {}).get("document_id") or document.get("id") or "",
        "document_title": document.get("title") or "",
        "document_url": document.get("url") or "",
        "reason": item.get("reason") or "",
    }
    if extra_values:
        values.update(extra_values)
    return command_template.format_map(DefaultFormatValues(values))


class DefaultFormatValues(dict):
    def __missing__(self, key: str) -> str:
        return ""


def render_run_media_text_markdown(report: dict) -> str:
    summary = report.get("summary", {})
    parts = [
        "# Link2Context Run Media Text",
        "",
        f"- Output: {report.get('path')}",
        f"- Preset: {(report.get('runner') or {}).get('preset') or 'custom'}",
        f"- Model: {(report.get('runner') or {}).get('model') or 'unknown'}",
        f"- Language: {(report.get('runner') or {}).get('language') or 'unknown'}",
        f"- Queued: {summary.get('queued', 0)}",
        f"- Written: {summary.get('written', 0)}",
        f"- Skipped: {summary.get('skipped', 0)}",
        f"- Applied: {summary.get('applied', 0)}",
        "",
    ]
    if report.get("results"):
        parts.extend(["## Written Results", ""])
        for result in report["results"][:10]:
            hint = result.get("output_hint", {})
            parts.append(
                f"- document={hint.get('document_id')} "
                f"{result.get('kind')}[{hint.get('media_index')}] "
                f"model={result.get('model') or 'unknown'}"
            )
        parts.append("")
    if report.get("skipped"):
        parts.extend(["## Skipped", ""])
        for item in report["skipped"][:10]:
            parts.append(
                f"- document={item.get('document_id')} "
                f"{item.get('kind')}[{item.get('media_index')}] "
                f"reason={item.get('reason')}"
            )
        parts.append("")
    if report.get("apply"):
        apply_summary = report["apply"].get("summary", {})
        parts.extend(
            [
                "## Apply Summary",
                "",
                f"- Applied: {apply_summary.get('applied', 0)}",
                f"- Skipped: {apply_summary.get('skipped', 0)}",
                f"- Low confidence: {apply_summary.get('low_confidence', 0)}",
                "",
            ]
        )
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def apply_media_text(
    conn: sqlite3.Connection,
    path: Path,
    status: str = "processed",
    reindex: bool = False,
    reindex_limit: int = 200,
) -> dict:
    results = read_media_text_results(path)
    applied = []
    skipped = []
    for index, result in enumerate(results, start=1):
        normalized = normalize_media_text_result(result)
        if not normalized.get("ok"):
            skipped.append({"index": index, "reason": normalized["reason"], "input": result})
            continue
        row = conn.execute(
            """
            SELECT id
            FROM media
            WHERE document_id = ? AND media_index = ?
              AND (? IS NULL OR kind = ?)
            ORDER BY id ASC
            LIMIT 1
            """,
            (
                normalized["document_id"],
                normalized["media_index"],
                normalized.get("kind"),
                normalized.get("kind"),
            ),
        ).fetchone()
        if row is None:
            skipped.append({"index": index, "reason": "media_not_found", "input": result})
            continue
        conn.execute(
            """
            UPDATE media
            SET text = ?, status = ?, text_model = ?, text_language = ?, text_confidence = ?
            WHERE id = ?
            """,
            (
                normalized["text"],
                status,
                normalized.get("model"),
                normalized.get("language"),
                normalized.get("confidence"),
                row["id"],
            ),
        )
        applied.append(
            {
                "index": index,
                "media_id": row["id"],
                "document_id": normalized["document_id"],
                "media_index": normalized["media_index"],
                "kind": normalized.get("kind"),
                "status": status,
                "text_length": len(normalized["text"]),
                "model": normalized.get("model"),
                "language": normalized.get("language"),
                "confidence": normalized.get("confidence"),
            }
        )
    conn.commit()
    reindex_report = None
    if reindex and applied:
        reindex_report = reindex_media_text(
            conn,
            reindex_limit,
            sorted({item["document_id"] for item in applied}),
        )
    low_confidence = [
        {
            "media_id": item["media_id"],
            "document_id": item["document_id"],
            "media_index": item["media_index"],
            "kind": item.get("kind"),
            "confidence": item.get("confidence"),
            "threshold": MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD,
        }
        for item in applied
        if item.get("confidence") is not None
        and item["confidence"] < MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD
    ]
    return {
        "path": str(path),
        "status": status,
        "reindex_requested": reindex,
        "reindex": reindex_report,
        "applied": applied,
        "skipped": skipped,
        "low_confidence": low_confidence,
        "summary": {
            "input": len(results),
            "applied": len(applied),
            "skipped": len(skipped),
            "low_confidence": len(low_confidence),
        },
        "note": "Applied text updates media.text and media.status only; source context_json is unchanged.",
    }


def read_media_text_results(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [
            json.loads(line)
            for line in text.splitlines()
            if line.strip()
        ]
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    return [data]


def normalize_media_text_result(result: dict) -> dict:
    output_hint = result.get("output_hint") if isinstance(result.get("output_hint"), dict) else {}
    document = result.get("document") if isinstance(result.get("document"), dict) else {}
    document_id = result.get("document_id") or output_hint.get("document_id") or document.get("id")
    media_index = result.get("media_index") or output_hint.get("media_index") or result.get("index")
    text = result.get("text") or result.get("output_text") or result.get("transcript")
    if document_id is None:
        return {"ok": False, "reason": "missing_document_id"}
    if media_index is None:
        return {"ok": False, "reason": "missing_media_index"}
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "reason": "missing_text"}
    confidence = normalize_optional_float(result.get("confidence", result.get("text_confidence")))
    return {
        "ok": True,
        "document_id": int(document_id),
        "media_index": int(media_index),
        "kind": result.get("kind"),
        "text": text.strip(),
        "model": result.get("model") or result.get("text_model"),
        "language": result.get("language") or result.get("lang") or result.get("text_language"),
        "confidence": confidence,
    }


def normalize_optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def verify_media_text(
    conn: sqlite3.Connection,
    path: Path,
    status: str = "processed",
    require_reindex: bool = False,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    verified = []
    skipped = []
    if not path.exists():
        return {
            "path": str(path),
            "ok": False,
            "status": status,
            "require_reindex": require_reindex,
            "errors": [f"{path} does not exist"],
            "warnings": [],
            "verified": [],
            "skipped": [],
            "summary": {"input": 0, "verified": 0, "skipped": 0, "errors": 1},
        }
    try:
        results = read_media_text_results(path)
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "path": str(path),
            "ok": False,
            "status": status,
            "require_reindex": require_reindex,
            "errors": [f"failed to read media text results: {exc}"],
            "warnings": [],
            "verified": [],
            "skipped": [],
            "summary": {"input": 0, "verified": 0, "skipped": 0, "errors": 1},
        }
    touched_documents: set[int] = set()
    for index, result in enumerate(results, start=1):
        normalized = normalize_media_text_result(result)
        if not normalized.get("ok"):
            skipped.append({"index": index, "reason": normalized["reason"], "input": result})
            continue
        row = conn.execute(
            """
            SELECT id, document_id, media_index, kind, text, status, text_model, text_language, text_confidence
            FROM media
            WHERE document_id = ? AND media_index = ?
              AND (? IS NULL OR kind = ?)
            ORDER BY id ASC
            LIMIT 1
            """,
            (
                normalized["document_id"],
                normalized["media_index"],
                normalized.get("kind"),
                normalized.get("kind"),
            ),
        ).fetchone()
        if row is None:
            errors.append(f"input #{index}: media row not found")
            skipped.append({"index": index, "reason": "media_not_found", "input": result})
            continue
        item_errors = []
        if row["status"] != status:
            item_errors.append(f"status expected {status}, got {row['status']}")
        if (row["text"] or "").strip() != normalized["text"]:
            item_errors.append("text does not match result")
        if normalized.get("model") and row["text_model"] != normalized.get("model"):
            item_errors.append(f"model expected {normalized.get('model')}, got {row['text_model']}")
        if normalized.get("language") and row["text_language"] != normalized.get("language"):
            item_errors.append(f"language expected {normalized.get('language')}, got {row['text_language']}")
        expected_confidence = normalized.get("confidence")
        if expected_confidence is not None:
            actual_confidence = row["text_confidence"]
            if actual_confidence is None or abs(float(actual_confidence) - float(expected_confidence)) > 1e-9:
                item_errors.append(f"confidence expected {expected_confidence}, got {actual_confidence}")
        if item_errors:
            for error in item_errors:
                errors.append(f"media_id={row['id']}: {error}")
        else:
            touched_documents.add(row["document_id"])
            verified.append(
                {
                    "index": index,
                    "media_id": row["id"],
                    "document_id": row["document_id"],
                    "media_index": row["media_index"],
                    "kind": row["kind"],
                    "text_length": len(row["text"] or ""),
                    "status": row["status"],
                    "model": row["text_model"],
                    "language": row["text_language"],
                    "confidence": row["text_confidence"],
                }
            )
    reindex = {"required": require_reindex, "ok": None, "documents": []}
    if require_reindex:
        reindex_documents = []
        for document_id in sorted(touched_documents):
            entity_count = conn.execute(
                "SELECT COUNT(*) AS count FROM document_entities WHERE document_id = ? AND evidence = 'media.text'",
                (document_id,),
            ).fetchone()["count"]
            relation_count = conn.execute(
                "SELECT COUNT(*) AS count FROM relationships WHERE document_id = ? AND evidence = 'media.text'",
                (document_id,),
            ).fetchone()["count"]
            document_ok = entity_count > 0 or relation_count > 0
            if not document_ok:
                errors.append(f"document_id={document_id}: missing media.text graph signals")
            reindex_documents.append(
                {
                    "document_id": document_id,
                    "ok": document_ok,
                    "entities": entity_count,
                    "relations": relation_count,
                }
            )
        reindex = {
            "required": True,
            "ok": all(item["ok"] for item in reindex_documents) if reindex_documents else False,
            "documents": reindex_documents,
        }
        if not reindex_documents and results:
            errors.append("require_reindex is true but no verified documents were available")
    if not results:
        warnings.append("media text result file is empty")
    return {
        "path": str(path),
        "ok": not errors,
        "status": status,
        "require_reindex": require_reindex,
        "errors": errors,
        "warnings": warnings,
        "verified": verified,
        "skipped": skipped,
        "reindex": reindex,
        "summary": {
            "input": len(results),
            "verified": len(verified),
            "skipped": len(skipped),
            "errors": len(errors),
        },
        "note": "Verification checks applied media rows; source context_json remains unchanged.",
    }


def render_verify_media_text_markdown(report: dict) -> str:
    summary = report.get("summary", {})
    parts = [
        "# Link2Context Verify Media Text",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        f"- Expected status: {report.get('status')}",
        f"- Require reindex: {str(report.get('require_reindex')).lower()}",
        f"- Input: {summary.get('input', 0)}",
        f"- Verified: {summary.get('verified', 0)}",
        f"- Skipped: {summary.get('skipped', 0)}",
        f"- Errors: {summary.get('errors', 0)}",
        "",
    ]
    if report.get("errors"):
        parts.extend(["## Errors", ""])
        for error in report["errors"]:
            parts.append(f"- {error}")
        parts.append("")
    if report.get("warnings"):
        parts.extend(["## Warnings", ""])
        for warning in report["warnings"]:
            parts.append(f"- {warning}")
        parts.append("")
    if report.get("verified"):
        parts.extend(["## Verified", ""])
        for item in report["verified"][:20]:
            parts.append(
                f"- media_id={item.get('media_id')} document={item.get('document_id')} "
                f"{item.get('kind')}[{item.get('media_index')}] text_length={item.get('text_length')}"
            )
        parts.append("")
    reindex = report.get("reindex") or {}
    if reindex.get("required"):
        parts.extend(["## Reindex", ""])
        parts.append(f"- OK: {str(reindex.get('ok')).lower()}")
        for item in reindex.get("documents", []):
            marker = "ok" if item.get("ok") else "fail"
            parts.append(
                f"- {marker} document={item.get('document_id')} "
                f"entities={item.get('entities', 0)} relations={item.get('relations', 0)}"
            )
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def render_apply_media_text_markdown(report: dict) -> str:
    summary = report.get("summary", {})
    parts = [
        "# Link2Context Apply Media Text",
        "",
        f"- Path: {report.get('path')}",
        f"- Status: {report.get('status')}",
        f"- Reindex requested: {str(report.get('reindex_requested', False)).lower()}",
        f"- Input: {summary.get('input', 0)}",
        f"- Applied: {summary.get('applied', 0)}",
        f"- Skipped: {summary.get('skipped', 0)}",
        f"- Low confidence: {summary.get('low_confidence', 0)}",
        "",
    ]
    if report.get("applied"):
        parts.extend(["## Applied", ""])
        for item in report["applied"]:
            details = []
            if item.get("model"):
                details.append(f"model={item['model']}")
            if item.get("language"):
                details.append(f"language={item['language']}")
            if item.get("confidence") is not None:
                details.append(f"confidence={item['confidence']:.2f}")
            detail_text = f" ({', '.join(details)})" if details else ""
            parts.append(
                f"- media_id={item['media_id']} document={item['document_id']} "
                f"media_index={item['media_index']} text_length={item['text_length']}{detail_text}"
            )
        parts.append("")
    if report.get("skipped"):
        parts.extend(["## Skipped", ""])
        for item in report["skipped"]:
            parts.append(f"- input #{item['index']}: {item['reason']}")
        parts.append("")
    if report.get("low_confidence"):
        parts.extend(["## Low Confidence After Apply", ""])
        for item in report["low_confidence"]:
            parts.append(
                f"- media_id={item['media_id']} document={item['document_id']} "
                f"{item.get('kind') or 'media'}[{item['media_index']}] "
                f"confidence={item['confidence']:.2f} threshold={item['threshold']:.2f}"
            )
        parts.append("")
    if report.get("reindex"):
        reindex = report["reindex"]
        parts.extend(["## Reindex", ""])
        parts.append(f"- Media items: {reindex.get('media_items', 0)}")
        parts.append(f"- Entities: {reindex.get('entities', 0)}")
        parts.append(f"- Relations: {reindex.get('relations', 0)}")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def reindex_media_text(
    conn: sqlite3.Connection,
    limit: int = 200,
    document_ids: list[int] | None = None,
) -> dict:
    normalized_document_ids = sorted({int(document_id) for document_id in document_ids or []})
    conditions = ["m.text IS NOT NULL", "trim(m.text) != ''"]
    params: list[int] = []
    if normalized_document_ids:
        placeholders = ", ".join("?" for _ in normalized_document_ids)
        conditions.append(f"m.document_id IN ({placeholders})")
        params.extend(normalized_document_ids)
    rows = conn.execute(
        f"""
        SELECT
          m.document_id, m.kind, m.media_index, m.text,
          d.url AS document_url, d.title, d.platform, d.account_name
        FROM media m
        JOIN documents d ON d.id = m.document_id
        WHERE {' AND '.join(conditions)}
        ORDER BY d.imported_at DESC, d.id DESC, m.kind ASC, m.media_index ASC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    if normalized_document_ids:
        placeholders = ", ".join("?" for _ in normalized_document_ids)
        conn.execute(
            f"DELETE FROM relationships WHERE evidence = 'media.text' AND document_id IN ({placeholders})",
            normalized_document_ids,
        )
        conn.execute(
            f"DELETE FROM document_entities WHERE evidence = 'media.text' AND document_id IN ({placeholders})",
            normalized_document_ids,
        )
    else:
        conn.execute("DELETE FROM relationships WHERE evidence = 'media.text'")
        conn.execute("DELETE FROM document_entities WHERE evidence = 'media.text'")
    indexed = []
    total_entities = 0
    total_relations = 0
    for row in rows:
        context = {
            "source": {
                "url": row["document_url"],
                "platform": row["platform"],
            },
            "article": {
                "title": "",
                "account_name": None,
                "author": None,
            },
            "content": {
                "plain_text": row["text"],
            },
        }
        graph = extract_graph(context)
        entities = [
            {**entity, "source": "media.text", "confidence": min(entity.get("confidence", 0.5), 0.55)}
            for entity in graph["entities"]
            if entity.get("type") not in {"source_account", "person_or_author"}
        ]
        relations = [
            {**relation, "evidence": "media.text", "confidence": min(relation.get("confidence", 0.5), 0.55)}
            for relation in graph["relations"]
            if relation.get("predicate") == "mentions"
        ]
        for entity in entities:
            entity_id = upsert_entity(conn, entity)
            conn.execute(
                """
                INSERT OR REPLACE INTO document_entities (
                  document_id, entity_id, role, confidence, evidence
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["document_id"],
                    entity_id,
                    entity["type"],
                    entity["confidence"],
                    entity["source"],
                ),
            )
        for relation in relations:
            conn.execute(
                """
                INSERT INTO relationships (
                  document_id, subject, predicate, object, confidence, evidence
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row["document_id"],
                    relation["subject"],
                    relation["predicate"],
                    relation["object"],
                    relation["confidence"],
                    relation["evidence"],
                ),
            )
        total_entities += len(entities)
        total_relations += len(relations)
        indexed.append(
            {
                "document_id": row["document_id"],
                "kind": row["kind"],
                "media_index": row["media_index"],
                "entities": len(entities),
                "relations": len(relations),
            }
        )
    conn.commit()
    return {
        "limit": limit,
        "scope": "documents" if normalized_document_ids else "all",
        "document_ids": normalized_document_ids,
        "media_items": len(rows),
        "entities": total_entities,
        "relations": total_relations,
        "indexed": indexed,
        "note": "Reindexed graph signals from media.text. Existing media.text graph edges were rebuilt.",
    }


def render_reindex_media_text_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Reindex Media Text",
        "",
        f"- Limit: {report.get('limit')}",
        f"- Scope: {report.get('scope', 'all')}",
        f"- Document IDs: {', '.join(str(document_id) for document_id in report.get('document_ids', [])) or 'all'}",
        f"- Media items: {report.get('media_items', 0)}",
        f"- Entities: {report.get('entities', 0)}",
        f"- Relations: {report.get('relations', 0)}",
        "",
    ]
    if report.get("indexed"):
        parts.extend(["## Indexed", ""])
        for item in report["indexed"][:20]:
            parts.append(
                f"- document={item['document_id']} {item['kind']}[{item['media_index']}]: "
                f"{item['entities']} entities, {item['relations']} relations"
            )
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def quality_report(conn: sqlite3.Connection, status: str | None = None, limit: int = 50) -> dict:
    conditions = []
    params: list[str | int] = []
    if status:
        conditions.append("quality_status = ?")
        params.append(status)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""
        SELECT id, title, url, platform, account_name, quality_status, context_json, imported_at
        FROM documents
        {where_clause}
        ORDER BY
          CASE WHEN quality_status = 'ok' THEN 1 ELSE 0 END ASC,
          imported_at DESC,
          id DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    summary_rows = conn.execute(
        f"""
        SELECT COALESCE(quality_status, 'unknown') AS status, COUNT(*) AS count
        FROM documents
        {where_clause}
        GROUP BY COALESCE(quality_status, 'unknown')
        ORDER BY status ASC
        """,
        params,
    ).fetchall()
    documents = [quality_document(row) for row in rows]
    warning_counts: dict[str, int] = {}
    missing_field_counts: dict[str, int] = {}
    for document in documents:
        for warning in document["warnings"]:
            warning_counts[warning] = warning_counts.get(warning, 0) + 1
        for field in document["missing_fields"]:
            missing_field_counts[field] = missing_field_counts.get(field, 0) + 1
    return {
        "filters": {
            "status": status,
            "limit": limit,
        },
        "summary": [
            {
                "status": row["status"],
                "count": row["count"],
            }
            for row in summary_rows
        ],
        "warning_counts": dict(sorted(warning_counts.items(), key=lambda item: (-item[1], item[0]))),
        "missing_field_counts": dict(sorted(missing_field_counts.items(), key=lambda item: (-item[1], item[0]))),
        "documents": documents,
        "note": "Quality data is imported from context.json and reflects extraction completeness, not factual correctness.",
    }


def quality_document(row: sqlite3.Row) -> dict:
    try:
        context = json.loads(row["context_json"])
    except json.JSONDecodeError:
        context = {}
    quality = context.get("quality", {}) if isinstance(context, dict) else {}
    return {
        "id": row["id"],
        "title": row["title"],
        "url": row["url"],
        "platform": row["platform"],
        "account_name": row["account_name"],
        "status": row["quality_status"],
        "warnings": list(quality.get("warnings") or []),
        "missing_fields": list(quality.get("missing_fields") or []),
    }


def render_quality_markdown(report: dict) -> str:
    filters = report.get("filters", {})
    parts = [
        "# Link2Context Quality Report",
        "",
        f"- Status filter: {filters.get('status') or 'all'}",
        f"- Limit: {filters.get('limit')}",
        "",
    ]
    if report.get("summary"):
        parts.extend(["## Summary", ""])
        for row in report["summary"]:
            parts.append(f"- {row['status']}: {row['count']}")
        parts.append("")
    if report.get("warning_counts"):
        parts.extend(["## Warning Counts", ""])
        for warning, count in report["warning_counts"].items():
            parts.append(f"- {warning}: {count}")
        parts.append("")
    if report.get("missing_field_counts"):
        parts.extend(["## Missing Field Counts", ""])
        for field, count in report["missing_field_counts"].items():
            parts.append(f"- {field}: {count}")
        parts.append("")
    if not report.get("documents"):
        parts.extend(["No matching documents.", ""])
        return "\n".join(parts).strip() + "\n"
    parts.extend(["## Documents", ""])
    for document in report["documents"]:
        parts.append(f"- [{document['id']}] {document.get('title') or 'Untitled'} ({document.get('status') or 'unknown'})")
        parts.append(f"  - URL: {document.get('url')}")
        if document.get("warnings"):
            parts.append(f"  - Warnings: {', '.join(document['warnings'])}")
        if document.get("missing_fields"):
            parts.append(f"  - Missing: {', '.join(document['missing_fields'])}")
    parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def action_plan(conn: sqlite3.Connection, limit: int = 20) -> dict:
    doctor = store_doctor(conn)
    quality = quality_report(conn, None, limit)
    media = media_inventory(conn, "all", None, limit)
    actions: list[dict] = []
    if doctor["status"] == "empty":
        actions.append(
            {
                "priority": 1,
                "kind": "ingest",
                "title": "Import contexts into the local store",
                "detail": "The store has no imported documents.",
                "command": "python -m link2context.store --db data/link2context.db ingest outputs/batch",
            }
        )
    for document in quality.get("documents", []):
        if document.get("status") != "ok" or document.get("warnings") or document.get("missing_fields"):
            actions.append(
                {
                    "priority": 2,
                    "kind": "quality",
                    "title": f"Review document [{document['id']}] {document.get('title') or 'Untitled'}",
                    "detail": quality_action_detail(document),
                    "command": f"python -m link2context.store --db data/link2context.db doc {document['id']}",
                }
            )
    low_confidence_keys = {
        (item.get("document", {}).get("id"), item.get("kind"), item.get("index"))
        for item in media.get("low_confidence", [])
    }
    for item in media.get("items", []):
        document = item["document"]
        is_low_confidence = (document.get("id"), item.get("kind"), item.get("index")) in low_confidence_keys
        if media_needs_cache(item, is_low_confidence):
            actions.append(
                {
                    "priority": 2,
                    "kind": "media_cache",
                    "title": media_cache_action_title(item),
                    "detail": media_cache_action_detail(item),
                    "command": media_cache_action_command(item),
                }
            )
        if item.get("status") not in ("ok", "done", "processed"):
            actions.append(
                {
                    "priority": 3,
                    "kind": "media",
                    "title": f"Process {item['kind']}[{item['index']}] from document [{document['id']}]",
                    "detail": media_process_action_detail(item),
                    "command": media_process_action_command(item),
                }
            )
    for item in media.get("low_confidence", []):
        document = item["document"]
        actions.append(
            {
                "priority": 2,
                "kind": "media_review",
                "title": f"Review low-confidence {item['kind']}[{item['index']}] from document [{document['id']}]",
                "detail": (
                    f"confidence={item.get('text_confidence'):.2f}; "
                    f"threshold={MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD:.2f}; "
                    f"source={item.get('url') or 'no-url'}"
                ),
                "command": (
                    f"python -m link2context.store --db data/link2context.db queue "
                    f"--low-confidence --kind {item['kind']} --format jsonl"
                ),
            }
        )
    if doctor["ready_for_agent"]:
        actions.append(
            {
                "priority": 3,
                "kind": "handoff",
                "title": "Export an agent handoff bundle",
                "detail": "The store is ready for agent use.",
                "command": "python -m link2context.store --db data/link2context.db export --out outputs/agent-handoff",
            }
        )
    actions = sorted(actions, key=lambda item: (item["priority"], item["kind"], item["title"]))[:limit]
    return {
        "status": doctor["status"],
        "ready_for_agent": doctor["ready_for_agent"],
        "actions": actions,
        "note": "Action priorities are rule-based and derived from doctor, quality, and media reports.",
    }


def quality_action_detail(document: dict) -> str:
    parts = [f"status={document.get('status') or 'unknown'}"]
    if document.get("warnings"):
        parts.append(f"warnings={'; '.join(document['warnings'])}")
    if document.get("missing_fields"):
        parts.append(f"missing={'; '.join(document['missing_fields'])}")
    return "; ".join(parts)


def media_needs_cache(item: dict, low_confidence: bool = False) -> bool:
    if item.get("local_path"):
        return False
    if item.get("cache_status") in {"missing_url", "download_failed", "empty_response"}:
        return True
    if not item.get("url"):
        return False
    return low_confidence or item.get("status") not in ("ok", "done", "processed")


def media_cache_action_command(item: dict) -> str:
    status = item.get("status") or "not_processed"
    cache_status = item.get("cache_status")
    if cache_status in {"missing_url", "download_failed", "empty_response"}:
        return (
            "python -m link2context.store --db data/link2context.db export-media-fixes "
            f"--out outputs/media-fixes-{item.get('kind')}-{cache_status}.jsonl "
            f"--kind {item.get('kind')} --status {status} --cache-status {cache_status}"
        )
    return (
        "python -m link2context.store --db data/link2context.db cache-media "
        f"--kind {item.get('kind')} --status {status} --out-dir outputs/media-cache"
    )


def media_cache_action_title(item: dict) -> str:
    document = item.get("document", {})
    prefix = {
        "missing_url": "Add media URL before caching",
        "download_failed": "Retry media cache download",
        "empty_response": "Retry empty media cache download",
    }.get(item.get("cache_status"), "Cache")
    return f"{prefix} {item.get('kind')}[{item.get('index')}] from document [{document.get('id')}]"


def media_cache_action_detail(item: dict) -> str:
    retry_mode = {
        "missing_url": "manual_url_required",
        "download_failed": "retry_download",
        "empty_response": "retry_download",
    }.get(item.get("cache_status"), "download")
    parts = ["local_path=missing", f"retry_mode={retry_mode}", f"source={item.get('url') or 'no-url'}"]
    if item.get("cache_status"):
        parts.append(f"cache_status={item['cache_status']}")
        parts.append(
            f"verify_media_fixes=python -m link2context.store --db data/link2context.db "
            f"verify-media-fixes outputs/media-fixes-{item.get('kind')}-{item['cache_status']}.jsonl"
        )
        parts.append(
            f"apply_media_fixes=python -m link2context.store --db data/link2context.db "
            f"apply-media-fixes outputs/media-fixes-{item.get('kind')}-{item['cache_status']}.jsonl"
        )
    if item.get("cache_error"):
        parts.append(f"cache_error={item['cache_error']}")
    return "; ".join(parts)


def media_process_action_detail(item: dict) -> str:
    parts = [f"status={item.get('status') or 'unknown'}", f"source={item.get('url') or 'no-url'}"]
    if item.get("local_path"):
        parts.append(f"local_path={item['local_path']}")
        parts.append("next_step=queue_media_text")
    return "; ".join(parts)


def media_process_action_command(item: dict) -> str:
    status = item.get("status") or "unknown"
    if item.get("local_path"):
        return (
            "python -m link2context.store --db data/link2context.db queue "
            f"--kind {item['kind']} --status {status} --format jsonl"
        )
    return f"python -m link2context.store --db data/link2context.db media --kind {item['kind']} --status {status}"


def render_action_plan_markdown(plan: dict) -> str:
    parts = [
        "# Link2Context Actions",
        "",
        f"- Store status: {plan.get('status')}",
        f"- Ready for agent: {str(plan.get('ready_for_agent')).lower()}",
        "",
    ]
    if not plan.get("actions"):
        parts.extend(["No actions suggested.", ""])
        return "\n".join(parts).strip() + "\n"
    parts.extend(["## Recommended Actions", ""])
    for action in plan["actions"]:
        parts.append(f"- P{action['priority']} [{action['kind']}] {action['title']}")
        parts.append(f"  - Detail: {action['detail']}")
        parts.append(f"  - Command: `{action['command']}`")
    parts.append("")
    if plan.get("note"):
        parts.extend(["## Note", "", plan["note"], ""])
    return "\n".join(parts).strip() + "\n"


def source_report(conn: sqlite3.Connection, limit: int = 20) -> dict:
    platform_rows = conn.execute(
        """
        SELECT platform, COUNT(*) AS documents
        FROM documents
        GROUP BY platform
        ORDER BY documents DESC, platform ASC
        """
    ).fetchall()
    account_rows = conn.execute(
        """
        SELECT
          platform,
          COALESCE(NULLIF(account_name, ''), 'Unknown') AS account_name,
          COUNT(*) AS documents,
          SUM(CASE WHEN quality_status = 'ok' THEN 1 ELSE 0 END) AS ok_documents,
          SUM(CASE WHEN quality_status != 'ok' OR quality_status IS NULL THEN 1 ELSE 0 END) AS non_ok_documents,
          MAX(COALESCE(published_at, imported_at)) AS latest_at
        FROM documents
        GROUP BY platform, COALESCE(NULLIF(account_name, ''), 'Unknown')
        ORDER BY documents DESC, latest_at DESC, account_name ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return {
        "platforms": [
            {
                "platform": row["platform"],
                "documents": row["documents"],
            }
            for row in platform_rows
        ],
        "sources": [
            {
                "platform": row["platform"],
                "account_name": row["account_name"],
                "documents": row["documents"],
                "ok_documents": row["ok_documents"],
                "non_ok_documents": row["non_ok_documents"],
                "latest_at": row["latest_at"],
                "recent_documents": source_recent_documents(
                    conn,
                    row["platform"],
                    None if row["account_name"] == "Unknown" else row["account_name"],
                    3,
                ),
            }
            for row in account_rows
        ],
        "limit": limit,
        "note": "Sources are grouped by platform and account_name from imported context metadata.",
    }


def source_recent_documents(
    conn: sqlite3.Connection,
    platform: str,
    account_name: str | None,
    limit: int = 3,
) -> list[dict]:
    if account_name is None:
        condition = "(account_name IS NULL OR account_name = '')"
        params: tuple[str | int, ...] = (platform, limit)
    else:
        condition = "account_name = ?"
        params = (platform, account_name, limit)
    rows = conn.execute(
        f"""
        SELECT id, title, url, quality_status, published_at, imported_at
        FROM documents
        WHERE platform = ?
          AND {condition}
        ORDER BY COALESCE(published_at, imported_at) DESC, imported_at DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "quality_status": row["quality_status"],
            "published_at": row["published_at"],
            "imported_at": row["imported_at"],
        }
        for row in rows
    ]


def render_sources_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Sources",
        "",
    ]
    if report.get("platforms"):
        parts.extend(["## Platforms", ""])
        for platform in report["platforms"]:
            parts.append(f"- {platform['platform']}: {platform['documents']} document(s)")
        parts.append("")
    if not report.get("sources"):
        parts.extend(["No sources found.", ""])
        return "\n".join(parts).strip() + "\n"
    parts.extend(["## Source Accounts", ""])
    for source in report["sources"]:
        parts.append(f"- {source['account_name']} ({source['platform']}): {source['documents']} document(s)")
        parts.append(f"  - Quality: ok={source['ok_documents']}, non_ok={source['non_ok_documents']}")
        parts.append(f"  - Latest: {source.get('latest_at') or 'unknown'}")
        for document in source.get("recent_documents", []):
            parts.append(
                f"  - [{document['id']}] {document.get('title') or 'Untitled'} "
                f"({document.get('quality_status') or 'unknown'})"
            )
    parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def coverage_report(conn: sqlite3.Connection, limit: int = 20) -> dict:
    store_stats = stats(conn)
    doctor = store_doctor(conn)
    sources = source_report(conn, limit)
    quality = quality_report(conn, None, limit)
    duplicates = duplicate_report(conn, limit)
    platform_rows = conn.execute(
        """
        SELECT
          platform,
          COUNT(*) AS documents,
          COUNT(DISTINCT account_name) AS account_names,
          SUM(CASE WHEN quality_status = 'ok' THEN 1 ELSE 0 END) AS ok_documents,
          SUM(CASE WHEN quality_status != 'ok' OR quality_status IS NULL THEN 1 ELSE 0 END) AS non_ok_documents
        FROM documents
        GROUP BY platform
        ORDER BY documents DESC, platform ASC
        """
    ).fetchall()
    coverage_row = conn.execute(
        """
        SELECT
          (SELECT COUNT(DISTINCT document_id) FROM citations) AS documents_with_citations,
          (SELECT COUNT(DISTINCT document_id) FROM document_entities) AS documents_with_entities,
          (SELECT COUNT(DISTINCT document_id) FROM media) AS documents_with_media,
          (SELECT COUNT(*) FROM media) AS media_total,
          (SELECT COUNT(*) FROM media WHERE status IN ('ok', 'done', 'processed') OR COALESCE(text, '') != '') AS media_processed,
          (SELECT COUNT(*) FROM media WHERE NOT (status IN ('ok', 'done', 'processed') OR COALESCE(text, '') != '')) AS media_pending
        """
    ).fetchone()
    documents = store_stats["documents"]
    coverage = {
        "documents_with_citations": coverage_row["documents_with_citations"],
        "documents_with_entities": coverage_row["documents_with_entities"],
        "documents_with_media": coverage_row["documents_with_media"],
        "media_total": coverage_row["media_total"],
        "media_processed": coverage_row["media_processed"],
        "media_pending": coverage_row["media_pending"],
        "duplicate_groups": duplicates["summary"]["groups"],
        "duplicate_documents": duplicates["summary"]["documents"],
    }
    gaps = coverage_gaps(documents, sources["platforms"], quality, coverage)
    return {
        "status": doctor["status"],
        "ready_for_agent": doctor["ready_for_agent"],
        "limit": limit,
        "stats": store_stats,
        "platforms": [
            {
                "platform": row["platform"],
                "documents": row["documents"],
                "account_names": row["account_names"],
                "ok_documents": row["ok_documents"],
                "non_ok_documents": row["non_ok_documents"],
            }
            for row in platform_rows
        ],
        "coverage": coverage,
        "quality": {
            "summary": quality["summary"],
            "warning_counts": quality["warning_counts"],
            "missing_field_counts": quality["missing_field_counts"],
        },
        "sources": sources["sources"],
        "gaps": gaps,
        "commands": coverage_commands(gaps),
        "note": "Coverage is a rule-based readiness view across imported links, sources, graph signals, and media processing.",
    }


def coverage_gaps(documents: int, platforms: list[dict], quality: dict, coverage: dict) -> list[dict]:
    gaps: list[dict] = []
    if documents == 0:
        gaps.append(
            {
                "kind": "ingest",
                "severity": "high",
                "detail": "No documents have been imported.",
            }
        )
    if documents > 0 and len(platforms) < 2:
        gaps.append(
            {
                "kind": "platform",
                "severity": "medium",
                "detail": "Only one platform is represented; cross-platform interest signals are weak.",
            }
        )
    if documents > coverage.get("documents_with_citations", 0):
        missing = documents - coverage.get("documents_with_citations", 0)
        gaps.append(
            {
                "kind": "citation",
                "severity": "medium",
                "detail": f"{missing} document(s) have no citation snippets.",
            }
        )
    if documents > coverage.get("documents_with_entities", 0):
        missing = documents - coverage.get("documents_with_entities", 0)
        gaps.append(
            {
                "kind": "graph",
                "severity": "medium",
                "detail": f"{missing} document(s) have no extracted graph entities.",
            }
        )
    if coverage.get("media_pending", 0):
        gaps.append(
            {
                "kind": "media",
                "severity": "medium",
                "detail": f"{coverage['media_pending']} media item(s) still need OCR/ASR text.",
            }
        )
    non_ok = sum(row["count"] for row in quality.get("summary", []) if row.get("status") != "ok")
    if non_ok:
        gaps.append(
            {
                "kind": "quality",
                "severity": "medium",
                "detail": f"{non_ok} document(s) are not marked ok.",
            }
        )
    if coverage.get("duplicate_groups", 0):
        gaps.append(
            {
                "kind": "duplicates",
                "severity": "low",
                "detail": f"{coverage['duplicate_groups']} duplicate candidate group(s) need review.",
            }
        )
    return gaps


def coverage_commands(gaps: list[dict]) -> list[str]:
    commands = [
        "python -m link2context.store --db data/link2context.db sources",
        "python -m link2context.store --db data/link2context.db quality",
    ]
    gap_kinds = {gap["kind"] for gap in gaps}
    if "ingest" in gap_kinds or "platform" in gap_kinds:
        commands.append("python -m link2context.store --db data/link2context.db ingest outputs/batch")
    if "media" in gap_kinds:
        commands.append("python -m link2context.store --db data/link2context.db queue")
        commands.append("python -m link2context.store --db data/link2context.db reindex-media-text")
    if "duplicates" in gap_kinds:
        commands.append("python -m link2context.store --db data/link2context.db duplicates")
    commands.append("python -m link2context.store --db data/link2context.db snapshot --out outputs/snapshot")
    return commands


def render_coverage_markdown(report: dict) -> str:
    stats_value = report.get("stats", {})
    coverage = report.get("coverage", {})
    parts = [
        "# Link2Context Coverage",
        "",
        f"- Store status: {report.get('status')}",
        f"- Ready for agent: {str(report.get('ready_for_agent')).lower()}",
        f"- Documents: {stats_value.get('documents', 0)}",
        f"- Citations: {stats_value.get('citations', 0)}",
        f"- Entities: {stats_value.get('entities', 0)}",
        f"- Relationships: {stats_value.get('relationships', 0)}",
        "",
    ]
    if report.get("platforms"):
        parts.extend(["## Platform Coverage", ""])
        for platform in report["platforms"]:
            parts.append(
                f"- {platform['platform']}: {platform['documents']} document(s), "
                f"ok={platform['ok_documents']}, non_ok={platform['non_ok_documents']}"
            )
        parts.append("")
    parts.extend(
        [
            "## Processing Coverage",
            "",
            f"- Documents with citations: {coverage.get('documents_with_citations', 0)}",
            f"- Documents with graph entities: {coverage.get('documents_with_entities', 0)}",
            f"- Documents with media: {coverage.get('documents_with_media', 0)}",
            f"- Media processed: {coverage.get('media_processed', 0)} / {coverage.get('media_total', 0)}",
            f"- Media pending: {coverage.get('media_pending', 0)}",
            f"- Duplicate groups: {coverage.get('duplicate_groups', 0)}",
            "",
        ]
    )
    quality = report.get("quality", {})
    if quality.get("warning_counts") or quality.get("missing_field_counts"):
        parts.extend(["## Quality Gaps", ""])
        for warning, count in quality.get("warning_counts", {}).items():
            parts.append(f"- Warning {warning}: {count}")
        for field, count in quality.get("missing_field_counts", {}).items():
            parts.append(f"- Missing {field}: {count}")
        parts.append("")
    if report.get("sources"):
        parts.extend(["## Source Accounts", ""])
        for source in report["sources"]:
            parts.append(f"- {source['account_name']} ({source['platform']}): {source['documents']} document(s)")
        parts.append("")
    if report.get("gaps"):
        parts.extend(["## Gaps", ""])
        for gap in report["gaps"]:
            parts.append(f"- {gap['severity']} [{gap['kind']}] {gap['detail']}")
        parts.append("")
    if report.get("commands"):
        parts.extend(["## Commands", ""])
        for command in report["commands"]:
            parts.append(f"- `{command}`")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def topics_report(conn: sqlite3.Connection, entity_type: str | None = None, limit: int = 20) -> dict:
    conditions = [
        "e.type NOT IN ('source_account', 'person_or_author')",
        "NOT (e.type = 'term' AND (length(e.name) <= 2 OR e.name IN ('AI', 'Agent', 'Agents', 'Skill', 'Skills')))",
    ]
    params: list[str | int] = []
    if entity_type:
        conditions.append("e.type = ?")
        params.append(entity_type)
    where_clause = " AND ".join(conditions)
    rows = conn.execute(
        f"""
        SELECT e.id, e.name, e.type, COUNT(DISTINCT de.document_id) AS documents, AVG(de.confidence) AS avg_confidence
        FROM entities e
        JOIN document_entities de ON de.entity_id = e.id
        WHERE {where_clause}
        GROUP BY e.id
        ORDER BY documents DESC, avg_confidence DESC, e.name ASC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return {
        "filters": {
            "type": entity_type,
            "limit": limit,
        },
        "topics": [
            {
                "name": row["name"],
                "type": row["type"],
                "documents": row["documents"],
                "avg_confidence": row["avg_confidence"],
                "evidence_documents": entity_evidence(conn, row["id"], 3),
                "evidence_citations": entity_citation_evidence(conn, row["id"], row["name"], 3),
            }
            for row in rows
        ],
        "note": "Topics are extracted entities from imported contexts; this is rule-based, not semantic clustering.",
    }


def render_topics_markdown(report: dict) -> str:
    filters = report.get("filters", {})
    parts = [
        "# Link2Context Topics",
        "",
        f"- Type filter: {filters.get('type') or 'all'}",
        f"- Limit: {filters.get('limit')}",
        "",
    ]
    if not report.get("topics"):
        parts.extend(["No topics found.", ""])
        return "\n".join(parts).strip() + "\n"
    for topic in report["topics"]:
        confidence = topic.get("avg_confidence")
        confidence_text = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "unknown"
        parts.append(f"## {topic['name']} ({topic['type']})")
        parts.append("")
        parts.append(f"- Documents: {topic['documents']}")
        parts.append(f"- Average confidence: {confidence_text}")
        if topic.get("evidence_documents"):
            parts.append("- Evidence documents:")
            for document in topic["evidence_documents"]:
                parts.append(f"  - {document.get('title') or 'Untitled'}: {document.get('url')}")
        if topic.get("evidence_citations"):
            parts.append("- Evidence citations:")
            for citation in topic["evidence_citations"]:
                parts.append(f"  - {citation.get('ref')} | {citation.get('title') or 'Untitled'}")
                parts.append(f"    {citation.get('text')}")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def clusters_report(conn: sqlite3.Connection, min_docs: int = 2, limit: int = 20) -> dict:
    min_docs = max(1, min_docs)
    conditions = [
        "e.type NOT IN ('source_account', 'person_or_author')",
        "NOT (e.type = 'term' AND (length(e.name) <= 2 OR e.name IN ('AI', 'Agent', 'Agents', 'Skill', 'Skills')))",
    ]
    where_clause = " AND ".join(conditions)
    rows = conn.execute(
        f"""
        SELECT
          e.id,
          e.name,
          e.type,
          COUNT(DISTINCT de.document_id) AS documents,
          AVG(de.confidence) AS avg_confidence
        FROM entities e
        JOIN document_entities de ON de.entity_id = e.id
        WHERE {where_clause}
        GROUP BY e.id
        HAVING COUNT(DISTINCT de.document_id) >= ?
        ORDER BY documents DESC, avg_confidence DESC, e.name ASC
        LIMIT ?
        """,
        (min_docs, limit),
    ).fetchall()
    return {
        "filters": {
            "min_docs": min_docs,
            "limit": limit,
        },
        "clusters": [
            {
                "name": row["name"],
                "type": row["type"],
                "documents": row["documents"],
                "avg_confidence": row["avg_confidence"],
                "evidence_documents": entity_evidence(conn, row["id"], 5),
                "evidence_citations": entity_citation_evidence(conn, row["id"], row["name"], 3),
                "commands": {
                    "explain": f'python -m link2context.store --db data/link2context.db explain "{row["name"]}"',
                    "evidence": f'python -m link2context.store --db data/link2context.db evidence "{row["name"]}"',
                },
            }
            for row in rows
        ],
        "note": "Clusters are rule-based groups of documents sharing extracted entities; they are not vector or LLM clusters.",
    }


def render_clusters_markdown(report: dict) -> str:
    filters = report.get("filters", {})
    parts = [
        "# Link2Context Clusters",
        "",
        f"- Minimum documents: {filters.get('min_docs')}",
        f"- Limit: {filters.get('limit')}",
        "",
    ]
    if not report.get("clusters"):
        parts.extend(["No clusters found.", ""])
        return "\n".join(parts).strip() + "\n"
    for cluster in report["clusters"]:
        confidence = cluster.get("avg_confidence")
        confidence_text = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "unknown"
        parts.append(f"## {cluster['name']} ({cluster['type']})")
        parts.append("")
        parts.append(f"- Documents: {cluster['documents']}")
        parts.append(f"- Average confidence: {confidence_text}")
        commands = cluster.get("commands", {})
        if commands:
            parts.append(f"- Explain: `{commands.get('explain')}`")
            parts.append(f"- Evidence: `{commands.get('evidence')}`")
        if cluster.get("evidence_documents"):
            parts.append("- Representative documents:")
            for document in cluster["evidence_documents"]:
                parts.append(f"  - [{document.get('id')}] {document.get('title') or 'Untitled'}")
                parts.append(f"    {document.get('url')}")
        if cluster.get("evidence_citations"):
            parts.append("- Evidence citations:")
            for citation in cluster["evidence_citations"]:
                parts.append(f"  - {citation.get('ref')} | {citation.get('title') or 'Untitled'}")
                parts.append(f"    {citation.get('text')}")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def questions_report(conn: sqlite3.Connection, limit: int = 20) -> dict:
    clusters = clusters_report(conn, 2, limit)["clusters"]
    questions: list[dict] = []
    question_templates = [
        {
            "kind": "synthesis",
            "question": "What have I collected about {name}, and what pattern does it suggest?",
            "command": "explain",
        },
        {
            "kind": "evidence",
            "question": "Which citations are the strongest evidence for {name}?",
            "command": "evidence",
        },
        {
            "kind": "connection",
            "question": "Which documents connect {name} to other recurring topics in my collection?",
            "command": "relations",
        },
    ]
    for template in question_templates:
        for cluster in clusters:
            if len(questions) >= limit:
                break
            name = cluster["name"]
            commands = cluster.get("commands", {})
            if template["command"] == "relations":
                command = f'python -m link2context.store --db data/link2context.db relations "{name}"'
            else:
                command = commands.get(template["command"])
            questions.append(
                {
                    "topic": name,
                    "type": cluster.get("type"),
                    "documents": cluster.get("documents", 0),
                    "kind": template["kind"],
                    "question": template["question"].format(name=name),
                    "command": command,
                    "evidence_documents": cluster.get("evidence_documents", [])[:3],
                }
            )
        if len(questions) >= limit:
            break
    return {
        "limit": limit,
        "questions": questions,
        "note": "Questions are deterministic prompts generated from rule-based topic clusters; verify answers with citations.",
    }


def render_questions_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Questions",
        "",
        f"- Limit: {report.get('limit')}",
        "",
    ]
    if not report.get("questions"):
        parts.extend(["No questions found. Import more documents or lower cluster thresholds.", ""])
        return "\n".join(parts).strip() + "\n"
    for index, question in enumerate(report["questions"], start=1):
        parts.append(f"## {index}. {question['question']}")
        parts.append("")
        parts.append(f"- Topic: {question.get('topic')} ({question.get('type')})")
        parts.append(f"- Kind: {question.get('kind')}")
        parts.append(f"- Documents: {question.get('documents')}")
        if question.get("command"):
            parts.append(f"- Command: `{question.get('command')}`")
        if question.get("evidence_documents"):
            parts.append("- Evidence documents:")
            for document in question["evidence_documents"]:
                parts.append(f"  - [{document.get('id')}] {document.get('title') or 'Untitled'}")
                parts.append(f"    {document.get('url')}")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def relations_report(
    conn: sqlite3.Connection,
    entity: str | None = None,
    predicate: str | None = None,
    limit: int = 50,
) -> dict:
    conditions = []
    params: list[str | int] = []
    if entity:
        conditions.append("(r.subject = ? OR r.object = ?)")
        params.extend([entity, entity])
    if predicate:
        conditions.append("r.predicate = ?")
        params.append(predicate)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""
        SELECT
          r.subject, r.predicate, r.object, r.confidence, r.evidence,
          d.id AS document_id, d.title, d.url, d.platform, d.account_name
        FROM relationships r
        JOIN documents d ON d.id = r.document_id
        {where_clause}
        ORDER BY r.confidence DESC, d.imported_at DESC, r.id ASC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return {
        "filters": {
            "entity": entity,
            "predicate": predicate,
            "limit": limit,
        },
        "relations": [
            {
                "subject": row["subject"],
                "predicate": row["predicate"],
                "object": row["object"],
                "confidence": row["confidence"],
                "evidence": row["evidence"],
                "document": {
                    "id": row["document_id"],
                    "title": row["title"],
                    "url": row["url"],
                    "platform": row["platform"],
                    "account_name": row["account_name"],
                },
            }
            for row in rows
        ],
        "note": "Relations are rule-based graph edges extracted from imported contexts.",
    }


def render_relations_markdown(report: dict) -> str:
    filters = report.get("filters", {})
    parts = [
        "# Link2Context Relations",
        "",
        f"- Entity filter: {filters.get('entity') or 'all'}",
        f"- Predicate filter: {filters.get('predicate') or 'all'}",
        f"- Limit: {filters.get('limit')}",
        "",
    ]
    if not report.get("relations"):
        parts.extend(["No matching relations.", ""])
        return "\n".join(parts).strip() + "\n"
    for relation in report["relations"]:
        document = relation["document"]
        parts.append(
            f"- {relation['subject']} --{relation['predicate']}--> {relation['object']} "
            f"(confidence={relation['confidence']})"
        )
        parts.append(f"  - Evidence: {relation.get('evidence')}")
        parts.append(f"  - Source: [{document['id']}] {document.get('title') or 'Untitled'}")
        parts.append(f"  - URL: {document.get('url')}")
    parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def digest_report(conn: sqlite3.Connection, limit: int = 10) -> dict:
    return {
        "stats": stats(conn),
        "recent": document_timeline(conn, min(limit, 10))["documents"],
        "topics": topics_report(conn, None, min(limit, 10))["topics"],
        "clusters": clusters_report(conn, 2, min(limit, 5))["clusters"],
        "questions": questions_report(conn, min(limit, 5))["questions"],
        "sources": source_report(conn, min(limit, 10))["sources"],
        "quality": quality_report(conn, None, min(limit, 10)),
        "actions": action_plan(conn, min(limit, 10))["actions"],
        "limit": limit,
        "note": "Digest is a compact rule-based review assembled from store reports; it is not an LLM-generated summary.",
    }


def render_digest_markdown(report: dict) -> str:
    store_stats = report.get("stats", {})
    parts = [
        "# Link2Context Digest",
        "",
        "## Store",
        "",
        f"- Documents: {store_stats.get('documents', 0)}",
        f"- Citations: {store_stats.get('citations', 0)}",
        f"- Entities: {store_stats.get('entities', 0)}",
        f"- Relationships: {store_stats.get('relationships', 0)}",
        "",
    ]
    if report.get("recent"):
        parts.extend(["## Recent Documents", ""])
        for document in report["recent"][:5]:
            date = document.get("published_at") or document.get("imported_at") or "unknown"
            parts.append(f"- [{document['id']}] {document.get('title') or 'Untitled'} ({date})")
        parts.append("")
    if report.get("topics"):
        parts.extend(["## Top Topics", ""])
        for topic in report["topics"][:5]:
            parts.append(f"- {topic['name']} ({topic['type']}): {topic['documents']} document(s)")
        parts.append("")
    if report.get("clusters"):
        parts.extend(["## Topic Clusters", ""])
        for cluster in report["clusters"][:5]:
            parts.append(f"- {cluster['name']} ({cluster['type']}): {cluster['documents']} document(s)")
            commands = cluster.get("commands", {})
            if commands.get("explain"):
                parts.append(f"  - `{commands.get('explain')}`")
        parts.append("")
    if report.get("questions"):
        parts.extend(["## Follow-up Questions", ""])
        for question in report["questions"][:5]:
            parts.append(f"- [{question.get('kind')}] {question.get('question')}")
            if question.get("command"):
                parts.append(f"  - `{question.get('command')}`")
        parts.append("")
    if report.get("sources"):
        parts.extend(["## Top Sources", ""])
        for source in report["sources"][:5]:
            parts.append(
                f"- {source['account_name']} ({source['platform']}): "
                f"{source['documents']} document(s), ok={source['ok_documents']}, non_ok={source['non_ok_documents']}"
            )
        parts.append("")
    quality = report.get("quality", {})
    if quality.get("summary"):
        parts.extend(["## Quality", ""])
        for row in quality["summary"]:
            parts.append(f"- {row['status']}: {row['count']}")
        parts.append("")
    if report.get("actions"):
        parts.extend(["## Next Actions", ""])
        for action in report["actions"][:5]:
            parts.append(f"- P{action['priority']} [{action['kind']}] {action['title']}")
            parts.append(f"  - `{action['command']}`")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def review_report(conn: sqlite3.Connection, limit: int = 10) -> dict:
    doctor = store_doctor(conn)
    digest = digest_report(conn, limit)
    actions = action_plan(conn, min(limit, 10))
    questions = questions_report(conn, min(limit, 10))
    return {
        "status": doctor["status"],
        "ready_for_agent": doctor["ready_for_agent"],
        "stats": digest["stats"],
        "top_clusters": digest.get("clusters", [])[:5],
        "follow_up_questions": questions.get("questions", [])[:5],
        "actions": actions.get("actions", [])[:5],
        "recommended_next": [
            "python -m link2context.store --db data/link2context.db brief",
            "python -m link2context.store --db data/link2context.db questions",
            "python -m link2context.store --db data/link2context.db export --out outputs/agent-handoff",
        ],
        "note": "Review is a compact one-page entry point assembled from doctor, digest, questions, and actions.",
    }


def render_review_markdown(report: dict) -> str:
    stats_value = report.get("stats", {})
    parts = [
        "# Link2Context Review",
        "",
        f"- Status: {report.get('status')}",
        f"- Ready for agent: {str(report.get('ready_for_agent')).lower()}",
        f"- Documents: {stats_value.get('documents', 0)}",
        f"- Citations: {stats_value.get('citations', 0)}",
        f"- Entities: {stats_value.get('entities', 0)}",
        "",
    ]
    if report.get("top_clusters"):
        parts.extend(["## Top Clusters", ""])
        for cluster in report["top_clusters"]:
            parts.append(f"- {cluster['name']} ({cluster['type']}): {cluster['documents']} document(s)")
            commands = cluster.get("commands", {})
            if commands.get("explain"):
                parts.append(f"  - `{commands.get('explain')}`")
        parts.append("")
    if report.get("follow_up_questions"):
        parts.extend(["## Follow-up Questions", ""])
        for question in report["follow_up_questions"]:
            parts.append(f"- [{question.get('kind')}] {question.get('question')}")
            if question.get("command"):
                parts.append(f"  - `{question.get('command')}`")
        parts.append("")
    if report.get("actions"):
        parts.extend(["## Actions", ""])
        for action in report["actions"]:
            parts.append(f"- P{action['priority']} [{action['kind']}] {action['title']}")
            parts.append(f"  - `{action['command']}`")
        parts.append("")
    if report.get("recommended_next"):
        parts.extend(["## Recommended Next", ""])
        for command in report["recommended_next"]:
            parts.append(f"- `{command}`")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def inbox_report(conn: sqlite3.Connection, limit: int = 10) -> dict:
    limit = max(1, limit)
    doctor = store_doctor(conn)
    media = media_inventory(conn, "all", None, limit)
    quality = quality_report(conn, None, limit)
    actions = action_plan(conn, limit)
    statuses = status_report(conn, None, limit)
    pending_media = [
        item
        for item in media.get("items", [])
        if item.get("status") not in ("ok", "done", "processed")
    ][:limit]
    quality_issues = [
        document
        for document in quality.get("documents", [])
        if document.get("status") != "ok" or document.get("warnings") or document.get("missing_fields")
    ][:limit]
    return {
        "status": doctor["status"],
        "ready_for_agent": doctor["ready_for_agent"],
        "stats": stats(conn),
        "recent_documents": document_timeline(conn, min(limit, 10))["documents"][:limit],
        "pending_media": pending_media,
        "quality_issues": quality_issues,
        "top_topics": topics_report(conn, None, min(limit, 5))["topics"],
        "top_clusters": clusters_report(conn, 2, min(limit, 5))["clusters"],
        "status_summary": statuses["summary"],
        "actions": actions.get("actions", [])[:limit],
        "commands": [
            "python -m link2context.store --db data/link2context.db ingest outputs/batch",
            "python -m link2context.store --db data/link2context.db queue --format jsonl",
            "python -m link2context.store --db data/link2context.db review",
            "python -m link2context.store --db data/link2context.db snapshot --out outputs/snapshot",
        ],
        "note": "Inbox is a daily triage view assembled from recent documents, quality, media, topics, and actions.",
    }


def render_inbox_markdown(report: dict) -> str:
    stats_value = report.get("stats", {})
    parts = [
        "# Link2Context Inbox",
        "",
        f"- Status: {report.get('status')}",
        f"- Ready for agent: {str(report.get('ready_for_agent')).lower()}",
        f"- Documents: {stats_value.get('documents', 0)}",
        f"- Citations: {stats_value.get('citations', 0)}",
        f"- Pending media: {len(report.get('pending_media', []))}",
        f"- Quality issues: {len(report.get('quality_issues', []))}",
        "",
    ]
    if report.get("recent_documents"):
        parts.extend(["## Recent", ""])
        for document in report["recent_documents"][:5]:
            date = document.get("published_at") or document.get("imported_at") or "unknown"
            parts.append(f"- [{document['id']}] {document.get('title') or 'Untitled'} ({date})")
            parts.append(f"  - URL: {document.get('url')}")
        parts.append("")
    if report.get("quality_issues"):
        parts.extend(["## Quality Issues", ""])
        for document in report["quality_issues"][:5]:
            parts.append(f"- [{document['id']}] {document.get('title') or 'Untitled'} ({document.get('status') or 'unknown'})")
            parts.append(f"  - {quality_action_detail(document)}")
            parts.append(f"  - `python -m link2context.store --db data/link2context.db doc {document['id']}`")
        parts.append("")
    if report.get("pending_media"):
        parts.extend(["## Pending Media", ""])
        for item in report["pending_media"][:5]:
            document = item.get("document", {})
            parts.append(
                f"- [{document.get('id')}] {item.get('kind')}[{item.get('index')}] "
                f"status={item.get('status') or 'unknown'}"
            )
            parts.append(f"  - Source: {item.get('url') or 'no-url'}")
        parts.append("")
    if report.get("top_topics"):
        parts.extend(["## Top Topics", ""])
        for topic in report["top_topics"][:5]:
            parts.append(f"- {topic['name']} ({topic['type']}): {topic['documents']} document(s)")
        parts.append("")
    if report.get("top_clusters"):
        parts.extend(["## Clusters", ""])
        for cluster in report["top_clusters"][:5]:
            parts.append(f"- {cluster['name']} ({cluster['type']}): {cluster['documents']} document(s)")
            command = cluster.get("commands", {}).get("explain")
            if command:
                parts.append(f"  - `{command}`")
        parts.append("")
    if report.get("status_summary"):
        parts.extend(["## User Statuses", ""])
        for row in report["status_summary"]:
            parts.append(f"- {row['status']}: {row['documents']}")
        parts.append("")
    if report.get("actions"):
        parts.extend(["## Next Actions", ""])
        for action in report["actions"][:5]:
            parts.append(f"- P{action['priority']} [{action['kind']}] {action['title']}")
            parts.append(f"  - `{action['command']}`")
        parts.append("")
    if report.get("commands"):
        parts.extend(["## Useful Commands", ""])
        for command in report["commands"]:
            parts.append(f"- `{command}`")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def curate_report(conn: sqlite3.Connection, limit: int = 10) -> dict:
    limit = max(1, limit)
    inbox = inbox_report(conn, limit)
    coverage = coverage_report(conn, limit)
    duplicates = duplicate_report(conn, limit)
    statuses = status_report(conn, None, limit)
    media = media_inventory(conn, "all", None, limit)
    status_by_document_id = {
        item["document"]["id"]: item["status"]
        for item in statuses.get("documents", [])
    }
    read_now = [
        document
        for document in inbox.get("recent_documents", [])
        if document.get("quality_status") == "ok"
        and status_by_document_id.get(document["id"]) not in ("later", "reading", "read", "archived")
    ][:limit]
    continue_marked = [
        item
        for item in statuses.get("documents", [])
        if item.get("status") in ("later", "reading")
    ][:limit]
    low_confidence_keys = {
        (item.get("document", {}).get("id"), item.get("kind"), item.get("index"))
        for item in media.get("low_confidence", [])
    }
    cache_media_items = [
        {
            "document_id": item.get("document", {}).get("id"),
            "title": item.get("document", {}).get("title") or "Untitled",
            "kind": item.get("kind"),
            "index": item.get("index"),
            "status": item.get("status") or "unknown",
            "url": item.get("url"),
            "reason": "needs_local_cache",
            "detail": media_cache_action_detail(item),
            "command": media_cache_action_command(item),
        }
        for item in media.get("items", [])
        if media_needs_cache(
            item,
            (item.get("document", {}).get("id"), item.get("kind"), item.get("index")) in low_confidence_keys,
        )
    ][:limit]
    pending_media_items = [
        {
            "document_id": item.get("document", {}).get("id"),
            "title": item.get("document", {}).get("title") or "Untitled",
            "kind": item.get("kind"),
            "index": item.get("index"),
            "status": item.get("status") or "unknown",
            "url": item.get("url"),
            "reason": "needs_text",
            "command": "python -m link2context.store --db data/link2context.db queue --format jsonl",
        }
        for item in inbox.get("pending_media", [])[:limit]
    ]
    review_media_items = [
        {
            "document_id": item.get("document", {}).get("id"),
            "title": item.get("document", {}).get("title") or "Untitled",
            "kind": item.get("kind"),
            "index": item.get("index"),
            "status": item.get("status") or "unknown",
            "url": item.get("url"),
            "reason": "low_confidence_text",
            "text_confidence": item.get("text_confidence"),
            "low_confidence_threshold": MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD,
            "detail": (
                f"confidence={item.get('text_confidence'):.2f}; "
                f"threshold={MEDIA_TEXT_LOW_CONFIDENCE_THRESHOLD:.2f}"
            ),
            "command": (
                f"python -m link2context.store --db data/link2context.db queue "
                f"--low-confidence --kind {item.get('kind')} --format jsonl"
            ),
        }
        for item in media.get("low_confidence", [])[:limit]
    ]
    process_media_items = (cache_media_items + pending_media_items + review_media_items)[:limit]
    lanes = [
        {
            "name": "read_now",
            "title": "Read Now",
            "purpose": "Recent good-enough documents worth reading or asking an agent about.",
            "items": [
                {
                    "id": document["id"],
                    "title": document.get("title") or "Untitled",
                    "url": document.get("url"),
                    "platform": document.get("platform"),
                    "account_name": document.get("account_name"),
                    "command": f"python -m link2context.store --db data/link2context.db doc {document['id']}",
                }
                for document in read_now
            ],
        },
        {
            "name": "continue_marked",
            "title": "Continue Marked",
            "purpose": "Documents explicitly marked later or reading.",
            "items": [
                {
                    "id": item["document"]["id"],
                    "title": item["document"].get("title") or "Untitled",
                    "status": item.get("status"),
                    "detail": item.get("note"),
                    "url": item["document"].get("url"),
                    "command": f"python -m link2context.store --db data/link2context.db doc {item['document']['id']}",
                }
                for item in continue_marked
            ],
        },
        {
            "name": "fix_quality",
            "title": "Fix Quality",
            "purpose": "Partial or warning-heavy documents that need review before they become reliable context.",
            "items": [
                {
                    "id": document["id"],
                    "title": document.get("title") or "Untitled",
                    "status": document.get("status") or "unknown",
                    "detail": quality_action_detail(document),
                    "command": f"python -m link2context.store --db data/link2context.db doc {document['id']}",
                }
                for document in inbox.get("quality_issues", [])[:limit]
            ],
        },
        {
            "name": "process_media",
            "title": "Process Media",
            "purpose": "Images or videos that need local caching, OCR/ASR text, or low-confidence OCR/ASR review.",
            "items": process_media_items,
        },
        {
            "name": "review_duplicates",
            "title": "Review Duplicates",
            "purpose": "Candidate duplicate groups to inspect before deleting or merging anything.",
            "items": [
                {
                    "kind": group.get("kind"),
                    "key": group.get("key"),
                    "documents": [
                        {
                            "id": document["id"],
                            "title": document.get("title") or "Untitled",
                            "url": document.get("url"),
                        }
                        for document in group.get("documents", [])
                    ],
                    "command": "python -m link2context.store --db data/link2context.db duplicates",
                }
                for group in duplicates.get("groups", [])[:limit]
            ],
        },
        {
            "name": "agent_handoff",
            "title": "Agent Handoff",
            "purpose": "Commands that package the collection for another agent or external knowledge tool.",
            "items": [
                {
                    "title": "Export agent handoff",
                    "command": "python -m link2context.store --db data/link2context.db export --out outputs/agent-handoff",
                },
                {
                    "title": "Create full snapshot",
                    "command": "python -m link2context.store --db data/link2context.db snapshot --out outputs/snapshot",
                },
            ] if inbox.get("ready_for_agent") else [],
        },
    ]
    return {
        "status": inbox["status"],
        "ready_for_agent": inbox["ready_for_agent"],
        "stats": inbox["stats"],
        "coverage": coverage["coverage"],
        "lanes": lanes,
        "gaps": coverage["gaps"],
        "commands": [
            "python -m link2context.store --db data/link2context.db inbox",
            "python -m link2context.store --db data/link2context.db coverage",
            "python -m link2context.store --db data/link2context.db actions",
        ],
        "note": "Curate is a read-only action board for turning collected links into maintained external-brain context.",
    }


def render_curate_markdown(report: dict) -> str:
    stats_value = report.get("stats", {})
    parts = [
        "# Link2Context Curate",
        "",
        f"- Status: {report.get('status')}",
        f"- Ready for agent: {str(report.get('ready_for_agent')).lower()}",
        f"- Documents: {stats_value.get('documents', 0)}",
        f"- Citations: {stats_value.get('citations', 0)}",
        f"- Entities: {stats_value.get('entities', 0)}",
        "",
    ]
    for lane in report.get("lanes", []):
        parts.extend([f"## {lane['title']}", "", lane["purpose"], ""])
        if not lane.get("items"):
            parts.extend(["No items.", ""])
            continue
        for item in lane["items"]:
            if lane["name"] == "process_media":
                parts.append(
                    f"- [{item.get('document_id')}] {item.get('kind')}[{item.get('index')}] "
                    f"{item.get('title')} ({item.get('status')})"
                )
                if item.get("reason"):
                    parts.append(f"  - Reason: {item['reason']}")
                if item.get("detail"):
                    parts.append(f"  - {item['detail']}")
                if item.get("url"):
                    parts.append(f"  - Source: {item['url']}")
            elif lane["name"] == "review_duplicates":
                parts.append(f"- {item.get('kind')} {item.get('key')}")
                for document in item.get("documents", []):
                    parts.append(f"  - [{document['id']}] {document.get('title')}")
            elif "id" in item:
                parts.append(f"- [{item['id']}] {item.get('title')}")
                if item.get("detail"):
                    parts.append(f"  - {item['detail']}")
                if item.get("url"):
                    parts.append(f"  - URL: {item['url']}")
            else:
                parts.append(f"- {item.get('title')}")
            if item.get("command"):
                parts.append(f"  - `{item['command']}`")
        parts.append("")
    if report.get("gaps"):
        parts.extend(["## Gaps", ""])
        for gap in report["gaps"]:
            parts.append(f"- {gap['severity']} [{gap['kind']}] {gap['detail']}")
        parts.append("")
    if report.get("commands"):
        parts.extend(["## Useful Commands", ""])
        for command in report["commands"]:
            parts.append(f"- `{command}`")
        parts.append("")
    if report.get("note"):
        parts.extend(["## Note", "", report["note"], ""])
    return "\n".join(parts).strip() + "\n"


def entity_evidence(conn: sqlite3.Connection, entity_id: int, limit: int = 3) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.id, d.title, d.url, d.platform, de.evidence
        FROM document_entities de
        JOIN documents d ON d.id = de.document_id
        WHERE de.entity_id = ?
        ORDER BY d.imported_at DESC, d.id DESC
        LIMIT ?
        """,
        (entity_id, limit),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "platform": row["platform"],
            "evidence": row["evidence"],
        }
        for row in rows
    ]


def entity_citation_evidence(
    conn: sqlite3.Connection,
    entity_id: int,
    entity_name: str,
    limit: int = 3,
) -> list[dict]:
    aliases = entity_citation_aliases(entity_name)
    if not aliases:
        return []
    conditions = " OR ".join(["c.text LIKE ?"] * len(aliases))
    rows = conn.execute(
        f"""
        SELECT c.ref, c.text, c.source, d.title, d.url, d.platform
        FROM document_entities de
        JOIN documents d ON d.id = de.document_id
        JOIN citations c ON c.document_id = d.id
        WHERE de.entity_id = ?
          AND ({conditions})
        ORDER BY d.imported_at DESC, d.id DESC, c.id ASC
        LIMIT ?
        """,
        (entity_id, *[f"%{alias}%" for alias in aliases], limit),
    ).fetchall()
    return [
        {
            "ref": row["ref"],
            "text": row["text"],
            "source": row["source"],
            "title": row["title"],
            "url": row["url"],
            "platform": row["platform"],
        }
        for row in rows
    ]


def entity_citation_aliases(entity_name: str) -> list[str]:
    name = str(entity_name or "").strip()
    if not name:
        return []
    aliases = [name]
    compact = re.sub(r"[\s._-]+", "", name)
    if compact and compact != name:
        aliases.append(compact)
    spaced = re.sub(r"[\s._-]+", " ", name).strip()
    if spaced and spaced != name:
        aliases.append(spaced)
    camel_spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).strip()
    if camel_spaced and camel_spaced != name:
        aliases.append(camel_spaced)

    chinese_runs = re.findall(r"[\u4e00-\u9fff]{3,}", name)
    for run in chinese_runs:
        for size in range(min(6, len(run)), 1, -1):
            for index in range(0, len(run) - size + 1):
                aliases.append(run[index : index + size])

    seen: set[str] = set()
    result: list[str] = []
    for alias in aliases:
        cleaned = alias.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result[:12]


def account_evidence(conn: sqlite3.Connection, account_name: str, limit: int = 3) -> list[dict]:
    rows = conn.execute(
        """
        SELECT title, url, platform
        FROM documents
        WHERE account_name = ?
        ORDER BY imported_at DESC, id DESC
        LIMIT ?
        """,
        (account_name, limit),
    ).fetchall()
    return [
        {
            "title": row["title"],
            "url": row["url"],
            "platform": row["platform"],
            "evidence": "article.account_name",
        }
        for row in rows
    ]


def export_graph(conn: sqlite3.Connection, limit: int = 100, include_terms: bool = False) -> dict:
    document_rows = conn.execute(
        """
        SELECT id, title, url, platform, account_name, quality_status
        FROM documents
        ORDER BY imported_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    document_ids = [row["id"] for row in document_rows]
    if not document_ids:
        return {"nodes": [], "edges": [], "note": "No imported documents."}

    placeholders = ",".join("?" for _ in document_ids)
    entity_type_filter = "" if include_terms else "AND e.type != 'term'"
    entity_rows = conn.execute(
        f"""
        SELECT DISTINCT e.id, e.normalized_name, e.name, e.type
        FROM entities e
        JOIN document_entities de ON de.entity_id = e.id
        WHERE de.document_id IN ({placeholders})
          {entity_type_filter}
        ORDER BY e.name ASC
        """,
        document_ids,
    ).fetchall()
    document_entity_rows = conn.execute(
        f"""
        SELECT de.document_id, e.normalized_name, de.role, de.confidence, de.evidence
        FROM document_entities de
        JOIN entities e ON e.id = de.entity_id
        WHERE de.document_id IN ({placeholders})
          {entity_type_filter}
        ORDER BY de.document_id ASC, e.name ASC
        """,
        document_ids,
    ).fetchall()
    relationship_rows = conn.execute(
        f"""
        SELECT document_id, predicate, object, confidence, evidence
        FROM relationships
        WHERE document_id IN ({placeholders})
        ORDER BY document_id ASC, predicate ASC, object ASC
        """,
        document_ids,
    ).fetchall()

    nodes = [
        {
            "id": f"document:{row['id']}",
            "kind": "document",
            "label": row["title"] or row["url"],
            "url": row["url"],
            "platform": row["platform"],
            "account_name": row["account_name"],
            "quality_status": row["quality_status"],
        }
        for row in document_rows
    ]
    known_entities = {row["normalized_name"] for row in entity_rows}
    nodes.extend(
        {
            "id": f"entity:{row['normalized_name']}",
            "kind": "entity",
            "label": row["name"],
            "entity_type": row["type"],
        }
        for row in entity_rows
    )

    literal_nodes: dict[str, dict] = {}
    edges = [
        {
            "source": f"document:{row['document_id']}",
            "target": f"entity:{row['normalized_name']}",
            "predicate": row["role"],
            "confidence": row["confidence"],
            "evidence": row["evidence"],
        }
        for row in document_entity_rows
    ]
    for row in relationship_rows:
        if not include_terms and row["predicate"] == "mentions":
            continue
        object_key = normalize_graph_key(row["object"])
        if object_key in known_entities:
            target = f"entity:{object_key}"
        else:
            target = f"literal:{object_key}"
            literal_nodes[target] = {
                "id": target,
                "kind": "literal",
                "label": row["object"],
            }
        edges.append(
            {
                "source": f"document:{row['document_id']}",
                "target": target,
                "predicate": row["predicate"],
                "confidence": row["confidence"],
                "evidence": row["evidence"],
            }
        )
    nodes.extend(literal_nodes.values())
    return {
        "nodes": nodes,
        "edges": edges,
        "include_terms": include_terms,
        "note": "Conservative graph export from imported documents, extracted entities, and relationships.",
    }


def dump_graph_csv(conn: sqlite3.Connection, out_dir: Path, limit: int = 100, include_terms: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    graph = export_graph(conn, limit, include_terms)
    nodes_path = out_dir / "nodes.csv"
    edges_path = out_dir / "edges.csv"
    node_fields = [
        "id",
        "kind",
        "label",
        "entity_type",
        "url",
        "platform",
        "account_name",
        "quality_status",
    ]
    edge_fields = ["source", "target", "predicate", "confidence", "evidence"]
    write_csv_rows(nodes_path, node_fields, graph.get("nodes", []))
    write_csv_rows(edges_path, edge_fields, graph.get("edges", []))
    files = ["nodes.csv", "edges.csv"]
    manifest = {
        "project": "Link2Context",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "format": "graph-csv",
        "include_terms": include_terms,
        "limit": limit,
        "files": files,
        "row_counts": {
            "nodes.csv": len(graph.get("nodes", [])),
            "edges.csv": len(graph.get("edges", [])),
        },
        "file_details": {
            file_name: export_file_detail(out_dir / file_name)
            for file_name in files
        },
        "note": "CSV graph export for graph databases, Gephi, or other external graph tools.",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_graph_csv(path: Path) -> dict:
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return {
            "path": str(path),
            "ok": False,
            "errors": ["manifest.json is missing"],
            "files": {},
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    files: dict[str, dict] = {}
    expected_files = manifest.get("files", [])
    details = manifest.get("file_details", {})
    row_counts = manifest.get("row_counts", {})
    if manifest.get("format") != "graph-csv":
        errors.append("manifest format is not graph-csv")
    for file_name in expected_files:
        file_path = path / file_name
        if not file_path.exists():
            errors.append(f"{file_name} is missing")
            files[file_name] = {"ok": False, "error": "missing"}
            continue
        actual = export_file_detail(file_path)
        expected = details.get(file_name)
        actual_rows = count_csv_data_rows(file_path)
        expected_rows = row_counts.get(file_name)
        file_errors = []
        if expected is None:
            file_errors.append("missing_detail")
            errors.append(f"{file_name} has no manifest detail")
        elif actual != expected:
            file_errors.append("detail_mismatch")
            errors.append(f"{file_name} does not match manifest detail")
        if expected_rows is None:
            file_errors.append("missing_row_count")
            errors.append(f"{file_name} has no manifest row count")
        elif actual_rows != expected_rows:
            file_errors.append("row_count_mismatch")
            errors.append(f"{file_name} row count does not match manifest")
        files[file_name] = {
            "ok": not file_errors,
            "expected": expected,
            "actual": actual,
            "expected_rows": expected_rows,
            "actual_rows": actual_rows,
            "errors": file_errors,
        }
    extra_files = sorted(
        file.name
        for file in path.iterdir()
        if file.is_file() and file.name != "manifest.json" and file.name not in expected_files
    )
    return {
        "path": str(path),
        "ok": not errors,
        "errors": errors,
        "extra_files": extra_files,
        "files": files,
        "manifest": {
            "project": manifest.get("project"),
            "exported_at": manifest.get("exported_at"),
            "format": manifest.get("format"),
            "include_terms": manifest.get("include_terms"),
            "limit": manifest.get("limit"),
        },
    }


def count_csv_data_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            next(reader)
        except StopIteration:
            return 0
        return sum(1 for _row in reader)


def render_verify_graph_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Graph CSV Verification",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        "",
    ]
    if report.get("errors"):
        parts.extend(["## Errors", ""])
        for error in report["errors"]:
            parts.append(f"- {error}")
        parts.append("")
    if report.get("extra_files"):
        parts.extend(["## Extra Files", ""])
        for file_name in report["extra_files"]:
            parts.append(f"- {file_name}")
        parts.append("")
    if report.get("files"):
        parts.extend(["## Files", ""])
        for file_name, detail in report["files"].items():
            marker = "ok" if detail.get("ok") else "fail"
            parts.append(
                f"- {marker} {file_name}: "
                f"{detail.get('actual_rows')} row(s)"
            )
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def dump_neo4j_cypher(conn: sqlite3.Connection, out_path: Path, limit: int = 100, include_terms: bool = False) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    graph = export_graph(conn, limit, include_terms)
    content = render_neo4j_cypher(graph)
    out_path.write_text(content, encoding="utf-8")
    manifest = {
        "path": str(out_path),
        "format": "neo4j-cypher",
        "include_terms": include_terms,
        "limit": limit,
        "nodes": len(graph.get("nodes", [])),
        "edges": len(graph.get("edges", [])),
        "file_detail": export_file_detail(out_path),
        "manifest_path": str(neo4j_manifest_path(out_path)),
        "note": "Neo4j Cypher import script generated from the current Link2Context graph export.",
    }
    neo4j_manifest_path(out_path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_neo4j_cypher(path: Path) -> dict:
    if not path.exists():
        return {
            "path": str(path),
            "ok": False,
            "errors": ["cypher file is missing"],
            "manifest": None,
            "counts": {},
        }
    content = path.read_text(encoding="utf-8")
    errors: list[str] = []
    actual_detail = export_file_detail(path)
    counts = count_neo4j_cypher_statements(content)
    if actual_detail["size_bytes"] == 0:
        errors.append("cypher file is empty")
    if "CREATE CONSTRAINT link2context_node_id" not in content:
        errors.append("node id constraint is missing")
    if counts["nodes"] == 0 and counts["relationships"] == 0:
        errors.append("cypher file has no node or relationship MERGE statements")

    manifest = None
    sidecar = neo4j_manifest_path(path)
    if sidecar.exists():
        manifest = json.loads(sidecar.read_text(encoding="utf-8"))
        if manifest.get("format") != "neo4j-cypher":
            errors.append("manifest format is not neo4j-cypher")
        expected_detail = manifest.get("file_detail")
        if expected_detail != actual_detail:
            errors.append("cypher file does not match manifest detail")
        if manifest.get("nodes") != counts["nodes"]:
            errors.append("node count does not match manifest")
        if manifest.get("edges") != counts["relationships"]:
            errors.append("relationship count does not match manifest")
    return {
        "path": str(path),
        "ok": not errors,
        "errors": errors,
        "manifest_path": str(sidecar),
        "manifest": manifest,
        "file_detail": actual_detail,
        "counts": counts,
    }


def neo4j_manifest_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.manifest.json")


def count_neo4j_cypher_statements(content: str) -> dict:
    return {
        "nodes": len(re.findall(r"^MERGE \(n:Link2ContextNode:", content, flags=re.MULTILINE)),
        "relationships": len(re.findall(r"^MERGE \(source\)-\[r:", content, flags=re.MULTILINE)),
        "constraints": len(re.findall(r"^CREATE CONSTRAINT ", content, flags=re.MULTILINE)),
    }


def render_verify_neo4j_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Neo4j Verification",
        "",
        f"- Path: {report.get('path')}",
        f"- OK: {str(report.get('ok')).lower()}",
        "",
    ]
    if report.get("errors"):
        parts.extend(["## Errors", ""])
        for error in report["errors"]:
            parts.append(f"- {error}")
        parts.append("")
    counts = report.get("counts", {})
    if counts:
        parts.extend(["## Counts", ""])
        parts.append(f"- Nodes: {counts.get('nodes', 0)}")
        parts.append(f"- Relationships: {counts.get('relationships', 0)}")
        parts.append(f"- Constraints: {counts.get('constraints', 0)}")
        parts.append("")
    manifest = report.get("manifest")
    if manifest:
        parts.extend(["## Manifest", ""])
        parts.append(f"- Path: {report.get('manifest_path')}")
        parts.append(f"- Nodes: {manifest.get('nodes', 0)}")
        parts.append(f"- Edges: {manifest.get('edges', 0)}")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def render_neo4j_cypher(graph: dict) -> str:
    lines = [
        "// Link2Context Neo4j import script",
        "CREATE CONSTRAINT link2context_node_id IF NOT EXISTS FOR (n:Link2ContextNode) REQUIRE n.id IS UNIQUE;",
        "",
    ]
    for node in graph.get("nodes", []):
        label = neo4j_node_label(node)
        props = {
            "id": node.get("id"),
            "kind": node.get("kind"),
            "label": node.get("label"),
            "entity_type": node.get("entity_type"),
            "url": node.get("url"),
            "platform": node.get("platform"),
            "account_name": node.get("account_name"),
            "quality_status": node.get("quality_status"),
        }
        lines.append(f"MERGE (n:Link2ContextNode:{label} {{id: {cypher_value(node.get('id'))}}})")
        lines.append(f"SET n += {cypher_map(props)};")
    if graph.get("nodes"):
        lines.append("")
    for edge in graph.get("edges", []):
        relationship_type = cypher_relationship_type(edge.get("predicate"))
        props = {
            "predicate": edge.get("predicate"),
            "confidence": edge.get("confidence"),
            "evidence": edge.get("evidence"),
        }
        lines.append(f"MATCH (source:Link2ContextNode {{id: {cypher_value(edge.get('source'))}}})")
        lines.append(f"MATCH (target:Link2ContextNode {{id: {cypher_value(edge.get('target'))}}})")
        lines.append(f"MERGE (source)-[r:{relationship_type}]->(target)")
        lines.append(f"SET r += {cypher_map(props)};")
    return "\n".join(lines).strip() + "\n"


def neo4j_node_label(node: dict) -> str:
    kind = str(node.get("kind") or "node")
    if kind == "document":
        return "Document"
    if kind == "entity":
        return "Entity"
    if kind == "literal":
        return "Literal"
    return "Node"


def cypher_relationship_type(value: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "RELATED")).strip("_").upper()
    if not cleaned:
        cleaned = "RELATED"
    if cleaned[0].isdigit():
        cleaned = f"R_{cleaned}"
    return cleaned


def cypher_map(values: dict) -> str:
    items = [
        f"{key}: {cypher_value(value)}"
        for key, value in values.items()
        if value is not None
    ]
    return "{" + ", ".join(items) + "}"


def cypher_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: "" if row.get(field) is None else row.get(field)
                for field in fieldnames
            })


def normalize_graph_key(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def render_graph_mermaid(graph: dict) -> str:
    node_ids = {node["id"]: mermaid_id(node["id"]) for node in graph.get("nodes", [])}
    lines = ["graph LR"]
    for node in graph.get("nodes", []):
        label = mermaid_label(node.get("label") or node["id"])
        shape = ("[", "]") if node.get("kind") == "document" else ("(", ")")
        lines.append(f"  {node_ids[node['id']]}{shape[0]}\"{label}\"{shape[1]}")
    for edge in graph.get("edges", []):
        source = node_ids.get(edge["source"], mermaid_id(edge["source"]))
        target = node_ids.get(edge["target"], mermaid_id(edge["target"]))
        predicate = mermaid_label(edge.get("predicate") or "related")
        lines.append(f"  {source} -->|\"{predicate}\"| {target}")
    return "\n".join(lines) + "\n"


def mermaid_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"n_{cleaned}"
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned}_{digest}"


def mermaid_label(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value)).strip()
    value = value.replace('"', "'")
    return value[:80]


def stats(conn: sqlite3.Connection) -> dict:
    platform_rows = conn.execute(
        "SELECT platform, COUNT(*) AS count FROM documents GROUP BY platform ORDER BY platform"
    ).fetchall()
    quality_rows = conn.execute(
        "SELECT quality_status, COUNT(*) AS count FROM documents GROUP BY quality_status ORDER BY quality_status"
    ).fetchall()
    totals = conn.execute(
        """
        SELECT
          COUNT(*) AS documents,
          (SELECT COUNT(*) FROM media WHERE kind='image') AS images,
          (SELECT COUNT(*) FROM media WHERE kind='video') AS videos,
          (SELECT COUNT(*) FROM citations) AS citations,
          (SELECT COUNT(*) FROM entities) AS entities,
          (SELECT COUNT(*) FROM relationships) AS relationships
        FROM documents
        """
    ).fetchone()
    return {
        "documents": totals["documents"],
        "images": totals["images"],
        "videos": totals["videos"],
        "citations": totals["citations"],
        "entities": totals["entities"],
        "relationships": totals["relationships"],
        "by_platform": {row["platform"]: row["count"] for row in platform_rows},
        "by_quality": {row["quality_status"]: row["count"] for row in quality_rows},
    }


if __name__ == "__main__":
    main()

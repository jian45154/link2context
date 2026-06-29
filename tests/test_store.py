import csv
import json
import hashlib
import sqlite3
import sys
from pathlib import Path

from link2context import __version__
from link2context.graph import extract_graph
import link2context.store as store_cli
from link2context.store import (
    action_plan,
    add_document_tags,
    add_document_note,
    auto_queue_next_commands,
    agent_task_commands,
    agent_tasks,
    agent_task_report,
    agent_query,
    annotations_report,
    apply_media_text,
    apply_media_fixes,
    cache_media,
    citation_lookup,
    citation_ref_sort_key,
    clusters_report,
    coverage_report,
    curate_report,
    digest_report,
    document_timeline,
    duplicate_report,
    dump_docs_markdown,
    dump_jsonl,
    dump_graph_csv,
    dump_neo4j_cypher,
    evidence_report,
    explain_entity,
    external_brain_brief,
    export_media_fixes,
    export_agent_handoff,
    export_graph,
    export_snapshot,
    get_document,
    handoff_hot_commands,
    import_context,
    import_snapshot,
    inbox_report,
    ingest_paths,
    init_db,
    import_jsonl_dump,
    interest_profile,
    list_entities,
    mark_document_status,
    media_inventory,
    media_pipeline_status,
    media_text_presets_report,
    media_queue,
    media_cache_action_command,
    media_cache_action_detail,
    media_cache_action_title,
    media_process_action_command,
    media_process_action_detail,
    media_text_command,
    prepare_media_model,
    mermaid_id,
    questions_report,
    query_terms,
    quality_report,
    recent_documents,
    reindex_media_text,
    render_action_plan_markdown,
    render_agent_tasks_markdown,
    render_annotations_markdown,
    render_apply_media_fixes_markdown,
    render_apply_media_text_markdown,
    render_brief_markdown,
    render_cache_media_markdown,
    render_citation_markdown,
    render_clusters_markdown,
    render_coverage_markdown,
    render_curate_markdown,
    render_document_markdown,
    render_duplicate_markdown,
    render_digest_markdown,
    render_evidence_markdown,
    render_entity_explanation_markdown,
    render_export_media_fixes_markdown,
    render_graph_mermaid,
    render_handoff_markdown,
    render_hot_command_commands,
    render_hot_command_jsonl,
    render_ingest_markdown,
    render_neo4j_cypher,
    render_verify_neo4j_markdown,
    render_import_jsonl_markdown,
    render_import_snapshot_markdown,
    render_inbox_markdown,
    render_media_markdown,
    render_media_pipeline_markdown,
    render_media_text_presets_markdown,
    render_media_queue_markdown,
    render_mark_result_markdown,
    render_note_result_markdown,
    render_notes_markdown,
    render_prepare_media_model_markdown,
    render_profile_markdown,
    render_quality_markdown,
    render_questions_markdown,
    render_query_markdown,
    render_related_markdown,
    render_relations_markdown,
    render_reindex_media_text_markdown,
    render_review_markdown,
    render_run_media_text_markdown,
    render_run_auto_queue_markdown,
    render_run_auto_queue_next_markdown,
    render_sources_markdown,
    render_statuses_markdown,
    render_starter_queries_markdown,
    render_tag_result_markdown,
    render_tags_markdown,
    render_timeline_markdown,
    render_topics_markdown,
    render_verify_auto_queue_markdown,
    render_verify_auto_queue_next_markdown,
    render_verify_export_markdown,
    render_verify_docs_markdown,
    render_verify_graph_markdown,
    render_verify_jsonl_markdown,
    render_verify_media_fixes_markdown,
    render_verify_media_text_markdown,
    render_verify_snapshot_markdown,
    related_documents,
    relations_report,
    review_report,
    run_auto_queue,
    run_auto_queue_next,
    resolve_media_text_runner,
    run_media_text,
    search,
    source_report,
    stats,
    starter_queries,
    status_report,
    store_doctor,
    notes_report,
    tag_report,
    verify_export_bundle,
    verify_auto_queue,
    verify_auto_queue_next,
    verify_docs_markdown,
    verify_graph_csv,
    verify_neo4j_cypher,
    verify_jsonl_dump,
    verify_media_fixes,
    verify_media_text,
    verify_snapshot,
    topics_report,
    render_doctor_markdown,
)
from link2context.wechat import build_wechat_context


def test_store_cli_version_uses_package_version(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["link2context-store", "--version"])

    try:
        store_cli.parse_args()
    except SystemExit as exc:
        assert exc.code == 0
    else:  # pragma: no cover - argparse version always exits.
        raise AssertionError("--version did not exit")

    assert capsys.readouterr().out.strip() == f"link2context-store {__version__}"


def test_store_cli_help_lists_core_commands(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["link2context-store", "--help"])

    try:
        store_cli.parse_args()
    except SystemExit as exc:
        assert exc.code == 0
    else:  # pragma: no cover - argparse help always exits.
        raise AssertionError("--help did not exit")

    output = capsys.readouterr().out
    assert "Import Link2Context context.json files into a local SQLite knowledge store." in output
    assert "ingest" in output
    assert "media-pipeline" in output
    assert "verify-auto-queue-next" in output


def test_import_context_populates_store_counts() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)

    document_id = import_context(conn, context)

    assert document_id == 1
    assert stats(conn) == {
        "documents": 1,
        "images": 1,
        "videos": 1,
        "citations": len(context["agent_package"]["citations"]),
        "entities": len(extract_graph(context)["entities"]),
        "relationships": len(extract_graph(context)["relations"]),
        "by_platform": {"wechat_official_account": 1},
        "by_quality": {"ok": 1},
    }


def test_import_context_updates_existing_document() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["media"]["images"][0]["local_path"] = "outputs/media/image-1.png"
    import_context(conn, context)
    conn.execute(
        """
        UPDATE media
        SET cache_status = ?, cache_error = ?, cache_sha256 = ?, cache_bytes = ?, cache_checked_at = ?
        WHERE document_id = ? AND media_index = ?
        """,
        ("cached", None, "abc123", 42, "2026-06-29T00:00:00+00:00", 1, 1),
    )
    add_document_tags(conn, "1", ["知识管理"])
    add_document_note(conn, "1", "这是我的个人判断。")
    mark_document_status(conn, "1", "later", "今晚处理")
    add_document_note(conn, "1", "这是我的个人判断。")

    context["article"]["title"] = "更新后的标题"
    document_id = import_context(conn, context)

    row = conn.execute("SELECT title FROM documents WHERE id = ?", (document_id,)).fetchone()
    assert row["title"] == "更新后的标题"
    assert stats(conn)["documents"] == 1


def test_import_context_accepts_null_citations_from_old_outputs() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["agent_package"]["citations"] = None

    import_context(conn, context)

    assert stats(conn)["citations"] == 0


def test_media_inventory_lists_media_with_document_context() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["media"]["images"][0]["local_path"] = "outputs/media/image-1.png"
    import_context(conn, context)

    inventory = media_inventory(conn, kind="image", status="not_processed", limit=10)

    assert inventory["filters"] == {"kind": "image", "status": "not_processed", "limit": 10}
    assert inventory["summary"] == [
        {"kind": "image", "status": "not_processed", "count": 1}
    ]
    assert inventory["items"][0]["kind"] == "image"
    assert inventory["items"][0]["local_path"] == "outputs/media/image-1.png"
    assert inventory["items"][0]["document"]["id"] == 1
    assert inventory["items"][0]["document"]["title"] == "示例公众号文章"
    assert inventory["note"].startswith("Media status")


def test_media_queue_builds_ocr_asr_tasks_from_unprocessed_media() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["media"]["images"][0]["local_path"] = "outputs/media/image-1.png"
    import_context(conn, context)

    queue = media_queue(conn, kind="image", status="not_processed", limit=10)

    assert queue["filters"] == {
        "kind": "image",
        "status": "not_processed",
        "limit": 10,
        "low_confidence": False,
    }
    assert queue["items"][0]["task"] == "ocr"
    assert queue["items"][0]["priority"] == 3
    assert queue["items"][0]["reason"] == "needs_text"
    assert queue["items"][0]["input_url"] == "https://example.com/image-one.jpg"
    assert queue["items"][0]["input_path"] == "outputs/media/image-1.png"
    assert queue["items"][0]["input_source"] == "outputs/media/image-1.png"
    assert queue["items"][0]["document"]["id"] == 1
    assert queue["items"][0]["output_hint"] == {
        "document_id": 1,
        "media_index": 1,
        "field": "text",
    }
    assert queue["items"][0]["result_template"] == {
        "kind": "image",
        "output_hint": {"document_id": 1, "media_index": 1},
        "text": "",
        "model": "",
        "language": "",
        "confidence": None,
    }


def test_cache_media_downloads_and_updates_local_path(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)

    def fake_fetcher(url: str, timeout: int) -> tuple[bytes, str | None]:
        assert url == "https://example.com/image-one.jpg"
        assert timeout == 7
        return b"image bytes", "image/jpeg"

    report = cache_media(
        conn,
        kind="image",
        status="not_processed",
        limit=10,
        out_dir=tmp_path,
        timeout=7,
        fetcher=fake_fetcher,
    )

    assert report["summary"] == {"candidates": 1, "cached": 1, "skipped": 0}
    assert report["cached"][0]["sha256"] == hashlib.sha256(b"image bytes").hexdigest()
    assert report["retry"]["failed"] == 0
    cached_path = Path(report["cached"][0]["local_path"])
    assert cached_path.exists()
    assert cached_path.read_bytes() == b"image bytes"
    assert cached_path.suffix == ".jpg"
    inventory = media_inventory(conn, kind="image", status="not_processed", limit=10)
    assert inventory["items"][0]["cache_status"] == "cached"
    assert inventory["items"][0]["cache_error"] is None
    assert inventory["items"][0]["cache_sha256"] == hashlib.sha256(b"image bytes").hexdigest()
    assert inventory["items"][0]["cache_bytes"] == len(b"image bytes")
    assert inventory["items"][0]["cache_checked_at"]
    queue = media_queue(conn, kind="image", status="not_processed", limit=10)
    assert queue["items"][0]["input_path"] == str(cached_path)
    assert queue["items"][0]["input_source"] == str(cached_path)
    markdown = render_cache_media_markdown(report)
    assert "# Link2Context Cache Media" in markdown
    assert "Cached: 1" in markdown
    assert "sha256=" in markdown


def test_cache_media_skips_existing_local_path_without_overwrite(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["media"]["images"][0]["local_path"] = "outputs/media/existing.jpg"
    import_context(conn, context)

    def failing_fetcher(url: str, timeout: int) -> tuple[bytes, str | None]:
        raise AssertionError("fetcher should not be called")

    report = cache_media(conn, kind="image", status="not_processed", limit=10, out_dir=tmp_path, fetcher=failing_fetcher)

    assert report["summary"] == {"candidates": 1, "cached": 0, "skipped": 1}
    assert report["skipped"][0]["reason"] == "already_cached"
    assert report["retry"]["failed"] == 0


def test_cache_media_reports_failed_download_retry_command(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)

    def failing_fetcher(url: str, timeout: int) -> tuple[bytes, str | None]:
        raise RuntimeError("network down")

    report = cache_media(
        conn,
        kind="image",
        status="not_processed",
        limit=10,
        out_dir=tmp_path,
        timeout=9,
        fetcher=failing_fetcher,
    )

    assert report["summary"] == {"candidates": 1, "cached": 0, "skipped": 1}
    assert report["skipped"][0]["reason"] == "download_failed"
    assert report["skipped"][0]["error"] == "network down"
    assert report["retry"]["failed"] == 1
    assert "cache-media --kind image" in report["retry"]["command"]
    assert "--timeout 9" in report["retry"]["command"]
    inventory = media_inventory(conn, kind="image", status="not_processed", limit=10)
    assert inventory["items"][0]["cache_status"] == "download_failed"
    assert inventory["items"][0]["cache_error"] == "network down"
    plan = action_plan(conn, limit=10)
    cache_action = next(
        action
        for action in plan["actions"]
        if action["kind"] == "media_cache" and "cache_status=download_failed" in action["detail"]
    )
    assert cache_action["title"].startswith("Retry media cache download")
    assert "export-media-fixes" in cache_action["command"]
    assert "--cache-status download_failed" in cache_action["command"]
    assert "retry_mode=retry_download" in cache_action["detail"]
    assert "cache_status=download_failed" in cache_action["detail"]
    assert "verify-media-fixes outputs/media-fixes-image-download_failed.jsonl" in cache_action["detail"]
    assert "apply-media-fixes outputs/media-fixes-image-download_failed.jsonl" in cache_action["detail"]
    assert "cache_error=network down" in cache_action["detail"]
    retry_tasks = agent_task_report(conn, limit=10, kind="media_cache", retry_mode="retry_download")
    assert retry_tasks["filters"]["retry_mode"] == "retry_download"
    assert retry_tasks["tasks"]
    assert all(task.get("retry_mode") == "retry_download" for task in retry_tasks["tasks"])
    failed_tasks = agent_task_report(conn, limit=10, kind="media_cache", cache_status="download_failed")
    assert failed_tasks["filters"]["cache_status"] == "download_failed"
    assert failed_tasks["tasks"]
    assert all(task.get("cache_status") == "download_failed" for task in failed_tasks["tasks"])
    markdown = render_cache_media_markdown(report)
    assert "## Retry" in markdown
    assert "Failed items: 1" in markdown


def test_export_media_fixes_writes_editable_failed_manifest(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    conn.execute(
        """
        UPDATE media
        SET cache_status = ?, cache_error = ?
        WHERE document_id = ? AND media_index = ?
        """,
        ("download_failed", "network down", 1, 1),
    )

    out_path = tmp_path / "media-fixes.jsonl"
    report = export_media_fixes(conn, out_path, kind="image", cache_status="failed", limit=10)

    assert report["exported"] == 1
    row = json.loads(out_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["media_id"] == 1
    assert row["cache_status"] == "download_failed"
    assert row["current_url"] == "https://example.com/image-one.jpg"
    assert row["fixed_url"] == ""
    assert row["fixed_local_path"] == ""
    markdown = render_export_media_fixes_markdown(report)
    assert "# Link2Context Media Fix Export" in markdown
    assert "media_id=1 image[1]" in markdown


def test_apply_media_fixes_updates_fixed_url_and_local_path(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    local_file = tmp_path / "fixed.jpg"
    local_file.write_bytes(b"fixed image")
    fixes_path = tmp_path / "media-fixes.jsonl"
    fixes_path.write_text(
        json.dumps(
            {
                "media_id": 1,
                "fixed_url": "https://example.com/fixed.jpg",
                "fixed_local_path": str(local_file),
            },
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps({"media_id": 1, "fixed_url": "", "fixed_local_path": ""}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    report = apply_media_fixes(conn, fixes_path)

    assert report["summary"] == {"rows": 2, "applied": 1, "skipped": 1}
    row = conn.execute(
        "SELECT url, local_path, cache_status, cache_error, cache_sha256, cache_bytes FROM media WHERE id = 1"
    ).fetchone()
    assert row["url"] == "https://example.com/fixed.jpg"
    assert row["local_path"] == str(local_file)
    assert row["cache_status"] == "manual_local_path"
    assert row["cache_error"] is None
    assert row["cache_sha256"] == hashlib.sha256(b"fixed image").hexdigest()
    assert row["cache_bytes"] == len(b"fixed image")
    assert report["applied"][0]["next_step"] == "queue_media_text"
    assert report["next_commands"] == [
        "python -m link2context.store --db data/link2context.db queue --kind image --status not_processed --format jsonl"
    ]
    markdown = render_apply_media_fixes_markdown(report)
    assert "# Link2Context Media Fix Apply" in markdown
    assert "- OK: true" in markdown
    assert "- Applied: 1" in markdown
    assert "queue --kind image --status not_processed --format jsonl" in markdown


def test_apply_media_fixes_recommends_cache_for_url_only_fix(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    fixes_path = tmp_path / "media-fixes.jsonl"
    fixes_path.write_text(
        json.dumps({"media_id": 1, "fixed_url": "https://example.com/fixed.jpg"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    report = apply_media_fixes(conn, fixes_path)

    assert report["applied"][0]["next_step"] == "cache_media"
    assert report["next_commands"] == [
        "python -m link2context.store --db data/link2context.db cache-media --kind image --status not_processed --out-dir outputs/media-cache"
    ]
    markdown = render_apply_media_fixes_markdown(report)
    assert "cache-media --kind image --status not_processed --out-dir outputs/media-cache" in markdown


def test_apply_media_fixes_refuses_invalid_manifest_without_force(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    fixes_path = tmp_path / "media-fixes.jsonl"
    fixes_path.write_text(
        json.dumps({"media_id": 1, "fixed_url": "notaurl"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    report = apply_media_fixes(conn, fixes_path)

    assert report["ok"] is False
    assert report["summary"] == {"rows": 1, "applied": 0, "skipped": 1}
    row = conn.execute("SELECT url, cache_status FROM media WHERE id = 1").fetchone()
    assert row["url"] == "https://example.com/image-one.jpg"
    assert row["cache_status"] is None
    markdown = render_apply_media_fixes_markdown(report)
    assert "- OK: false" in markdown
    assert "fixed_url is not an http(s) URL" in markdown


def test_apply_media_fixes_force_overrides_verification(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    fixes_path = tmp_path / "media-fixes.jsonl"
    fixes_path.write_text(
        json.dumps({"media_id": 1, "fixed_url": "notaurl"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    report = apply_media_fixes(conn, fixes_path, force=True)

    assert report["ok"] is True
    assert report["forced"] is True
    row = conn.execute("SELECT url, cache_status FROM media WHERE id = 1").fetchone()
    assert row["url"] == "notaurl"
    assert row["cache_status"] == "fix_applied"


def test_verify_media_fixes_accepts_ready_manifest(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    local_file = tmp_path / "fixed.jpg"
    local_file.write_bytes(b"fixed image")
    fixes_path = tmp_path / "media-fixes.jsonl"
    fixes_path.write_text(
        json.dumps({"media_id": 1, "fixed_url": "https://example.com/fixed.jpg", "fixed_local_path": str(local_file)})
        + "\n",
        encoding="utf-8",
    )

    report = verify_media_fixes(conn, fixes_path)

    assert report["ok"] is True
    assert report["rows"] == 1
    assert report["ready_to_apply"] == 1
    assert report["errors"] == []
    markdown = render_verify_media_fixes_markdown(report)
    assert "# Link2Context Media Fix Verification" in markdown
    assert "- OK: true" in markdown
    assert "apply-media-fixes" in markdown


def test_verify_media_fixes_reports_invalid_rows(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    fixes_path = tmp_path / "media-fixes.jsonl"
    fixes_path.write_text(
        "\n".join(
            [
                json.dumps({"media_id": 999, "fixed_url": "notaurl"}),
                json.dumps({"media_id": 1, "fixed_local_path": str(tmp_path / "missing.jpg")}),
                json.dumps({"media_id": 1, "fixed_url": "", "fixed_local_path": ""}),
                "{bad json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = verify_media_fixes(conn, fixes_path)

    assert report["ok"] is False
    assert any("media_id 999 does not exist" in error for error in report["errors"])
    assert any("fixed_url is not an http(s) URL" in error for error in report["errors"])
    assert any("fixed_local_path does not exist" in error for error in report["errors"])
    assert any("invalid JSON" in error for error in report["errors"])
    assert any("apply will skip this row" in warning for warning in report["warnings"])
    markdown = render_verify_media_fixes_markdown(report)
    assert "- OK: false" in markdown
    assert "## Errors" in markdown


def test_media_text_command_expands_queue_fields() -> None:
    item = {
        "task": "ocr",
        "kind": "image",
        "index": 2,
        "input_url": "https://example.com/a.png",
        "input_path": "outputs/media/a.png",
        "input_source": "outputs/media/a.png",
        "reason": "needs_text",
        "output_hint": {"document_id": 7},
        "document": {"id": 7, "title": "示例标题", "url": "https://example.com/doc"},
    }

    command = media_text_command(
        "ocr --url {input_url} --doc {document_id} --index {media_index} --title {document_title}",
        item,
    )

    assert command == "ocr --url https://example.com/a.png --doc 7 --index 2 --title 示例标题"
    assert media_text_command("ocr {input_source}", item) == "ocr outputs/media/a.png"


def test_media_cache_action_labels_cache_failures() -> None:
    item = {
        "kind": "image",
        "index": 1,
        "url": None,
        "cache_status": "missing_url",
        "cache_error": "missing media URL",
        "document": {"id": 7},
    }

    assert media_cache_action_title(item) == "Add media URL before caching image[1] from document [7]"
    command = media_cache_action_command(item)
    assert "export-media-fixes" in command
    assert "--cache-status missing_url" in command
    detail = media_cache_action_detail(item)
    assert "retry_mode=manual_url_required" in detail
    assert "cache_status=missing_url" in detail
    assert "verify-media-fixes outputs/media-fixes-image-missing_url.jsonl" in detail
    assert "apply-media-fixes outputs/media-fixes-image-missing_url.jsonl" in detail
    assert "cache_error=missing media URL" in detail


def test_media_process_action_queues_cached_media() -> None:
    item = {
        "kind": "image",
        "status": "not_processed",
        "url": "https://example.com/image.jpg",
        "local_path": "outputs/media-cache/image.jpg",
    }

    assert media_process_action_command(item) == (
        "python -m link2context.store --db data/link2context.db queue "
        "--kind image --status not_processed --format jsonl"
    )
    detail = media_process_action_detail(item)
    assert "local_path=outputs/media-cache/image.jpg" in detail
    assert "next_step=queue_media_text" in detail


def test_resolve_media_text_runner_supports_presets() -> None:
    tesseract = resolve_media_text_runner(preset="tesseract")

    assert tesseract["preset"] == "tesseract"
    assert tesseract["model"] == "tesseract"
    assert tesseract["language"] == "chi_sim+eng"
    assert "{input_source}" in tesseract["command_template"]

    sona = resolve_media_text_runner(
        preset="sona",
        preset_model="models/ggml-small.bin",
        tool_path="sona.exe",
        language="en",
    )
    assert sona["preset"] == "sona"
    assert sona["model"] == "sona"
    assert sona["format_values"]["preset_model"] == "models/ggml-small.bin"
    assert sona["format_values"]["tool_path"] == "sona.exe"
    assert sona["format_values"]["language"] == "en"


def test_resolve_media_text_runner_rejects_invalid_runner_config() -> None:
    try:
        resolve_media_text_runner()
    except ValueError as exc:
        assert "command_template is required" in str(exc)
    else:
        raise AssertionError("missing command_template should fail")

    try:
        resolve_media_text_runner(preset="sona")
    except ValueError as exc:
        assert "preset_model is required" in str(exc)
    else:
        raise AssertionError("sona without preset_model should fail")

    try:
        resolve_media_text_runner(preset="tesseract", command_template="ocr {input_url}")
    except ValueError as exc:
        assert "either preset or command_template" in str(exc)
    else:
        raise AssertionError("preset and command_template together should fail")


def test_media_text_presets_report_lists_templates_and_examples() -> None:
    report = media_text_presets_report()
    names = {preset["name"] for preset in report["presets"]}
    sona = next(preset for preset in report["presets"] if preset["name"] == "sona")
    tesseract = next(preset for preset in report["presets"] if preset["name"] == "tesseract")

    assert names == {"tesseract", "sona"}
    assert sona["requires_model"] is True
    assert sona["tool_path"] == "sona"
    assert sona["model_available"] is False
    assert sona["ready"] is False
    assert "--preset sona" in sona["example"]
    assert '--preset-model "models/ggml-small.bin"' in sona["example"]
    assert "--apply --reindex" in sona["example"]
    assert tesseract["kind"] == "image"
    assert "{input_source}" in tesseract["template"]
    assert set(report["available"] + report["missing"]) == names


def test_media_text_presets_report_validates_model_and_tool_overrides(tmp_path: Path) -> None:
    model_path = tmp_path / "ggml-small.bin"
    tool_path = tmp_path / "sona.exe"
    model_path.write_bytes(b"model")
    tool_path.write_bytes(b"tool")

    report = media_text_presets_report(preset_model=str(model_path), tool_path=str(tool_path))
    sona = next(preset for preset in report["presets"] if preset["name"] == "sona")
    tesseract = next(preset for preset in report["presets"] if preset["name"] == "tesseract")

    assert sona["available"] is True
    assert sona["ready"] is True
    assert sona["model_available"] is True
    assert sona["model_resolved_path"] == str(model_path)
    assert sona["resolved_path"] == str(tool_path)
    assert f'--preset-model "{model_path}"' in sona["example"]
    assert f'--tool-path "{tool_path}"' in sona["example"]
    assert tesseract["executable"] == "tesseract"
    assert f'--tool-path "{tool_path}"' not in tesseract["example"]
    assert "sona" in report["ready"]


def test_media_text_presets_report_discovers_sona_models(tmp_path: Path) -> None:
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    model_path = model_dir / "ggml-small.bin"
    ignored_path = model_dir / "notes.bin"
    tool_path = tmp_path / "sona.exe"
    model_path.write_bytes(b"model")
    ignored_path.write_bytes(b"not a model")
    tool_path.write_bytes(b"tool")

    report = media_text_presets_report(model_dirs=[model_dir], tool_path=str(tool_path))
    sona = next(preset for preset in report["presets"] if preset["name"] == "sona")

    assert report["discovered_models"] == [
        {"path": str(model_path), "name": "ggml-small.bin", "size_bytes": 5}
    ]
    assert sona["preset_model"] == str(model_path)
    assert sona["model_available"] is True
    assert sona["ready"] is True
    assert f'--preset-model "{model_path}"' in sona["example"]


def test_render_media_text_presets_markdown_includes_status_and_examples() -> None:
    markdown = render_media_text_presets_markdown(
        {
            "available": ["sona"],
            "ready": [],
            "missing": ["tesseract"],
            "discovered_models": [
                {"path": "models/ggml-small.bin", "name": "ggml-small.bin", "size_bytes": 5}
            ],
            "presets": [
                {
                    "name": "sona",
                    "available": True,
                    "ready": False,
                    "kind": "video",
                    "language": "zh",
                    "requires_model": True,
                    "preset_model": "models/missing.bin",
                    "model_available": False,
                    "model_resolved_path": None,
                    "model_note": "preset_model path does not exist.",
                    "executable": "sona.exe",
                    "resolved_path": "C:/Tools/sona.exe",
                    "description": "Transcribe media.",
                    "template": '"sona.exe" transcribe "{preset_model}" "{input_source}" --language {language}',
                    "example": "python -m link2context.store run-media-text --preset sona --apply --reindex",
                }
            ],
            "note": "Presets only define command templates.",
        }
    )

    assert "# Link2Context Media Text Presets" in markdown
    assert "- Status: available" in markdown
    assert "- Requires model: true" in markdown
    assert "- Ready: false" in markdown
    assert "- Discovered models: 1" in markdown
    assert "`models/ggml-small.bin`" in markdown
    assert "- Model available: false" in markdown
    assert "preset_model path does not exist" in markdown
    assert "`python -m link2context.store run-media-text --preset sona --apply --reindex`" in markdown


def test_prepare_media_model_dry_run_does_not_write(tmp_path: Path) -> None:
    out_path = tmp_path / "models" / "ggml-small.bin"

    report = prepare_media_model("https://example.com/model.bin", out_path)

    assert report["ok"] is True
    assert report["execute"] is False
    assert report["downloaded"] is False
    assert not out_path.exists()
    assert "Dry run" in report["note"]


def test_prepare_media_model_dry_run_verifies_existing_file(tmp_path: Path) -> None:
    data = b"existing model"
    expected = hashlib.sha256(data).hexdigest()
    out_path = tmp_path / "models" / "ggml-small.bin"
    out_path.parent.mkdir()
    out_path.write_bytes(data)

    report = prepare_media_model("https://example.com/model.bin", out_path, sha256=expected)

    assert report["ok"] is True
    assert report["execute"] is False
    assert report["downloaded"] is False
    assert report["bytes"] == len(data)
    assert report["sha256"] == expected
    assert report["verified"] is True
    assert out_path.read_bytes() == data


def test_prepare_media_model_dry_run_reports_existing_checksum_mismatch(tmp_path: Path) -> None:
    out_path = tmp_path / "models" / "ggml-small.bin"
    out_path.parent.mkdir()
    out_path.write_bytes(b"existing model")

    report = prepare_media_model("https://example.com/model.bin", out_path, sha256="0" * 64)

    assert report["ok"] is False
    assert report["execute"] is False
    assert report["downloaded"] is False
    assert report["verified"] is False
    assert "does not match" in report["note"]
    assert out_path.read_bytes() == b"existing model"


def test_prepare_media_model_downloads_and_verifies(tmp_path: Path) -> None:
    data = b"model bytes"
    expected = hashlib.sha256(data).hexdigest()
    out_path = tmp_path / "models" / "ggml-small.bin"

    report = prepare_media_model(
        "https://example.com/model.bin",
        out_path,
        sha256=expected,
        execute=True,
        downloader=lambda url, timeout: data,
    )

    assert report["ok"] is True
    assert report["downloaded"] is True
    assert report["verified"] is True
    assert report["bytes"] == len(data)
    assert report["sha256"] == expected
    assert out_path.read_bytes() == data


def test_prepare_media_model_rejects_checksum_mismatch(tmp_path: Path) -> None:
    out_path = tmp_path / "models" / "ggml-small.bin"

    report = prepare_media_model(
        "https://example.com/model.bin",
        out_path,
        sha256="0" * 64,
        execute=True,
        downloader=lambda url, timeout: b"bad model",
    )

    assert report["ok"] is False
    assert report["downloaded"] is False
    assert not out_path.exists()
    assert "does not match" in report["note"]


def test_render_prepare_media_model_markdown_includes_verification() -> None:
    markdown = render_prepare_media_model_markdown(
        {
            "ok": True,
            "execute": True,
            "path": "models/ggml-small.bin",
            "exists_before": False,
            "downloaded": True,
            "bytes": 11,
            "sha256": "abc",
            "expected_sha256": "abc",
            "verified": True,
            "url": "https://example.com/model.bin",
            "note": "Model file downloaded successfully.",
        }
    )

    assert "# Link2Context Media Model Preparation" in markdown
    assert "- OK: true" in markdown
    assert "- Downloaded: true" in markdown
    assert "- Verified: true" in markdown
    assert "`https://example.com/model.bin`" in markdown


def test_run_media_text_writes_results_and_can_apply(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["media"]["images"][0]["local_path"] = "outputs/media/image-1.png"
    import_context(conn, context)
    out_path = tmp_path / "media-results.jsonl"
    command_template = f'"{sys.executable}" -c "print(\'图像 OCR 文本\')"'

    report = run_media_text(
        conn,
        kind="image",
        status="not_processed",
        limit=10,
        out_path=out_path,
        command_template=command_template,
        model="test-ocr",
        language="zh",
        confidence=0.91,
        apply=True,
        reindex=True,
    )

    assert report["summary"] == {"queued": 1, "written": 1, "skipped": 0, "applied": 1}
    assert report["runner"] == {
        "preset": None,
        "model": "test-ocr",
        "language": "zh",
        "confidence": 0.91,
    }
    result = json.loads(out_path.read_text(encoding="utf-8").strip())
    assert result["text"] == "图像 OCR 文本"
    assert result["model"] == "test-ocr"
    assert result["language"] == "zh"
    assert result["confidence"] == 0.91
    row = conn.execute(
        "SELECT text, status, text_model, text_language, text_confidence FROM media WHERE document_id = 1 AND media_index = 1"
    ).fetchone()
    assert dict(row) == {
        "text": "图像 OCR 文本",
        "status": "processed",
        "text_model": "test-ocr",
        "text_language": "zh",
        "text_confidence": 0.91,
    }
    assert report["apply"]["reindex"]["scope"] == "documents"
    markdown = render_run_media_text_markdown(report)
    assert "Written: 1" in markdown
    assert "Preset: custom" in markdown


def test_run_media_text_can_use_preset_metadata(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    out_path = tmp_path / "media-results.jsonl"

    report = run_media_text(
        conn,
        kind="image",
        status="not_processed",
        limit=10,
        out_path=out_path,
        preset="sona",
        preset_model="models/ggml-small.bin",
        tool_path=sys.executable,
        language="zh",
        confidence=0.88,
    )

    assert report["summary"]["queued"] == 1
    assert report["summary"]["skipped"] == 1
    assert report["runner"]["preset"] == "sona"
    assert report["runner"]["model"] == "sona"
    assert report["runner"]["language"] == "zh"


def test_run_media_text_records_command_failures(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    out_path = tmp_path / "media-results.jsonl"
    command_template = f'"{sys.executable}" -c "import sys; sys.exit(3)"'

    report = run_media_text(
        conn,
        kind="image",
        status="not_processed",
        limit=10,
        out_path=out_path,
        command_template=command_template,
    )

    assert report["summary"] == {"queued": 1, "written": 0, "skipped": 1, "applied": 0}
    assert report["skipped"][0]["reason"] == "command_failed"
    assert report["skipped"][0]["returncode"] == 3
    assert out_path.read_text(encoding="utf-8") == ""


def test_apply_media_text_updates_media_text_and_status(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    results_path = tmp_path / "ocr.jsonl"
    results_path.write_text(
        json.dumps(
            {
                "kind": "image",
                "output_hint": {"document_id": 1, "media_index": 1},
                "text": "图片里的 OCR 文本",
                "model": "paddleocr-v4",
                "language": "zh",
                "confidence": 0.61,
            },
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps({"document_id": 999, "media_index": 1, "text": "missing"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    report = apply_media_text(conn, results_path, status="processed")

    assert report["summary"] == {"input": 2, "applied": 1, "skipped": 1, "low_confidence": 1}
    assert report["applied"][0]["document_id"] == 1
    assert report["applied"][0]["model"] == "paddleocr-v4"
    assert report["applied"][0]["language"] == "zh"
    assert report["applied"][0]["confidence"] == 0.61
    assert report["low_confidence"] == [
        {
            "media_id": 1,
            "document_id": 1,
            "media_index": 1,
            "kind": "image",
            "confidence": 0.61,
            "threshold": 0.7,
        }
    ]
    assert report["skipped"][0]["reason"] == "media_not_found"
    inventory = media_inventory(conn, kind="image", status="processed", limit=10)
    assert inventory["items"][0]["text"] == "图片里的 OCR 文本"
    assert inventory["items"][0]["text_model"] == "paddleocr-v4"
    assert inventory["items"][0]["text_language"] == "zh"
    assert inventory["items"][0]["text_confidence"] == 0.61
    assert inventory["quality"] == {
        "low_confidence_threshold": 0.7,
        "low_confidence_count": 1,
    }
    assert inventory["low_confidence"][0]["document"]["id"] == 1


def test_apply_media_text_can_reindex_media_text_graph_signals(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    second = build_wechat_context("https://mp.weixin.qq.com/s/other", html)
    first_id = import_context(conn, first)
    second_id = import_context(conn, second)
    conn.execute(
        "UPDATE media SET text = ?, status = ? WHERE document_id = ? AND media_index = ?",
        ("PreservedDocTwoNeedle 出现在另一个 OCR 文本里。", "processed", second_id, 1),
    )
    reindex_media_text(conn, limit=10)
    results_path = tmp_path / "ocr.jsonl"
    results_path.write_text(
        json.dumps(
            {
                "kind": "image",
                "output_hint": {"document_id": first_id, "media_index": 1},
                "text": "ApplyReindexNeedle 出现在 OCR 文本里。",
                "confidence": 0.91,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = apply_media_text(conn, results_path, status="processed", reindex=True, reindex_limit=10)

    assert report["summary"]["low_confidence"] == 0
    assert report["reindex_requested"] is True
    assert report["reindex"]["scope"] == "documents"
    assert report["reindex"]["document_ids"] == [first_id]
    assert report["reindex"]["media_items"] == 1
    assert report["reindex"]["entities"] >= 1
    entity = conn.execute(
        """
        SELECT e.name, de.evidence
        FROM entities e
        JOIN document_entities de ON de.entity_id = e.id
        WHERE de.document_id = ? AND e.name = ?
        """,
        (first_id, "ApplyReindexNeedle"),
    ).fetchone()
    assert dict(entity) == {"name": "ApplyReindexNeedle", "evidence": "media.text"}
    preserved = conn.execute(
        """
        SELECT e.name, de.evidence
        FROM entities e
        JOIN document_entities de ON de.entity_id = e.id
        WHERE de.document_id = ? AND e.name = ?
        """,
        (second_id, "PreservedDocTwoNeedle"),
    ).fetchone()
    assert dict(preserved) == {"name": "PreservedDocTwoNeedle", "evidence": "media.text"}


def test_verify_media_text_passes_after_apply(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    results_path = tmp_path / "ocr.jsonl"
    results_path.write_text(
        json.dumps(
            {
                "kind": "image",
                "output_hint": {"document_id": 1, "media_index": 1},
                "text": "VerifyMediaNeedle 出现在 OCR 文本里。",
                "model": "paddleocr-v4",
                "language": "zh",
                "confidence": 0.91,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    apply_media_text(conn, results_path, status="processed")

    report = verify_media_text(conn, results_path, status="processed")

    assert report["ok"] is True
    assert report["summary"] == {"input": 1, "verified": 1, "skipped": 0, "errors": 0}
    assert report["verified"][0]["media_id"] == 1
    assert report["verified"][0]["model"] == "paddleocr-v4"
    assert report["reindex"] == {"required": False, "ok": None, "documents": []}


def test_verify_media_text_requires_reindex_when_requested(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    results_path = tmp_path / "ocr.jsonl"
    results_path.write_text(
        json.dumps(
            {
                "kind": "image",
                "output_hint": {"document_id": 1, "media_index": 1},
                "text": "VerifyReindexNeedle 出现在 OCR 文本里。",
                "confidence": 0.91,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    apply_media_text(conn, results_path, status="processed")

    missing = verify_media_text(conn, results_path, status="processed", require_reindex=True)
    reindex_media_text(conn, limit=10, document_ids=[1])
    verified = verify_media_text(conn, results_path, status="processed", require_reindex=True)

    assert missing["ok"] is False
    assert "document_id=1: missing media.text graph signals" in missing["errors"]
    assert verified["ok"] is True
    assert verified["reindex"]["ok"] is True
    assert verified["reindex"]["documents"][0]["document_id"] == 1


def test_verify_media_text_reports_mismatched_rows(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    results_path = tmp_path / "ocr.jsonl"
    results_path.write_text(
        json.dumps(
            {
                "kind": "image",
                "output_hint": {"document_id": 1, "media_index": 1},
                "text": "Expected OCR text",
                "confidence": 0.8,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    conn.execute(
        "UPDATE media SET text = ?, status = ?, text_confidence = ? WHERE document_id = ? AND media_index = ?",
        ("Different text", "not_processed", 0.2, 1, 1),
    )

    report = verify_media_text(conn, results_path, status="processed")

    assert report["ok"] is False
    assert "media_id=1: status expected processed, got not_processed" in report["errors"]
    assert "media_id=1: text does not match result" in report["errors"]
    assert any("confidence expected 0.8" in error for error in report["errors"])


def test_render_verify_media_text_markdown_includes_errors_and_reindex() -> None:
    report = {
        "path": "outputs/ocr.jsonl",
        "ok": False,
        "status": "processed",
        "require_reindex": True,
        "summary": {"input": 1, "verified": 0, "skipped": 0, "errors": 1},
        "errors": ["document_id=1: missing media.text graph signals"],
        "warnings": [],
        "verified": [],
        "reindex": {
            "required": True,
            "ok": False,
            "documents": [{"document_id": 1, "ok": False, "entities": 0, "relations": 0}],
        },
        "note": "Verification checks applied media rows; source context_json remains unchanged.",
    }

    markdown = render_verify_media_text_markdown(report)

    assert "# Link2Context Verify Media Text" in markdown
    assert "- OK: false" in markdown
    assert "missing media.text graph signals" in markdown
    assert "- fail document=1 entities=0 relations=0" in markdown


def test_media_queue_builds_low_confidence_rerun_templates(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    results_path = tmp_path / "ocr.jsonl"
    results_path.write_text(
        json.dumps(
            {
                "kind": "image",
                "output_hint": {"document_id": 1, "media_index": 1},
                "text": "低置信度 OCR 文本",
                "model": "paddleocr-v4",
                "language": "zh",
                "confidence": 0.61,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    apply_media_text(conn, results_path, status="processed")

    queue = media_queue(conn, kind="image", status="not_processed", limit=10, low_confidence=True)

    assert queue["filters"] == {
        "kind": "image",
        "status": "not_processed",
        "limit": 10,
        "low_confidence": True,
    }
    assert queue["quality"] == {"low_confidence_threshold": 0.7, "low_confidence_count": 1}
    assert queue["items"][0]["task"] == "ocr_review"
    assert queue["items"][0]["priority"] == 1
    assert queue["items"][0]["reason"] == "low_confidence_text"
    assert queue["items"][0]["previous_confidence"] == 0.61
    assert queue["items"][0]["low_confidence_threshold"] == 0.7
    assert queue["items"][0]["result_template"] == {
        "kind": "image",
        "output_hint": {"document_id": 1, "media_index": 1},
        "text": "",
        "model": "",
        "language": "",
        "confidence": None,
    }


def test_reindex_media_text_adds_graph_signals_from_ocr_text() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    document_id = import_context(conn, context)
    conn.execute(
        "UPDATE media SET text = ?, status = ? WHERE document_id = ? AND media_index = ?",
        ("MediaGraphNeedle 出现在 OCR 文本里。", "processed", document_id, 1),
    )

    report = reindex_media_text(conn, limit=10)

    assert report["media_items"] >= 1
    assert report["entities"] >= 1
    entity = conn.execute(
        """
        SELECT e.name, de.evidence
        FROM entities e
        JOIN document_entities de ON de.entity_id = e.id
        WHERE de.document_id = ? AND e.name = ?
        """,
        (document_id, "MediaGraphNeedle"),
    ).fetchone()
    assert dict(entity) == {"name": "MediaGraphNeedle", "evidence": "media.text"}
    relation = conn.execute(
        """
        SELECT object, evidence
        FROM relationships
        WHERE document_id = ? AND object = ?
        """,
        (document_id, "MediaGraphNeedle"),
    ).fetchone()
    assert dict(relation) == {"object": "MediaGraphNeedle", "evidence": "media.text"}


def test_quality_report_lists_warnings_and_missing_fields() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["quality"] = {
        "status": "partial",
        "warnings": ["missing account", "short body"],
        "missing_fields": ["article.account_name"],
    }
    context["article"]["account_name"] = None
    import_context(conn, context)

    report = quality_report(conn, status="partial", limit=10)

    assert report["filters"] == {"status": "partial", "limit": 10}
    assert report["summary"] == [{"status": "partial", "count": 1}]
    assert report["warning_counts"] == {"missing account": 1, "short body": 1}
    assert report["missing_field_counts"] == {"article.account_name": 1}
    assert report["documents"][0]["status"] == "partial"
    assert report["documents"][0]["warnings"] == ["missing account", "short body"]


def test_render_quality_markdown_includes_counts_and_documents() -> None:
    report = {
        "filters": {"status": "partial", "limit": 10},
        "summary": [{"status": "partial", "count": 1}],
        "warning_counts": {"short body": 1},
        "missing_field_counts": {"article.account_name": 1},
        "documents": [
            {
                "id": 3,
                "title": "低质量文章",
                "url": "https://example.com/partial",
                "status": "partial",
                "warnings": ["short body"],
                "missing_fields": ["article.account_name"],
            }
        ],
        "note": "Quality data is imported.",
    }

    markdown = render_quality_markdown(report)

    assert "# Link2Context Quality Report" in markdown
    assert "- partial: 1" in markdown
    assert "- short body: 1" in markdown
    assert "- article.account_name: 1" in markdown
    assert "[3] 低质量文章 (partial)" in markdown


def test_action_plan_suggests_ingest_for_empty_store() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)

    plan = action_plan(conn)

    assert plan["status"] == "empty"
    assert plan["ready_for_agent"] is False
    assert plan["actions"][0]["kind"] == "ingest"
    assert "ingest outputs/batch" in plan["actions"][0]["command"]


def test_action_plan_suggests_quality_media_and_export_actions() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["quality"] = {
        "status": "partial",
        "warnings": ["short body"],
        "missing_fields": ["article.account_name"],
    }
    import_context(conn, context)

    plan = action_plan(conn, limit=10)

    kinds = {action["kind"] for action in plan["actions"]}
    assert {"quality", "media_cache", "media", "handoff"}.issubset(kinds)
    quality_action = next(action for action in plan["actions"] if action["kind"] == "quality")
    assert "short body" in quality_action["detail"]
    assert quality_action["command"].endswith("doc 1")
    cache_action = next(action for action in plan["actions"] if action["kind"] == "media_cache")
    assert cache_action["priority"] == 2
    assert "local_path=missing" in cache_action["detail"]
    assert "cache-media --kind image --status not_processed" in cache_action["command"]

    cache_tasks = agent_task_report(conn, limit=10, kind="media_cache")
    assert cache_tasks["tasks"]
    assert {task["kind"] for task in cache_tasks["tasks"]} == {"media_cache"}
    assert any("cache-media --kind image --status not_processed" in task["command"] for task in cache_tasks["tasks"])


def test_action_plan_suggests_review_for_low_confidence_media_text(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    results_path = tmp_path / "ocr.jsonl"
    results_path.write_text(
        json.dumps(
            {
                "kind": "image",
                "output_hint": {"document_id": 1, "media_index": 1},
                "text": "低置信度 OCR 文本",
                "model": "paddleocr-v4",
                "language": "zh",
                "confidence": 0.61,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    apply_media_text(conn, results_path, status="processed")

    plan = action_plan(conn, limit=10)

    review = next(action for action in plan["actions"] if action["kind"] == "media_review")
    assert review["priority"] == 2
    assert "confidence=0.61" in review["detail"]
    assert "threshold=0.70" in review["detail"]
    assert "queue --low-confidence --kind image --format jsonl" in review["command"]

    tasks = agent_task_report(conn, limit=10, kind="media_review")
    assert [task["kind"] for task in tasks["tasks"]] == ["media_review"]
    assert "queue --low-confidence --kind image --format jsonl" in tasks["tasks"][0]["command"]


def test_cached_media_process_action_propagates_to_digest_and_inbox() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["media"]["images"][0]["local_path"] = "outputs/media-cache/image.jpg"
    import_context(conn, context)

    plan = action_plan(conn, limit=10)
    media_action = next(action for action in plan["actions"] if action["kind"] == "media")

    assert "queue --kind image --status not_processed --format jsonl" in media_action["command"]
    assert "next_step=queue_media_text" in media_action["detail"]
    digest = digest_report(conn, limit=10)
    assert any("queue --kind image --status not_processed --format jsonl" in action["command"] for action in digest["actions"])
    inbox = inbox_report(conn, limit=10)
    assert any("queue --kind image --status not_processed --format jsonl" in action["command"] for action in inbox["actions"])


def test_render_action_plan_markdown_includes_priorities_and_commands() -> None:
    plan = {
        "status": "ok",
        "ready_for_agent": True,
        "actions": [
            {
                "priority": 2,
                "kind": "quality",
                "title": "Review document [1]",
                "detail": "status=partial",
                "command": "python -m link2context.store --db data/link2context.db doc 1",
            }
        ],
        "note": "Rule-based.",
    }

    markdown = render_action_plan_markdown(plan)

    assert "# Link2Context Actions" in markdown
    assert "P2 [quality] Review document [1]" in markdown
    assert "`python -m link2context.store --db data/link2context.db doc 1`" in markdown
    assert "Rule-based." in markdown


def test_agent_tasks_combines_actions_queries_and_curate_lanes() -> None:
    actions = {
        "status": "ok",
        "ready_for_agent": True,
        "actions": [
            {
                "priority": 4,
                "kind": "handoff",
                "title": "Export an agent handoff bundle",
                "detail": "The store is ready.",
                "command": "python -m link2context.store --db data/link2context.db export --out outputs/agent-handoff",
            }
        ],
    }
    curate = {
        "status": "ok",
        "ready_for_agent": True,
        "lanes": [
            {
                "name": "read_now",
                "title": "Read Now",
                "purpose": "Recent good documents.",
                "items": [
                    {
                        "id": 1,
                        "title": "图谱文章",
                        "command": "python -m link2context.store --db data/link2context.db doc 1",
                    }
                ],
            }
        ],
    }
    starter_query_items = [
        {
            "query": "知识管理",
            "source": "user_tag",
            "reason": "User tag on 1 document(s).",
            "documents": 1,
            "command": 'python -m link2context.store --db data/link2context.db query "知识管理" --format markdown',
        }
    ]

    report = agent_tasks(actions, curate, starter_query_items, limit=10)
    markdown = render_agent_tasks_markdown(report)

    assert report["ready_for_agent"] is True
    assert [task["kind"] for task in report["tasks"]] == ["query", "read_now", "handoff"]
    assert report["tasks"][0]["documents"] == 1
    assert report["tasks"][1]["document_id"] == 1
    assert "# Link2Context Agent Tasks" in markdown
    assert "P2 [read_now] 图谱文章" in markdown
    assert "P2 [query] Query: 知识管理" in markdown
    assert "- Kind filter: all" in markdown
    assert "- Source filter: all" in markdown
    assert "- Max priority: all" in markdown
    assert "- Contains: all" in markdown
    assert "- Retry mode: all" in markdown
    assert "- Cache status: all" in markdown

    query_report = agent_tasks(actions, curate, starter_query_items, limit=10, kind="query")
    assert [task["kind"] for task in query_report["tasks"]] == ["query"]
    assert query_report["filters"] == {
        "kind": "query",
        "source": None,
        "max_priority": None,
        "contains": None,
        "retry_mode": None,
        "cache_status": None,
    }

    starter_query_report = agent_tasks(actions, curate, starter_query_items, limit=10, source="starter_query")
    assert [task["source"] for task in starter_query_report["tasks"]] == ["starter_query:user_tag"]
    assert starter_query_report["filters"] == {
        "kind": None,
        "source": "starter_query",
        "max_priority": None,
        "contains": None,
        "retry_mode": None,
        "cache_status": None,
    }

    high_priority_report = agent_tasks(actions, curate, starter_query_items, limit=10, max_priority=2)
    assert high_priority_report["filters"] == {
        "kind": None,
        "source": None,
        "max_priority": 2,
        "contains": None,
        "retry_mode": None,
        "cache_status": None,
    }
    assert {task["priority"] for task in high_priority_report["tasks"]} == {2}

    contains_report = agent_tasks(actions, curate, starter_query_items, limit=10, contains="知识管理")
    assert contains_report["filters"] == {
        "kind": None,
        "source": None,
        "max_priority": None,
        "contains": "知识管理",
        "retry_mode": None,
        "cache_status": None,
    }
    assert [task["title"] for task in contains_report["tasks"]] == ["Query: 知识管理"]

    duplicate_command_actions = {
        "status": "ok",
        "ready_for_agent": True,
        "actions": [
            {
                "priority": 2,
                "kind": "media_review",
                "title": "Review image[1]",
                "detail": "confidence=0.61",
                "command": "python -m link2context.store --db data/link2context.db queue --low-confidence --kind image --format jsonl",
            },
            {
                "priority": 2,
                "kind": "media_review",
                "title": "Review image[2]",
                "detail": "confidence=0.62",
                "command": "python -m link2context.store --db data/link2context.db queue --low-confidence --kind image --format jsonl",
            },
        ],
    }
    media_review_report = agent_tasks(duplicate_command_actions, {"lanes": []}, [], limit=10, kind="media_review")
    assert len(media_review_report["tasks"]) == 2
    assert {
        task["command"]
        for task in media_review_report["tasks"]
    } == {"python -m link2context.store --db data/link2context.db queue --low-confidence --kind image --format jsonl"}
    assert agent_task_commands(media_review_report) == [
        "python -m link2context.store --db data/link2context.db queue --low-confidence --kind image --format jsonl"
    ]


def test_agent_task_report_builds_tasks_from_store() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    add_document_tags(conn, "1", ["知识管理"])

    report = agent_task_report(conn, limit=20)

    assert report["status"] == "ok"
    assert report["ready_for_agent"] is True
    assert any(task["kind"] == "query" and task["title"] == "Query: 知识管理" for task in report["tasks"])
    assert any(task["kind"] == "handoff" for task in report["tasks"])

    query_report = agent_task_report(conn, limit=20, kind="query")
    assert query_report["filters"] == {
        "kind": "query",
        "source": None,
        "max_priority": None,
        "contains": None,
        "retry_mode": None,
        "cache_status": None,
    }
    assert query_report["tasks"]
    assert {task["kind"] for task in query_report["tasks"]} == {"query"}

    source_report = agent_task_report(conn, limit=20, source="starter_query")
    assert source_report["filters"] == {
        "kind": None,
        "source": "starter_query",
        "max_priority": None,
        "contains": None,
        "retry_mode": None,
        "cache_status": None,
    }
    assert source_report["tasks"]
    assert all(task["source"].startswith("starter_query:") for task in source_report["tasks"])

    high_priority_report = agent_task_report(conn, limit=20, max_priority=2)
    assert high_priority_report["filters"] == {
        "kind": None,
        "source": None,
        "max_priority": 2,
        "contains": None,
        "retry_mode": None,
        "cache_status": None,
    }
    assert high_priority_report["tasks"]
    assert all(task["priority"] <= 2 for task in high_priority_report["tasks"])

    contains_report = agent_task_report(conn, limit=20, contains="知识管理")
    assert contains_report["filters"] == {
        "kind": None,
        "source": None,
        "max_priority": None,
        "contains": "知识管理",
        "retry_mode": None,
        "cache_status": None,
    }
    assert contains_report["tasks"]
    assert all("知识管理" in task["title"] or "知识管理" in task.get("command", "") for task in contains_report["tasks"])


def test_source_report_groups_platforms_and_accounts() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/first", html)
    first["article"]["account_name"] = "账号A"
    first["article"]["title"] = "第一篇"
    second = build_wechat_context("https://mp.weixin.qq.com/s/second", html)
    second["article"]["account_name"] = "账号A"
    second["article"]["title"] = "第二篇"
    second["quality"]["status"] = "partial"
    third = build_wechat_context("https://mp.weixin.qq.com/s/third", html)
    third["article"]["account_name"] = "账号B"
    third["article"]["title"] = "第三篇"
    import_context(conn, first)
    import_context(conn, second)
    import_context(conn, third)

    report = source_report(conn, limit=10)

    assert report["platforms"] == [
        {"platform": "wechat_official_account", "documents": 3}
    ]
    account_a = next(source for source in report["sources"] if source["account_name"] == "账号A")
    assert account_a["documents"] == 2
    assert account_a["ok_documents"] == 1
    assert account_a["non_ok_documents"] == 1
    assert account_a["recent_documents"][0]["id"] in {1, 2}


def test_render_sources_markdown_includes_quality_and_recent_documents() -> None:
    report = {
        "platforms": [{"platform": "wechat_official_account", "documents": 2}],
        "sources": [
            {
                "platform": "wechat_official_account",
                "account_name": "灵渠测试号",
                "documents": 2,
                "ok_documents": 1,
                "non_ok_documents": 1,
                "latest_at": "2026-02-01",
                "recent_documents": [
                    {"id": 3, "title": "图谱文章", "quality_status": "ok"}
                ],
            }
        ],
        "note": "Sources are grouped.",
    }

    markdown = render_sources_markdown(report)

    assert "# Link2Context Sources" in markdown
    assert "wechat_official_account: 2 document(s)" in markdown
    assert "灵渠测试号 (wechat_official_account): 2 document(s)" in markdown
    assert "Quality: ok=1, non_ok=1" in markdown
    assert "[3] 图谱文章 (ok)" in markdown


def test_coverage_report_summarizes_processing_and_gaps() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/one", html)
    first["article"]["title"] = "重复标题"
    second = build_wechat_context("https://mp.weixin.qq.com/s/two", html)
    second["article"]["title"] = "重复标题"
    second["quality"]["status"] = "partial"
    second["quality"]["warnings"] = ["short body"]
    second["quality"]["missing_fields"] = ["article.summary"]
    import_context(conn, first)
    import_context(conn, second)

    report = coverage_report(conn, limit=10)

    assert report["stats"]["documents"] == 2
    assert report["platforms"][0]["platform"] == "wechat_official_account"
    assert report["coverage"]["documents_with_citations"] == 2
    assert report["coverage"]["documents_with_entities"] == 2
    assert report["coverage"]["media_pending"] > 0
    assert report["coverage"]["duplicate_groups"] >= 1
    gap_kinds = {gap["kind"] for gap in report["gaps"]}
    assert {"platform", "media", "quality", "duplicates"}.issubset(gap_kinds)
    assert "short body" in report["quality"]["warning_counts"]


def test_render_coverage_markdown_includes_gaps_and_commands() -> None:
    report = {
        "status": "ok",
        "ready_for_agent": True,
        "stats": {
            "documents": 2,
            "citations": 4,
            "entities": 3,
            "relationships": 2,
        },
        "platforms": [
            {
                "platform": "wechat_official_account",
                "documents": 2,
                "ok_documents": 1,
                "non_ok_documents": 1,
            }
        ],
        "coverage": {
            "documents_with_citations": 2,
            "documents_with_entities": 1,
            "documents_with_media": 2,
            "media_total": 3,
            "media_processed": 1,
            "media_pending": 2,
            "duplicate_groups": 1,
        },
        "quality": {
            "warning_counts": {"short body": 1},
            "missing_field_counts": {"article.summary": 1},
        },
        "sources": [
            {
                "account_name": "灵渠测试号",
                "platform": "wechat_official_account",
                "documents": 2,
            }
        ],
        "gaps": [
            {
                "kind": "media",
                "severity": "medium",
                "detail": "2 media item(s) still need OCR/ASR text.",
            }
        ],
        "commands": ["python -m link2context.store --db data/link2context.db queue"],
        "note": "Rule-based.",
    }

    markdown = render_coverage_markdown(report)

    assert "# Link2Context Coverage" in markdown
    assert "wechat_official_account: 2 document(s), ok=1, non_ok=1" in markdown
    assert "Media processed: 1 / 3" in markdown
    assert "medium [media] 2 media item(s) still need OCR/ASR text." in markdown
    assert "`python -m link2context.store --db data/link2context.db queue`" in markdown
    assert "Rule-based." in markdown


def test_topics_report_returns_entity_evidence() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["article"]["title"] = "产品观察"
    context["content"]["plain_text"] += " ProductX 是一个适合知识图谱测试的工具。"
    context["agent_package"]["citations"] = [
        {
            "ref": "paragraph_custom",
            "text": "ProductX 是一个适合知识图谱测试的工具。",
            "source": "article_body",
        }
    ]
    import_context(conn, context)

    report = topics_report(conn, entity_type="term", limit=10)

    product = next(topic for topic in report["topics"] if topic["name"] == "ProductX")
    assert product["type"] == "term"
    assert product["documents"] == 1
    assert product["evidence_documents"][0]["id"] == 1
    assert product["evidence_documents"][0]["title"] == "产品观察"
    assert product["evidence_citations"][0]["ref"] == "paragraph_custom"


def test_render_topics_markdown_includes_documents_and_citations() -> None:
    report = {
        "filters": {"type": "term", "limit": 5},
        "topics": [
            {
                "name": "ProductX",
                "type": "term",
                "documents": 1,
                "avg_confidence": 0.6,
                "evidence_documents": [
                    {"title": "产品观察", "url": "https://example.com/productx"}
                ],
                "evidence_citations": [
                    {
                        "ref": "paragraph_custom",
                        "title": "产品观察",
                        "text": "ProductX 是一个适合知识图谱测试的工具。",
                    }
                ],
            }
        ],
        "note": "Rule-based.",
    }

    markdown = render_topics_markdown(report)

    assert "# Link2Context Topics" in markdown
    assert "## ProductX (term)" in markdown
    assert "- Average confidence: 0.60" in markdown
    assert "https://example.com/productx" in markdown
    assert "paragraph_custom | 产品观察" in markdown


def test_clusters_report_groups_documents_by_shared_entities() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/cluster-a", html)
    first["article"]["title"] = "知识图谱 A"
    first["content"]["plain_text"] += " ProductX KnowledgeGraph"
    first["agent_package"]["citations"] = [
        {"ref": "paragraph_custom", "text": "ProductX 适合做知识图谱。", "source": "article_body"}
    ]
    second = build_wechat_context("https://mp.weixin.qq.com/s/cluster-b", html)
    second["article"]["title"] = "知识图谱 B"
    second["content"]["plain_text"] += " ProductX KnowledgeGraph"
    import_context(conn, first)
    import_context(conn, second)

    report = clusters_report(conn, min_docs=2, limit=5)

    product = next(cluster for cluster in report["clusters"] if cluster["name"] == "ProductX")
    assert product["documents"] == 2
    assert product["evidence_documents"][0]["id"] in {1, 2}
    assert product["evidence_documents"][0]["title"] in {"知识图谱 A", "知识图谱 B"}
    assert product["commands"]["explain"].endswith('explain "ProductX"')
    assert product["commands"]["evidence"].endswith('evidence "ProductX"')


def test_render_clusters_markdown_includes_commands_and_evidence() -> None:
    report = {
        "filters": {"min_docs": 2, "limit": 5},
        "clusters": [
            {
                "name": "ProductX",
                "type": "term",
                "documents": 2,
                "avg_confidence": 0.7,
                "commands": {
                    "explain": 'python -m link2context.store --db data/link2context.db explain "ProductX"',
                    "evidence": 'python -m link2context.store --db data/link2context.db evidence "ProductX"',
                },
                "evidence_documents": [
                    {"id": 1, "title": "知识图谱 A", "url": "https://example.com/a"}
                ],
                "evidence_citations": [
                    {"ref": "paragraph_custom", "title": "知识图谱 A", "text": "ProductX 适合做知识图谱。"}
                ],
            }
        ],
        "note": "Clusters are rule-based.",
    }

    markdown = render_clusters_markdown(report)

    assert "# Link2Context Clusters" in markdown
    assert "## ProductX (term)" in markdown
    assert 'explain "ProductX"' in markdown
    assert "ProductX 适合做知识图谱。" in markdown


def test_questions_report_generates_follow_up_questions_from_clusters() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/question-a", html)
    first["content"]["plain_text"] += " ProductX"
    second = build_wechat_context("https://mp.weixin.qq.com/s/question-b", html)
    second["article"]["title"] = "第二篇 ProductX"
    second["content"]["plain_text"] += " ProductX"
    import_context(conn, first)
    import_context(conn, second)

    report = questions_report(conn, limit=20)

    product_questions = [question for question in report["questions"] if question["topic"] == "ProductX"]
    assert {question["kind"] for question in product_questions} == {"synthesis", "evidence", "connection"}
    synthesis = next(question for question in product_questions if question["kind"] == "synthesis")
    assert 'explain "ProductX"' in synthesis["command"]
    assert synthesis["evidence_documents"][0]["id"] in {1, 2}


def test_render_questions_markdown_includes_commands_and_sources() -> None:
    report = {
        "limit": 3,
        "questions": [
            {
                "topic": "ProductX",
                "type": "term",
                "documents": 2,
                "kind": "synthesis",
                "question": "What have I collected about ProductX?",
                "command": 'python -m link2context.store --db data/link2context.db explain "ProductX"',
                "evidence_documents": [
                    {"id": 1, "title": "ProductX 文章", "url": "https://example.com/productx"}
                ],
            }
        ],
        "note": "Questions are deterministic.",
    }

    markdown = render_questions_markdown(report)

    assert "# Link2Context Questions" in markdown
    assert "What have I collected about ProductX?" in markdown
    assert 'explain "ProductX"' in markdown
    assert "[1] ProductX 文章" in markdown


def test_relations_report_filters_by_entity_and_predicate() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["content"]["plain_text"] += " ProductX"
    import_context(conn, context)

    report = relations_report(conn, entity="ProductX", predicate="mentions", limit=5)

    assert report["filters"] == {"entity": "ProductX", "predicate": "mentions", "limit": 5}
    assert report["relations"]
    assert report["relations"][0]["object"] == "ProductX"
    assert report["relations"][0]["predicate"] == "mentions"
    assert report["relations"][0]["document"]["id"] == 1


def test_render_relations_markdown_includes_source_document() -> None:
    report = {
        "filters": {"entity": "ProductX", "predicate": "mentions", "limit": 5},
        "relations": [
            {
                "subject": "产品观察",
                "predicate": "mentions",
                "object": "ProductX",
                "confidence": 0.6,
                "evidence": "content.plain_text",
                "document": {
                    "id": 1,
                    "title": "产品观察",
                    "url": "https://example.com/productx",
                },
            }
        ],
        "note": "Rule-based.",
    }

    markdown = render_relations_markdown(report)

    assert "# Link2Context Relations" in markdown
    assert "产品观察 --mentions--> ProductX" in markdown
    assert "Source: [1] 产品观察" in markdown
    assert "https://example.com/productx" in markdown


def test_digest_report_combines_recent_topics_sources_quality_and_actions() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    first["content"]["plain_text"] += " ProductX"
    second = build_wechat_context("https://mp.weixin.qq.com/s/second", html)
    second["article"]["title"] = "第二篇文章"
    second["content"]["plain_text"] += " ProductX"
    import_context(conn, first)
    import_context(conn, second)

    report = digest_report(conn, limit=5)

    assert report["stats"]["documents"] == 2
    assert report["recent"][0]["id"] == 2
    assert report["topics"]
    assert next(cluster for cluster in report["clusters"] if cluster["name"] == "ProductX")
    assert next(question for question in report["questions"] if question["topic"] == "ProductX")
    assert report["sources"][0]["account_name"] == "灵渠测试号"
    assert report["quality"]["summary"] == [{"status": "ok", "count": 2}]
    assert any(action["kind"] == "handoff" for action in report["actions"])


def test_render_digest_markdown_includes_compact_review_sections() -> None:
    report = {
        "stats": {"documents": 2, "citations": 5, "entities": 4, "relationships": 3},
        "recent": [
            {"id": 1, "title": "最近文章", "published_at": "2026-02-01", "imported_at": "2026-02-02"}
        ],
        "topics": [{"name": "ProductX", "type": "term", "documents": 2}],
        "clusters": [
            {
                "name": "ProductX",
                "type": "term",
                "documents": 2,
                "commands": {
                    "explain": 'python -m link2context.store --db data/link2context.db explain "ProductX"'
                },
            }
        ],
        "questions": [
            {
                "kind": "synthesis",
                "question": "What have I collected about ProductX?",
                "command": 'python -m link2context.store --db data/link2context.db explain "ProductX"',
            }
        ],
        "sources": [
            {
                "account_name": "灵渠测试号",
                "platform": "wechat_official_account",
                "documents": 2,
                "ok_documents": 1,
                "non_ok_documents": 1,
            }
        ],
        "quality": {"summary": [{"status": "ok", "count": 1}, {"status": "partial", "count": 1}]},
        "actions": [
            {
                "priority": 2,
                "kind": "quality",
                "title": "Review document [1]",
                "command": "python -m link2context.store --db data/link2context.db doc 1",
            }
        ],
        "note": "Digest note.",
    }

    markdown = render_digest_markdown(report)

    assert "# Link2Context Digest" in markdown
    assert "[1] 最近文章" in markdown
    assert "ProductX (term): 2 document(s)" in markdown
    assert "## Topic Clusters" in markdown
    assert 'explain "ProductX"' in markdown
    assert "## Follow-up Questions" in markdown
    assert "What have I collected about ProductX?" in markdown
    assert "灵渠测试号 (wechat_official_account): 2 document(s), ok=1, non_ok=1" in markdown
    assert "P2 [quality] Review document [1]" in markdown


def test_review_report_combines_status_clusters_questions_and_actions() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/review-a", html)
    first["content"]["plain_text"] += " ProductX"
    second = build_wechat_context("https://mp.weixin.qq.com/s/review-b", html)
    second["article"]["title"] = "第二篇 ProductX"
    second["content"]["plain_text"] += " ProductX"
    import_context(conn, first)
    import_context(conn, second)

    report = review_report(conn, limit=5)

    assert report["status"] == "ok"
    assert report["ready_for_agent"] is True
    assert next(cluster for cluster in report["top_clusters"] if cluster["name"] == "ProductX")
    assert next(question for question in report["follow_up_questions"] if question["topic"] == "ProductX")
    assert any(action["kind"] == "handoff" for action in report["actions"])
    assert report["recommended_next"][0].endswith("brief")


def test_render_review_markdown_includes_one_page_entry_points() -> None:
    report = {
        "status": "ok",
        "ready_for_agent": True,
        "stats": {"documents": 2, "citations": 5, "entities": 4},
        "top_clusters": [
            {
                "name": "ProductX",
                "type": "term",
                "documents": 2,
                "commands": {
                    "explain": 'python -m link2context.store --db data/link2context.db explain "ProductX"'
                },
            }
        ],
        "follow_up_questions": [
            {
                "kind": "synthesis",
                "question": "What have I collected about ProductX?",
                "command": 'python -m link2context.store --db data/link2context.db explain "ProductX"',
            }
        ],
        "actions": [
            {
                "priority": 1,
                "kind": "handoff",
                "title": "Export handoff",
                "command": "python -m link2context.store --db data/link2context.db export --out outputs/agent-handoff",
            }
        ],
        "recommended_next": ["python -m link2context.store --db data/link2context.db brief"],
        "note": "Review note.",
    }

    markdown = render_review_markdown(report)

    assert "# Link2Context Review" in markdown
    assert "Ready for agent: true" in markdown
    assert "ProductX (term): 2 document(s)" in markdown
    assert "What have I collected about ProductX?" in markdown
    assert "Export handoff" in markdown
    assert "python -m link2context.store --db data/link2context.db brief" in markdown


def test_render_media_markdown_includes_status_and_source() -> None:
    inventory = {
        "filters": {"kind": "image", "status": "not_processed", "limit": 5},
        "summary": [{"kind": "image", "status": "not_processed", "count": 1}],
        "items": [
            {
                "kind": "image",
                "index": 1,
                "url": "https://example.com/image.png",
                "local_path": "outputs/media/image.png",
                "status": "not_processed",
                "text": "图片里的字",
                "text_model": "paddleocr-v4",
                "text_language": "zh",
                "text_confidence": 0.61,
                "document": {
                    "id": 7,
                    "title": "图文文章",
                    "url": "https://example.com/doc",
                },
            }
        ],
        "quality": {"low_confidence_threshold": 0.7, "low_confidence_count": 1},
        "low_confidence": [
            {
                "kind": "image",
                "index": 1,
                "text_confidence": 0.61,
                "document": {"id": 7, "title": "图文文章"},
            }
        ],
        "note": "Media status is imported.",
    }

    markdown = render_media_markdown(inventory)

    assert "# Link2Context Media Inventory" in markdown
    assert "- image / not_processed: 1" in markdown
    assert "image[1] (not_processed)" in markdown
    assert "Document: [7] 图文文章" in markdown
    assert "https://example.com/image.png" in markdown
    assert "Local path: outputs/media/image.png" in markdown
    assert "Text metadata: model=paddleocr-v4, language=zh, confidence=0.61" in markdown
    assert "## Low Confidence Text" in markdown
    assert "image[1] confidence=0.61 document=[7] 图文文章" in markdown


def test_media_pipeline_status_summarizes_processing_chain() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    document_id = import_context(conn, context)
    conn.execute(
        """
        UPDATE media
        SET local_path = ?, cache_status = ?, text = ?, status = ?, text_confidence = ?
        WHERE document_id = ? AND kind = ? AND media_index = ?
        """,
        (
            "outputs/media-cache/image.jpg",
            "cached",
            "PipelineNeedle 出现在 OCR 文本里。",
            "processed",
            0.61,
            document_id,
            "image",
            1,
        ),
    )
    reindex_media_text(conn, limit=10, document_ids=[document_id])

    report = media_pipeline_status(conn)
    markdown = render_media_pipeline_markdown(report)

    assert report["counts"]["total"] == 2
    assert report["counts"]["with_text"] == 1
    assert report["counts"]["with_local_path"] == 1
    assert report["counts"]["low_confidence"] == 1
    assert report["counts"]["indexed_documents"] == 1
    assert "low_confidence" in report["blockers"]
    assert any("media-text-presets" in command for command in report["recommended_commands"])
    assert any("prepare-media-model" in command for command in report["recommended_commands"])
    assert any("verify-auto-queue-next" in command for command in report["recommended_commands"])
    assert "# Link2Context Media Pipeline" in markdown
    assert "low_confidence" in markdown
    assert "## Recommended Commands" in markdown
    assert "media-text-presets" in markdown
    assert "prepare-media-model" in markdown


def test_render_media_queue_markdown_includes_task_and_priority() -> None:
    queue = {
        "filters": {"kind": "image", "status": "not_processed", "limit": 5},
        "summary": [{"kind": "image", "status": "not_processed", "count": 1}],
        "items": [
            {
                "task": "ocr",
                "kind": "image",
                "index": 1,
                "status": "not_processed",
                "input_url": "https://example.com/image.png",
                "input_path": "outputs/media/image.png",
                "input_source": "outputs/media/image.png",
                "priority": 3,
                "document": {
                    "id": 7,
                    "title": "图文文章",
                    "url": "https://example.com/doc",
                },
            }
        ],
        "note": "Queue note.",
    }

    markdown = render_media_queue_markdown(queue)

    assert "# Link2Context Media Queue" in markdown
    assert "- image / not_processed: 1" in markdown
    assert "P3 ocr image[1]" in markdown
    assert "Document: [7] 图文文章" in markdown
    assert "https://example.com/image.png" in markdown
    assert "Local input: outputs/media/image.png" in markdown
    assert "Preferred input: outputs/media/image.png" in markdown


def test_render_apply_media_text_markdown_includes_summary_and_skips() -> None:
    report = {
        "path": "ocr.jsonl",
        "status": "processed",
        "reindex_requested": True,
        "reindex": {"media_items": 1, "entities": 2, "relations": 2},
        "summary": {"input": 2, "applied": 1, "skipped": 1, "low_confidence": 1},
        "applied": [
            {
                "media_id": 3,
                "document_id": 7,
                "media_index": 1,
                "text_length": 12,
                "model": "whisper-large-v3",
                "language": "zh",
                "confidence": 0.88,
            }
        ],
        "skipped": [{"index": 2, "reason": "missing_text"}],
        "low_confidence": [
            {
                "media_id": 4,
                "document_id": 8,
                "media_index": 2,
                "kind": "image",
                "confidence": 0.55,
                "threshold": 0.7,
            }
        ],
        "note": "Applied text updates media.text.",
    }

    markdown = render_apply_media_text_markdown(report)

    assert "# Link2Context Apply Media Text" in markdown
    assert "- Reindex requested: true" in markdown
    assert "- Applied: 1" in markdown
    assert "- Low confidence: 1" in markdown
    assert "media_id=3 document=7 media_index=1 text_length=12 (model=whisper-large-v3, language=zh, confidence=0.88)" in markdown
    assert "input #2: missing_text" in markdown
    assert "## Low Confidence After Apply" in markdown
    assert "media_id=4 document=8 image[2] confidence=0.55 threshold=0.70" in markdown
    assert "## Reindex" in markdown
    assert "- Entities: 2" in markdown


def test_render_reindex_media_text_markdown_includes_counts() -> None:
    report = {
        "limit": 10,
        "media_items": 1,
        "entities": 2,
        "relations": 2,
        "indexed": [
            {"document_id": 7, "kind": "image", "media_index": 1, "entities": 2, "relations": 2}
        ],
        "note": "Reindexed.",
    }

    markdown = render_reindex_media_text_markdown(report)

    assert "# Link2Context Reindex Media Text" in markdown
    assert "- Entities: 2" in markdown
    assert "document=7 image[1]: 2 entities, 2 relations" in markdown


def test_render_handoff_markdown_includes_read_order_and_caution() -> None:
    brief = {"stats": {"documents": 2, "citations": 4, "entities": 3, "relationships": 1}}
    doctor = {"status": "ok", "ready_for_agent": True}
    media = {"summary": [{"kind": "image", "status": "not_processed", "count": 5}]}

    markdown = render_handoff_markdown(brief, doctor, media, limit=10)

    assert "# Link2Context Agent Handoff" in markdown
    assert "1. `inbox.md`" in markdown
    assert "2. `curate.md`" in markdown
    assert "3. `review.md`" in markdown
    assert "4. `doctor.md`" in markdown
    assert "5. `duplicates.md`" in markdown
    assert "6. `coverage.md`" in markdown
    assert "7. `quality.md`" in markdown
    assert "8. `evidence.md`" in markdown
    assert "9. `actions.md`" in markdown
    assert "10. `agent-tasks.md/json`" in markdown
    assert "11. `digest.md`" in markdown
    assert "13. `starter-queries.md/json`" in markdown
    assert "14. `sources.md`" in markdown
    assert "15. `tags.md`" in markdown
    assert "16. `notes.md`" in markdown
    assert "17. `statuses.md`" in markdown
    assert "18. `annotations.md`" in markdown
    assert "19. `topics.md`" in markdown
    assert "20. `clusters.md`" in markdown
    assert "21. `questions.md`" in markdown
    assert "24. `media-pipeline.md/json`" in markdown
    assert "25. `queue.md`" in markdown
    assert "27. `relations.md`" in markdown
    assert "- Documents: 2" in markdown
    assert "- image / not_processed: 5" in markdown
    assert "Use citations and source URLs as evidence" in markdown


def test_ingest_paths_imports_and_returns_doctor_report(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context_dir = tmp_path / "sample"
    context_dir.mkdir()
    (context_dir / "context.json").write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")

    result = ingest_paths(conn, [tmp_path])

    assert result["imported"] == 1
    assert result["doctor"]["status"] == "ok"
    assert result["doctor"]["ready_for_agent"] is True
    assert result["recommended_next"][0].endswith("brief")


def test_ingest_paths_reports_batch_manifest_warnings(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/ok", html)
    ok_dir = tmp_path / "001-ok"
    fail_dir = tmp_path / "002-fail"
    ok_dir.mkdir()
    fail_dir.mkdir()
    (ok_dir / "context.json").write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    (ok_dir / "context.md").write_text("# ok\n", encoding="utf-8")
    (fail_dir / "error.json").write_text('{"error":"login required"}', encoding="utf-8")
    error_item = {
        "index": 2,
        "url": "https://mp.weixin.qq.com/s/fail",
        "status": "error",
        "error": "login required",
        "output_dir": str(fail_dir),
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "project": "Link2Context",
                "format": "batch-context",
                "version": 1,
                "generated_at": "2026-06-29T00:00:00+00:00",
                "count": 2,
                "succeeded": 1,
                "failed": 1,
                "ok": False,
                "items": [
                    {
                        "index": 1,
                        "url": "https://mp.weixin.qq.com/s/ok",
                        "status": "ok",
                        "output_dir": str(ok_dir),
                    },
                    error_item,
                ],
                "failures": [error_item],
                "recommended_next": [
                    f"python -m link2context --failed-url-list {tmp_path} > outputs/retry_urls.txt",
                    f"python -m link2context --retry-failed {tmp_path} --out outputs/retry",
                    f"python -m link2context.store --db data/link2context.db ingest {tmp_path}",
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = ingest_paths(conn, [tmp_path])
    markdown = render_ingest_markdown(result, Path("data/link2context.db"))

    assert result["imported"] == 1
    assert result["batch_checks"][0]["ok"] is True
    assert result["batch_checks"][0]["count"] == 2
    assert result["batch_checks"][0]["succeeded"] == 1
    assert result["batch_warnings"][0]["failed"] == 1
    assert "1 failed item(s)" in result["batch_warnings"][0]["summary"]
    assert "## Batch Checks" in markdown
    assert "## Batch Warnings" in markdown
    assert "1 failed item(s)" in markdown


def test_render_ingest_markdown_includes_next_steps() -> None:
    result = {
        "imported": 2,
        "doctor": {
            "status": "ok",
            "ready_for_agent": True,
            "checks": [
                {"name": "documents", "ok": True, "detail": "2 imported document(s)"},
                {"name": "citations", "ok": True, "detail": "8 citation(s)"},
            ],
        },
        "recommended_next": ["python -m link2context.store --db data/link2context.db brief"],
    }

    markdown = render_ingest_markdown(result, Path("data/link2context.db"))

    assert "# Link2Context Ingest" in markdown
    assert "- Imported: 2 context file(s)" in markdown
    assert "- Store status: ok" in markdown
    assert "- ok documents: 2 imported document(s)" in markdown
    assert "`python -m link2context.store --db data/link2context.db brief`" in markdown


def test_get_document_returns_full_context_by_url_and_id() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    document_id = import_context(conn, context)

    by_url = get_document(conn, "https://mp.weixin.qq.com/s/example")
    by_id = get_document(conn, str(document_id))

    assert by_url["found"] is True
    assert by_url["document"]["title"] == "示例公众号文章"
    assert by_url["document"]["url"] == "https://mp.weixin.qq.com/s/example"
    assert by_url["media"][0]["kind"] == "image"
    assert by_url["citations"]
    assert any(entity["name"] == "灵渠测试号" for entity in by_url["entities"])
    assert by_id["document"]["url"] == by_url["document"]["url"]


def test_add_document_tags_updates_document_and_graph() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)

    result = add_document_tags(conn, "1", ["知识管理", "#Agent", "agent", "  "])

    assert result["ok"] is True
    assert result["added"] == ["知识管理", "Agent"]
    document = get_document(conn, "1")
    assert document["tags"] == ["Agent", "知识管理"]
    entity = conn.execute(
        """
        SELECT e.name, e.type, de.evidence
        FROM entities e
        JOIN document_entities de ON de.entity_id = e.id
        WHERE de.document_id = ? AND e.name = ?
        """,
        (1, "知识管理"),
    ).fetchone()
    assert dict(entity) == {"name": "知识管理", "type": "user_tag", "evidence": "user.tag"}
    relation = conn.execute(
        """
        SELECT predicate, object, evidence
        FROM relationships
        WHERE document_id = ? AND object = ?
        """,
        (1, "知识管理"),
    ).fetchone()
    assert dict(relation) == {"predicate": "user_tagged_as", "object": "知识管理", "evidence": "user.tag"}


def test_import_context_preserves_existing_user_tags_in_graph() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    add_document_tags(conn, "1", ["长期关注"])

    import_context(conn, context)

    document = get_document(conn, "1")
    assert document["tags"] == ["长期关注"]
    tagged_entity = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM document_entities de
        JOIN entities e ON e.id = de.entity_id
        WHERE de.document_id = ? AND e.name = ? AND de.evidence = 'user.tag'
        """,
        (1, "长期关注"),
    ).fetchone()
    assert tagged_entity["count"] == 1


def test_tag_report_and_markdown_list_user_tags() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    add_document_tags(conn, "1", ["知识管理"])

    report = tag_report(conn, limit=10)
    markdown = render_tags_markdown(report)
    result_markdown = render_tag_result_markdown(add_document_tags(conn, "1", ["Agent"]))

    assert report["tags"][0]["tag"] == "知识管理"
    assert report["tags"][0]["documents"] == 1
    assert "# Link2Context Tags" in markdown
    assert "[1] 示例公众号文章" in markdown
    assert "# Link2Context Tag" in result_markdown
    assert "Agent" in result_markdown


def test_add_document_note_updates_document_and_graph() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)

    result = add_document_note(conn, "1", "这是我对这篇文章的判断。")

    assert result["ok"] is True
    assert result["note_added"]["note"] == "这是我对这篇文章的判断。"
    document = get_document(conn, "1")
    assert document["notes"][0]["note"] == "这是我对这篇文章的判断。"
    relation = conn.execute(
        """
        SELECT predicate, object, evidence
        FROM relationships
        WHERE document_id = ? AND evidence = 'user.note'
        """,
        (1,),
    ).fetchone()
    assert dict(relation) == {
        "predicate": "user_note",
        "object": "这是我对这篇文章的判断。",
        "evidence": "user.note",
    }


def test_import_context_preserves_existing_user_notes_in_graph() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    add_document_note(conn, "1", "长期关注这个主题。")

    import_context(conn, context)

    document = get_document(conn, "1")
    assert document["notes"][0]["note"] == "长期关注这个主题。"
    relation_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM relationships
        WHERE document_id = ? AND predicate = 'user_note' AND evidence = 'user.note'
        """,
        (1,),
    ).fetchone()
    assert relation_count["count"] == 1


def test_notes_report_and_markdown_list_user_notes() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    add_document_note(conn, "1", "值得之后追问。")

    report = notes_report(conn, limit=10)
    markdown = render_notes_markdown(report)
    result_markdown = render_note_result_markdown(add_document_note(conn, "1", "第二条笔记。"))

    assert report["notes"][0]["note"] == "值得之后追问。"
    assert report["notes"][0]["document"]["title"] == "示例公众号文章"
    assert "# Link2Context Notes" in markdown
    assert "值得之后追问。" in markdown
    assert "# Link2Context Note" in result_markdown
    assert "第二条笔记。" in result_markdown


def test_mark_document_status_updates_document_and_report() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)

    result = mark_document_status(conn, "1", "later", "今晚处理")

    assert result["ok"] is True
    assert result["user_status"]["status"] == "later"
    assert result["user_status"]["note"] == "今晚处理"
    document = get_document(conn, "1")
    assert document["user_status"]["status"] == "later"
    report = status_report(conn, status="later", limit=10)
    assert report["summary"] == [{"status": "later", "documents": 1}]
    assert report["documents"][0]["document"]["title"] == "示例公众号文章"


def test_render_status_markdown_outputs_documents_and_commands() -> None:
    result = {
        "ok": True,
        "document": {"id": 1, "title": "图谱文章", "url": "https://example.com/graph"},
        "user_status": {"status": "reading", "note": "继续看", "updated_at": "2026-06-28"},
        "note": "Stored.",
    }
    report = {
        "filters": {"status": None, "limit": 10},
        "summary": [{"status": "reading", "documents": 1}],
        "documents": [
            {
                "status": "reading",
                "note": "继续看",
                "updated_at": "2026-06-28",
                "document": {"id": 1, "title": "图谱文章", "url": "https://example.com/graph"},
            }
        ],
        "note": "Workflow statuses.",
    }

    mark_markdown = render_mark_result_markdown(result)
    statuses_markdown = render_statuses_markdown(report)

    assert "# Link2Context Mark" in mark_markdown
    assert "Status: reading" in mark_markdown
    assert "# Link2Context Statuses" in statuses_markdown
    assert "reading: 1" in statuses_markdown
    assert "[1] 图谱文章 (reading)" in statuses_markdown


def test_annotations_report_combines_user_signals() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    add_document_tags(conn, "1", ["知识管理"])
    add_document_note(conn, "1", "值得之后追问。")
    mark_document_status(conn, "1", "later", "今晚处理")

    report = annotations_report(conn, limit=10)
    markdown = render_annotations_markdown(report)

    assert report["summary"] == {
        "documents": 1,
        "with_tags": 1,
        "with_notes": 1,
        "with_status": 1,
    }
    document = report["documents"][0]
    assert document["tags"] == ["知识管理"]
    assert document["notes"][0]["note"] == "值得之后追问。"
    assert document["user_status"]["status"] == "later"
    assert "# Link2Context Annotations" in markdown
    assert "Tags: 知识管理" in markdown
    assert "User status: later" in markdown
    assert "值得之后追问。" in markdown


def test_search_returns_document_id_for_follow_up_commands() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    document_id = import_context(conn, context)

    rows = search(conn, "示例公众号文章")

    assert rows[0]["id"] == document_id
    assert rows[0]["title"] == "示例公众号文章"


def test_search_matches_applied_media_text() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    document_id = import_context(conn, context)
    conn.execute(
        "UPDATE media SET text = ?, status = ? WHERE document_id = ? AND media_index = ?",
        ("OCRUniqueSignal", "processed", document_id, 1),
    )

    rows = search(conn, "OCRUniqueSignal")

    assert rows[0]["id"] == document_id


def test_get_document_returns_not_found_payload() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)

    package = get_document(conn, "https://example.com/missing")

    assert package == {
        "query": "https://example.com/missing",
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


def test_render_document_markdown_includes_full_context() -> None:
    package = {
        "found": True,
        "document": {
            "id": 1,
            "title": "图谱文章",
            "url": "https://example.com/graph",
            "platform": "wechat_official_account",
            "account_name": "灵渠测试号",
            "author": None,
            "published_at": "2026-02-01",
            "quality_status": "ok",
            "summary": "一段摘要",
            "markdown": "正文内容",
        },
        "tags": ["知识管理"],
        "notes": [{"id": 7, "note": "我的判断", "created_at": "2026-06-28"}],
        "user_status": {"status": "reading", "note": "继续看", "updated_at": "2026-06-28"},
        "entities": [
            {"name": "知识图谱", "type": "topic", "role": "topic", "confidence": 0.8}
        ],
        "media": [
            {"kind": "image", "index": 1, "url": "https://example.com/image.png", "status": "pending"}
        ],
        "citations": [
            {"ref": "paragraph_1", "source": "article_body", "text": "证据段落"}
        ],
        "note": "Full imported document context from the local store.",
    }

    markdown = render_document_markdown(package)

    assert "# 图谱文章" in markdown
    assert "URL: https://example.com/graph" in markdown
    assert "User status: reading" in markdown
    assert "Status note: 继续看" in markdown
    assert "## User Tags" in markdown
    assert "- 知识管理" in markdown
    assert "## User Notes" in markdown
    assert "我的判断" in markdown
    assert "知识图谱 (topic, role=topic, confidence=0.8)" in markdown
    assert "image[1]: https://example.com/image.png (pending)" in markdown
    assert "paragraph_1 (article_body)" in markdown
    assert "正文内容" in markdown


def test_dump_docs_markdown_writes_one_file_per_document_and_manifest(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/first", html)
    first["article"]["title"] = "第一篇/含非法字符"
    second = build_wechat_context("https://mp.weixin.qq.com/s/second", html)
    second["article"]["title"] = "第二篇文章"
    import_context(conn, first)
    import_context(conn, second)

    manifest = dump_docs_markdown(conn, tmp_path, limit=10)

    assert manifest["format"] == "markdown-documents"
    assert len(manifest["files"]) == 2
    assert manifest["documents"][0]["id"] == 2
    assert manifest["documents"][0]["file"].startswith("0002-第二篇文章")
    assert manifest["documents"][1]["file"] == "0001-第一篇_含非法字符.md"
    markdown = (tmp_path / manifest["documents"][0]["file"]).read_text(encoding="utf-8")
    assert "# 第二篇文章" in markdown
    assert "## Citations" in markdown
    assert "## Content" in markdown
    assert set(manifest["file_details"]) == set(manifest["files"])
    file_bytes = (tmp_path / manifest["documents"][0]["file"]).read_bytes()
    assert manifest["file_details"][manifest["documents"][0]["file"]] == {
        "size_bytes": len(file_bytes),
        "sha256": hashlib.sha256(file_bytes).hexdigest(),
    }
    assert (tmp_path / "manifest.json").exists()


def test_verify_docs_markdown_passes_for_clean_export(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    dump_docs_markdown(conn, tmp_path, limit=10)

    report = verify_docs_markdown(tmp_path)

    assert report["ok"] is True
    assert report["errors"] == []
    assert report["manifest"]["format"] == "markdown-documents"
    assert report["manifest"]["documents"] == 1
    assert next(iter(report["files"].values()))["ok"] is True


def test_verify_docs_markdown_fails_for_modified_file(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    manifest = dump_docs_markdown(conn, tmp_path, limit=10)
    (tmp_path / manifest["files"][0]).write_text("tampered", encoding="utf-8")

    report = verify_docs_markdown(tmp_path)

    assert report["ok"] is False
    assert f"{manifest['files'][0]} does not match manifest detail" in report["errors"]
    assert report["files"][manifest["files"][0]]["ok"] is False


def test_render_verify_docs_markdown_includes_files_and_errors() -> None:
    report = {
        "path": "outputs/markdown-docs",
        "ok": False,
        "errors": ["0001-doc.md does not match manifest detail"],
        "extra_files": ["extra.md"],
        "manifest": {"documents": 1},
        "files": {
            "0001-doc.md": {"ok": False},
            "0002-doc.md": {"ok": True},
        },
    }

    markdown = render_verify_docs_markdown(report)

    assert "# Link2Context Markdown Docs Verification" in markdown
    assert "- Documents: 1" in markdown
    assert "0001-doc.md does not match manifest detail" in markdown
    assert "- extra.md" in markdown
    assert "- fail 0001-doc.md" in markdown
    assert "- ok 0002-doc.md" in markdown


def test_citation_lookup_returns_specific_ref() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["agent_package"]["citations"] = [
        {"ref": "paragraph_1", "text": "第一段证据", "source": "article_body"},
        {"ref": "paragraph_2", "text": "第二段证据", "source": "article_body"},
    ]
    import_context(conn, context)

    package = citation_lookup(conn, "1", "paragraph_2")

    assert package["found"] is True
    assert package["document"]["id"] == 1
    assert package["citations"] == [
        {"ref": "paragraph_2", "text": "第二段证据", "source": "article_body"}
    ]


def test_citation_lookup_lists_all_document_citations() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)

    package = citation_lookup(conn, "https://mp.weixin.qq.com/s/example")

    assert package["found"] is True
    assert len(package["citations"]) == len(context["agent_package"]["citations"])


def test_render_citation_markdown_includes_ref_and_text() -> None:
    package = {
        "query": "1",
        "ref": "paragraph_2",
        "found": True,
        "document": {
            "id": 1,
            "title": "证据文章",
            "url": "https://example.com/doc",
        },
        "citations": [
            {"ref": "paragraph_2", "text": "第二段证据", "source": "article_body"}
        ],
        "note": "Citation evidence.",
    }

    markdown = render_citation_markdown(package)

    assert "# Link2Context Citation Evidence" in markdown
    assert "Document: [1] 证据文章" in markdown
    assert "## paragraph_2" in markdown
    assert "第二段证据" in markdown


def test_evidence_report_searches_citations_across_store() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["article"]["title"] = "产品观察"
    context["agent_package"]["citations"] = [
        {"ref": "paragraph_custom", "text": "ProductX 是可核查的证据。", "source": "article_body"},
        {"ref": "paragraph_other", "text": "另一段不相关内容。", "source": "article_body"},
    ]
    import_context(conn, context)

    report = evidence_report(conn, "ProductX", 10)

    assert report["query"] == "ProductX"
    assert len(report["items"]) == 1
    assert report["items"][0]["ref"] == "paragraph_custom"
    assert report["items"][0]["text"] == "ProductX 是可核查的证据。"
    assert report["items"][0]["document"]["id"] == 1
    assert report["items"][0]["document"]["title"] == "产品观察"


def test_render_evidence_markdown_includes_follow_up_command() -> None:
    report = {
        "query": "ProductX",
        "limit": 10,
        "items": [
            {
                "ref": "paragraph_custom",
                "text": "ProductX 是可核查的证据。",
                "source": "article_body",
                "document": {
                    "id": 1,
                    "title": "产品观察",
                    "url": "https://example.com/doc",
                    "platform": "wechat",
                    "account_name": "测试账号",
                    "quality_status": "ok",
                },
            }
        ],
        "note": "Citation evidence.",
    }

    markdown = render_evidence_markdown(report)

    assert "# Link2Context Evidence" in markdown
    assert "ProductX 是可核查的证据。" in markdown
    assert "citation 1 paragraph_custom" in markdown


def test_related_documents_returns_shared_entity_matches() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/first", html)
    first["article"]["title"] = "ProductX 入门"
    first["content"]["plain_text"] += " ProductX GraphTool"
    second = build_wechat_context("https://mp.weixin.qq.com/s/second", html)
    second["article"]["title"] = "ProductX 进阶"
    second["content"]["plain_text"] += " ProductX GraphTool"
    third = build_wechat_context("https://mp.weixin.qq.com/s/third", html)
    third["article"]["title"] = "无关文章"
    third["article"]["account_name"] = "另一个账号"
    third["content"]["plain_text"] = "CompletelyDifferentTerm"
    first_id = import_context(conn, first)
    import_context(conn, second)
    import_context(conn, third)

    package = related_documents(conn, str(first_id), limit=5)

    assert package["found"] is True
    assert package["source"]["title"] == "ProductX 入门"
    assert package["results"][0]["title"] == "ProductX 进阶"
    assert "ProductX" in package["results"][0]["entities"]
    assert "无关文章" not in {result["title"] for result in package["results"]}


def test_related_documents_returns_not_found_payload() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)

    package = related_documents(conn, "999")

    assert package == {
        "query": "999",
        "found": False,
        "source": None,
        "results": [],
        "note": "No matching source document found by id or URL.",
    }


def test_render_related_markdown_includes_shared_entities() -> None:
    package = {
        "found": True,
        "source": {"title": "ProductX 入门", "url": "https://example.com/first"},
        "results": [
            {
                "title": "ProductX 进阶",
                "url": "https://example.com/second",
                "platform": "wechat_official_account",
                "account_name": "灵渠测试号",
                "shared_entities": 2,
                "score": 1.2,
                "entities": ["ProductX", "GraphTool"],
            }
        ],
        "note": "Rule-based.",
    }

    markdown = render_related_markdown(package)

    assert "# Link2Context Related Documents" in markdown
    assert "Source: ProductX 入门" in markdown
    assert "ProductX 进阶" in markdown
    assert "Entities: ProductX, GraphTool" in markdown


def test_duplicate_report_groups_by_canonical_url_and_title() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://www.xiaohongshu.com/explore/abc?share_id=one&xsec_token=one", html)
    first["source"]["platform"] = "xiaohongshu"
    first["article"]["title"] = "同一篇收藏"
    second = build_wechat_context("https://www.xiaohongshu.com/explore/abc?share_id=two&xsec_token=two", html)
    second["source"]["platform"] = "xiaohongshu"
    second["article"]["title"] = "另一个标题"
    third = build_wechat_context("https://mp.weixin.qq.com/s/title-one", html)
    third["article"]["title"] = "重复标题"
    fourth = build_wechat_context("https://mp.weixin.qq.com/s/title-two", html)
    fourth["article"]["title"] = "重复标题"
    for context in (first, second, third, fourth):
        import_context(conn, context)

    report = duplicate_report(conn)

    kinds = {group["kind"] for group in report["groups"]}
    assert "same_canonical_url" in kinds
    assert "same_normalized_title" in kinds
    url_group = next(group for group in report["groups"] if group["kind"] == "same_canonical_url")
    assert url_group["key"] == "https://www.xiaohongshu.com/explore/abc"
    assert {document["id"] for document in url_group["documents"]} == {1, 2}
    title_group = next(group for group in report["groups"] if group["kind"] == "same_normalized_title")
    assert title_group["key"] == "重复标题"
    assert {document["id"] for document in title_group["documents"]} == {3, 4}


def test_render_duplicate_markdown_includes_groups_and_documents() -> None:
    report = {
        "summary": {"groups": 1, "documents": 2},
        "limit": 20,
        "groups": [
            {
                "kind": "same_normalized_title",
                "key": "重复标题",
                "documents": [
                    {
                        "id": 1,
                        "title": "重复标题",
                        "url": "https://example.com/a",
                        "platform": "wechat_official_account",
                        "account_name": "测试账号",
                    },
                    {
                        "id": 2,
                        "title": "重复标题",
                        "url": "https://example.com/b",
                        "platform": "wechat_official_account",
                        "account_name": "测试账号",
                    },
                ],
            }
        ],
        "note": "Review before deleting.",
    }

    markdown = render_duplicate_markdown(report)

    assert "# Link2Context Duplicates" in markdown
    assert "- Groups: 1" in markdown
    assert "same_normalized_title" in markdown
    assert "重复标题" in markdown
    assert "https://example.com/a" in markdown
    assert "Review before deleting." in markdown


def test_import_context_extracts_entities_and_relationships() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)

    import_context(conn, context)

    entity_names = {row["name"] for row in list_entities(conn)}
    relation_count = conn.execute("SELECT COUNT(*) AS count FROM relationships").fetchone()["count"]
    assert "灵渠测试号" in entity_names
    assert "示例公众号文章" in entity_names
    assert relation_count >= 2


def test_explain_entity_returns_documents_citations_and_relations() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["article"]["title"] = "产品观察"
    context["content"]["plain_text"] += " ProductX 是一个适合知识图谱测试的工具。"
    context["agent_package"]["citations"] = [
        {
            "ref": "paragraph_custom",
            "text": "ProductX 是一个适合知识图谱测试的工具。",
            "source": "article_body",
        }
    ]
    import_context(conn, context)

    explanation = explain_entity(conn, "ProductX")

    assert explanation["found"] is True
    assert explanation["entity"]["name"] == "ProductX"
    assert explanation["documents"][0]["title"] == "产品观察"
    assert explanation["documents"][0]["role"] == "term"
    assert explanation["citations"][0]["text"] == "ProductX 是一个适合知识图谱测试的工具。"
    assert explanation["relations"][0]["predicate"] == "mentions"


def test_explain_entity_returns_not_found_payload() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)

    explanation = explain_entity(conn, "不存在的实体")

    assert explanation == {
        "query": "不存在的实体",
        "found": False,
        "entity": None,
        "documents": [],
        "citations": [],
        "relations": [],
        "note": "No matching entity found in the local store.",
    }


def test_render_entity_explanation_markdown_includes_evidence() -> None:
    explanation = {
        "found": True,
        "entity": {
            "name": "ProductX",
            "type": "term",
            "normalized_name": "productx",
        },
        "documents": [
            {
                "title": "产品观察",
                "url": "https://example.com/productx",
                "platform": "wechat_official_account",
                "account_name": "灵渠测试号",
                "role": "term",
                "evidence": "content.plain_text",
            }
        ],
        "citations": [
            {
                "ref": "paragraph_custom",
                "title": "产品观察",
                "text": "ProductX 是一个适合知识图谱测试的工具。",
            }
        ],
        "relations": [
            {
                "subject": "产品观察",
                "predicate": "mentions",
                "object": "ProductX",
                "confidence": 0.5,
                "evidence": "content.plain_text",
                "title": "产品观察",
            }
        ],
        "note": "Rule-based.",
    }

    markdown = render_entity_explanation_markdown(explanation)

    assert "# Link2Context Entity: ProductX" in markdown
    assert "URL: https://example.com/productx" in markdown
    assert "paragraph_custom | 产品观察" in markdown
    assert "产品观察 --mentions--> ProductX" in markdown


def test_interest_profile_aggregates_imported_context() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)

    import_context(conn, context)
    profile = interest_profile(conn)

    assert profile["documents"] == 1
    assert profile["top_accounts"][0]["name"] == "灵渠测试号"
    assert profile["top_accounts"][0]["documents"] == 1
    assert profile["top_accounts"][0]["evidence_documents"][0]["title"] == "示例公众号文章"
    assert profile["by_platform"] == {"wechat_official_account": 1}
    topic = next(entity for entity in profile["top_entities"] if entity["name"] == "示例公众号文章")
    assert topic["evidence_documents"][0]["url"] == "https://mp.weixin.qq.com/s/example"
    assert profile["recent_documents"][0]["title"] == "示例公众号文章"
    assert profile["recent_entities"][0]["latest_at"]
    assert profile["recent_accounts"][0]["name"] == "灵渠测试号"


def test_interest_profile_includes_recency_signals() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    older = build_wechat_context("https://mp.weixin.qq.com/s/older", html)
    older["article"]["title"] = "旧收藏 ProductX"
    older["article"]["account_name"] = "旧账号"
    older["article"]["published_at"] = "2026-01-01T00:00:00+00:00"
    older["content"]["plain_text"] += " ProductX"
    newer = build_wechat_context("https://mp.weixin.qq.com/s/newer", html)
    newer["article"]["title"] = "新收藏 ProductY"
    newer["article"]["account_name"] = "新账号"
    newer["article"]["published_at"] = "2026-02-01T00:00:00+00:00"
    newer["content"]["plain_text"] += " ProductY"
    import_context(conn, older)
    import_context(conn, newer)

    profile = interest_profile(conn, limit=10)

    assert [item["title"] for item in profile["recent_documents"][:2]] == [
        "新收藏 ProductY",
        "旧收藏 ProductX",
    ]
    product_y = next(entity for entity in profile["recent_entities"] if entity["name"] == "ProductY")
    assert product_y["latest_at"] == "2026-02-01T00:00:00+00:00"
    assert profile["recent_accounts"][0]["name"] == "新账号"
    assert profile["recent_accounts"][0]["latest_at"] == "2026-02-01T00:00:00+00:00"


def test_interest_profile_includes_citation_evidence() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["article"]["title"] = "产品观察"
    context["content"]["plain_text"] += " ProductX 是一个适合知识图谱测试的工具。"
    context["agent_package"]["citations"] = [
        {
            "ref": "paragraph_custom",
            "text": "ProductX 是一个适合知识图谱测试的工具。",
            "source": "article_body",
        }
    ]

    import_context(conn, context)
    profile = interest_profile(conn)

    product = next(entity for entity in profile["top_entities"] if entity["name"] == "ProductX")
    assert product["evidence_citations"] == [
        {
            "ref": "paragraph_custom",
            "text": "ProductX 是一个适合知识图谱测试的工具。",
            "source": "article_body",
            "title": "产品观察",
            "url": "https://mp.weixin.qq.com/s/example",
            "platform": "wechat_official_account",
        }
    ]


def test_interest_profile_includes_confidence_and_media_text_counts() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/media-profile", html)
    document_id = import_context(conn, context)
    conn.execute(
        "UPDATE media SET text = ?, status = 'processed' WHERE document_id = ? AND media_index = 1",
        ("MediaProfileNeedle 出现在 OCR 文本中。", document_id),
    )

    reindex_media_text(conn, limit=10)
    profile = interest_profile(conn)

    media_entity = next(entity for entity in profile["top_entities"] if entity["name"] == "MediaProfileNeedle")
    recent_media_entity = next(
        entity for entity in profile["recent_entities"] if entity["name"] == "MediaProfileNeedle"
    )
    assert media_entity["avg_confidence"] == 0.55
    assert media_entity["media_documents"] == 1
    assert recent_media_entity["avg_confidence"] == 0.55
    assert recent_media_entity["media_documents"] == 1


def test_interest_profile_matches_citation_aliases_for_topics_and_terms() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/alias", html)
    context["article"]["title"] = "知识图谱方法论 ProductX"
    context["content"]["plain_text"] += " ProductX"
    context["agent_package"]["citations"] = [
        {
            "ref": "paragraph_topic",
            "text": "知识图谱可以把收藏内容连接起来。",
            "source": "article_body",
        },
        {
            "ref": "paragraph_term",
            "text": "Product X 也可以作为工具词被追溯。",
            "source": "article_body",
        },
    ]

    import_context(conn, context)
    profile = interest_profile(conn)

    topic = next(entity for entity in profile["top_entities"] if entity["name"] == "知识图谱方法论")
    product = next(entity for entity in profile["top_entities"] if entity["name"] == "ProductX")
    assert topic["evidence_citations"][0]["ref"] == "paragraph_topic"
    assert product["evidence_citations"][0]["ref"] == "paragraph_term"


def test_interest_profile_filters_generic_terms() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["content"]["plain_text"] += " AI Agent Skill Article Image Video Markdown JSON URL Content Context ProductX"

    import_context(conn, context)
    profile = interest_profile(conn)

    entity_names = {entity["name"] for entity in profile["top_entities"]}
    assert {
        "AI",
        "Agent",
        "Skill",
        "Article",
        "Image",
        "Video",
        "Markdown",
        "JSON",
        "URL",
        "Content",
        "Context",
    }.isdisjoint(entity_names)
    assert "ProductX" in entity_names


def test_render_profile_markdown_includes_evidence() -> None:
    profile = {
        "documents": 2,
        "by_platform": {"wechat_official_account": 2},
        "top_entities": [
            {
                "name": "知识图谱",
                "type": "topic",
                "documents": 1,
                "avg_confidence": 0.8,
                "media_documents": 1,
                "evidence_documents": [
                    {"title": "图谱文章", "url": "https://example.com/graph"}
                ],
            }
        ],
        "top_accounts": [
            {
                "name": "灵渠测试号",
                "documents": 2,
                "evidence_documents": [
                    {"title": "账号文章", "url": "https://example.com/account"}
                ],
            }
        ],
        "recent_documents": [
            {
                "title": "最近图谱",
                "url": "https://example.com/recent",
                "published_at": "2026-02-01T00:00:00+00:00",
            }
        ],
        "recent_entities": [
            {
                "name": "ProductX",
                "type": "term",
                "documents": 1,
                "latest_at": "2026-02-01T00:00:00+00:00",
                "avg_confidence": 0.55,
                "media_documents": 1,
            }
        ],
        "recent_accounts": [
            {
                "name": "最近账号",
                "documents": 1,
                "latest_at": "2026-02-01T00:00:00+00:00",
            }
        ],
        "note": "Conservative profile.",
    }

    markdown = render_profile_markdown(profile)

    assert "# Link2Context Interest Profile" in markdown
    assert "- wechat_official_account: 2" in markdown
    assert "知识图谱 (topic): 1 document(s), avg confidence 0.80, 1 media-text document(s)" in markdown
    assert "https://example.com/graph" in markdown
    assert "灵渠测试号: 2 document(s)" in markdown
    assert "https://example.com/account" in markdown
    assert "## Recent Documents" in markdown
    assert "最近图谱" in markdown
    assert "## Recent Entities" in markdown
    assert (
        "ProductX (term): latest 2026-02-01T00:00:00+00:00, "
        "1 document(s), avg confidence 0.55, 1 media-text document(s)"
    ) in markdown
    assert "## Recent Accounts" in markdown
    assert "最近账号: latest 2026-02-01T00:00:00+00:00" in markdown


def test_inbox_report_combines_recent_quality_media_topics_and_actions() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["quality"]["status"] = "partial"
    context["quality"]["warnings"] = ["missing_media_text"]
    context["quality"]["missing_fields"] = ["ocr"]
    context["content"]["plain_text"] += " ProductX"
    import_context(conn, context)

    inbox = inbox_report(conn, limit=5)

    assert inbox["status"] == "ok"
    assert inbox["stats"]["documents"] == 1
    assert inbox["recent_documents"][0]["title"] == "示例公众号文章"
    assert inbox["quality_issues"][0]["warnings"] == ["missing_media_text"]
    assert inbox["pending_media"]
    assert any(topic["name"] == "ProductX" for topic in inbox["top_topics"])
    assert inbox["actions"]
    assert "queue --format jsonl" in inbox["commands"][1]


def test_render_inbox_markdown_includes_daily_triage_sections() -> None:
    report = {
        "status": "ok",
        "ready_for_agent": True,
        "stats": {"documents": 2, "citations": 5},
        "recent_documents": [
            {"id": 2, "title": "最近文章", "url": "https://example.com/recent", "published_at": "2026-06-28"}
        ],
        "quality_issues": [
            {"id": 1, "title": "待修文章", "status": "partial", "warnings": ["missing"], "missing_fields": ["ocr"]}
        ],
        "pending_media": [
            {
                "kind": "image",
                "index": 1,
                "status": "not_processed",
                "url": "https://example.com/image.png",
                "document": {"id": 1},
            }
        ],
        "top_topics": [{"name": "ProductX", "type": "term", "documents": 2}],
        "top_clusters": [
            {
                "name": "ProductX",
                "type": "term",
                "documents": 2,
                "commands": {"explain": "python -m link2context.store --db data/link2context.db explain ProductX"},
            }
        ],
        "actions": [
            {"priority": 2, "kind": "quality", "title": "Review doc", "command": "python -m link2context.store --db data/link2context.db doc 1"}
        ],
        "commands": ["python -m link2context.store --db data/link2context.db review"],
        "note": "Daily triage.",
    }

    markdown = render_inbox_markdown(report)

    assert "# Link2Context Inbox" in markdown
    assert "## Recent" in markdown
    assert "## Quality Issues" in markdown
    assert "## Pending Media" in markdown
    assert "## Top Topics" in markdown
    assert "## Next Actions" in markdown
    assert "Daily triage." in markdown


def test_curate_report_groups_documents_into_action_lanes() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/first", html)
    first["article"]["title"] = "可阅读文章"
    second = build_wechat_context("https://mp.weixin.qq.com/s/second", html)
    second["article"]["title"] = "重复标题"
    third = build_wechat_context("https://mp.weixin.qq.com/s/third", html)
    third["article"]["title"] = "重复标题"
    third["quality"]["status"] = "partial"
    third["quality"]["warnings"] = ["short body"]
    import_context(conn, first)
    import_context(conn, second)
    import_context(conn, third)

    report = curate_report(conn, limit=10)

    lanes = {lane["name"]: lane for lane in report["lanes"]}
    assert lanes["read_now"]["items"]
    assert lanes["fix_quality"]["items"][0]["title"] == "重复标题"
    assert lanes["process_media"]["items"]
    assert lanes["process_media"]["items"][0]["reason"] == "needs_local_cache"
    assert "cache-media --kind image --status not_processed" in lanes["process_media"]["items"][0]["command"]
    assert lanes["review_duplicates"]["items"]
    assert lanes["agent_handoff"]["items"]
    assert report["coverage"]["media_pending"] > 0


def test_curate_report_process_media_includes_low_confidence_review(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    results_path = tmp_path / "ocr.jsonl"
    results_path.write_text(
        json.dumps(
            {
                "kind": "image",
                "output_hint": {"document_id": 1, "media_index": 1},
                "text": "低置信度 OCR 文本",
                "confidence": 0.61,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    apply_media_text(conn, results_path, status="processed")

    report = curate_report(conn, limit=10)
    lanes = {lane["name"]: lane for lane in report["lanes"]}
    review_items = [
        item
        for item in lanes["process_media"]["items"]
        if item.get("reason") == "low_confidence_text"
    ]
    markdown = render_curate_markdown(report)

    assert review_items
    assert review_items[0]["text_confidence"] == 0.61
    assert review_items[0]["low_confidence_threshold"] == 0.7
    assert "Reason: low_confidence_text" in markdown
    assert "confidence=0.61; threshold=0.70" in markdown


def test_render_curate_markdown_includes_lanes_and_commands() -> None:
    report = {
        "status": "ok",
        "ready_for_agent": True,
        "stats": {"documents": 2, "citations": 4, "entities": 3},
        "lanes": [
            {
                "name": "read_now",
                "title": "Read Now",
                "purpose": "Recent good-enough documents.",
                "items": [
                    {
                        "id": 1,
                        "title": "图谱文章",
                        "url": "https://example.com/graph",
                        "command": "python -m link2context.store --db data/link2context.db doc 1",
                    }
                ],
            },
            {
                "name": "process_media",
                "title": "Process Media",
                "purpose": "Images or videos.",
                "items": [
                    {
                        "document_id": 1,
                        "title": "图谱文章",
                        "kind": "image",
                        "index": 0,
                        "status": "not_processed",
                        "url": "https://example.com/image.png",
                        "command": "python -m link2context.store --db data/link2context.db queue --format jsonl",
                    }
                ],
            },
        ],
        "gaps": [
            {"severity": "medium", "kind": "media", "detail": "1 media item needs OCR."}
        ],
        "commands": ["python -m link2context.store --db data/link2context.db coverage"],
        "note": "Read-only.",
    }

    markdown = render_curate_markdown(report)

    assert "# Link2Context Curate" in markdown
    assert "## Read Now" in markdown
    assert "[1] 图谱文章" in markdown
    assert "## Process Media" in markdown
    assert "image[0]" in markdown
    assert "medium [media] 1 media item needs OCR." in markdown
    assert "`python -m link2context.store --db data/link2context.db coverage`" in markdown
    assert "Read-only." in markdown


def test_external_brain_brief_summarizes_store_for_agents() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    first["content"]["plain_text"] += " ProductX"
    second = build_wechat_context("https://mp.weixin.qq.com/s/second", html)
    second["article"]["title"] = "第二篇文章"
    second["content"]["plain_text"] += " ProductX"
    import_context(conn, first)
    import_context(conn, second)
    add_document_tags(conn, "1", ["知识管理"])
    add_document_note(conn, "1", "值得之后追问。")
    mark_document_status(conn, "1", "later", "今晚处理")

    brief = external_brain_brief(conn, limit=3)

    assert brief["project"] == "Link2Context"
    assert brief["stats"]["documents"] == 2
    assert brief["profile"]["documents"] == 2
    assert next(cluster for cluster in brief["clusters"] if cluster["name"] == "ProductX")
    assert brief["annotations"]["summary"] == {
        "documents": 1,
        "with_tags": 1,
        "with_notes": 1,
        "with_status": 1,
    }
    assert brief["annotations"]["documents"][0]["tags"] == ["知识管理"]
    assert brief["starter_queries"][0]["query"] == "知识管理"
    assert brief["starter_queries"][0]["source"] == "user_tag"
    assert 'query "知识管理" --format markdown' in brief["starter_queries"][0]["command"]
    assert brief["recent_documents"][0] == {
        "id": 2,
        "title": "第二篇文章",
        "url": "https://mp.weixin.qq.com/s/second",
        "platform": "wechat_official_account",
        "account_name": "灵渠测试号",
        "published_at": "2026-06-28T04:00:00+00:00",
        "quality_status": "ok",
    }
    assert brief["recent_documents"][1] == (
        {
            "id": 1,
            "title": "示例公众号文章",
            "url": "https://mp.weixin.qq.com/s/example",
            "platform": "wechat_official_account",
            "account_name": "灵渠测试号",
            "published_at": "2026-06-28T04:00:00+00:00",
            "quality_status": "ok",
        }
    )
    assert "query" in brief["agent_usage"]["query_command"]
    assert "clusters" in brief["agent_usage"]["clusters_command"]
    assert "questions" in brief["agent_usage"]["questions_command"]
    assert "annotations" in brief["agent_usage"]["annotations_command"]


def test_recent_documents_returns_newest_imports() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    first = build_wechat_context("https://mp.weixin.qq.com/s/first", html)
    second = build_wechat_context("https://mp.weixin.qq.com/s/second", html)
    second["article"]["title"] = "第二篇文章"

    import_context(conn, first)
    import_context(conn, second)

    documents = recent_documents(conn, limit=1)

    assert documents[0]["title"] == "第二篇文章"
    assert documents[0]["id"] == 2
    assert documents[0]["url"] == "https://mp.weixin.qq.com/s/second"


def test_starter_queries_prioritize_user_signals_and_dedupe() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["content"]["plain_text"] += " ProductX"
    import_context(conn, context)
    add_document_tags(conn, "1", ["知识管理"])
    add_document_note(conn, "1", "知识管理")
    mark_document_status(conn, "1", "later", "今晚处理")

    queries = starter_queries(conn, limit=5)

    assert queries[0]["query"] == "知识管理"
    assert queries[0]["source"] == "user_tag"
    assert [item["query"] for item in queries].count("知识管理") == 1
    assert any(item["query"] == "今晚处理" and item["source"] == "user_status" for item in queries)
    assert any(item["query"] == "ProductX" and item["source"] == "entity:term" for item in queries)


def test_render_starter_queries_markdown_outputs_commands() -> None:
    markdown = render_starter_queries_markdown(
        [
            {
                "query": "知识管理",
                "source": "user_tag",
                "reason": "User tag on 1 document(s).",
                "documents": 1,
                "command": 'python -m link2context.store --db data/link2context.db query "知识管理" --format markdown',
            }
        ]
    )

    assert "# Link2Context Starter Queries" in markdown
    assert "## 1. 知识管理" in markdown
    assert "- Source: user_tag, documents=1" in markdown
    assert 'query "知识管理" --format markdown' in markdown


def test_render_brief_markdown_includes_agent_commands() -> None:
    brief = {
        "purpose": "Agent-ready brief.",
        "stats": {
            "documents": 2,
            "citations": 5,
            "entities": 3,
            "relationships": 4,
            "by_platform": {"wechat_official_account": 2},
        },
        "profile": {
            "top_entities": [
                {"name": "知识图谱", "type": "topic", "documents": 2}
            ],
            "top_accounts": [
                {"name": "灵渠测试号", "documents": 2}
            ],
        },
        "annotations": {
            "summary": {"documents": 1, "with_tags": 1, "with_notes": 1, "with_status": 1},
            "documents": [
                {
                    "id": 1,
                    "title": "图谱文章",
                    "user_status": {"status": "later"},
                    "tags": ["知识管理"],
                    "notes": [{"note": "值得之后追问。"}],
                }
            ],
        },
        "clusters": [
            {
                "name": "ProductX",
                "type": "term",
                "documents": 2,
                "commands": {
                    "explain": 'python -m link2context.store --db data/link2context.db explain "ProductX"',
                    "evidence": 'python -m link2context.store --db data/link2context.db evidence "ProductX"',
                },
            }
        ],
        "starter_queries": [
            {
                "query": "知识管理",
                "source": "user_tag",
                "reason": "User tag on 1 document(s).",
                "documents": 1,
                "command": 'python -m link2context.store --db data/link2context.db query "知识管理" --format markdown',
            }
        ],
        "recent_documents": [
            {
                "title": "图谱文章",
                "url": "https://example.com/graph",
                "platform": "wechat_official_account",
                "account_name": "灵渠测试号",
            }
        ],
        "agent_usage": {
            "query_command": "python -m link2context.store --db data/link2context.db query \"<question>\" --format markdown",
            "clusters_command": "python -m link2context.store --db data/link2context.db clusters",
            "questions_command": "python -m link2context.store --db data/link2context.db questions",
            "annotations_command": "python -m link2context.store --db data/link2context.db annotations",
            "graph_command": "python -m link2context.store --db data/link2context.db graph --format mermaid",
            "profile_command": "python -m link2context.store --db data/link2context.db profile --format markdown",
            "caution": "Use citations.",
        },
        "note": "Imported contexts only.",
    }

    markdown = render_brief_markdown(brief)

    assert "# Link2Context External Brain Brief" in markdown
    assert "- Documents: 2" in markdown
    assert "知识图谱 (topic): 2 document(s)" in markdown
    assert "## Topic Clusters" in markdown
    assert "## User Annotations" in markdown
    assert "Tags: 知识管理" in markdown
    assert "值得之后追问。" in markdown
    assert "## Starter Queries" in markdown
    assert 'query "知识管理" --format markdown' in markdown
    assert 'evidence "ProductX"' in markdown
    assert "https://example.com/graph" in markdown
    assert "python -m link2context.store --db data/link2context.db query" in markdown
    assert "python -m link2context.store --db data/link2context.db clusters" in markdown
    assert "python -m link2context.store --db data/link2context.db questions" in markdown
    assert "python -m link2context.store --db data/link2context.db annotations" in markdown
    assert "Imported contexts only." in markdown


def test_export_agent_handoff_writes_agent_bundle(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    add_document_tags(conn, "1", ["知识管理"])
    add_document_note(conn, "1", "这是我的个人判断。")
    mark_document_status(conn, "1", "later", "今晚处理")
    conn.execute(
        "UPDATE media SET local_path = ? WHERE document_id = ? AND kind = ? AND media_index = ?",
        ("outputs/media-cache/image.jpg", 1, "image", 1),
    )

    manifest = export_agent_handoff(conn, tmp_path, limit=3)

    assert manifest["project"] == "Link2Context"
    assert manifest["stats"]["documents"] == 1
    assert manifest["files"] == [
        "handoff.md",
        "auto-queue.commands.txt",
        "auto-queue.jsonl",
        "inbox.md",
        "inbox.json",
        "curate.md",
        "curate.json",
        "duplicates.md",
        "duplicates.json",
        "coverage.md",
        "coverage.json",
        "review.md",
        "review.json",
        "brief.md",
        "brief.json",
        "starter-queries.md",
        "starter-queries.json",
        "doctor.md",
        "doctor.json",
        "quality.md",
        "quality.json",
        "evidence.md",
        "evidence.json",
        "actions.md",
        "actions.json",
        "agent-tasks.md",
        "agent-tasks.json",
        "digest.md",
        "digest.json",
        "sources.md",
        "sources.json",
        "tags.md",
        "tags.json",
        "notes.md",
        "notes.json",
        "statuses.md",
        "statuses.json",
        "annotations.md",
        "annotations.json",
        "topics.md",
        "topics.json",
        "clusters.md",
        "clusters.json",
        "questions.md",
        "questions.json",
        "relations.md",
        "relations.json",
        "profile.md",
        "profile.json",
        "timeline.md",
        "timeline.json",
        "media-pipeline.md",
        "media-pipeline.json",
        "queue.md",
        "queue.json",
        "media.md",
        "media.json",
        "graph.json",
        "graph.mmd",
    ]
    assert set(manifest["file_details"]) == set(manifest["files"])
    assert manifest["media_pipeline"]["counts"]["local_ready"] == 1
    assert "media-pipeline.md" in manifest["files"]
    brief_bytes = (tmp_path / "brief.md").read_bytes()
    assert manifest["file_details"]["brief.md"] == {
        "size_bytes": len(brief_bytes),
        "sha256": hashlib.sha256(brief_bytes).hexdigest(),
    }
    assert any(
        entry["command"].endswith("queue --kind image --status not_processed --format jsonl")
        and entry["kind"] == "media"
        and entry["source"] == "actions"
        and isinstance(entry["priority"], int)
        and entry["reason"]
        and entry["automation"] == "auto_queue"
        and entry["requires_review"] is False
        for entry in manifest["hot_commands"]
    )
    assert manifest["hot_command_groups"]["auto_queue"]
    assert all(entry["automation"] == "auto_queue" for entry in manifest["hot_command_groups"]["auto_queue"])
    assert all(entry["requires_review"] for entry in manifest["hot_command_groups"]["manual_review"])
    assert sorted(
        entry["command"]
        for group in manifest["hot_command_groups"].values()
        for entry in group
    ) == sorted(entry["command"] for entry in manifest["hot_commands"])
    assert (tmp_path / "manifest.json").exists()
    manifest_json = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_json["hot_commands"] == manifest["hot_commands"]
    assert manifest_json["hot_command_groups"] == manifest["hot_command_groups"]
    auto_queue_commands = (tmp_path / "auto-queue.commands.txt").read_text(encoding="utf-8")
    assert "queue --kind image --status not_processed --format jsonl" in auto_queue_commands
    auto_queue_jsonl = (tmp_path / "auto-queue.jsonl").read_text(encoding="utf-8").splitlines()
    assert auto_queue_jsonl
    assert all(json.loads(line)["automation"] == "auto_queue" for line in auto_queue_jsonl)
    handoff = (tmp_path / "handoff.md").read_text(encoding="utf-8")
    assert "# Link2Context Agent Handoff" in handoff
    assert "`inbox.md` - start with daily triage and next actions." in handoff
    assert "`curate.md` - choose the next action lane: read, fix, process media, or hand off." in handoff
    assert "`duplicates.md` - inspect repeated or near-duplicate documents." in handoff
    assert "`coverage.md` - inspect platform, source, graph, and media coverage gaps." in handoff
    assert "`media-pipeline.md/json` - inspect OCR/ASR pipeline status and blockers." in handoff
    assert "## Media Pipeline" in handoff
    assert "- Details: `media-pipeline.md`" in handoff
    assert "- Next commands:" in handoff
    assert "media-text-presets --format markdown" in handoff
    assert "prepare-media-model --url <model-url>" in handoff
    assert "`review.md` - read the one-page agent review." in handoff
    assert "`doctor.md` - check whether the store is ready for agent use." in handoff
    assert "`quality.md` - inspect low-quality or partial extractions." in handoff
    assert "`evidence.md` - inspect citation evidence snippets and follow-up citation commands." in handoff
    assert "`actions.md` - inspect prioritized next steps." in handoff
    assert "`agent-tasks.md/json` - inspect the machine-readable handoff checklist." in handoff
    assert "`digest.md` - review recent documents, topics, sources, quality, and actions together." in handoff
    assert "`starter-queries.md/json` - use machine-readable first queries for agent handoff." in handoff
    assert "`sources.md` - inspect source accounts and platform distribution." in handoff
    assert "`tags.md` - inspect user-added personal tags." in handoff
    assert "`notes.md` - inspect user-written notes and judgments." in handoff
    assert "`statuses.md` - inspect user workflow statuses." in handoff
    assert "`annotations.md` - inspect combined user tags, notes, and statuses." in handoff
    assert "`topics.md` - inspect topic/entity signals with evidence." in handoff
    assert "`clusters.md` - inspect document clusters formed by shared entities." in handoff
    assert "`questions.md` - inspect generated follow-up questions for agent exploration." in handoff
    assert "`queue.md` - inspect OCR/ASR processing queue." in handoff
    assert "`relations.md` - inspect relationship edges with source documents." in handoff
    assert "## Hot Commands" in handoff
    assert "queue --kind image --status not_processed --format jsonl" in handoff
    assert "python -m link2context.store --db data/link2context.db doc <id>" in handoff
    assert "# Link2Context Review" in (tmp_path / "review.md").read_text(encoding="utf-8")
    assert "# Link2Context Inbox" in (tmp_path / "inbox.md").read_text(encoding="utf-8")
    assert "# Link2Context Curate" in (tmp_path / "curate.md").read_text(encoding="utf-8")
    assert "# Link2Context Duplicates" in (tmp_path / "duplicates.md").read_text(encoding="utf-8")
    assert "# Link2Context Coverage" in (tmp_path / "coverage.md").read_text(encoding="utf-8")
    assert "# Link2Context External Brain Brief" in (tmp_path / "brief.md").read_text(encoding="utf-8")
    assert "# Link2Context Starter Queries" in (tmp_path / "starter-queries.md").read_text(encoding="utf-8")
    assert "# Link2Context Store Doctor" in (tmp_path / "doctor.md").read_text(encoding="utf-8")
    assert "# Link2Context Quality Report" in (tmp_path / "quality.md").read_text(encoding="utf-8")
    assert "# Link2Context Evidence" in (tmp_path / "evidence.md").read_text(encoding="utf-8")
    assert "# Link2Context Actions" in (tmp_path / "actions.md").read_text(encoding="utf-8")
    assert "# Link2Context Agent Tasks" in (tmp_path / "agent-tasks.md").read_text(encoding="utf-8")
    assert "# Link2Context Digest" in (tmp_path / "digest.md").read_text(encoding="utf-8")
    assert "# Link2Context Sources" in (tmp_path / "sources.md").read_text(encoding="utf-8")
    assert "# Link2Context Tags" in (tmp_path / "tags.md").read_text(encoding="utf-8")
    assert "# Link2Context Notes" in (tmp_path / "notes.md").read_text(encoding="utf-8")
    assert "# Link2Context Statuses" in (tmp_path / "statuses.md").read_text(encoding="utf-8")
    assert "# Link2Context Annotations" in (tmp_path / "annotations.md").read_text(encoding="utf-8")
    assert "# Link2Context Topics" in (tmp_path / "topics.md").read_text(encoding="utf-8")
    assert "# Link2Context Clusters" in (tmp_path / "clusters.md").read_text(encoding="utf-8")
    assert "# Link2Context Questions" in (tmp_path / "questions.md").read_text(encoding="utf-8")
    assert "# Link2Context Relations" in (tmp_path / "relations.md").read_text(encoding="utf-8")
    assert "示例公众号文章" in (tmp_path / "profile.md").read_text(encoding="utf-8")
    assert "# Link2Context Timeline" in (tmp_path / "timeline.md").read_text(encoding="utf-8")
    assert "# Link2Context Media Queue" in (tmp_path / "queue.md").read_text(encoding="utf-8")
    assert "# Link2Context Media Inventory" in (tmp_path / "media.md").read_text(encoding="utf-8")
    assert "graph LR" in (tmp_path / "graph.mmd").read_text(encoding="utf-8")
    review_json = json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert review_json["status"] == "ok"
    doctor_json = json.loads((tmp_path / "doctor.json").read_text(encoding="utf-8"))
    assert doctor_json["status"] == "ok"
    quality_json = json.loads((tmp_path / "quality.json").read_text(encoding="utf-8"))
    assert quality_json["documents"]
    coverage_json = json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))
    assert coverage_json["coverage"]["documents_with_citations"] == 1
    curate_json = json.loads((tmp_path / "curate.json").read_text(encoding="utf-8"))
    assert curate_json["lanes"]
    evidence_json = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert evidence_json["items"]
    actions_json = json.loads((tmp_path / "actions.json").read_text(encoding="utf-8"))
    assert actions_json["actions"]
    digest_json = json.loads((tmp_path / "digest.json").read_text(encoding="utf-8"))
    assert digest_json["recent"]
    sources_json = json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))
    assert sources_json["sources"]
    tags_json = json.loads((tmp_path / "tags.json").read_text(encoding="utf-8"))
    assert tags_json["tags"][0]["tag"] == "知识管理"
    notes_json = json.loads((tmp_path / "notes.json").read_text(encoding="utf-8"))
    assert notes_json["notes"][0]["note"] == "这是我的个人判断。"
    statuses_json = json.loads((tmp_path / "statuses.json").read_text(encoding="utf-8"))
    assert statuses_json["documents"][0]["status"] == "later"
    annotations_json = json.loads((tmp_path / "annotations.json").read_text(encoding="utf-8"))
    assert annotations_json["documents"][0]["tags"] == ["知识管理"]
    starter_queries_json = json.loads((tmp_path / "starter-queries.json").read_text(encoding="utf-8"))
    assert starter_queries_json[0]["query"] == "知识管理"
    assert starter_queries_json[0]["source"] == "user_tag"
    agent_tasks_json = json.loads((tmp_path / "agent-tasks.json").read_text(encoding="utf-8"))
    assert agent_tasks_json["tasks"]
    assert any(task["kind"] == "query" and task["title"] == "Query: 知识管理" for task in agent_tasks_json["tasks"])
    topics_json = json.loads((tmp_path / "topics.json").read_text(encoding="utf-8"))
    assert topics_json["topics"]
    clusters_json = json.loads((tmp_path / "clusters.json").read_text(encoding="utf-8"))
    assert "clusters" in clusters_json
    questions_json = json.loads((tmp_path / "questions.json").read_text(encoding="utf-8"))
    assert "questions" in questions_json
    relations_json = json.loads((tmp_path / "relations.json").read_text(encoding="utf-8"))
    assert relations_json["relations"]
    timeline_json = json.loads((tmp_path / "timeline.json").read_text(encoding="utf-8"))
    assert timeline_json["documents"]
    queue_json = json.loads((tmp_path / "queue.json").read_text(encoding="utf-8"))
    assert "items" in queue_json
    media_json = json.loads((tmp_path / "media.json").read_text(encoding="utf-8"))
    assert media_json["items"]
    graph_json = json.loads((tmp_path / "graph.json").read_text(encoding="utf-8"))
    assert graph_json["nodes"]


def test_handoff_hot_commands_prioritizes_media_tasks() -> None:
    tasks = {
        "tasks": [
            {"kind": "query", "command": "query command"},
            {"kind": "media", "command": "queue command"},
            {"kind": "media_cache", "command": "cache command"},
            {"kind": "media", "command": "queue command"},
            {"kind": "handoff", "command": "handoff command"},
        ]
    }

    assert handoff_hot_commands(tasks) == [
        {
            "command": "queue command",
            "kind": "media",
            "priority": 9,
            "source": "",
            "reason": "",
            "automation": "auto_queue",
            "requires_review": False,
        },
        {
            "command": "cache command",
            "kind": "media_cache",
            "priority": 9,
            "source": "",
            "reason": "",
            "automation": "manual_review",
            "requires_review": True,
        },
    ]


def test_render_hot_command_execution_files() -> None:
    commands = [
        {
            "command": "queue command",
            "kind": "media",
            "priority": 3,
            "source": "actions",
            "reason": "ready",
            "automation": "auto_queue",
            "requires_review": False,
        }
    ]

    assert render_hot_command_commands(commands) == "queue command\n"
    assert json.loads(render_hot_command_jsonl(commands).strip()) == commands[0]
    assert render_hot_command_commands([]) == ""
    assert render_hot_command_jsonl([]) == ""


def test_verify_auto_queue_passes_for_matching_files(tmp_path: Path) -> None:
    media_path = tmp_path / "media.jpg"
    media_path.write_bytes(b"image")
    entry = {
        "command": "python -m link2context.store --db data/link2context.db queue --kind image --status not_processed --format jsonl",
        "kind": "media",
        "priority": 3,
        "source": "actions",
        "reason": f"local_path={media_path.name}; next_step=queue_media_text",
        "automation": "auto_queue",
        "requires_review": False,
    }
    (tmp_path / "auto-queue.commands.txt").write_text(entry["command"] + "\n", encoding="utf-8")
    (tmp_path / "auto-queue.jsonl").write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    report = verify_auto_queue(tmp_path, tmp_path)

    assert report["ok"] is True
    assert report["commands"] == 1
    assert report["entries"] == 1
    assert report["errors"] == []


def test_verify_auto_queue_fails_for_empty_or_missing_media(tmp_path: Path) -> None:
    entry = {
        "command": "queue command",
        "kind": "media",
        "priority": 3,
        "source": "actions",
        "reason": "local_path=missing.jpg; next_step=queue_media_text",
        "automation": "auto_queue",
        "requires_review": False,
    }
    (tmp_path / "auto-queue.commands.txt").write_text("", encoding="utf-8")
    (tmp_path / "auto-queue.jsonl").write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    report = verify_auto_queue(tmp_path, tmp_path)

    assert report["ok"] is False
    assert "auto-queue.commands.txt has no executable commands" in report["errors"]
    assert any("local_path does not exist" in error for error in report["errors"])


def test_render_verify_auto_queue_markdown_includes_errors() -> None:
    report = {
        "path": "outputs/agent-handoff",
        "base_dir": ".",
        "ok": False,
        "commands": 0,
        "entries": 1,
        "errors": ["auto-queue.commands.txt has no executable commands"],
        "warnings": ["auto-queue.jsonl entry 1 has no local_path in reason"],
        "note": "Run auto-queue.commands.txt only when this preflight report is ok.",
    }

    markdown = render_verify_auto_queue_markdown(report)

    assert "# Link2Context Auto Queue Verification" in markdown
    assert "- OK: false" in markdown
    assert "auto-queue.commands.txt has no executable commands" in markdown
    assert "auto-queue.jsonl entry 1 has no local_path in reason" in markdown


def test_run_auto_queue_dry_run_and_execute(tmp_path: Path) -> None:
    media_path = tmp_path / "media.jpg"
    media_path.write_bytes(b"image")
    command = "queue command"
    entry = {
        "command": command,
        "kind": "media",
        "priority": 3,
        "source": "actions",
        "reason": f"local_path={media_path.name}; next_step=queue_media_text",
        "automation": "auto_queue",
        "requires_review": False,
    }
    (tmp_path / "auto-queue.commands.txt").write_text(command + "\n", encoding="utf-8")
    (tmp_path / "auto-queue.jsonl").write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    calls = []

    def fake_runner(cmd: str, timeout: int) -> dict:
        calls.append((cmd, timeout))
        return {"command": cmd, "returncode": 0, "stdout": "ok", "stderr": ""}

    dry = run_auto_queue(tmp_path, tmp_path, execute=False, runner=fake_runner)
    executed = run_auto_queue(tmp_path, tmp_path, execute=True, timeout=9, runner=fake_runner)

    assert dry["ok"] is True
    assert dry["execute"] is False
    assert dry["commands"] == [command]
    assert dry["next_commands"]
    assert "run-media-text" in dry["next_commands"][0]
    assert "--apply --reindex" in dry["next_commands"][0]
    assert calls == [(command, 9)]
    assert executed["ok"] is True
    assert executed["results"][0]["returncode"] == 0


def test_run_auto_queue_does_not_execute_when_verification_fails(tmp_path: Path) -> None:
    (tmp_path / "auto-queue.commands.txt").write_text("queue command\n", encoding="utf-8")
    (tmp_path / "auto-queue.jsonl").write_text("", encoding="utf-8")
    calls = []

    report = run_auto_queue(
        tmp_path,
        tmp_path,
        execute=True,
        runner=lambda cmd, timeout: calls.append((cmd, timeout)) or {"command": cmd, "returncode": 0},
    )

    assert report["ok"] is False
    assert calls == []
    assert "preflight verification failed" in report["note"]


def test_run_auto_queue_writes_next_handoff_files(tmp_path: Path) -> None:
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"video")
    command = "python -m link2context.store --db data/link2context.db queue --kind video --status not_processed --format jsonl"
    entry = {
        "command": command,
        "kind": "media",
        "priority": 3,
        "source": "actions",
        "reason": f"local_path={media_path.name}; next_step=queue_media_text",
        "automation": "auto_queue",
        "requires_review": False,
    }
    (tmp_path / "auto-queue.commands.txt").write_text(command + "\n", encoding="utf-8")
    (tmp_path / "auto-queue.jsonl").write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "project": "Link2Context",
                "files": ["auto-queue.commands.txt", "auto-queue.jsonl"],
                "file_details": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_auto_queue(
        tmp_path,
        tmp_path,
        write_next=True,
        next_plan={
            "preset": "sona",
            "preset_model": "models/ggml-medium.bin",
            "language": "zh",
            "out_dir": "outputs/media-text",
        },
    )

    assert report["ok"] is True
    assert report["write_next"] is True
    assert report["next_files"]["entries"] == 1
    assert report["next_files"]["files"] == ["auto-queue-next.commands.txt", "auto-queue-next.jsonl"]
    assert report["next_files"]["manifest_updated"] is True
    next_commands = (tmp_path / "auto-queue-next.commands.txt").read_text(encoding="utf-8")
    assert "--preset sona" in next_commands
    assert "--apply --reindex" in next_commands
    next_entry = json.loads((tmp_path / "auto-queue-next.jsonl").read_text(encoding="utf-8").strip())
    assert next_entry["command"] == report["next_commands"][0]
    assert next_entry["source_command"] == command
    assert next_entry["automation"] == "manual_review"
    assert next_entry["requires_review"] is True
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "auto-queue-next.commands.txt" in manifest["files"]
    assert "auto-queue-next.jsonl" in manifest["files"]
    assert manifest["auto_queue_next"] == {
        "files": ["auto-queue-next.commands.txt", "auto-queue-next.jsonl"],
        "entries": 1,
        "requires_review": True,
    }


def test_verify_auto_queue_next_passes_for_written_next_files(tmp_path: Path) -> None:
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"video")
    command = "python -m link2context.store --db data/link2context.db queue --kind video --status not_processed --format jsonl"
    entry = {
        "command": command,
        "kind": "media",
        "priority": 3,
        "source": "actions",
        "reason": f"local_path={media_path.name}; next_step=queue_media_text",
        "automation": "auto_queue",
        "requires_review": False,
    }
    (tmp_path / "auto-queue.commands.txt").write_text(command + "\n", encoding="utf-8")
    (tmp_path / "auto-queue.jsonl").write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "project": "Link2Context",
                "files": ["auto-queue.commands.txt", "auto-queue.jsonl"],
                "file_details": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    run_auto_queue(
        tmp_path,
        tmp_path,
        write_next=True,
        next_plan={"preset": "sona", "preset_model": "models/ggml-medium.bin", "language": "zh"},
    )

    report = verify_auto_queue_next(tmp_path)

    assert report["ok"] is True
    assert report["commands"] == 1
    assert report["entries"] == 1
    assert report["errors"] == []
    assert report["out_paths"] == ["outputs/auto-queue-media-text-video-not_processed.jsonl"]
    assert report["manifest"]["present"] is True


def test_verify_auto_queue_next_fails_for_unsafe_entries(tmp_path: Path) -> None:
    command = (
        "python -m link2context.store --db data/link2context.db run-media-text "
        "--kind image --out outputs/result.txt --command-template \"ocr {input_source}\" --apply"
    )
    entry = {
        "command": command,
        "kind": "image",
        "stage": "run_media_text",
        "source_command": "queue command",
        "automation": "auto_queue",
        "requires_review": False,
    }
    (tmp_path / "auto-queue-next.commands.txt").write_text(command + "\n", encoding="utf-8")
    (tmp_path / "auto-queue-next.jsonl").write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    report = verify_auto_queue_next(tmp_path)

    assert report["ok"] is False
    assert "auto-queue-next.jsonl entry 1 automation is not manual_review" in report["errors"]
    assert "auto-queue-next.jsonl entry 1 requires_review must be true" in report["errors"]
    assert "auto-queue-next.jsonl entry 1 command is missing --reindex" in report["errors"]
    assert any("--out is not a JSONL file" in error for error in report["errors"])
    assert "manifest.json is missing; file details were not checked" in report["warnings"]


def test_render_verify_auto_queue_next_markdown_includes_errors_and_outputs() -> None:
    report = {
        "path": "outputs/agent-handoff",
        "ok": False,
        "commands": 1,
        "entries": 1,
        "errors": ["auto-queue-next.jsonl entry 1 requires_review must be true"],
        "warnings": ["manifest.json is missing; file details were not checked"],
        "out_paths": ["outputs/result.jsonl"],
        "note": "Review auto-queue-next.commands.txt before executing OCR/ASR write-back commands.",
    }

    markdown = render_verify_auto_queue_next_markdown(report)

    assert "# Link2Context Auto Queue Next Verification" in markdown
    assert "- OK: false" in markdown
    assert "requires_review must be true" in markdown
    assert "`outputs/result.jsonl`" in markdown


def test_run_auto_queue_next_dry_run_and_execute(tmp_path: Path) -> None:
    command = (
        "python -m link2context.store --db data/link2context.db run-media-text "
        "--kind image --status not_processed --out outputs/result.jsonl "
        "--command-template \"ocr {input_source}\" --apply --reindex"
    )
    entry = {
        "command": command,
        "kind": "image",
        "stage": "run_media_text",
        "source_command": "python -m link2context.store --db data/link2context.db queue --kind image --format jsonl",
        "automation": "manual_review",
        "requires_review": True,
        "plan": {"command_template": "ocr {input_source}"},
        "reason": "generated by run-auto-queue after verified media queue handoff",
    }
    (tmp_path / "auto-queue-next.commands.txt").write_text(command + "\n", encoding="utf-8")
    (tmp_path / "auto-queue-next.jsonl").write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    command_bytes = (tmp_path / "auto-queue-next.commands.txt").read_bytes()
    jsonl_bytes = (tmp_path / "auto-queue-next.jsonl").read_bytes()
    details = {
        "auto-queue-next.commands.txt": {
            "size_bytes": len(command_bytes),
            "sha256": hashlib.sha256(command_bytes).hexdigest(),
        },
        "auto-queue-next.jsonl": {
            "size_bytes": len(jsonl_bytes),
            "sha256": hashlib.sha256(jsonl_bytes).hexdigest(),
        },
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "files": ["auto-queue-next.commands.txt", "auto-queue-next.jsonl"],
                "file_details": details,
                "auto_queue_next": {
                    "files": ["auto-queue-next.commands.txt", "auto-queue-next.jsonl"],
                    "entries": 1,
                    "requires_review": True,
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    calls = []

    def fake_runner(cmd: str, timeout: int) -> dict:
        calls.append((cmd, timeout))
        return {"command": cmd, "returncode": 0, "stdout": "ok", "stderr": ""}

    dry = run_auto_queue_next(tmp_path, execute=False, runner=fake_runner)
    executed = run_auto_queue_next(tmp_path, execute=True, timeout=11, runner=fake_runner)

    assert dry["ok"] is True
    assert dry["execute"] is False
    assert dry["commands"] == [command]
    assert dry["results"] == []
    assert calls == [(command, 11)]
    assert executed["ok"] is True
    assert executed["results"][0]["returncode"] == 0


def test_media_pipeline_demo_runs_handoff_to_verified_media_text(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    media_file = tmp_path / "sample-image.png"
    media_file.write_bytes(b"demo image")
    conn.execute(
        "UPDATE media SET local_path = ? WHERE document_id = ? AND kind = ? AND media_index = ?",
        (str(media_file), 1, "image", 1),
    )
    handoff_dir = tmp_path / "agent-handoff"
    fake_ocr = Path("examples/media-pipeline/fake_ocr.py").resolve()
    command_template = f'"{sys.executable}" "{fake_ocr}" "{{input_source}}"'

    before = media_pipeline_status(conn)
    manifest = export_agent_handoff(conn, handoff_dir, limit=3)
    auto_queue = run_auto_queue(
        handoff_dir,
        tmp_path,
        write_next=True,
        next_plan={
            "command_template": command_template,
            "model": "demo-ocr",
            "language": "zh",
            "confidence": 0.93,
            "out_dir": str(tmp_path / "media-results"),
        },
    )
    next_check = verify_auto_queue_next(handoff_dir)
    results_path = Path(next_check["out_paths"][0])

    def execute_media_text(_cmd: str, _timeout: int) -> dict:
        report = run_media_text(
            conn,
            kind="image",
            status="not_processed",
            limit=50,
            out_path=results_path,
            command_template=command_template,
            model="demo-ocr",
            language="zh",
            confidence=0.93,
            apply=True,
            reindex=True,
        )
        return {"command": _cmd, "returncode": 0, "stdout": json.dumps(report, ensure_ascii=False), "stderr": ""}

    executed = run_auto_queue_next(handoff_dir, execute=True, runner=execute_media_text)
    verified = verify_media_text(conn, results_path, status="processed", require_reindex=True)
    after = media_pipeline_status(conn)

    assert before["counts"]["local_ready"] == 1
    assert manifest["media_pipeline"]["counts"]["local_ready"] == 1
    assert auto_queue["ok"] is True
    assert auto_queue["write_next"] is True
    assert next_check["ok"] is True
    assert executed["ok"] is True
    assert verified["ok"] is True
    assert after["counts"]["with_text"] == 1
    assert after["counts"]["indexed_documents"] >= 1
    assert "MediaPipelineDemoText" in results_path.read_text(encoding="utf-8")


def test_run_auto_queue_next_does_not_execute_when_verification_fails(tmp_path: Path) -> None:
    command = "python -m link2context.store --db data/link2context.db run-media-text --kind image --out outputs/result.txt --apply"
    (tmp_path / "auto-queue-next.commands.txt").write_text(command + "\n", encoding="utf-8")
    (tmp_path / "auto-queue-next.jsonl").write_text("", encoding="utf-8")
    calls = []

    report = run_auto_queue_next(
        tmp_path,
        execute=True,
        runner=lambda cmd, timeout: calls.append((cmd, timeout)) or {"command": cmd, "returncode": 0},
    )

    assert report["ok"] is False
    assert calls == []
    assert "preflight verification failed" in report["note"]


def test_render_run_auto_queue_next_markdown_includes_dry_run_commands() -> None:
    report = {
        "path": "outputs/agent-handoff",
        "ok": True,
        "execute": False,
        "verification": {"ok": True},
        "commands": ["run-media-text command"],
        "results": [],
        "note": "Dry run only. Re-run with --execute after reviewing OCR/ASR write-back commands.",
    }

    markdown = render_run_auto_queue_next_markdown(report)

    assert "# Link2Context Auto Queue Next Run" in markdown
    assert "- Execute: false" in markdown
    assert "`run-media-text command`" in markdown


def test_auto_queue_next_commands_preserve_queue_filters() -> None:
    commands = [
        "python -m link2context.store --db data/link2context.db queue --kind image --status not_processed --format jsonl",
        "python -m link2context.store --db data/link2context.db queue --low-confidence --kind video --format jsonl",
    ]

    next_commands = auto_queue_next_commands(commands)

    assert "--kind image" in next_commands[0]
    assert "--status not_processed" in next_commands[0]
    assert "--low-confidence" in next_commands[1]
    assert "--kind video" in next_commands[1]
    assert all("--apply --reindex" in command for command in next_commands)


def test_auto_queue_next_commands_use_configured_preset() -> None:
    commands = [
        "python -m link2context.store --db data/link2context.db queue --kind video --status not_processed --limit 7 --format jsonl",
    ]

    next_commands = auto_queue_next_commands(
        commands,
        {
            "preset": "sona",
            "preset_model": "models/ggml-medium.bin",
            "tool_path": r"C:\Tools\sona.exe",
            "language": "zh",
            "out_dir": "outputs/media-text",
        },
    )

    assert len(next_commands) == 1
    assert "--kind video" in next_commands[0]
    assert "--status not_processed" in next_commands[0]
    assert "--limit 7" in next_commands[0]
    assert "--preset sona" in next_commands[0]
    assert '--preset-model "models/ggml-medium.bin"' in next_commands[0]
    assert '--tool-path "C:\\Tools\\sona.exe"' in next_commands[0]
    assert "--language \"zh\"" in next_commands[0]
    assert "--out outputs/media-text/auto-queue-media-text-video-not_processed.jsonl" in next_commands[0]
    assert "--apply --reindex" in next_commands[0]


def test_auto_queue_next_commands_use_configured_command_template() -> None:
    commands = [
        "python -m link2context.store --db data/link2context.db queue --low-confidence --kind image --format jsonl",
    ]

    next_commands = auto_queue_next_commands(
        commands,
        {
            "command_template": "ocr-cli --input {input_source}",
            "model": "ocr-cli",
            "language": "zh",
            "confidence": 0.82,
        },
    )

    assert len(next_commands) == 1
    assert "--low-confidence" in next_commands[0]
    assert "--kind image" in next_commands[0]
    assert '--command-template "ocr-cli --input {input_source}"' in next_commands[0]
    assert '--model "ocr-cli"' in next_commands[0]
    assert '--language "zh"' in next_commands[0]
    assert "--confidence 0.82" in next_commands[0]


def test_render_run_auto_queue_markdown_includes_dry_run_commands() -> None:
    report = {
        "path": "outputs/agent-handoff",
        "ok": True,
        "execute": False,
        "write_next": True,
        "verification": {"ok": True},
        "commands": ["queue command"],
        "next_commands": ["run-media-text command"],
        "next_files": {
            "files": ["auto-queue-next.commands.txt", "auto-queue-next.jsonl"],
            "note": "Review generated run-media-text commands before executing them.",
        },
        "results": [],
        "note": "Dry run only. Re-run with --execute after reviewing commands.",
    }

    markdown = render_run_auto_queue_markdown(report)

    assert "# Link2Context Auto Queue Run" in markdown
    assert "- Execute: false" in markdown
    assert "- Write next: true" in markdown
    assert "`queue command`" in markdown
    assert "`run-media-text command`" in markdown
    assert "`auto-queue-next.commands.txt`" in markdown


def test_export_snapshot_writes_handoff_and_jsonl_backup(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)

    manifest = export_snapshot(conn, tmp_path, limit=3)

    assert manifest["project"] == "Link2Context"
    assert manifest["ok"] is True
    assert manifest["handoff"]["path"] == "agent-handoff"
    assert manifest["handoff"]["ok"] is True
    assert manifest["jsonl"]["path"] == "jsonl-dump"
    assert manifest["jsonl"]["ok"] is True
    assert manifest["markdown_docs"]["path"] == "markdown-docs"
    assert manifest["markdown_docs"]["ok"] is True
    assert manifest["graph_csv"]["path"] == "graph-csv"
    assert manifest["graph_csv"]["ok"] is True
    assert manifest["neo4j"]["path"] == "graph.cypher"
    assert manifest["neo4j"]["ok"] is True
    assert (tmp_path / "snapshot.json").exists()
    assert (tmp_path / "agent-handoff" / "manifest.json").exists()
    assert (tmp_path / "agent-handoff" / "review.md").exists()
    assert (tmp_path / "jsonl-dump" / "manifest.json").exists()
    assert (tmp_path / "jsonl-dump" / "documents.jsonl").exists()
    assert (tmp_path / "markdown-docs" / "manifest.json").exists()
    assert list((tmp_path / "markdown-docs").glob("*.md"))
    assert (tmp_path / "graph-csv" / "manifest.json").exists()
    assert (tmp_path / "graph-csv" / "nodes.csv").exists()
    assert (tmp_path / "graph.cypher").exists()
    assert (tmp_path / "graph.cypher.manifest.json").exists()


def test_verify_snapshot_passes_for_clean_snapshot(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    export_snapshot(conn, tmp_path, limit=3)

    report = verify_snapshot(tmp_path)

    assert report["ok"] is True
    assert report["errors"] == []
    assert report["handoff"]["ok"] is True
    assert report["jsonl"]["ok"] is True
    assert report["markdown_docs"]["ok"] is True
    assert report["graph_csv"]["ok"] is True
    assert report["neo4j"]["ok"] is True


def test_verify_snapshot_fails_when_child_bundle_is_modified(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    export_snapshot(conn, tmp_path, limit=3)
    (tmp_path / "agent-handoff" / "review.md").write_text("tampered", encoding="utf-8")

    report = verify_snapshot(tmp_path)

    assert report["ok"] is False
    assert "agent-handoff verification failed" in report["errors"]
    assert report["handoff"]["ok"] is False


def test_verify_snapshot_fails_when_graph_export_is_modified(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    export_snapshot(conn, tmp_path, limit=3)
    (tmp_path / "graph-csv" / "edges.csv").write_text("source,target,predicate,confidence,evidence\n", encoding="utf-8")

    report = verify_snapshot(tmp_path)

    assert report["ok"] is False
    assert "graph-csv verification failed" in report["errors"]
    assert report["graph_csv"]["ok"] is False


def test_verify_snapshot_fails_when_markdown_docs_are_modified(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    export_snapshot(conn, tmp_path, limit=3)
    first_doc = next((tmp_path / "markdown-docs").glob("*.md"))
    first_doc.write_text("tampered", encoding="utf-8")

    report = verify_snapshot(tmp_path)

    assert report["ok"] is False
    assert "markdown-docs verification failed" in report["errors"]
    assert report["markdown_docs"]["ok"] is False


def test_verify_snapshot_fails_when_neo4j_export_is_modified(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    export_snapshot(conn, tmp_path, limit=3)
    (tmp_path / "graph.cypher").write_text("// tampered\n", encoding="utf-8")

    report = verify_snapshot(tmp_path)

    assert report["ok"] is False
    assert "neo4j verification failed" in report["errors"]
    assert report["neo4j"]["ok"] is False


def test_render_verify_snapshot_markdown_includes_child_status() -> None:
    report = {
        "path": "outputs/snapshot",
        "ok": False,
        "errors": ["agent-handoff verification failed"],
        "handoff": {"path": "outputs/snapshot/agent-handoff", "ok": False, "errors": ["review.md mismatch"]},
        "jsonl": {"path": "outputs/snapshot/jsonl-dump", "ok": True, "errors": []},
        "markdown_docs": {"path": "outputs/snapshot/markdown-docs", "ok": True, "errors": []},
        "graph_csv": {"path": "outputs/snapshot/graph-csv", "ok": True, "errors": []},
        "neo4j": {"path": "outputs/snapshot/graph.cypher", "ok": True, "errors": []},
    }

    markdown = render_verify_snapshot_markdown(report)

    assert "# Link2Context Snapshot Verification" in markdown
    assert "agent-handoff verification failed" in markdown
    assert "## handoff" in markdown
    assert "## markdown_docs" in markdown
    assert "## graph_csv" in markdown
    assert "## neo4j" in markdown
    assert "- OK: false" in markdown
    assert "review.md mismatch" in markdown


def test_import_snapshot_restores_store_from_verified_snapshot(tmp_path: Path) -> None:
    source = sqlite3.connect(":memory:")
    source.row_factory = sqlite3.Row
    source.execute("PRAGMA foreign_keys=ON")
    init_db(source)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(source, context)
    export_snapshot(source, tmp_path, limit=3)

    target = sqlite3.connect(":memory:")
    target.row_factory = sqlite3.Row
    target.execute("PRAGMA foreign_keys=ON")
    init_db(target)
    report = import_snapshot(target, tmp_path)

    assert report["ok"] is True
    assert report["verification"]["ok"] is True
    assert report["imported"]["documents"] == 1
    assert stats(target)["documents"] == 1
    assert stats(target)["citations"] == len(context["agent_package"]["citations"])
    document = get_document(target, "https://mp.weixin.qq.com/s/example")
    assert document["found"] is True
    assert document["document"]["title"] == "示例公众号文章"
    assert document["citations"]
    assert document["media"]


def test_import_snapshot_refuses_failed_verification(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    export_snapshot(conn, tmp_path, limit=3)
    (tmp_path / "jsonl-dump" / "documents.jsonl").write_text("", encoding="utf-8")

    target = sqlite3.connect(":memory:")
    target.row_factory = sqlite3.Row
    target.execute("PRAGMA foreign_keys=ON")
    init_db(target)
    report = import_snapshot(target, tmp_path)

    assert report["ok"] is False
    assert report["imported"] == {}
    assert "jsonl-dump verification failed" in report["verification"]["errors"]
    assert stats(target)["documents"] == 0


def test_render_import_snapshot_markdown_includes_counts() -> None:
    report = {
        "path": "outputs/snapshot",
        "ok": True,
        "jsonl_path": "outputs/snapshot/jsonl-dump",
        "imported": {"documents": 1, "citations": 5},
        "stats": {"documents": 1, "citations": 5, "entities": 3, "relationships": 2},
        "note": "Imported.",
    }

    markdown = render_import_snapshot_markdown(report)

    assert "# Link2Context Snapshot Import" in markdown
    assert "- JSONL path: outputs/snapshot/jsonl-dump" in markdown
    assert "- documents: 1" in markdown
    assert "- Citations: 5" in markdown


def test_dump_jsonl_writes_portable_tables_and_manifest(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["media"]["images"][0]["local_path"] = "outputs/media/image-1.png"
    import_context(conn, context)
    conn.execute(
        """
        UPDATE media
        SET cache_status = ?, cache_error = ?, cache_sha256 = ?, cache_bytes = ?, cache_checked_at = ?
        WHERE document_id = ? AND media_index = ?
        """,
        ("cached", None, "abc123", 42, "2026-06-29T00:00:00+00:00", 1, 1),
    )
    add_document_tags(conn, "1", ["知识管理"])
    add_document_note(conn, "1", "这是我的个人判断。")
    mark_document_status(conn, "1", "later", "今晚处理")

    manifest = dump_jsonl(conn, tmp_path)

    assert manifest["project"] == "Link2Context"
    assert manifest["format"] == "jsonl"
    assert manifest["files"] == [
        "documents.jsonl",
        "media.jsonl",
        "citations.jsonl",
        "entities.jsonl",
        "document_entities.jsonl",
        "document_tags.jsonl",
        "document_notes.jsonl",
        "document_status.jsonl",
        "relationships.jsonl",
    ]
    assert manifest["row_counts"]["documents.jsonl"] == 1
    assert manifest["row_counts"]["document_tags.jsonl"] == 1
    assert manifest["row_counts"]["document_notes.jsonl"] == 1
    assert manifest["row_counts"]["document_status.jsonl"] == 1
    assert manifest["row_counts"]["citations.jsonl"] == len(context["agent_package"]["citations"])
    document = json.loads((tmp_path / "documents.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert document["url"] == "https://mp.weixin.qq.com/s/example"
    assert "context_json" not in document
    citation = json.loads((tmp_path / "citations.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert citation["document_id"] == 1
    media = json.loads((tmp_path / "media.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert media["local_path"] == "outputs/media/image-1.png"
    assert media["cache_status"] == "cached"
    assert media["cache_sha256"] == "abc123"
    assert media["cache_bytes"] == 42
    tag = json.loads((tmp_path / "document_tags.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert tag["tag"] == "知识管理"
    note = json.loads((tmp_path / "document_notes.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert note["note"] == "这是我的个人判断。"
    status = json.loads((tmp_path / "document_status.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert status["status"] == "later"
    assert set(manifest["file_details"]) == set(manifest["files"])
    documents_bytes = (tmp_path / "documents.jsonl").read_bytes()
    assert manifest["file_details"]["documents.jsonl"] == {
        "size_bytes": len(documents_bytes),
        "sha256": hashlib.sha256(documents_bytes).hexdigest(),
    }
    assert (tmp_path / "manifest.json").exists()


def test_verify_jsonl_dump_passes_for_clean_dump(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    dump_jsonl(conn, tmp_path)

    report = verify_jsonl_dump(tmp_path)

    assert report["ok"] is True
    assert report["errors"] == []
    assert report["files"]["documents.jsonl"]["ok"] is True
    assert report["files"]["documents.jsonl"]["actual_rows"] == 1


def test_import_jsonl_dump_restores_store_tables(tmp_path: Path) -> None:
    source = sqlite3.connect(":memory:")
    source.row_factory = sqlite3.Row
    source.execute("PRAGMA foreign_keys=ON")
    init_db(source)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["media"]["images"][0]["local_path"] = "outputs/media/image-1.png"
    import_context(source, context)
    source.execute(
        """
        UPDATE media
        SET cache_status = ?, cache_error = ?, cache_sha256 = ?, cache_bytes = ?, cache_checked_at = ?
        WHERE document_id = ? AND media_index = ?
        """,
        ("download_failed", "network down", None, None, "2026-06-29T00:00:00+00:00", 1, 1),
    )
    add_document_tags(source, "1", ["知识管理"])
    add_document_note(source, "1", "这是我的个人判断。")
    mark_document_status(source, "1", "later", "今晚处理")
    dump_jsonl(source, tmp_path)

    target = sqlite3.connect(":memory:")
    target.row_factory = sqlite3.Row
    target.execute("PRAGMA foreign_keys=ON")
    init_db(target)
    report = import_jsonl_dump(target, tmp_path)

    assert report["ok"] is True
    assert report["imported"]["documents"] == 1
    assert stats(target)["documents"] == 1
    assert stats(target)["citations"] == len(context["agent_package"]["citations"])
    document = get_document(target, "https://mp.weixin.qq.com/s/example")
    assert document["found"] is True
    assert document["document"]["title"] == "示例公众号文章"
    assert document["tags"] == ["知识管理"]
    assert document["notes"][0]["note"] == "这是我的个人判断。"
    assert document["user_status"]["status"] == "later"
    assert document["citations"]
    assert document["media"]
    assert document["media"][0]["local_path"] == "outputs/media/image-1.png"
    assert document["media"][0]["cache_status"] == "download_failed"
    assert document["media"][0]["cache_error"] == "network down"


def test_import_jsonl_dump_refuses_failed_verification(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text('{"format":"jsonl","files":["documents.jsonl"]}', encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    report = import_jsonl_dump(conn, tmp_path)

    assert report["ok"] is False
    assert report["imported"] == {}
    assert stats(conn)["documents"] == 0


def test_render_import_jsonl_markdown_includes_counts() -> None:
    report = {
        "path": "outputs/jsonl-dump",
        "ok": True,
        "imported": {"documents": 1, "citations": 5},
        "stats": {"documents": 1, "citations": 5, "entities": 3, "relationships": 2},
        "note": "Imported.",
    }

    markdown = render_import_jsonl_markdown(report)

    assert "# Link2Context JSONL Import" in markdown
    assert "- documents: 1" in markdown
    assert "- Citations: 5" in markdown


def test_verify_jsonl_dump_fails_for_modified_file(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    dump_jsonl(conn, tmp_path)
    (tmp_path / "documents.jsonl").write_text("", encoding="utf-8")

    report = verify_jsonl_dump(tmp_path)

    assert report["ok"] is False
    assert "documents.jsonl does not match manifest detail" in report["errors"]
    assert "documents.jsonl row count does not match manifest" in report["errors"]
    assert report["files"]["documents.jsonl"]["ok"] is False


def test_render_verify_jsonl_markdown_includes_row_counts_and_errors() -> None:
    report = {
        "path": "outputs/jsonl-dump",
        "ok": False,
        "errors": ["documents.jsonl row count does not match manifest"],
        "extra_files": ["extra.jsonl"],
        "files": {
            "documents.jsonl": {"ok": False, "actual_rows": 0},
            "citations.jsonl": {"ok": True, "actual_rows": 5},
        },
    }

    markdown = render_verify_jsonl_markdown(report)

    assert "# Link2Context JSONL Verification" in markdown
    assert "documents.jsonl row count does not match manifest" in markdown
    assert "- fail documents.jsonl: 0 row(s)" in markdown
    assert "- ok citations.jsonl: 5 row(s)" in markdown


def test_verify_export_bundle_passes_for_clean_export(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    export_agent_handoff(conn, tmp_path, limit=3)

    report = verify_export_bundle(tmp_path)

    assert report["ok"] is True
    assert report["errors"] == []
    assert report["files"]["handoff.md"]["ok"] is True
    assert "media_pipeline" in report["manifest"]


def test_verify_export_bundle_fails_for_modified_file(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    export_agent_handoff(conn, tmp_path, limit=3)
    (tmp_path / "handoff.md").write_text("tampered", encoding="utf-8")

    report = verify_export_bundle(tmp_path)

    assert report["ok"] is False
    assert "handoff.md does not match manifest detail" in report["errors"]
    assert report["files"]["handoff.md"]["ok"] is False


def test_verify_export_bundle_checks_hot_commands_shape(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    export_agent_handoff(conn, tmp_path, limit=3)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["hot_commands"] = [{"command": "queue command"}]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = verify_export_bundle(tmp_path)

    assert report["ok"] is False
    assert "hot_commands[1] missing kind" in report["errors"]


def test_verify_export_bundle_checks_hot_command_groups_shape(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    export_agent_handoff(conn, tmp_path, limit=3)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["hot_command_groups"] = {"auto_queue": "bad", "manual_review": []}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = verify_export_bundle(tmp_path)

    assert report["ok"] is False
    assert "hot_command_groups.auto_queue must be a list" in report["errors"]


def test_verify_export_bundle_checks_media_pipeline_recommended_commands(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    export_agent_handoff(conn, tmp_path, limit=3)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["media_pipeline"]["recommended_commands"] = [
        command
        for command in manifest["media_pipeline"]["recommended_commands"]
        if "prepare-media-model" not in command
    ]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = verify_export_bundle(tmp_path)

    assert report["ok"] is False
    assert "media_pipeline.recommended_commands missing prepare-media-model" in report["errors"]


def test_render_verify_export_markdown_includes_errors() -> None:
    report = {
        "path": "outputs/agent-handoff",
        "ok": False,
        "errors": ["handoff.md does not match manifest detail"],
        "extra_files": ["notes.txt"],
        "files": {
            "handoff.md": {"ok": False},
            "brief.md": {"ok": True},
        },
    }

    markdown = render_verify_export_markdown(report)

    assert "# Link2Context Export Verification" in markdown
    assert "- OK: false" in markdown
    assert "handoff.md does not match manifest detail" in markdown
    assert "- notes.txt" in markdown
    assert "- fail handoff.md" in markdown


def test_store_doctor_reports_empty_store() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)

    report = store_doctor(conn)

    assert report["status"] == "empty"
    assert report["ready_for_agent"] is False
    assert report["stats"]["documents"] == 0
    assert report["checks"][0]["name"] == "documents"
    assert report["checks"][0]["ok"] is False
    assert "import outputs/batch" in report["recommended_next"][1]


def test_store_doctor_reports_agent_ready_store() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)

    report = store_doctor(conn)

    assert report["status"] == "ok"
    assert report["ready_for_agent"] is True
    assert all(check["ok"] for check in report["checks"])
    assert "export --out outputs/agent-handoff" in report["recommended_next"][1]


def test_render_doctor_markdown_includes_checks_and_next_steps() -> None:
    report = {
        "status": "warn",
        "ready_for_agent": False,
        "checks": [
            {"name": "documents", "ok": True, "detail": "2 imported document(s)", "fix": None},
            {"name": "citations", "ok": False, "detail": "0 citation(s)", "fix": "Re-import richer contexts."},
        ],
        "recommended_next": ["Re-import richer contexts."],
    }

    markdown = render_doctor_markdown(report)

    assert "# Link2Context Store Doctor" in markdown
    assert "- Status: warn" in markdown
    assert "- ok documents: 2 imported document(s)" in markdown
    assert "- warn citations: 0 citation(s)" in markdown
    assert "Fix: Re-import richer contexts." in markdown


def test_document_timeline_orders_by_published_time() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    older = build_wechat_context("https://mp.weixin.qq.com/s/older", html)
    older["article"]["title"] = "旧文章"
    older["article"]["published_at"] = "2026-01-01T00:00:00+00:00"
    newer = build_wechat_context("https://mp.weixin.qq.com/s/newer", html)
    newer["article"]["title"] = "新文章"
    newer["article"]["published_at"] = "2026-02-01T00:00:00+00:00"
    import_context(conn, older)
    import_context(conn, newer)

    timeline = document_timeline(conn, limit=2)

    assert [item["title"] for item in timeline["documents"]] == ["新文章", "旧文章"]
    assert [item["id"] for item in timeline["documents"]] == [2, 1]
    assert timeline["note"] == "Ordered by published_at when available, otherwise imported_at."


def test_render_timeline_markdown_includes_source_fields() -> None:
    timeline = {
        "note": "Ordered by published_at.",
        "documents": [
            {
                "title": "图谱文章",
                "url": "https://example.com/graph",
                "platform": "wechat_official_account",
                "account_name": "灵渠测试号",
                "author": "Ian",
                "published_at": "2026-02-01T00:00:00+00:00",
                "imported_at": "2026-02-02T00:00:00+00:00",
                "quality_status": "ok",
            }
        ],
    }

    markdown = render_timeline_markdown(timeline)

    assert "# Link2Context Timeline" in markdown
    assert "## 2026-02-01T00:00:00+00:00" in markdown
    assert "- 图谱文章" in markdown
    assert "URL: https://example.com/graph" in markdown
    assert "Account: 灵渠测试号" in markdown
    assert "Author: Ian" in markdown


def test_render_timeline_markdown_handles_empty_store() -> None:
    markdown = render_timeline_markdown({"documents": [], "note": "Ordered."})

    assert "# Link2Context Timeline" in markdown
    assert "No imported documents." in markdown


def test_agent_query_returns_evidence_package() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["article"]["title"] = "产品观察"
    context["content"]["plain_text"] += " ProductX 是一个适合知识图谱测试的工具。"
    context["agent_package"]["citations"] = [
        {
            "ref": "paragraph_custom",
            "text": "ProductX 是一个适合知识图谱测试的工具。",
            "source": "article_body",
        }
    ]
    document_id = import_context(conn, context)
    conn.execute(
        "UPDATE media SET text = ?, status = ? WHERE document_id = ? AND media_index = ?",
        ("ProductX 出现在 OCR 结果里。", "processed", document_id, 1),
    )

    package = agent_query(conn, "ProductX")

    assert package["query"] == "ProductX"
    assert package["results"][0]["title"] == "产品观察"
    assert package["results"][0]["url"] == "https://mp.weixin.qq.com/s/example"
    assert package["results"][0]["matched_entities"] == [
        {"name": "ProductX", "type": "term", "evidence": "content.plain_text"}
    ]
    assert package["results"][0]["citations"] == [
        {
            "ref": "paragraph_custom",
            "text": "ProductX 是一个适合知识图谱测试的工具。",
            "source": "article_body",
            "matched_terms": ["ProductX"],
            "score": 4,
        }
    ]
    assert any(
        media["kind"] == "image"
        and media["index"] == 1
        and media["status"] == "processed"
        and media["text"] == "ProductX 出现在 OCR 结果里。"
        and media["matched_terms"] == ["ProductX"]
        and media["score"] == 4
        for media in package["results"][0]["media_evidence"]
    )


def test_agent_query_matches_user_annotations() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["article"]["title"] = "普通标题"
    context["content"]["plain_text"] = "这是一篇没有目标关键词的正文。"
    import_context(conn, context)
    add_document_tags(conn, "1", ["知识管理"])
    add_document_note(conn, "1", "这是我的个人判断。")
    mark_document_status(conn, "1", "later", "今晚处理")

    package = agent_query(conn, "知识管理")

    assert len(package["results"]) == 1
    assert package["results"][0]["title"] == "普通标题"
    assert package["results"][0]["annotation_matched_terms"] == ["知识管理"]
    assert package["results"][0]["user_annotations"]["tags"] == ["知识管理"]
    assert package["results"][0]["user_annotations"]["notes"][0]["note"] == "这是我的个人判断。"
    assert package["results"][0]["user_annotations"]["user_status"]["status"] == "later"


def test_render_query_markdown_includes_agent_evidence() -> None:
    package = {
        "query": "ProductX",
        "terms": ["ProductX"],
        "results": [
            {
                "title": "产品观察",
                "url": "https://mp.weixin.qq.com/s/example",
                "platform": "wechat_official_account",
                "account_name": "灵渠测试号",
                "quality_status": "ok",
                "score": 43,
                "summary": "一段摘要",
                "annotation_matched_terms": ["ProductX"],
                "user_annotations": {
                    "tags": ["知识管理"],
                    "notes": [{"id": 1, "note": "这是我的个人判断。", "created_at": "2026-01-01"}],
                    "user_status": {
                        "status": "later",
                        "note": "今晚处理",
                        "updated_at": "2026-01-01",
                    },
                },
                "matched_entities": [
                    {"name": "ProductX", "type": "term", "evidence": "content.plain_text"}
                ],
                "citations": [
                    {
                        "ref": "paragraph_custom",
                        "text": "ProductX 是一个适合知识图谱测试的工具。",
                        "matched_terms": ["ProductX"],
                        "score": 4,
                    }
                ],
                "media_evidence": [
                    {
                        "kind": "image",
                        "index": 1,
                        "text": "ProductX 出现在 OCR 结果里。",
                        "matched_terms": ["ProductX"],
                        "score": 4,
                    }
                ],
            }
        ],
    }

    markdown = render_query_markdown(package)

    assert "# Link2Context Query: ProductX" in markdown
    assert "https://mp.weixin.qq.com/s/example" in markdown
    assert "ProductX (term, evidence=content.plain_text)" in markdown
    assert "paragraph_custom | score=4 | matched=ProductX" in markdown
    assert "### Media Evidence" in markdown
    assert "image[1] | score=4 | matched=ProductX" in markdown
    assert "### User Annotations" in markdown
    assert "- Status: later" in markdown
    assert "- Tags: 知识管理" in markdown
    assert "- Annotation matched terms: ProductX" in markdown


def test_export_graph_returns_document_entity_nodes_and_edges() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)

    graph = export_graph(conn)

    node_ids = {node["id"] for node in graph["nodes"]}
    assert "document:1" in node_ids
    assert "entity:灵渠测试号" in node_ids
    assert any(
        edge["source"] == "document:1"
        and edge["target"] == "entity:灵渠测试号"
        and edge["predicate"] == "source_account"
        for edge in graph["edges"]
    )


def test_export_graph_filters_terms_by_default() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["content"]["plain_text"] += " ProductX"
    import_context(conn, context)

    default_graph = export_graph(conn)
    full_graph = export_graph(conn, include_terms=True)

    assert "entity:productx" not in {node["id"] for node in default_graph["nodes"]}
    assert "literal:productx" not in {node["id"] for node in default_graph["nodes"]}
    assert "entity:productx" in {node["id"] for node in full_graph["nodes"]}
    assert default_graph["include_terms"] is False
    assert full_graph["include_terms"] is True


def test_dump_graph_csv_writes_nodes_edges_and_manifest(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)

    manifest = dump_graph_csv(conn, tmp_path, limit=10)

    assert manifest["format"] == "graph-csv"
    assert manifest["files"] == ["nodes.csv", "edges.csv"]
    assert manifest["row_counts"]["nodes.csv"] > 0
    assert manifest["row_counts"]["edges.csv"] > 0
    assert set(manifest["file_details"]) == {"nodes.csv", "edges.csv"}
    nodes = list(csv.DictReader((tmp_path / "nodes.csv").open(encoding="utf-8")))
    edges = list(csv.DictReader((tmp_path / "edges.csv").open(encoding="utf-8")))
    assert "document:1" in {node["id"] for node in nodes}
    assert "entity:灵渠测试号" in {node["id"] for node in nodes}
    assert any(
        edge["source"] == "document:1"
        and edge["target"] == "entity:灵渠测试号"
        and edge["predicate"] == "source_account"
        for edge in edges
    )
    assert (tmp_path / "manifest.json").exists()


def test_dump_graph_csv_respects_include_terms(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["content"]["plain_text"] += " ProductX"
    import_context(conn, context)

    dump_graph_csv(conn, tmp_path / "default")
    dump_graph_csv(conn, tmp_path / "full", include_terms=True)

    default_nodes = list(csv.DictReader((tmp_path / "default" / "nodes.csv").open(encoding="utf-8")))
    full_nodes = list(csv.DictReader((tmp_path / "full" / "nodes.csv").open(encoding="utf-8")))
    assert "entity:productx" not in {node["id"] for node in default_nodes}
    assert "entity:productx" in {node["id"] for node in full_nodes}


def test_verify_graph_csv_passes_for_clean_export(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    dump_graph_csv(conn, tmp_path, limit=10)

    report = verify_graph_csv(tmp_path)

    assert report["ok"] is True
    assert report["errors"] == []
    assert report["manifest"]["format"] == "graph-csv"
    assert report["files"]["nodes.csv"]["ok"] is True
    assert report["files"]["edges.csv"]["actual_rows"] > 0


def test_verify_graph_csv_fails_for_modified_file(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    dump_graph_csv(conn, tmp_path, limit=10)
    (tmp_path / "edges.csv").write_text("source,target,predicate,confidence,evidence\n", encoding="utf-8")

    report = verify_graph_csv(tmp_path)

    assert report["ok"] is False
    assert "edges.csv does not match manifest detail" in report["errors"]
    assert "edges.csv row count does not match manifest" in report["errors"]
    assert report["files"]["edges.csv"]["ok"] is False


def test_render_verify_graph_markdown_includes_row_counts_and_errors() -> None:
    report = {
        "path": "outputs/graph-csv",
        "ok": False,
        "errors": ["edges.csv row count does not match manifest"],
        "extra_files": ["extra.csv"],
        "files": {
            "nodes.csv": {"ok": True, "actual_rows": 3},
            "edges.csv": {"ok": False, "actual_rows": 0},
        },
    }

    markdown = render_verify_graph_markdown(report)

    assert "# Link2Context Graph CSV Verification" in markdown
    assert "edges.csv row count does not match manifest" in markdown
    assert "- extra.csv" in markdown
    assert "- ok nodes.csv: 3 row(s)" in markdown
    assert "- fail edges.csv: 0 row(s)" in markdown


def test_render_neo4j_cypher_outputs_nodes_and_relationships() -> None:
    graph = {
        "nodes": [
            {
                "id": "document:1",
                "kind": "document",
                "label": "示例文章",
                "url": "https://example.com/article",
                "platform": "wechat_official_account",
            },
            {
                "id": "entity:灵渠测试号",
                "kind": "entity",
                "label": "灵渠测试号",
                "entity_type": "source_account",
            },
        ],
        "edges": [
            {
                "source": "document:1",
                "target": "entity:灵渠测试号",
                "predicate": "source_account",
                "confidence": 1.0,
                "evidence": "article.account_name",
            }
        ],
    }

    cypher = render_neo4j_cypher(graph)

    assert "CREATE CONSTRAINT link2context_node_id" in cypher
    assert "MERGE (n:Link2ContextNode:Document {id: \"document:1\"})" in cypher
    assert "MERGE (n:Link2ContextNode:Entity {id: \"entity:灵渠测试号\"})" in cypher
    assert "MERGE (source)-[r:SOURCE_ACCOUNT]->(target)" in cypher
    assert 'predicate: "source_account"' in cypher
    assert 'url: "https://example.com/article"' in cypher


def test_dump_neo4j_cypher_writes_script_and_manifest(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)

    manifest = dump_neo4j_cypher(conn, tmp_path / "graph.cypher", limit=10)

    assert manifest["format"] == "neo4j-cypher"
    assert manifest["nodes"] > 0
    assert manifest["edges"] > 0
    assert manifest["file_detail"]["size_bytes"] > 0
    cypher = (tmp_path / "graph.cypher").read_text(encoding="utf-8")
    assert "Link2Context Neo4j import script" in cypher
    assert "SOURCE_ACCOUNT" in cypher
    assert (tmp_path / "graph.cypher.manifest.json").exists()


def test_verify_neo4j_cypher_passes_for_clean_export(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    dump_neo4j_cypher(conn, tmp_path / "graph.cypher", limit=10)

    report = verify_neo4j_cypher(tmp_path / "graph.cypher")

    assert report["ok"] is True
    assert report["errors"] == []
    assert report["manifest"]["format"] == "neo4j-cypher"
    assert report["counts"]["nodes"] == report["manifest"]["nodes"]
    assert report["counts"]["relationships"] == report["manifest"]["edges"]


def test_verify_neo4j_cypher_fails_for_modified_script(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    import_context(conn, context)
    dump_neo4j_cypher(conn, tmp_path / "graph.cypher", limit=10)
    (tmp_path / "graph.cypher").write_text("// tampered\n", encoding="utf-8")

    report = verify_neo4j_cypher(tmp_path / "graph.cypher")

    assert report["ok"] is False
    assert "node id constraint is missing" in report["errors"]
    assert "cypher file has no node or relationship MERGE statements" in report["errors"]
    assert "cypher file does not match manifest detail" in report["errors"]


def test_render_verify_neo4j_markdown_includes_counts_and_errors() -> None:
    report = {
        "path": "outputs/graph.cypher",
        "ok": False,
        "errors": ["cypher file does not match manifest detail"],
        "manifest_path": "outputs/graph.cypher.manifest.json",
        "manifest": {"nodes": 2, "edges": 1},
        "counts": {"nodes": 1, "relationships": 0, "constraints": 1},
    }

    markdown = render_verify_neo4j_markdown(report)

    assert "# Link2Context Neo4j Verification" in markdown
    assert "cypher file does not match manifest detail" in markdown
    assert "- Nodes: 1" in markdown
    assert "- Relationships: 0" in markdown
    assert "- Path: outputs/graph.cypher.manifest.json" in markdown


def test_render_graph_mermaid_outputs_nodes_and_edges() -> None:
    graph = {
        "nodes": [
            {"id": "document:1", "kind": "document", "label": "示例文章"},
            {"id": "entity:灵渠测试号", "kind": "entity", "label": "灵渠测试号"},
        ],
        "edges": [
            {
                "source": "document:1",
                "target": "entity:灵渠测试号",
                "predicate": "source_account",
            }
        ],
    }

    mermaid = render_graph_mermaid(graph)

    assert mermaid.startswith("graph LR\n")
    assert '["示例文章"]' in mermaid
    assert '("灵渠测试号")' in mermaid
    assert '-->|"source_account"|' in mermaid


def test_mermaid_id_avoids_chinese_collisions() -> None:
    assert mermaid_id("entity:大脑") != mermaid_id("entity:草稿纸")


def test_agent_query_supports_multiple_terms() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["article"]["title"] = "Claude Code 工作流"
    context["content"]["plain_text"] += " Codex 可以复用这个工作流。"
    context["agent_package"]["citations"] = [
        {
            "ref": "paragraph_custom",
            "text": "Codex 可以复用这个工作流。",
            "source": "article_body",
        }
    ]
    import_context(conn, context)

    package = agent_query(conn, "Claude Codex")

    assert package["terms"] == ["Claude", "Codex"]
    assert package["results"][0]["title"] == "Claude Code 工作流"
    assert package["results"][0]["matched_terms"] == ["Claude"]
    assert package["results"][0]["citations"][0]["text"] == "Codex 可以复用这个工作流。"
    assert package["results"][0]["citations"][0]["matched_terms"] == ["Codex"]
    assert package["results"][0]["citations"][0]["score"] == 4


def test_agent_query_ranks_citations_by_term_matches() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)
    context["article"]["title"] = "查询测试"
    context["content"]["plain_text"] += " ProductX Graph ProductX"
    context["agent_package"]["citations"] = [
        {"ref": "paragraph_1", "text": "ProductX 单独出现。", "source": "article_body"},
        {"ref": "paragraph_2", "text": "ProductX 和 Graph 同时出现，ProductX 再出现。", "source": "article_body"},
    ]
    import_context(conn, context)

    package = agent_query(conn, "ProductX Graph")

    citations = package["results"][0]["citations"]
    assert citations[0]["ref"] == "paragraph_2"
    assert citations[0]["matched_terms"] == ["ProductX", "Graph"]
    assert citations[0]["score"] > citations[1]["score"]


def test_citation_ref_sort_key_uses_trailing_number() -> None:
    assert citation_ref_sort_key("paragraph_27") < citation_ref_sort_key("paragraph_104")
    assert citation_ref_sort_key("custom") > citation_ref_sort_key("paragraph_104")


def test_query_terms_dedupes_and_keeps_chinese_phrases() -> None:
    assert query_terms("Claude Claude 知识图谱") == ["Claude", "知识图谱"]

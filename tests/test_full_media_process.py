import json
from pathlib import Path

from scripts.full_media_process import (
    OpenAITranscriptionConfig,
    RuntimePaths,
    build_parser,
    classify_queue_item,
    gif_frame_extract_command,
    graph_signals_only_failure,
    process_queue,
    render_markdown_summary,
    result_row,
    safe_join_media_cache,
    summary_counts,
    tesseract_command,
    validate_apply_report,
    validate_args,
    video_wav_extract_command,
    write_jsonl,
)


def runtime() -> RuntimePaths:
    return RuntimePaths(
        ffmpeg=Path("/tools/ffmpeg"),
        tesseract=Path("/tools/tesseract"),
        tessdata_prefix=Path("/tools/tessdata"),
        whisper_cli=Path("/tools/whisper-cli"),
        whisper_model=Path("/models/ggml-tiny.bin"),
    )


def queue_item(path: Path, kind: str = "image", index: int = 1) -> dict:
    return {
        "kind": kind,
        "index": index,
        "input_path": str(path),
        "input_url": "https://example.test/media",
        "output_hint": {"document_id": 42, "media_index": index},
    }


def test_classify_queue_items_by_local_file_type(tmp_path: Path) -> None:
    image = tmp_path / "image.jpg"
    gif = tmp_path / "animated.gif"
    video = tmp_path / "clip.mp4"
    for path in (image, gif, video):
        path.write_bytes(b"media")

    assert classify_queue_item(queue_item(image))["type"] == "image"
    assert classify_queue_item(queue_item(gif))["type"] == "gif"
    assert classify_queue_item(queue_item(video, kind="video"))["type"] == "video"
    assert classify_queue_item({**queue_item(tmp_path / "missing.jpg"), "input_path": ""})["type"] == "missing_local_path"
    assert classify_queue_item(queue_item(tmp_path / "missing.jpg"))["type"] == "missing_file"


def test_gif_frame_ocr_command_planning(tmp_path: Path) -> None:
    gif = tmp_path / "animated.gif"
    gif.write_bytes(b"GIF89a")
    queue = {"items": [queue_item(gif)]}

    report = process_queue(
        queue,
        tmp_path / "results.jsonl",
        runtime(),
        media_cache_root=None,
        ocr_language="chi_sim+eng",
        asr_language="zh",
        timeout=1,
        gif_frames=3,
        dry_run=True,
    )

    assert report["counts"] == {"queued": 1, "processed": 0, "written": 0, "skipped": 0, "low_confidence": 0}
    commands = report["planned"][0]["commands"]
    assert commands[0] == gif_frame_extract_command(runtime().ffmpeg, gif, Path("frame-%03d.png"), 3)
    assert commands[1] == tesseract_command(runtime().tesseract, Path("frame-001.png"), "chi_sim+eng")


def test_result_jsonl_shape(tmp_path: Path) -> None:
    item = queue_item(tmp_path / "image.jpg")
    row = result_row(item, "Detected text", "tesseract", "chi_sim+eng", 0.91)
    out = tmp_path / "results.jsonl"

    write_jsonl(out, [row])
    loaded = json.loads(out.read_text(encoding="utf-8"))

    assert loaded == {
        "kind": "image",
        "output_hint": {"document_id": 42, "media_index": 1},
        "text": "Detected text",
        "model": "tesseract",
        "language": "chi_sim+eng",
        "confidence": 0.91,
    }


def test_unsupported_html_video_placeholder_is_skipped(tmp_path: Path) -> None:
    placeholder = tmp_path / "video.html"
    placeholder.write_text("<!doctype html><video src='missing.mp4'></video>", encoding="utf-8")

    report = process_queue(
        {"items": [queue_item(placeholder, kind="video")]},
        tmp_path / "results.jsonl",
        runtime(),
        media_cache_root=None,
        ocr_language="chi_sim+eng",
        asr_language="zh",
        timeout=1,
        gif_frames=5,
        dry_run=False,
    )

    assert report["counts"]["processed"] == 0
    assert report["counts"]["skipped"] == 1
    assert report["skipped"][0]["reason"] == "html_video_placeholder"
    assert (tmp_path / "results.jsonl").read_text(encoding="utf-8") == ""


def test_summary_counts_and_markdown() -> None:
    counts = summary_counts(
        queued=3,
        processed=[{"document_id": 1}],
        skipped=[{"document_id": 2}, {"document_id": 3}],
        rows=[
            {"confidence": 0.9},
            {"confidence": 0.4},
        ],
    )
    summary = {
        "dry_run": False,
        "path": "outputs/results.jsonl",
        "counts": counts,
        "remaining_pending": 2,
        "low_confidence_count": 1,
        "verification": {"ok": True},
        "skipped": [{"document_id": 2, "kind": "video", "media_index": 1, "reason": "unsupported", "detail": "webpage"}],
    }

    markdown = render_markdown_summary(summary)

    assert counts == {"queued": 3, "processed": 1, "written": 2, "skipped": 2, "low_confidence": 1}
    assert "- Processed: 1" in markdown
    assert "- Remaining pending: 2" in markdown
    assert "reason=unsupported" in markdown


def test_result_row_uses_output_hint_media_index_and_rejects_mismatch(tmp_path: Path) -> None:
    item = queue_item(tmp_path / "image.jpg", index=1)
    item["output_hint"]["media_index"] = 2

    try:
        result_row(item, "text", "model", "zh", 0.8)
    except ValueError as exc:
        assert "queue index mismatch" in str(exc)
    else:
        raise AssertionError("expected mismatch to raise")

    item["index"] = None
    row = result_row(item, "text", "model", "zh", 0.8)
    assert row["output_hint"]["media_index"] == 2


def test_apply_report_skips_are_failures() -> None:
    assert validate_apply_report({"summary": {"applied": 1, "skipped": 0}}, 1) == []
    errors = validate_apply_report({"summary": {"applied": 0, "skipped": 1}}, 1)
    assert "skipped 1" in errors[0]
    assert "applied 0 of 1" in errors[1]


def test_graph_signal_failure_falls_back_only_for_graph_errors() -> None:
    assert graph_signals_only_failure({"ok": False, "errors": ["document_id=1: missing media.text graph signals"]})
    assert not graph_signals_only_failure({"ok": False, "errors": ["media row missing"]})
    assert not graph_signals_only_failure({"ok": True, "errors": []})


def test_safe_join_media_cache_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"x")

    assert safe_join_media_cache(root, "inside.jpg") == (root / "inside.jpg").resolve()
    assert safe_join_media_cache(root, "../outside.jpg") == Path("../outside.jpg")


def test_openai_video_asr_provider_extracts_audio_and_writes_result(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    calls = []

    def runner(command, env, timeout):
        calls.append(command)
        wav = Path(command[-1])
        wav.write_bytes(b"wav")
        import subprocess

        return subprocess.CompletedProcess(command, 0, "", "")

    def requester(audio_path, config, language, timeout):
        assert audio_path.name == "audio.wav"
        assert audio_path.read_bytes() == b"wav"
        assert config.api_key == "test-key"
        assert config.model == "gpt-4o-transcribe"
        assert language == "zh"
        return "高质量云端转写"

    report = process_queue(
        {"items": [queue_item(video, kind="video")]},
        tmp_path / "results.jsonl",
        runtime(),
        media_cache_root=None,
        ocr_language="chi_sim+eng",
        asr_language="zh",
        timeout=10,
        gif_frames=5,
        dry_run=False,
        runner=runner,
        video_asr_provider="openai",
        openai_config=OpenAITranscriptionConfig(api_key="test-key", model="gpt-4o-transcribe"),
        openai_requester=requester,
    )

    assert calls == [video_wav_extract_command(runtime().ffmpeg, video, Path(calls[0][-1]))]
    assert report["counts"] == {"queued": 1, "processed": 1, "written": 1, "skipped": 0, "low_confidence": 0}
    assert report["results"][0]["text"] == "高质量云端转写"
    assert report["results"][0]["model"] == "openai:gpt-4o-transcribe"
    assert report["results"][0]["confidence"] == 0.85


def test_openai_provider_cli_requires_api_key_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    args = build_parser().parse_args(["--video-asr-provider", "openai"])

    try:
        validate_args(args)
    except ValueError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("expected missing OpenAI API key env to fail")

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    validate_args(args)


def test_parser_accepts_kind_filter_for_video_only_queue() -> None:
    args = build_parser().parse_args(["--kind", "video"])

    assert args.kind == "video"

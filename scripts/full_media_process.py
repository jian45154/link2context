#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from link2context.store import (
    apply_media_text,
    connect,
    init_db,
    media_queue,
    verify_media_text,
)

DEFAULT_APK_ROOT = Path("/home/lmi/.local/apk-root")
DEFAULT_FFMPEG = DEFAULT_APK_ROOT / "usr/bin/ffmpeg"
DEFAULT_TESSERACT = DEFAULT_APK_ROOT / "usr/bin/tesseract"
DEFAULT_TESSDATA_PREFIX = DEFAULT_APK_ROOT / "usr/share/tessdata"
DEFAULT_WHISPER_CLI = Path("/home/lmi/apps/asr-tools/whisper.cpp/build/bin/whisper-cli")
DEFAULT_WHISPER_MODEL = Path("/home/lmi/apps/asr-tools/whisper.cpp/models/ggml-tiny.bin")
DEFAULT_OUT = Path("outputs/full-media-results.jsonl")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
GIF_SUFFIXES = {".gif"}
VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}
HTML_SUFFIXES = {".html", ".htm"}

Runner = Callable[[list[str], dict[str, str], int], subprocess.CompletedProcess[str]]
OpenAIRequester = Callable[[Path, "OpenAITranscriptionConfig", str, int], str]


@dataclass(frozen=True)
class RuntimePaths:
    ffmpeg: Path
    tesseract: Path
    tessdata_prefix: Path
    whisper_cli: Path
    whisper_model: Path


@dataclass(frozen=True)
class OpenAITranscriptionConfig:
    api_key: str
    model: str = "gpt-4o-transcribe"
    endpoint: str = "https://api.openai.com/v1/audio/transcriptions"
    prompt: str = ""


def default_runtime_paths() -> RuntimePaths:
    return RuntimePaths(
        ffmpeg=DEFAULT_FFMPEG,
        tesseract=DEFAULT_TESSERACT,
        tessdata_prefix=DEFAULT_TESSDATA_PREFIX,
        whisper_cli=DEFAULT_WHISPER_CLI,
        whisper_model=DEFAULT_WHISPER_MODEL,
    )


def default_runner(command: list[str], env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
        check=False,
    )


def classify_queue_item(item: dict, media_cache_root: Path | None = None) -> dict:
    input_path = resolve_input_path(item.get("input_path"), media_cache_root)
    if not input_path:
        return classification(item, "missing_local_path", None, "no local media path")
    if not input_path.exists():
        return classification(item, "missing_file", input_path, "local media path does not exist")
    suffix = input_path.suffix.casefold()
    if suffix in HTML_SUFFIXES or looks_like_html(input_path):
        return classification(item, "html_video_placeholder", input_path, "cached HTML placeholder is not media")
    if suffix in GIF_SUFFIXES:
        return classification(item, "gif", input_path, "")
    if item.get("kind") == "image" and suffix in IMAGE_SUFFIXES:
        return classification(item, "image", input_path, "")
    if item.get("kind") == "video" and suffix in VIDEO_SUFFIXES:
        return classification(item, "video", input_path, "")
    return classification(item, "unsupported", input_path, f"unsupported media suffix: {suffix or 'none'}")


def resolve_input_path(raw_path: str | None, media_cache_root: Path | None = None) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute() or path.exists() or media_cache_root is None:
        return path
    rooted = safe_join_media_cache(media_cache_root, raw_path)
    if rooted.exists():
        return rooted
    by_name = media_cache_root / path.name
    if by_name.exists():
        return by_name
    return path


def safe_join_media_cache(media_cache_root: Path, raw_path: str) -> Path:
    root = media_cache_root.resolve()
    candidate = (root / raw_path).resolve()
    if candidate == root or root not in candidate.parents:
        return Path(raw_path)
    return candidate


def looks_like_html(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:512].lstrip().lower()
    except OSError:
        return False
    return sample.startswith(b"<!doctype html") or sample.startswith(b"<html") or b"<video" in sample


def classification(item: dict, media_type: str, path: Path | None, reason: str) -> dict:
    return {
        "type": media_type,
        "path": path,
        "reason": reason,
        "document_id": (item.get("output_hint") or {}).get("document_id"),
        "media_index": item.get("index"),
        "kind": item.get("kind"),
    }


def tesseract_command(tesseract: Path, image_path: Path, language: str) -> list[str]:
    return [str(tesseract), str(image_path), "stdout", "-l", language]


def gif_frame_extract_command(ffmpeg: Path, gif_path: Path, frame_pattern: Path, max_frames: int) -> list[str]:
    return [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(gif_path),
        "-vf",
        "fps=1",
        "-frames:v",
        str(max_frames),
        str(frame_pattern),
    ]


def video_wav_extract_command(ffmpeg: Path, video_path: Path, wav_path: Path) -> list[str]:
    return [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(wav_path),
    ]


def whisper_command(whisper_cli: Path, model: Path, wav_path: Path, out_prefix: Path, language: str) -> list[str]:
    command = [
        str(whisper_cli),
        "-m",
        str(model),
        "-f",
        str(wav_path),
        "-otxt",
        "-of",
        str(out_prefix),
    ]
    if language:
        command.extend(["-l", language])
    return command


def process_image(path: Path, runtime: RuntimePaths, language: str, timeout: int, runner: Runner) -> str:
    env = process_env(runtime)
    completed = runner(tesseract_command(runtime.tesseract, path, language), env, timeout)
    require_success(completed, "tesseract")
    return completed.stdout.strip()


def process_gif(
    path: Path,
    runtime: RuntimePaths,
    language: str,
    timeout: int,
    runner: Runner,
    max_frames: int,
) -> str:
    env = process_env(runtime)
    with tempfile.TemporaryDirectory(prefix="link2context-gif-") as tmp:
        frame_pattern = Path(tmp) / "frame-%03d.png"
        completed = runner(gif_frame_extract_command(runtime.ffmpeg, path, frame_pattern, max_frames), env, timeout)
        require_success(completed, "ffmpeg gif frame extraction")
        texts = []
        for frame in sorted(Path(tmp).glob("frame-*.png")):
            ocr = runner(tesseract_command(runtime.tesseract, frame, language), env, timeout)
            require_success(ocr, f"tesseract {frame.name}")
            texts.append(ocr.stdout)
        return combine_unique_texts(texts)


def process_video(
    path: Path,
    runtime: RuntimePaths,
    language: str,
    timeout: int,
    runner: Runner,
    provider: str = "local",
    openai_config: OpenAITranscriptionConfig | None = None,
    openai_requester: OpenAIRequester | None = None,
) -> str:
    env = process_env(runtime)
    with tempfile.TemporaryDirectory(prefix="link2context-video-") as tmp:
        wav_path = Path(tmp) / "audio.wav"
        completed = runner(video_wav_extract_command(runtime.ffmpeg, path, wav_path), env, timeout)
        require_success(completed, "ffmpeg audio extraction")
        if provider == "openai":
            if openai_config is None:
                raise ValueError("openai_config is required when provider='openai'")
            requester = openai_requester or default_openai_requester
            return requester(wav_path, openai_config, language, timeout).strip()
        if provider != "local":
            raise ValueError(f"unsupported video ASR provider: {provider}")
        prefix = Path(tmp) / "transcript"
        transcribed = runner(whisper_command(runtime.whisper_cli, runtime.whisper_model, wav_path, prefix, language), env, timeout)
        require_success(transcribed, "whisper-cli")
        txt_path = prefix.with_suffix(".txt")
        if txt_path.exists():
            return txt_path.read_text(encoding="utf-8").strip()
        return transcribed.stdout.strip()


def default_openai_requester(audio_path: Path, config: OpenAITranscriptionConfig, language: str, timeout: int) -> str:
    boundary = f"----link2context-{uuid.uuid4().hex}"
    fields = {
        "model": config.model,
        "language": language,
        "response_format": "json",
    }
    if config.prompt:
        fields["prompt"] = config.prompt
    body = multipart_form_data(boundary, fields, "file", audio_path, "audio/wav")
    request = urllib.request.Request(
        config.endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI transcription API failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI transcription API request failed: {exc}") from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI transcription API returned non-JSON response: {payload[:200]}") from exc
    text = data.get("text")
    if not isinstance(text, str):
        raise RuntimeError(f"OpenAI transcription API response missing text: {payload[:200]}")
    return text


def multipart_form_data(boundary: str, fields: dict[str, str], file_field: str, file_path: Path, content_type: str) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks)


def process_env(runtime: RuntimePaths) -> dict[str, str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    env["TESSDATA_PREFIX"] = str(runtime.tessdata_prefix)
    apk_root = runtime.tesseract.parents[2] if len(runtime.tesseract.parents) >= 3 else None
    if apk_root and (apk_root / "usr/lib").exists():
        env["PATH"] = os.pathsep.join(
            [str(apk_root / "usr/bin"), str(apk_root / "bin"), env.get("PATH", "")]
        )
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            [str(apk_root / "usr/lib"), str(apk_root / "lib"), env.get("LD_LIBRARY_PATH", "")]
        )
    return env


def require_success(completed: subprocess.CompletedProcess[str], label: str) -> None:
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise RuntimeError(f"{label} failed with exit {completed.returncode}: {stderr}")


def combine_unique_texts(texts: list[str]) -> str:
    unique = []
    seen = set()
    for text in texts:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return "\n\n".join(unique)


def result_row(item: dict, text: str, model: str, language: str, confidence: float | None) -> dict:
    output_hint = item.get("output_hint") if isinstance(item.get("output_hint"), dict) else {}
    media_index = output_hint.get("media_index", item.get("index"))
    if item.get("index") is not None and output_hint.get("media_index") is not None and item.get("index") != output_hint.get("media_index"):
        raise ValueError(
            f"queue index mismatch for document_id={output_hint.get('document_id')}: "
            f"index={item.get('index')} output_hint.media_index={output_hint.get('media_index')}"
        )
    return {
        "kind": item.get("kind"),
        "output_hint": {
            "document_id": output_hint.get("document_id"),
            "media_index": media_index,
        },
        "text": text.strip(),
        "model": model,
        "language": language,
        "confidence": confidence,
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def remaining_pending(conn, limit: int = 1_000_000) -> int:
    queue = media_queue(conn, "all", "not_processed", limit, False)
    return len(queue.get("items", []))


def process_queue(
    queue: dict,
    out_path: Path,
    runtime: RuntimePaths,
    media_cache_root: Path | None,
    ocr_language: str,
    asr_language: str,
    timeout: int,
    gif_frames: int,
    dry_run: bool,
    runner: Runner = default_runner,
    video_asr_provider: str = "local",
    openai_config: OpenAITranscriptionConfig | None = None,
    openai_requester: OpenAIRequester | None = None,
) -> dict:
    rows: list[dict] = []
    processed = []
    skipped = []
    planned = []
    for item in queue.get("items", []):
        info = classify_queue_item(item, media_cache_root)
        if info["type"] in {"missing_local_path", "missing_file", "html_video_placeholder", "unsupported"}:
            skipped.append({**skip_identity(item), "reason": info["type"], "detail": info["reason"]})
            continue
        path = info["path"]
        if dry_run:
            planned.append(plan_for_item(info, runtime, ocr_language, asr_language, gif_frames))
            continue
        try:
            if info["type"] == "image":
                text = process_image(path, runtime, ocr_language, timeout, runner)
                model = "tesseract"
            elif info["type"] == "gif":
                text = process_gif(path, runtime, ocr_language, timeout, runner, gif_frames)
                model = "ffmpeg+tesseract"
            else:
                text = process_video(
                    path,
                    runtime,
                    asr_language,
                    timeout,
                    runner,
                    provider=video_asr_provider,
                    openai_config=openai_config,
                    openai_requester=openai_requester,
                )
                model = (
                    f"openai:{openai_config.model}"
                    if video_asr_provider == "openai" and openai_config is not None
                    else f"ffmpeg+whisper.cpp:{runtime.whisper_model.name}"
                )
        except Exception as exc:
            skipped.append({**skip_identity(item), "reason": "processing_failed", "detail": str(exc)})
            continue
        if not text.strip():
            skipped.append({**skip_identity(item), "reason": "empty_output", "detail": "processor returned no text"})
            continue
        language = ocr_language if info["type"] in {"image", "gif"} else asr_language
        confidence = 0.65 if info["type"] in {"image", "gif"} else (0.85 if video_asr_provider == "openai" else 0.55)
        row = result_row(item, text, model, language, confidence)
        rows.append(row)
        processed.append({**skip_identity(item), "type": info["type"], "text_length": len(text)})
    if not dry_run:
        write_jsonl(out_path, rows)
    return {
        "path": str(out_path),
        "dry_run": dry_run,
        "queued": len(queue.get("items", [])),
        "results": rows,
        "processed": processed,
        "planned": planned,
        "skipped": skipped,
        "counts": summary_counts(len(queue.get("items", [])), processed, skipped, rows),
    }


def skip_identity(item: dict) -> dict:
    return {
        "document_id": (item.get("output_hint") or {}).get("document_id"),
        "media_index": item.get("index"),
        "kind": item.get("kind"),
        "input_path": item.get("input_path"),
        "input_url": item.get("input_url"),
    }


def plan_for_item(info: dict, runtime: RuntimePaths, ocr_language: str, asr_language: str, gif_frames: int) -> dict:
    path = info["path"]
    if info["type"] == "gif":
        return {
            **{key: info[key] for key in ("document_id", "media_index", "kind", "type")},
            "commands": [
                gif_frame_extract_command(runtime.ffmpeg, path, Path("frame-%03d.png"), gif_frames),
                tesseract_command(runtime.tesseract, Path("frame-001.png"), ocr_language),
            ],
        }
    if info["type"] == "video":
        return {
            **{key: info[key] for key in ("document_id", "media_index", "kind", "type")},
            "commands": [
                video_wav_extract_command(runtime.ffmpeg, path, Path("audio.wav")),
                whisper_command(runtime.whisper_cli, runtime.whisper_model, Path("audio.wav"), Path("transcript"), asr_language),
            ],
        }
    return {
        **{key: info[key] for key in ("document_id", "media_index", "kind", "type")},
        "commands": [tesseract_command(runtime.tesseract, path, ocr_language)],
    }


def summary_counts(queued: int, processed: list[dict], skipped: list[dict], rows: list[dict]) -> dict:
    return {
        "queued": queued,
        "processed": len(processed),
        "written": len(rows),
        "skipped": len(skipped),
        "low_confidence": sum(
            1
            for row in rows
            if row.get("confidence") is not None and float(row["confidence"]) < 0.70
        ),
    }


def render_markdown_summary(summary: dict) -> str:
    counts = summary.get("counts", {})
    parts = [
        "# Link2Context Full Media Process",
        "",
        f"- Dry run: {str(summary.get('dry_run', False)).lower()}",
        f"- Output: {summary.get('path')}",
        f"- Queued: {counts.get('queued', 0)}",
        f"- Processed: {counts.get('processed', 0)}",
        f"- Written: {counts.get('written', 0)}",
        f"- Skipped/blockers: {counts.get('skipped', 0)}",
        f"- Remaining pending: {summary.get('remaining_pending', 0)}",
        f"- Low confidence: {summary.get('low_confidence_count', counts.get('low_confidence', 0))}",
        f"- Verification OK: {str((summary.get('verification') or {}).get('ok')).lower()}",
        "",
    ]
    if summary.get("skipped"):
        parts.extend(["## Skipped", ""])
        for item in summary["skipped"][:20]:
            parts.append(
                f"- document={item.get('document_id')} {item.get('kind')}[{item.get('media_index')}] "
                f"reason={item.get('reason')} detail={item.get('detail')}"
            )
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def run(args: argparse.Namespace) -> dict:
    validate_args(args)
    runtime = RuntimePaths(
        ffmpeg=Path(args.ffmpeg),
        tesseract=Path(args.tesseract),
        tessdata_prefix=Path(args.tessdata_prefix),
        whisper_cli=Path(args.whisper_cli),
        whisper_model=Path(args.whisper_model),
    )
    openai_config = None
    if args.video_asr_provider == "openai":
        openai_config = OpenAITranscriptionConfig(
            api_key=os.environ[args.openai_api_key_env],
            model=args.openai_model,
            endpoint=args.openai_endpoint,
            prompt=args.openai_prompt,
        )
    conn = connect(Path(args.db))
    init_db(conn)
    queue = media_queue(conn, args.kind, "not_processed", args.limit, False)
    report = process_queue(
        queue=queue,
        out_path=Path(args.out),
        runtime=runtime,
        media_cache_root=Path(args.media_cache_root) if args.media_cache_root else None,
        ocr_language=args.ocr_language,
        asr_language=args.asr_language,
        timeout=args.timeout,
        gif_frames=args.gif_frames,
        dry_run=args.dry_run,
        video_asr_provider=args.video_asr_provider,
        openai_config=openai_config,
    )
    apply_report = None
    verification = None
    if not args.dry_run and report["results"]:
        apply_report = apply_media_text(conn, Path(args.out), status="processed", reindex=True)
        apply_errors = validate_apply_report(apply_report, len(report["results"]))
        if apply_errors:
            verification = {"ok": False, "summary": {"errors": len(apply_errors)}, "errors": apply_errors}
        else:
            verification = verify_media_text(conn, Path(args.out), status="processed", require_reindex=True)
            if graph_signals_only_failure(verification):
                fallback = verify_media_text(conn, Path(args.out), status="processed", require_reindex=False)
                verification = {
                    **fallback,
                    "graph_warning": verification.get("errors", []),
                    "require_reindex_ok": False,
                }
    elif not args.dry_run:
        verification = {"ok": True, "summary": {"input": 0, "verified": 0, "skipped": 0, "errors": 0}, "errors": []}
    report["apply"] = apply_report
    report["verification"] = verification
    if not args.dry_run and report.get("skipped"):
        report["marked_skipped"] = mark_skipped_media(conn, report["skipped"])
    report["remaining_pending"] = remaining_pending(conn)
    report["low_confidence_count"] = (
        (apply_report or {}).get("summary", {}).get("low_confidence", 0)
        if apply_report
        else report["counts"]["low_confidence"]
    )
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    return report


def graph_signals_only_failure(verification: dict | None) -> bool:
    if not verification or verification.get("ok"):
        return False
    errors = verification.get("errors") or []
    return bool(errors) and all("missing media.text graph signals" in error for error in errors)


def validate_apply_report(apply_report: dict, expected_results: int) -> list[str]:
    summary = apply_report.get("summary", {}) if apply_report else {}
    errors = []
    if summary.get("skipped", 0) > 0:
        errors.append(f"apply-media-text skipped {summary.get('skipped')} row(s)")
    if summary.get("applied", 0) != expected_results:
        errors.append(f"apply-media-text applied {summary.get('applied', 0)} of {expected_results} result row(s)")
    return errors


def mark_skipped_media(conn, skipped: list[dict]) -> dict:
    marked = []
    failed_reasons = {"processing_failed", "empty_output"}
    for item in skipped:
        document_id = item.get("document_id")
        media_index = item.get("media_index")
        kind = item.get("kind")
        if document_id is None or media_index is None:
            continue
        status = "text_failed" if item.get("reason") in failed_reasons else "unsupported"
        cursor = conn.execute(
            """
            UPDATE media
            SET status = ?, text_model = ?, text_language = ?, text_confidence = ?
            WHERE document_id = ? AND media_index = ?
              AND (? IS NULL OR kind = ?)
            """,
            (
                status,
                f"full_media_process:{item.get('reason')}",
                "",
                0.0,
                int(document_id),
                int(media_index),
                kind,
                kind,
            ),
        )
        if cursor.rowcount:
            marked.append({"document_id": document_id, "media_index": media_index, "kind": kind, "status": status, "reason": item.get("reason")})
    conn.commit()
    return {"count": len(marked), "items": marked}


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def validate_args(args: argparse.Namespace) -> None:
    for name in ("limit", "timeout", "gif_frames"):
        if getattr(args, name) <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be a positive integer")
    if args.video_asr_provider == "openai" and not os.environ.get(args.openai_api_key_env):
        raise ValueError(f"--video-asr-provider openai requires ${args.openai_api_key_env}")


def build_parser() -> argparse.ArgumentParser:
    defaults = default_runtime_paths()
    parser = argparse.ArgumentParser(description="Process pending Link2Context media with deterministic local OCR/ASR.")
    parser.add_argument("--db", default="data/link2context.db", help="Link2Context SQLite database path.")
    parser.add_argument("--limit", type=positive_int, default=50, help="Maximum pending media items to process.")
    parser.add_argument("--kind", choices=("all", "image", "video"), default="all", help="Media kind filter for the pending queue.")
    parser.add_argument("--dry-run", action="store_true", help="Classify and plan commands without processing or applying.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSONL path for apply-media-text compatible results.")
    parser.add_argument("--media-cache-root", help="Optional base directory for resolving relative media paths.")
    parser.add_argument("--ffmpeg", default=str(defaults.ffmpeg))
    parser.add_argument("--tesseract", default=str(defaults.tesseract))
    parser.add_argument("--tessdata-prefix", default=str(defaults.tessdata_prefix))
    parser.add_argument("--whisper-cli", default=str(defaults.whisper_cli))
    parser.add_argument("--whisper-model", default=str(defaults.whisper_model))
    parser.add_argument("--ocr-language", default="chi_sim+eng", help="Tesseract language flag.")
    parser.add_argument("--asr-language", default="zh", help="whisper.cpp/OpenAI transcription language hint.")
    parser.add_argument("--video-asr-provider", choices=("local", "openai"), default="local", help="Video transcription backend: local whisper.cpp or OpenAI transcription API.")
    parser.add_argument("--openai-api-key-env", default="OPENAI_API_KEY", help="Environment variable containing the OpenAI API key when --video-asr-provider=openai.")
    parser.add_argument("--openai-model", default="gpt-4o-transcribe", help="OpenAI audio transcription model.")
    parser.add_argument("--openai-endpoint", default="https://api.openai.com/v1/audio/transcriptions", help="OpenAI-compatible transcription endpoint.")
    parser.add_argument("--openai-prompt", default="", help="Optional transcription prompt/context for OpenAI ASR.")
    parser.add_argument("--timeout", type=positive_int, default=300, help="Per-command/API timeout in seconds.")
    parser.add_argument("--gif-frames", type=positive_int, default=5, help="Maximum representative GIF frames to OCR.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(args)
    if args.format == "markdown":
        print(render_markdown_summary(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    verification = report.get("verification")
    if verification and not verification.get("ok"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

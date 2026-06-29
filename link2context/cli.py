from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .agent_reach import platform_backend_status
from .fetch import fetch_url
from .xiaohongshu import build_xiaohongshu_context
from .wechat import build_wechat_context


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="link2context",
        description="Convert social content URLs into agent-ready context packages.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("input_url", nargs="?", help="WeChat or Xiaohongshu URL.")
    parser.add_argument("--url", help="Source URL to store when using --html.")
    parser.add_argument("--url-list", help="Text file with one URL per line.")
    parser.add_argument("--verify-batch", help="Verify a batch output directory before ingesting it.")
    parser.add_argument("--failed-url-list", help="Print failed URLs from a batch manifest for retry.")
    parser.add_argument("--retry-failed", help="Retry failed URLs from a batch manifest into --out.")
    parser.add_argument("--html", help="Read article HTML from a local file instead of fetching a URL.")
    parser.add_argument("--out", default="outputs/context", help="Output directory.")
    parser.add_argument("--format", choices=("markdown", "json", "commands"), default="markdown")
    parser.add_argument("--cookie", help="Cookie header value to use when fetching live URLs.")
    parser.add_argument("--cookie-file", help="Read Cookie header value from a local text file.")
    parser.add_argument(
        "--backend",
        choices=("native", "agent-reach", "auto"),
        default="native",
        help="Content acquisition backend. native fetches HTML directly; auto may use agent-reach when available.",
    )
    parser.add_argument(
        "--platform",
        choices=("auto", "wechat", "xiaohongshu"),
        default="auto",
        help="Parser platform. Defaults to URL-based auto detection.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.verify_batch:
        report = verify_batch(Path(args.verify_batch))
        if args.format == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.format == "commands":
            print("\n".join(report.get("recommended_next") or []))
        else:
            print(render_verify_batch_markdown(report))
        return

    if args.failed_url_list:
        report = failed_url_report(Path(args.failed_url_list))
        if args.format == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("\n".join(report["urls"]))
        return

    if args.retry_failed:
        if args.html:
            raise SystemExit("--html is only for single-article offline parsing, not --retry-failed.")
        report = retry_failed_batch(
            Path(args.retry_failed),
            Path(args.out),
            args.platform,
            args.backend,
            read_cookie(args),
        )
        if args.format == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.format == "commands":
            print("\n".join(report.get("recommended_next") or []))
        else:
            print(render_retry_failed_markdown(report))
        return

    if args.url_list:
        if args.html:
            raise SystemExit("--html is only for single-article offline parsing, not --url-list.")
        run_batch(Path(args.url_list), Path(args.out), args.platform, args.backend, read_cookie(args))
        return

    source_url = normalize_source_url(args.url or args.input_url)
    if not source_url:
        raise SystemExit("Provide a WeChat article URL, --url-list, or use --html with --url.")

    if args.html:
        html = Path(args.html).read_text(encoding="utf-8")
    else:
        html = fetch_url(source_url, cookie=read_cookie(args))

    context = build_context(source_url, html, args.platform, args.backend)
    write_context(context, Path(args.out))


def run_batch(
    url_list: Path,
    out_root: Path,
    platform: str,
    backend: str,
    cookie: str | None = None,
) -> None:
    urls = read_url_list(url_list)
    if not urls:
        raise SystemExit(f"No URLs found in {url_list}.")
    run_batch_urls(urls, out_root, platform, backend, cookie)


def run_batch_urls(
    urls: list[str],
    out_root: Path,
    platform: str,
    backend: str,
    cookie: str | None = None,
) -> dict:
    out_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "project": "Link2Context",
        "format": "batch-context",
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(urls),
        "succeeded": 0,
        "failed": 0,
        "ok": False,
        "items": [],
        "failures": [],
    }

    for index, url in enumerate(urls, start=1):
        item_dir = out_root / f"{index:03d}-{slug_from_url(url)}"
        try:
            html = fetch_url(url, cookie=cookie)
            context = build_context(url, html, platform, backend)
            write_context(context, item_dir)
            item = {
                "index": index,
                "url": url,
                "status": "ok",
                "output_dir": str(item_dir),
                "platform": context["source"].get("platform"),
                "title": context["article"].get("title"),
                "file_details": {
                    "context.json": file_detail(item_dir / "context.json"),
                    "context.md": file_detail(item_dir / "context.md"),
                },
            }
            manifest["items"].append(item)
            manifest["succeeded"] += 1
        except Exception as exc:  # pragma: no cover - network behavior varies.
            item_dir.mkdir(parents=True, exist_ok=True)
            error = {"index": index, "url": url, "status": "error", "error": str(exc)}
            (item_dir / "error.json").write_text(
                json.dumps(error, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            item = {**error, "output_dir": str(item_dir)}
            item["file_details"] = {"error.json": file_detail(item_dir / "error.json")}
            manifest["items"].append(item)
            manifest["failures"].append(item)
            manifest["failed"] += 1
            print(f"Failed {index}: {url} ({exc})")

    manifest["ok"] = manifest["failed"] == 0
    summary = {
        "count": manifest["count"],
        "succeeded": manifest["succeeded"],
        "failed": manifest["failed"],
    }
    manifest["recommended_next"] = batch_recommended_next(out_root, summary, [])
    (out_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote batch manifest {out_root / 'manifest.json'}")
    return manifest


def retry_failed_batch(
    batch_dir: Path,
    out_root: Path,
    platform: str,
    backend: str,
    cookie: str | None = None,
) -> dict:
    failed = failed_url_report(batch_dir)
    if not failed["urls"]:
        raise SystemExit(f"No failed URLs found in {batch_dir}.")

    out_root.mkdir(parents=True, exist_ok=True)
    retry_list = out_root / "retry_urls.txt"
    retry_list.write_text("\n".join(failed["urls"]) + "\n", encoding="utf-8")
    manifest = run_batch_urls(failed["urls"], out_root, platform, backend, cookie)
    manifest["retry_source_batch"] = str(batch_dir)
    manifest["retry_url_list"] = str(retry_list)
    (out_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "ok": manifest.get("ok"),
        "source_batch": str(batch_dir),
        "retry_url_list": str(retry_list),
        "output_dir": str(out_root),
        "retried": len(failed["urls"]),
        "succeeded": manifest.get("succeeded", 0),
        "failed": manifest.get("failed", 0),
        "recommended_next": [
            f"python -m link2context --verify-batch {command_arg(out_root)}",
            f"python -m link2context.store --db data/link2context.db ingest {command_arg(out_root)}",
        ],
    }


def render_retry_failed_markdown(report: dict) -> str:
    parts = [
        "# Link2Context Retry Failed Batch",
        "",
        f"- Status: {'ok' if report.get('ok') else 'needs_attention'}",
        f"- Source batch: {report.get('source_batch')}",
        f"- Output: {report.get('output_dir')}",
        f"- Retry URL list: {report.get('retry_url_list')}",
        f"- Retried: {report.get('retried', 0)}",
        f"- Succeeded: {report.get('succeeded', 0)}",
        f"- Failed: {report.get('failed', 0)}",
        "",
    ]
    if report.get("recommended_next"):
        parts.extend(["## Recommended Next", ""])
        for command in report["recommended_next"]:
            parts.append(f"- `{command}`")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def verify_batch(path: Path) -> dict:
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return {
            "ok": False,
            "path": str(path),
            "errors": ["manifest.json is missing"],
            "items": [],
            "summary": {"count": 0, "succeeded": 0, "failed": 0},
            "recommended_next": [],
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = list(manifest.get("items") or [])
    errors: list[str] = []
    item_reports: list[dict] = []
    succeeded = sum(1 for item in items if item.get("status") == "ok")
    failed = sum(1 for item in items if item.get("status") == "error")
    failure_items = [item for item in items if item.get("status") == "error"]

    if manifest.get("project") != "Link2Context":
        errors.append("manifest project is not Link2Context")
    if manifest.get("format") != "batch-context":
        errors.append("manifest format is not batch-context")
    if manifest.get("version") != 1:
        errors.append("manifest version is not 1")
    generated_at_error = validate_generated_at(manifest.get("generated_at"))
    if generated_at_error:
        errors.append(generated_at_error)
    if manifest.get("count") != len(items):
        errors.append("manifest count does not match item count")
    if manifest.get("succeeded") != succeeded:
        errors.append("manifest succeeded does not match ok item count")
    if manifest.get("failed") != failed:
        errors.append("manifest failed does not match error item count")
    if manifest.get("failures", []) != failure_items:
        errors.append("manifest failures do not match error items")
    if bool(manifest.get("ok")) != (failed == 0):
        errors.append("manifest ok does not match failed count")

    for item in items:
        item_dir = batch_item_dir(path, item)
        item_errors: list[str] = []
        if not item_dir.exists():
            item_errors.append("output_dir is missing")
        elif item.get("status") == "ok":
            if not (item_dir / "context.json").exists():
                item_errors.append("context.json is missing")
            elif not file_detail_matches(item_dir / "context.json", item.get("file_details", {}).get("context.json")):
                item_errors.append("context.json does not match manifest detail")
            if not (item_dir / "context.md").exists():
                item_errors.append("context.md is missing")
            elif not file_detail_matches(item_dir / "context.md", item.get("file_details", {}).get("context.md")):
                item_errors.append("context.md does not match manifest detail")
        elif item.get("status") == "error":
            if not (item_dir / "error.json").exists():
                item_errors.append("error.json is missing")
            elif not file_detail_matches(item_dir / "error.json", item.get("file_details", {}).get("error.json")):
                item_errors.append("error.json does not match manifest detail")
        else:
            item_errors.append(f"unsupported status: {item.get('status')}")

        if item_errors:
            label = item.get("url") or item.get("output_dir") or item.get("index")
            errors.extend(f"{label}: {error}" for error in item_errors)
        item_reports.append(
            {
                "index": item.get("index"),
                "url": item.get("url"),
                "status": item.get("status"),
                "output_dir": str(item_dir),
                "ok": not item_errors,
                "errors": item_errors,
            }
        )

    summary = {
        "count": len(items),
        "succeeded": succeeded,
        "failed": failed,
    }
    expected_manifest_next = batch_recommended_next(path, summary, [])
    if manifest.get("recommended_next") != expected_manifest_next:
        errors.append("manifest recommended_next does not match expected commands")
    return {
        "ok": not errors,
        "path": str(path),
        "errors": errors,
        "summary": summary,
        "manifest": {
            "project": manifest.get("project"),
            "format": manifest.get("format"),
            "version": manifest.get("version"),
            "generated_at": manifest.get("generated_at"),
            "count": manifest.get("count"),
            "succeeded": manifest.get("succeeded"),
            "failed": manifest.get("failed"),
            "ok": manifest.get("ok"),
        },
        "items": item_reports,
        "recommended_next": batch_recommended_next(path, summary, errors),
    }


def batch_item_dir(batch_dir: Path, item: dict) -> Path:
    output_dir = item.get("output_dir")
    if not output_dir:
        return batch_dir / f"{int(item.get('index') or 0):03d}-{slug_from_url(item.get('url') or '')}"
    path = Path(output_dir)
    if path.exists() or path.is_absolute():
        return path
    fallback = batch_dir / path.name
    return fallback if fallback.exists() else path


def validate_generated_at(value: object) -> str | None:
    if not value:
        return "manifest generated_at is missing"
    if not isinstance(value, str):
        return "manifest generated_at is not a string"
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "manifest generated_at is not valid ISO datetime"
    return None


def file_detail(path: Path) -> dict:
    data = path.read_bytes()
    return {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def file_detail_matches(path: Path, expected: object) -> bool:
    if not isinstance(expected, dict):
        return True
    return file_detail(path) == {
        "size_bytes": expected.get("size_bytes"),
        "sha256": expected.get("sha256"),
    }


def render_verify_batch_markdown(report: dict) -> str:
    summary = report.get("summary") or {}
    parts = [
        "# Link2Context Batch Verification",
        "",
        f"- Status: {'ok' if report.get('ok') else 'needs_attention'}",
        f"- Path: {report.get('path')}",
        f"- Items: {summary.get('count', 0)}",
        f"- Succeeded: {summary.get('succeeded', 0)}",
        f"- Failed: {summary.get('failed', 0)}",
        "",
    ]
    if report.get("errors"):
        parts.extend(["## Errors", ""])
        parts.extend(f"- {error}" for error in report["errors"])
        parts.append("")
    if report.get("items"):
        parts.extend(["## Items", ""])
        for item in report["items"]:
            status = "ok" if item.get("ok") else "needs_attention"
            parts.append(f"- {item.get('index')}: {item.get('status')} ({status}) {item.get('url')}")
            for error in item.get("errors", []):
                parts.append(f"  - {error}")
        parts.append("")
    if report.get("recommended_next"):
        parts.extend(["## Recommended Next", ""])
        for command in report["recommended_next"]:
            parts.append(f"- `{command}`")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def batch_recommended_next(path: Path, summary: dict, errors: list[str]) -> list[str]:
    commands: list[str] = []
    batch_path = command_arg(path)
    if summary.get("failed", 0) > 0:
        commands.append(f"python -m link2context --failed-url-list {batch_path} > outputs/retry_urls.txt")
        commands.append(f"python -m link2context --retry-failed {batch_path} --out outputs/retry")
    if summary.get("succeeded", 0) > 0:
        commands.append(f"python -m link2context.store --db data/link2context.db ingest {batch_path}")
    if errors:
        commands.append(f"python -m link2context --verify-batch {batch_path}")
    return commands


def command_arg(value: Path | str) -> str:
    text = str(value)
    if not text:
        return '""'
    if not re.search(r"\s", text):
        return text
    return '"' + text.replace('"', '\\"') + '"'


def failed_url_report(path: Path) -> dict:
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return {
            "ok": False,
            "path": str(path),
            "urls": [],
            "items": [],
            "errors": ["manifest.json is missing"],
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    urls: list[str] = []
    seen: set[str] = set()
    items: list[dict] = []
    for item in manifest.get("items") or []:
        if item.get("status") != "error":
            continue
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        items.append(
            {
                "index": item.get("index"),
                "url": url,
                "error": item.get("error"),
                "output_dir": item.get("output_dir"),
            }
        )

    return {
        "ok": True,
        "path": str(path),
        "count": len(urls),
        "urls": urls,
        "items": items,
        "errors": [],
    }


def read_url_list(path: Path) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        value = normalize_source_url(value)
        if value in seen:
            continue
        seen.add(value)
        urls.append(value)
    return urls


def normalize_source_url(value: str | None) -> str | None:
    if not value:
        return value
    value = value.strip()
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        return value
    if value.startswith(("xiaohongshu.com/", "www.xiaohongshu.com/", "xhslink.com/", "mp.weixin.qq.com/")):
        return f"https://{value}"
    return value


def read_cookie(args: argparse.Namespace) -> str | None:
    if args.cookie and args.cookie_file:
        raise SystemExit("Use either --cookie or --cookie-file, not both.")
    if args.cookie_file:
        return Path(args.cookie_file).read_text(encoding="utf-8").strip()
    return args.cookie


def write_context(context: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "context.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "context.md").write_text(render_markdown(context), encoding="utf-8")

    print(f"Wrote {out_dir / 'context.json'}")
    print(f"Wrote {out_dir / 'context.md'}")


def build_context(url: str, html: str, platform: str = "auto", backend: str = "native") -> dict:
    resolved = detect_platform(url) if platform == "auto" else platform
    backend_warning = backend_status_warning(resolved, backend)
    if resolved == "wechat":
        context = build_wechat_context(url, html)
    elif resolved == "xiaohongshu":
        context = build_xiaohongshu_context(url, html)
    else:
        raise ValueError(f"Unsupported platform: {resolved}")

    if backend_warning:
        context["quality"].setdefault("warnings", []).append(backend_warning)
        context["source"]["backend"] = "native"
    else:
        context["source"]["backend"] = backend
    return context


def backend_status_warning(platform: str, backend: str) -> str | None:
    if backend == "native":
        return None
    if backend == "agent-reach" or backend == "auto":
        status = platform_backend_status(platform)
        if status["available"]:
            return (
                f"agent-reach backend {status['active_backend']} is available, "
                "but this MVP still uses native normalization for output."
            )
        if backend == "agent-reach":
            return f"agent-reach backend is unavailable for {platform}: {status['reason']}"
        return None
    return f"Unsupported backend requested: {backend}"


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return "xiaohongshu"
    if "weixin.qq.com" in host:
        return "wechat"
    return "wechat"


def slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    tail = re.sub(r"[^a-zA-Z0-9]+", "-", path.split("/")[-1]).strip("-")
    return (tail or "social-post")[:48]


def render_markdown(context: dict) -> str:
    article = context["article"]
    source = context["source"]
    content = context["content"]
    media = context["media"]
    warnings = context["quality"].get("warnings", [])

    parts = [
        f"# {article.get('title') or 'Untitled WeChat Article'}",
        "",
        f"- Platform: {source['platform']}",
        f"- URL: {source['url']}",
        f"- Account: {article.get('account_name') or 'Unknown'}",
        f"- Author: {article.get('author') or 'Unknown'}",
        f"- Published: {article.get('published_at') or 'Unknown'}",
        "",
    ]

    if article.get("summary"):
        parts.extend(["## Summary", "", article["summary"], ""])

    parts.extend(["## Article", "", content.get("markdown") or content.get("plain_text") or "", ""])

    if media["images"]:
        parts.extend(["## Images", ""])
        for image in media["images"]:
            parts.append(
                f"- image_{image['index']}: {image['url']} "
                f"(ocr_status={image['ocr']['status']})"
            )
        parts.append("")

    if media["videos"]:
        parts.extend(["## Videos", ""])
        for video in media["videos"]:
            parts.append(
                f"- video_{video['index']}: {video.get('embed_url') or 'embedded'} "
                f"(parse_status={video['analysis']['status']})"
            )
        parts.append("")

    parts.extend(
        [
            "## Agent Brief",
            "",
            context["agent_brief"]["summary"],
            "",
            f"Suggested use: {context['agent_brief']['suggested_use']}",
            "",
        ]
    )

    if warnings:
        parts.extend(["## Warnings", ""])
        parts.extend(f"- {warning}" for warning in warnings)
        parts.append("")

    return "\n".join(parts).strip() + "\n"


if __name__ == "__main__":
    main()

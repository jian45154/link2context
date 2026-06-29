from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse


def build_xiaohongshu_context(url: str, raw_html: str) -> dict:
    warnings: list[str] = []
    parser = XiaohongshuContentParser()
    parser.feed(raw_html)

    json_text = _extract_json_state(raw_html)
    json_values = _flatten_json_values(json_text) if json_text else []

    title = _clean_title(
        _extract_meta(raw_html, "og:title")
        or _extract_meta(raw_html, "title")
        or _pick_json_value(json_values, ("title", "displayTitle"))
    )
    author = (
        _extract_meta(raw_html, "author")
        or _pick_json_value(json_values, ("nickname", "nickName", "userName"))
    )
    description = _clean_note_text(
        _extract_meta(raw_html, "description")
        or _extract_meta(raw_html, "og:description")
        or _pick_json_value(json_values, ("desc", "description", "content"))
    )
    cover_image = _extract_meta(raw_html, "og:image") or _first(parser.images)
    video_url = _extract_meta(raw_html, "og:video") or _extract_meta(raw_html, "og:video:url")

    fragments = _clean_fragments(parser.text_fragments, title, description)
    markdown = _clean_markdown(_compose_markdown(title, description, fragments))
    plain_text = _markdown_to_text(markdown)
    image_urls = _dedupe([url for url in parser.images if url])
    if cover_image:
        image_urls = _dedupe([cover_image, *image_urls])
    video_urls = _dedupe([url for url in [video_url, *parser.videos] if url])

    if not json_text:
        warnings.append("Could not find an embedded Xiaohongshu JSON state; parsed meta tags and visible HTML only.")
    if not title:
        warnings.append("Title was not found.")
    if not plain_text:
        warnings.append("Note text was empty after parsing.")
    elif len(plain_text) < 40:
        warnings.append("Note text is unusually short; Xiaohongshu may have returned a restricted or shell page.")
    elif _looks_like_shell_text(plain_text):
        warnings.append("Note text looks dominated by Xiaohongshu shell or boilerplate content.")

    missing_fields = [
        field
        for field, value in {
            "title": title,
            "account_name": author,
            "plain_text": plain_text,
        }.items()
        if not value
    ]

    summary = description or _simple_summary(title, plain_text)

    return {
        "project": "Link2Context",
        "project_cn": "灵渠",
        "schema_version": "0.1",
        "source": {
            "platform": "xiaohongshu",
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "identifiers": _url_identifiers(url),
        },
        "article": {
            "title": title,
            "account_name": author,
            "author": author,
            "published_at": None,
            "summary": summary,
            "canonical_url": url,
        },
        "content": {
            "html": raw_html,
            "markdown": markdown,
            "plain_text": plain_text,
        },
        "media": {
            "cover_image": cover_image,
            "images": _images(image_urls),
            "videos": _videos(video_urls),
        },
        "agent_brief": {
            "summary": summary or "No summary available from extracted content.",
            "suggested_use": "Use this as a source-grounded Xiaohongshu note package for Chinese social content summarization, extraction, or RAG ingestion.",
        },
        "agent_package": {
            "brief": summary or _simple_summary(title, plain_text),
            "key_points": [],
            "claims": [],
            "entities": [],
            "links": parser.links,
            "citations": _citations(markdown),
        },
        "quality": {
            "status": _quality_status(title, plain_text, warnings),
            "warnings": warnings,
            "missing_fields": missing_fields,
        },
    }


class XiaohongshuContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[str] = []
        self.videos: list[str] = []
        self.links: list[dict] = []
        self.text_fragments: list[str] = []
        self._skip_depth = 0
        self._link_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value for key, value in attrs if value}
        if tag in {"script", "style", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "a":
            self._link_href = attr.get("href")
        elif tag == "img":
            image_url = attr.get("src") or attr.get("data-src")
            if image_url:
                self.images.append(html.unescape(image_url))
        elif tag in {"video", "source"}:
            video_url = attr.get("src")
            if video_url:
                self.videos.append(html.unescape(video_url))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "a":
            self._link_href = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = _clean_text(data)
        if not value:
            return
        if self._link_href:
            self.links.append({"text": value, "url": self._link_href})
        elif len(value) > 1:
            self.text_fragments.append(value)


def _extract_json_state(raw_html: str) -> str | None:
    patterns = [
        r'<script[^>]+id=["\']__INITIAL_STATE__["\'][^>]*>(.*?)</script>',
        r'<script[^>]*>\s*window\.__INITIAL_STATE__\s*=\s*(.*?)</script>',
        r'<script[^>]*>\s*window\.__NUXT__\s*=\s*(.*?)</script>',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_html, re.IGNORECASE | re.DOTALL)
        if match:
            return html.unescape(match.group(1)).strip().rstrip(";")
    return None


def _flatten_json_values(json_text: str | None) -> list[tuple[str, object]]:
    if not json_text:
        return []
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return []

    values: list[tuple[str, object]] = []

    def walk(value: object, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                walk(child_value, child_key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        else:
            values.append((key, value))

    walk(data)
    return values


def _pick_json_value(values: list[tuple[str, object]], keys: tuple[str, ...]) -> str | None:
    for key, value in values:
        if key in keys and isinstance(value, str) and value.strip():
            return _clean_text(value)
    return None


def _extract_meta(raw_html: str, name: str) -> str | None:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(name)}["\'][^>]+content=["\'](.*?)["\']',
        rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\'](.*?)["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']{re.escape(name)}["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']{re.escape(name)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_html, re.IGNORECASE | re.DOTALL)
        if match:
            return _clean_text(match.group(1))
    return None


def _url_identifiers(url: str) -> dict:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    identifiers = {
        key: query.get(key, [None])[0]
        for key in ("xsec_token", "xsec_source")
        if query.get(key)
    }
    parts = [part for part in parsed.path.split("/") if part]
    if parts:
        identifiers["path_id"] = parts[-1]
    return identifiers


def _images(urls: list[str]) -> list[dict]:
    return [
        {
            "index": index,
            "url": url,
            "alt": None,
            "ocr": {
                "status": "not_processed",
                "text": "",
                "blocks": [],
                "note": "OCR is reserved for the next MVP layer.",
            },
            "context_text": None,
        }
        for index, url in enumerate(urls, start=1)
    ]


def _videos(urls: list[str]) -> list[dict]:
    return [
        {
            "index": index,
            "embed_url": url,
            "status": "not_processed",
            "analysis": {
                "status": "not_processed",
                "transcript": [],
                "keyframes": [],
                "timeline": [],
                "note": "Video parsing is reserved for the next MVP layer.",
            },
        }
        for index, url in enumerate(urls, start=1)
    ]


def _compose_markdown(title: str | None, description: str | None, fragments: list[str]) -> str:
    parts: list[str] = []
    if title:
        parts.extend([f"# {title}", ""])
    if description:
        parts.extend([description, ""])
    for fragment in fragments:
        if fragment != title and fragment != description:
            parts.extend([fragment, ""])
    return "\n".join(parts)


def _clean_title(value: str | None) -> str | None:
    if not value:
        return None
    value = _clean_text(value)
    value = re.sub(r"\s*[-_]\s*小红书\s*$", "", value)
    return value or None


def _clean_fragments(
    fragments: list[str],
    title: str | None,
    description: str | None,
) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    blocked = {
        "创作中心",
        "业务合作",
        "关于我们",
        "社会责任",
        "加入我们",
        "更多",
        "关注",
        "加载中",
        "隐私政策",
        "用户协议",
        "小红书",
    }
    for fragment in fragments:
        value = _clean_note_text(fragment)
        if not value:
            continue
        if value in blocked:
            continue
        if value == title or value == description:
            continue
        if re.search(r"©\s*2014-20\d{2}", value):
            continue
        if "行吟信息科技" in value or "马当路388号" in value or "9501-3888" in value:
            continue
        if value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def _clean_note_text(value: str | None) -> str | None:
    if not value:
        return None
    value = _clean_text(value)
    cut_markers = [
        "创作中心",
        "业务合作",
        "© 2014-",
        "行吟信息科技",
        "地址：上海市黄浦区马当路388号",
        "电话：9501-3888",
        "更多 关于我们",
    ]
    positions = [value.find(marker) for marker in cut_markers if marker in value]
    if positions:
        value = value[: min(positions)].strip()
    return value or None


def _citations(markdown: str) -> list[dict]:
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n{2,}", markdown)
        if paragraph.strip()
    ]
    return [
        {
            "ref": f"paragraph_{index}",
            "text": paragraph[:500],
            "source": "note_body",
        }
        for index, paragraph in enumerate(paragraphs, start=1)
    ]


def _quality_status(title: str | None, text: str, warnings: list[str]) -> str:
    if not text:
        return "empty"
    if not title or len(text) < 40 or warnings:
        return "partial"
    return "ok"


def _looks_like_shell_text(text: str) -> bool:
    boilerplate_hits = sum(
        1
        for marker in ("创作中心", "业务合作", "行吟信息科技", "9501-3888", "关于我们")
        if marker in text
    )
    return boilerplate_hits >= 2 and len(text) < 240


def _simple_summary(title: str | None, text: str) -> str:
    sample = text[:240].strip()
    if title and sample:
        return f"{title}: {sample}"
    return title or sample or "No summary available from extracted content."


def _markdown_to_text(markdown: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", markdown)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    return _clean_text(text)


def _clean_markdown(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()


def _clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _first(values: list[str]) -> str | None:
    return values[0] if values else None

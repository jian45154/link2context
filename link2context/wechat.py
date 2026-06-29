from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timezone
from html.parser import HTMLParser


def build_wechat_context(url: str, raw_html: str) -> dict:
    warnings: list[str] = []
    content_html = _extract_js_content(raw_html)
    if not content_html:
        content_html = raw_html
        warnings.append("Could not find #js_content; parsed the full HTML document instead.")

    parser = WeChatContentParser()
    parser.feed(content_html)
    markdown = _clean_markdown(parser.markdown())
    text = _markdown_to_text(markdown)

    title = (
        _extract_meta(raw_html, "og:title")
        or _extract_var(raw_html, "msg_title")
        or _extract_first(raw_html, r'id=["\']activity-name["\'][^>]*>(.*?)</')
    )
    author = (
        _extract_meta(raw_html, "author")
        or _extract_var(raw_html, "nickname")
        or _extract_first(raw_html, r'id=["\']js_name["\'][^>]*>(.*?)</')
    )
    digest = _extract_meta(raw_html, "description") or _extract_var(raw_html, "msg_desc")
    published_at = _extract_published_at(raw_html)
    cover_image = _extract_meta(raw_html, "og:image") or _extract_var(raw_html, "msg_cdn_url")

    if not title:
        warnings.append("Title was not found.")
    if not text:
        warnings.append("Article body text was empty after parsing.")
    elif len(text) < 120:
        warnings.append("Article body text is unusually short; WeChat may have returned a redirect, image-detail page, or restricted page.")

    missing_fields = [
        field
        for field, value in {
            "title": title,
            "account_name": author,
            "published_at": published_at,
            "plain_text": text,
        }.items()
        if not value
    ]

    return {
        "project": "Link2Context",
        "project_cn": "灵渠",
        "schema_version": "0.1",
        "source": {
            "platform": "wechat_official_account",
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "identifiers": _url_identifiers(url, raw_html),
        },
        "article": {
            "title": title,
            "account_name": author,
            "author": None,
            "published_at": published_at,
            "summary": digest,
            "canonical_url": url,
        },
        "content": {
            "html": content_html,
            "markdown": markdown,
            "plain_text": text,
        },
        "media": {
            "cover_image": cover_image,
            "images": _images(parser.images),
            "videos": _videos(parser.videos),
        },
        "agent_brief": {
            "summary": _simple_summary(title, digest, text),
            "suggested_use": "Use this as a source-grounded context package for Chinese article summarization, extraction, or RAG ingestion.",
        },
        "agent_package": {
            "brief": _simple_summary(title, digest, text),
            "key_points": [],
            "claims": [],
            "entities": [],
            "links": parser.links,
            "citations": _citations(markdown),
        },
        "quality": {
            "status": _quality_status(title, text, warnings),
            "warnings": warnings,
            "missing_fields": missing_fields,
        },
    }


class WeChatContentParser(HTMLParser):
    block_tags = {"p", "div", "section", "article", "li", "blockquote"}
    heading_tags = {"h1", "h2", "h3"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.images: list[dict] = []
        self.videos: list[dict] = []
        self.links: list[dict] = []
        self._skip_depth = 0
        self._link_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value for key, value in attrs if value}
        if tag in {"script", "style", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag in self.block_tags:
            self.parts.append("\n\n")
        elif tag in self.heading_tags:
            level = {"h1": "#", "h2": "##", "h3": "###"}[tag]
            self.parts.append(f"\n\n{level} ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "a":
            self._link_href = attr.get("href")
        elif tag == "img":
            url = attr.get("data-src") or attr.get("src")
            if url:
                self.images.append(
                    {
                        "url": html.unescape(url),
                        "alt": attr.get("alt"),
                        "source_attrs": {
                            "data-src": attr.get("data-src"),
                            "src": attr.get("src"),
                        },
                    }
                )
                self.parts.append(f"\n\n[Image {len(self.images)}]\n\n")
        elif tag in {"video", "iframe"}:
            url = attr.get("data-src") or attr.get("src")
            self.videos.append({"url": html.unescape(url) if url else None, "tag": tag})
            self.parts.append(f"\n\n[Video {len(self.videos)}]\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a":
            self._link_href = None
        if tag in self.block_tags or tag in self.heading_tags:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = re.sub(r"\s+", " ", data).strip()
        if not value:
            return
        if self._link_href:
            self.links.append({"text": value, "url": self._link_href})
            self.parts.append(f"[{value}]({self._link_href})")
        else:
            self.parts.append(value)

    def markdown(self) -> str:
        return "".join(self.parts)


def _extract_js_content(raw_html: str) -> str | None:
    match = re.search(
        r'<div[^>]+id=["\']js_content["\'][^>]*>(.*?)</div>\s*</div>\s*</div>',
        raw_html,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1)

    start = re.search(r'<div[^>]+id=["\']js_content["\'][^>]*>', raw_html, re.IGNORECASE)
    if not start:
        return None
    return raw_html[start.end() :]


def _extract_meta(raw_html: str, name: str) -> str | None:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(name)}["\'][^>]+content=["\'](.*?)["\']',
        rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\'](.*?)["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']{re.escape(name)}["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']{re.escape(name)}["\']',
    ]
    for pattern in patterns:
        value = _extract_first(raw_html, pattern)
        if value:
            return value
    return None


def _extract_var(raw_html: str, name: str) -> str | None:
    return _extract_first(raw_html, rf'var\s+{re.escape(name)}\s*=\s*["\'](.*?)["\']')


def _extract_first(raw_html: str, pattern: str) -> str | None:
    match = re.search(pattern, raw_html, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return _clean_text(match.group(1))


def _extract_published_at(raw_html: str) -> str | None:
    ct = _extract_first(raw_html, r'var\s+ct\s*=\s*["\']?(\d{10})["\']?')
    if not ct:
        return None
    return datetime.fromtimestamp(int(ct), timezone.utc).isoformat()


def _url_identifiers(url: str, raw_html: str) -> dict:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    identifiers = {
        key: query.get(key, [None])[0]
        for key in ("__biz", "mid", "idx", "sn", "chksm")
        if query.get(key)
    }
    biz = _extract_var(raw_html, "biz") or _extract_first(raw_html, r'__biz=([^"&]+)')
    if biz and "__biz" not in identifiers:
        identifiers["__biz"] = biz
    return identifiers


def _images(images: list[dict]) -> list[dict]:
    return [
        {
            "index": index,
            "url": image["url"],
            "alt": image.get("alt"),
            "ocr": {
                "status": "not_processed",
                "text": "",
                "blocks": [],
                "note": "OCR is reserved for the next MVP layer.",
            },
            "context_text": None,
        }
        for index, image in enumerate(images, start=1)
    ]


def _videos(videos: list[dict]) -> list[dict]:
    return [
        {
            "index": index,
            "embed_url": video.get("url"),
            "status": "unresolved",
            "analysis": {
                "status": "not_processed",
                "transcript": [],
                "keyframes": [],
                "timeline": [],
                "note": "Video parsing is reserved for the next MVP layer.",
            },
        }
        for index, video in enumerate(videos, start=1)
    ]


def _citations(markdown: str) -> list[dict]:
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n{2,}", markdown)
        if paragraph.strip() and not paragraph.strip().startswith("[Image")
    ]
    return [
        {
            "ref": f"paragraph_{index}",
            "text": paragraph[:500],
            "source": "article_body",
        }
        for index, paragraph in enumerate(paragraphs, start=1)
    ]


def _quality_status(title: str | None, text: str, warnings: list[str]) -> str:
    if not text:
        return "empty"
    if not title or len(text) < 120 or any("#js_content" in warning for warning in warnings):
        return "partial"
    return "ok"


def _simple_summary(title: str | None, digest: str | None, text: str) -> str:
    if digest:
        return digest
    sample = text[:240].strip()
    if title and sample:
        return f"{title}: {sample}"
    return title or sample or "No summary available from extracted content."


def _clean_markdown(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()


def _markdown_to_text(markdown: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", markdown)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    return _clean_text(text)


def _clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()

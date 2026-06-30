from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse


SubtitleFetcher = Callable[[str], str]


def build_xiaohongshu_context(
    url: str,
    raw_html: str,
    subtitle_fetcher: SubtitleFetcher | None = None,
) -> dict:
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
        or _pick_author_link(parser.links)
    )
    description = _clean_note_text(
        _extract_meta(raw_html, "description")
        or _extract_meta(raw_html, "og:description")
        or _pick_json_value(json_values, ("desc", "description", "content"))
    )
    json_image_urls = _json_image_urls(raw_html)
    cover_image = _extract_meta(raw_html, "og:image") or _first(json_image_urls) or _first(_content_image_urls(parser.images))
    video_url = _extract_meta(raw_html, "og:video") or _extract_meta(raw_html, "og:video:url")
    links = _clean_links(parser.links)
    identifiers = _source_identifiers(url, raw_html, json_values)
    canonical_url = _canonical_url(url, identifiers)

    fragments = _clean_fragments(parser.text_fragments, title, description)
    markdown = _clean_markdown(_compose_markdown(title, description, fragments))
    plain_text = _markdown_to_text(markdown)
    image_urls = _dedupe([*json_image_urls, *_content_image_urls(parser.images)])
    if cover_image:
        image_urls = _dedupe([cover_image, *image_urls]) if _is_content_image_url(cover_image) else image_urls
    video_urls = _dedupe([url for url in [video_url, *parser.videos] if url])
    subtitle_tracks = _subtitle_tracks(raw_html)
    video_sources: list[str | None] = video_urls or ([None] if subtitle_tracks else [])
    videos = _videos(video_sources, subtitle_tracks, subtitle_fetcher, warnings)

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
            "identifiers": identifiers,
        },
        "article": {
            "title": title,
            "account_name": author,
            "author": author,
            "published_at": None,
            "summary": summary,
            "canonical_url": canonical_url,
        },
        "content": {
            "html": raw_html,
            "markdown": markdown,
            "plain_text": plain_text,
        },
        "media": {
            "cover_image": cover_image,
            "images": _images(image_urls),
            "videos": videos,
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
            "links": links,
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


def _pick_author_link(links: list[dict]) -> str | None:
    blocked = {"我", "用户", "小红书用户", "登录"}
    for link in links:
        url = str(link.get("url") or "")
        text = _clean_text(str(link.get("text") or ""))
        if "/user/profile/" not in url:
            continue
        if not text or text in blocked:
            continue
        return text
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


def _source_identifiers(url: str, raw_html: str, json_values: list[tuple[str, object]]) -> dict:
    identifiers = _url_identifiers(url)
    note_id = _pick_json_value(json_values, ("noteId", "note_id", "currentNoteId", "firstNoteId"))
    if not note_id:
        note_id = _extract_note_id(raw_html)
    if note_id:
        identifiers["note_id"] = note_id
    return identifiers


def _extract_note_id(raw_html: str) -> str | None:
    normalized = _normalize_escaped_markup(raw_html)
    for key in ("noteId", "currentNoteId", "firstNoteId"):
        match = re.search(rf'"{key}"\s*:\s*"([0-9a-fA-F]{{20,32}})"', normalized)
        if match:
            return match.group(1)
    match = re.search(r"/(?:explore|discovery/item)/([0-9a-fA-F]{20,32})", normalized)
    return match.group(1) if match else None


def _canonical_url(url: str, identifiers: dict) -> str:
    parsed = urlparse(url)
    note_id = identifiers.get("note_id")
    if note_id and "xhslink.com" in parsed.netloc.lower():
        return f"https://www.xiaohongshu.com/explore/{note_id}"
    return url


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


def _content_image_urls(urls: list[str]) -> list[str]:
    return [url for url in urls if _is_content_image_url(url)]


def _is_content_image_url(url: str | None) -> bool:
    if not url:
        return False
    return not url.strip().lower().startswith("data:image/")


def _json_image_urls(raw_html: str) -> list[str]:
    normalized = _normalize_escaped_markup(raw_html)
    urls: list[str] = []
    for match in re.finditer(r'"imageList"\s*:\s*\[', normalized):
        bracket_start = normalized.find("[", match.start())
        image_list_json = _balanced_json_array(normalized, bracket_start)
        if not image_list_json:
            continue
        try:
            image_list = json.loads(image_list_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(image_list, list):
            continue
        for image in image_list:
            url = _image_list_item_url(image)
            if url:
                urls.append(url)
    return _dedupe(_content_image_urls(urls))


def _image_list_item_url(image: object) -> str | None:
    if not isinstance(image, dict):
        return None
    for key in ("urlDefault", "url"):
        value = image.get(key)
        if isinstance(value, str) and value.strip():
            return value
    info_list = image.get("infoList")
    if isinstance(info_list, list):
        for preferred_scene in ("WB_DFT", "WB_PRV"):
            for item in info_list:
                if not isinstance(item, dict):
                    continue
                if item.get("imageScene") != preferred_scene:
                    continue
                url = item.get("url")
                if isinstance(url, str) and url.strip():
                    return url
    value = image.get("urlPre")
    return value if isinstance(value, str) and value.strip() else None


def _videos(
    urls: list[str | None],
    subtitle_tracks: list[dict] | None = None,
    subtitle_fetcher: SubtitleFetcher | None = None,
    warnings: list[str] | None = None,
) -> list[dict]:
    videos = []
    for index, url in enumerate(urls, start=1):
        tracks = subtitle_tracks if index == 1 else []
        analysis = _video_analysis(tracks or [], subtitle_fetcher, warnings)
        videos.append(
            {
                "index": index,
                "embed_url": url,
                "status": "processed" if analysis.get("transcript_text") else "not_processed",
                "analysis": analysis,
            }
        )
    return videos


def _video_analysis(
    subtitle_tracks: list[dict],
    subtitle_fetcher: SubtitleFetcher | None,
    warnings: list[str] | None = None,
) -> dict:
    analysis = {
        "status": "subtitle_available" if subtitle_tracks else "not_processed",
        "transcript": [],
        "transcript_text": "",
        "keyframes": [],
        "timeline": [],
        "subtitle_tracks": subtitle_tracks,
        "note": (
            "Subtitle tracks were found but not fetched."
            if subtitle_tracks
            else "Video parsing is reserved for the next MVP layer."
        ),
    }
    if not subtitle_tracks or subtitle_fetcher is None:
        return analysis

    track = _preferred_subtitle_track(subtitle_tracks)
    if not track:
        return analysis
    try:
        subtitle_text = subtitle_fetcher(track["url"])
    except Exception as exc:  # pragma: no cover - network behavior varies.
        analysis["note"] = f"Subtitle track found but could not be fetched: {exc}"
        if warnings is not None:
            warnings.append("Subtitle track was found but could not be fetched.")
        return analysis

    cues = _parse_srt(subtitle_text)
    if not cues:
        analysis["note"] = "Subtitle track was fetched but no SRT cues were parsed."
        if warnings is not None:
            warnings.append("Subtitle track was fetched but no SRT cues were parsed.")
        return analysis

    transcript_text = _transcript_text(cues)
    analysis.update(
        {
            "status": "processed",
            "transcript": cues,
            "transcript_text": transcript_text,
            "timeline": [
                {
                    "start": cue["start"],
                    "end": cue["end"],
                    "text": cue["text"],
                }
                for cue in cues
            ],
            "subtitle_track": track,
            "language": track.get("language"),
            "note": "Transcript parsed from Xiaohongshu subtitle SRT.",
        }
    )
    return analysis


def _subtitle_tracks(raw_html: str) -> list[dict]:
    normalized = _normalize_escaped_markup(raw_html)
    tracks: list[dict] = []
    for match in re.finditer(r'"subtitles"\s*:\s*\{', normalized):
        brace_start = normalized.find("{", match.start())
        subtitles_json = _balanced_json_object(normalized, brace_start)
        if not subtitles_json:
            continue
        try:
            subtitles = json.loads(subtitles_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(subtitles, dict):
            continue
        for role, items in subtitles.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if not _is_subtitle_url(url):
                    continue
                tracks.append(
                    {
                        "role": str(role),
                        "language": str(item.get("language") or role),
                        "format": "srt",
                        "url": str(url),
                    }
                )
    if not tracks:
        tracks = _subtitle_tracks_from_url_matches(normalized)
    return _dedupe_tracks(tracks)


def _subtitle_tracks_from_url_matches(normalized_html: str) -> list[dict]:
    tracks: list[dict] = []
    pattern = r'"url"\s*:\s*"(https://sns-subtitle[^"\\]+?\.srt\?[^"\\]+)"(?:\s*,\s*"language"\s*:\s*"([^"\\]+)")?'
    for match in re.finditer(pattern, normalized_html):
        role = _subtitle_role_before(normalized_html, match.start())
        language = match.group(2) or role
        tracks.append(
            {
                "role": role or language or "subtitle",
                "language": language or "unknown",
                "format": "srt",
                "url": match.group(1),
            }
        )
    return tracks


def _subtitle_role_before(text: str, index: int) -> str | None:
    prefix = text[max(0, index - 160):index]
    matches = list(re.finditer(r'"([^"]+)"\s*:\s*\[\s*\{[^{}]*$', prefix))
    return matches[-1].group(1) if matches else None


def _normalize_escaped_markup(value: str) -> str:
    value = html.unescape(value)
    replacements = (
        (r"\\u002F", "/"),
        (r"\u002F", "/"),
        (r"\\u0026", "&"),
        (r"\u0026", "&"),
        (r"\\/", "/"),
        (r"\/", "/"),
        (r'\\"', '"'),
        (r'\"', '"'),
    )
    for _ in range(4):
        previous = value
        for old, new in replacements:
            value = value.replace(old, new)
        if value == previous:
            break
    return value


def _balanced_json_object(text: str, start: int) -> str | None:
    if start < 0 or start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _balanced_json_array(text: str, start: int) -> str | None:
    if start < 0 or start >= len(text) or text[start] != "[":
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _is_subtitle_url(value: object) -> bool:
    return isinstance(value, str) and value.startswith("https://sns-subtitle") and ".srt?" in value


def _dedupe_tracks(tracks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for track in tracks:
        url = str(track.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(track)
    return result


def _preferred_subtitle_track(tracks: list[dict]) -> dict | None:
    if not tracks:
        return None
    for role, language in (("source", "zh-CN"), ("zh-CN", "zh-CN"), ("source", None), (None, "zh-CN")):
        for track in tracks:
            if role is not None and track.get("role") != role:
                continue
            if language is not None and track.get("language") != language:
                continue
            return track
    return tracks[0]


def _parse_srt(value: str) -> list[dict]:
    cues: list[dict] = []
    text = value.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n{2,}", text)
    timestamp_pattern = re.compile(
        r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
    )
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        timestamp_index = next((i for i, line in enumerate(lines) if timestamp_pattern.search(line)), None)
        if timestamp_index is None:
            continue
        match = timestamp_pattern.search(lines[timestamp_index])
        if not match:
            continue
        cue_text = _clean_text(" ".join(lines[timestamp_index + 1:]))
        if not cue_text:
            continue
        cues.append(
            {
                "index": len(cues) + 1,
                "start": _normalize_srt_timestamp(match.group("start")),
                "end": _normalize_srt_timestamp(match.group("end")),
                "start_seconds": _timestamp_seconds(match.group("start")),
                "end_seconds": _timestamp_seconds(match.group("end")),
                "text": cue_text,
            }
        )
    return cues


def _normalize_srt_timestamp(value: str) -> str:
    return value.replace(",", ".")


def _timestamp_seconds(value: str) -> float:
    hours, minutes, seconds = re.split(r"[:]", value.replace(",", "."))
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _transcript_text(cues: list[dict]) -> str:
    return _clean_text(" ".join(str(cue.get("text") or "") for cue in cues))


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
        if _is_ui_fragment(value):
            continue
        if value == title or value == description:
            continue
        if _is_title_fragment(value, title):
            continue
        if _is_description_duplicate(value, description):
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


def _is_title_fragment(value: str, title: str | None) -> bool:
    return bool(title and _clean_title(value) == title)


def _is_description_duplicate(value: str, description: str | None) -> bool:
    return bool(description and len(value) >= 12 and value in description)


def _is_ui_fragment(value: str) -> bool:
    if value in {"已关注", "未关注"}:
        return True
    if re.fullmatch(r"\d+\s*/\s*\d+", value):
        return True
    if re.fullmatch(r"\d+\s*(秒|分钟|小时|天|周|个月|年)前(?:\s+\S{1,12})?", value):
        return True
    return False


def _clean_links(links: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for link in links:
        text = _clean_text(str(link.get("text") or ""))
        url = str(link.get("url") or "").strip()
        if not text or not url:
            continue
        if _is_shell_link(text, url):
            continue
        key = (text, url)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"text": text, "url": url})
    return cleaned


def _is_shell_link(text: str, url: str) -> bool:
    if text in {"首页", "点点", "ai", "RED", "直播", "发布", "通知", "我"}:
        return True
    if any(marker in text for marker in (
        "ICP备",
        "营业执照",
        "公网安备",
        "增值电信",
        "医疗器械",
        "药品信息",
        "违法不良",
        "举报",
        "自营经营者",
        "网络文化经营许可证",
        "网信算备",
    )):
        return True
    return any(marker in url for marker in (
        "beian.miit.gov.cn",
        "beian.gov.cn",
        "shjbzx.cn",
        "12377.cn",
        "fe-platform",
        "fe-platform-file",
    ))


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

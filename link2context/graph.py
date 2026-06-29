from __future__ import annotations

import re
from collections import OrderedDict


STOP_TERMS = {
    "No",
    "Use",
    "Link2Context",
    "WeChat",
    "Xiaohongshu",
    "Untitled",
    "Unknown",
    "Image",
    "Video",
}


def extract_graph(context: dict) -> dict:
    article = context.get("article", {})
    content = context.get("content", {})
    source = context.get("source", {})
    url = source.get("url") or ""
    title = article.get("title") or ""
    plain_text = content.get("plain_text") or ""

    entities: OrderedDict[str, dict] = OrderedDict()
    relations: list[dict] = []

    account = article.get("account_name")
    if account:
        _add_entity(entities, account, "source_account", "article.account_name", 0.95)
        relations.append(_relation(url, "published_by", account, "article.account_name", 0.95))

    author = article.get("author")
    if author and author != account:
        _add_entity(entities, author, "person_or_author", "article.author", 0.85)
        relations.append(_relation(url, "authored_by", author, "article.author", 0.85))

    for hashtag in _hashtags(f"{title}\n{plain_text}"):
        _add_entity(entities, hashtag, "hashtag", "content.hashtag", 0.8)
        relations.append(_relation(url, "tagged_as", hashtag, "content.hashtag", 0.8))

    for term in _title_terms(title):
        _add_entity(entities, term, "topic", "article.title", 0.65)

    for term in _latin_terms(f"{title}\n{plain_text}"):
        _add_entity(entities, term, "term", "content.plain_text", 0.6)

    for entity in entities.values():
        if entity["source"] not in {"article.account_name", "article.author"}:
            relations.append(_relation(url, "mentions", entity["name"], entity["source"], entity["confidence"]))

    return {
        "entities": list(entities.values()),
        "relations": _dedupe_relations(relations),
    }


def _add_entity(
    entities: OrderedDict[str, dict],
    name: str,
    entity_type: str,
    source: str,
    confidence: float,
) -> None:
    cleaned = _clean_name(name)
    if not cleaned or cleaned in STOP_TERMS:
        return
    key = _normalized(cleaned)
    existing = entities.get(key)
    if existing and existing["confidence"] >= confidence:
        return
    entities[key] = {
        "name": cleaned,
        "normalized_name": key,
        "type": entity_type,
        "source": source,
        "confidence": confidence,
    }


def _relation(subject: str, predicate: str, object_name: str, evidence: str, confidence: float) -> dict:
    return {
        "subject": subject,
        "predicate": predicate,
        "object": _clean_name(object_name),
        "evidence": evidence,
        "confidence": confidence,
    }


def _hashtags(text: str) -> list[str]:
    return _dedupe(re.findall(r"#([A-Za-z0-9_\-\u4e00-\u9fff]{1,40})", text))


def _title_terms(title: str) -> list[str]:
    terms: list[str] = []
    for part in re.split(r"[\s,，.。!！?？:：;；|｜/\\()\[\]【】《》“”\"'_-]+", title):
        cleaned = _clean_name(part)
        if 2 <= len(cleaned) <= 18 and re.search(r"[\u4e00-\u9fff]", cleaned):
            terms.append(cleaned)
    return _dedupe(terms)


def _latin_terms(text: str) -> list[str]:
    terms = []
    for match in re.findall(r"\b[A-Z][A-Za-z0-9+._-]{1,30}\b", text):
        if match not in STOP_TERMS:
            terms.append(match)
    return _dedupe(terms)[:40]


def _clean_name(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value.strip("#,，.。!！?？:：;；|｜/\\()[]【】《》“”\"'")


def _normalized(value: str) -> str:
    return _clean_name(value).casefold()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = _normalized(value)
        if key and key not in seen:
            seen.add(key)
            result.append(_clean_name(value))
    return result


def _dedupe_relations(relations: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict] = []
    for relation in relations:
        key = (
            _normalized(relation["subject"]),
            relation["predicate"],
            _normalized(relation["object"]),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(relation)
    return result

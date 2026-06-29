# Open Source Landscape Scan

Date: 2026-06-29

## Target

灵渠 / Link2Context 的开源项目目标：

> 把用户主动收集的文章、链接、视频、图文和社媒内容转换成 agent-ready context，并作为本地知识图谱数据库的输入。

## Closest Public Projects

### Karakeep

Repo: https://github.com/karakeep-app/karakeep

Self-hostable bookmark-everything app. Its public repository describes support for links, notes, images, AI-based automatic tagging, and full-text search.

Read:

- Strongest adjacent project for the bookmark-to-knowledge wedge.
- More mature than Link2Context as a bookmark/read-it-later product.
- Does not appear focused on Chinese social platforms, agent-ready context schema, or personal knowledge graph extraction.

### Khoj

Repo: https://github.com/khoj-ai/khoj

Open-source AI second brain. Supports local/cloud LLMs, answers from web/docs, custom agents, automations, semantic search, and multiple client surfaces.

Read:

- Strongest competitor for the “AI second brain / agent assistant” layer.
- More mature than Link2Context for chat, semantic search, and agents.
- Less focused on bookmark ingestion, Chinese social media capture, and multimodal content normalization.

### Linkwarden

Repo: https://github.com/linkwarden/linkwarden

Self-hosted collaborative bookmark manager for collecting, reading, annotating, and preserving links.

Read:

- Strong competitor for bookmark preservation and read-it-later.
- Less AI-native than Karakeep/Khoj.
- Not focused on knowledge graph or agent-ready output.

### ArchiveBox

Repo: https://github.com/ArchiveBox/ArchiveBox

Open-source self-hosted web archiving for URLs, browser history, bookmarks, Pocket, Pinboard, HTML, PDFs, media, and more.

Read:

- Strong archival backend candidate.
- Not a personal knowledge graph or AI agent memory product by itself.

### Firecrawl

Repo: https://github.com/firecrawl/firecrawl

Open-source web data API for crawling and converting sites into LLM-ready Markdown or structured data.

Read:

- Strong candidate for generic webpage extraction.
- Useful reference for Markdown/JSON output contracts.
- Does not solve personal collection, Chinese social media adapters, or user-specific knowledge graph building by itself.

### Crawl4AI

Repo: https://github.com/unclecode/crawl4ai

Open-source LLM-friendly crawler focused on clean Markdown, structured extraction, browser automation, and crawler control.

Read:

- Strong candidate for the lower-level crawler/extractor layer.
- Relevant for cookie/profile-backed extraction and clean Markdown generation.
- It is infrastructure, not a complete local knowledge-graph workflow by itself.

### ScrapeGraphAI

Repo: https://github.com/ScrapeGraphAI/Scrapegraph-ai

Open-source AI-powered scraping framework for extracting structured data from websites with graph-based workflows.

Read:

- Useful reference for schema-guided extraction.
- Less focused on durable personal knowledge stores, citations, and social-media-specific ingestion.

### wallabag

Repo: https://github.com/wallabag/wallabag

Self-hosted read-it-later app for saving and classifying web pages.

Read:

- Mature read-it-later baseline.
- Not enough for multimodal social content or agent-ready knowledge graph workflows.

### Logseq

Repo: https://github.com/logseq/logseq

Privacy-first open-source knowledge management and collaboration platform.

Read:

- Strong graph-style personal knowledge management baseline.
- More manual note/PKM oriented.
- Does not solve automatic link/social/video ingestion by itself.

### Mem0

Repo: https://github.com/mem0ai/mem0

Universal memory layer for AI agents. Supports personalized memory across users, sessions, and agents.

Read:

- Strong candidate for the “agent memory” layer.
- Not a collection/bookmark/social-ingestion product.

## Verdict

Do not build a generic bookmark manager from scratch. Karakeep and Linkwarden already cover much of that surface.

Keep Link2Context only if it focuses on a sharper wedge:

1. Chinese social content ingestion: WeChat, Xiaohongshu, Bilibili, podcasts.
2. Multimodal normalization: article text, images/OCR, video/ASR, timeline, citations.
3. Agent-ready schema: clean `context.json`, `context.md`, citations, quality flags.
4. Personal knowledge graph: entities, relationships, interests, source evidence.
5. Integration layer: optionally feed Karakeep/Khoj/Mem0/Logseq instead of replacing them.
6. Extractor layer: optionally integrate or learn from Firecrawl/Crawl4AI/ScrapeGraphAI for generic web pages, while keeping custom adapters for WeChat/Xiaohongshu.

Best open-source positioning:

> Link2Context is not the bookmark app. It is the ingestion and knowledge-graph compiler for messy Chinese social/web content.

## Build/Fork Decision

Recommended path:

- Do not continue as a standalone all-in-one bookmark product.
- Continue as a focused pipeline that can integrate with mature open-source systems.
- Evaluate Karakeep as a possible UI/storage shell.
- Evaluate Khoj/Mem0 as possible agent-memory/query layers.
- Keep current Link2Context MVP as the ingestion/normalization module.

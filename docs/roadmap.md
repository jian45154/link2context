# Roadmap

This roadmap is intentionally conservative. Link2Context is an open-source, local-first CLI and Python library, not a hosted SaaS product.

## Now

- Keep WeChat and Xiaohongshu extraction stable through offline fixtures.
- Keep batch manifests, retry flows, and verification reports deterministic.
- Keep the SQLite store useful for agent handoff, graph export, and local querying.
- Keep OCR/ASR execution explicit, reviewable, and local.

## Next

- Improve real-world OCR/ASR examples without bundling a specific recognition engine.
- Add more fixture coverage for partial platform pages and media-heavy posts.
- Improve graph/profile heuristics while preserving citation evidence.
- Add clearer import/export contracts for external tools such as Markdown knowledge bases and graph databases.
- Tighten release automation after the repository has a confirmed GitHub remote and tag policy.

## Later

- Evaluate additional read-only adapters for public web pages, PDFs, Bilibili, podcasts, or RSS.
- Evaluate optional integrations with mature open-source systems instead of replacing them.
- Add semantic search only after the deterministic context store and citation pipeline are stable.

## Non-goals

- Hosted account service.
- Platform login or risk-control bypass.
- Automated likes, comments, posting, or account actions.
- Committing cookies, tokens, private exports, downloaded media, or generated local stores.

# Roadmap

This roadmap is intentionally conservative. Link2Context is an open-source, local-first CLI and Python library, not a hosted SaaS product.

## Now

- Keep WeChat and Xiaohongshu extraction stable through offline fixtures.
- Keep batch manifests, retry flows, and verification reports deterministic.
- Keep the SQLite store useful for agent handoff, graph export, and local querying.
- Keep OCR/ASR execution explicit, reviewable, and local.

## Next

- Improve real-world OCR/ASR examples without bundling a specific recognition engine. See [#5](https://github.com/jian45154/link2context/issues/5).
- Add more fixture coverage for partial platform pages and media-heavy posts. See [#3](https://github.com/jian45154/link2context/issues/3).
- Improve graph/profile heuristics while preserving citation evidence. See [#4](https://github.com/jian45154/link2context/issues/4).
- Add clearer import/export contracts for external tools such as Markdown knowledge bases and graph databases. See [#6](https://github.com/jian45154/link2context/issues/6).
- Tighten release automation after the repository has a confirmed GitHub remote and tag policy. See [#7](https://github.com/jian45154/link2context/issues/7).

## Later

- Evaluate additional read-only adapters for public web pages, PDFs, Bilibili, podcasts, or RSS.
- Evaluate optional integrations with mature open-source systems instead of replacing them.
- Add semantic search only after the deterministic context store and citation pipeline are stable.

## Non-goals

- Hosted account service.
- Platform login or risk-control bypass.
- Automated likes, comments, posting, or account actions.
- Committing cookies, tokens, private exports, downloaded media, or generated local stores.

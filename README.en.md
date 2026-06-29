# Lingqu / Link2Context

[![CI](https://github.com/jian45154/link2context/actions/workflows/ci.yml/badge.svg)](https://github.com/jian45154/link2context/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/jian45154/link2context)](https://github.com/jian45154/link2context/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-2f6f5e.svg)](LICENSE)

Language: [简体中文](README.md) | [English](README.en.md)

**Compile saved links into agent-ready context.**

Link2Context is an open-source, local-first CLI and Python library for turning articles, social links, video/image posts, and web content into searchable, citable local context that can feed AI agents and knowledge graphs.

```text
saved links -> normalized context -> local store -> graph/query/export -> agent handoff
```

The project is GitHub-first and local-first: no hosted SaaS, no platform bypass, and no comment/like interaction collection. The current alpha focuses on collection and normalization for public WeChat article URLs and public Xiaohongshu note URLs, producing `context.json`, `context.md`, batch manifests, and local query packages.

## What It Does

| Area | Current support |
| --- | --- |
| Sources | Public WeChat article URLs; conservative HTML parsing for public Xiaohongshu note URLs |
| Extraction | Title, author, published time, summary, body text, images, and video placeholders |
| Outputs | `context.json`, `context.md`, batch manifest, SQLite store, graph export, agent query package |
| Media | Image OCR and video ASR run through external command adapters; no built-in recognition engine yet |
| Boundaries | No comment collection, no interaction metrics, no platform bypass; cookies are used only as local request headers |

## Quick Links

- [Quickstart](docs/quickstart.md): minimal offline workflow from fixture to store query and handoff export.
- [Documentation Index](docs/index.md): architecture, graph, import/export contracts, media OCR/ASR, and release checklist.
- [Architecture](docs/architecture.md): module boundaries, data flow, and stable contracts.
- [Roadmap](docs/roadmap.md): near-term and later open-source direction.
- [Contributing](CONTRIBUTING.md): local development, tests, and pull request principles.
- [Project Page](index.html): static HTML project page for GitHub Pages.

## Project Status

Link2Context is currently alpha software. It is suitable for local personal use, developer extension, and offline fixture regression tests.

| Stable enough | Experimental | Not supported |
| --- | --- | --- |
| WeChat / Xiaohongshu context extraction; batch manifests; SQLite store; graph/export/query commands | OCR/ASR command adapters; media cache repair; Agent Reach integration; graph/profile heuristics | hosted service; account automation; platform bypass; comment/like/post collection |

## Repository Map

```text
link2context/   CLI, platform parsers, local store, graph logic
tests/          offline fixture regression tests
examples/       WeChat, Xiaohongshu, and media pipeline sample inputs
docs/           architecture, contracts, roadmap, release, and publishing notes
.github/        CI, Dependabot, issue templates, pull request template
```

## Install

Install the local development version from source:

```powershell
python -m pip install -e ".[dev]"
```

Run tests:

```powershell
python -m pytest tests -q
```

Check the version:

```powershell
python -m link2context --version
python -m link2context.store --version
```

## Basic Usage

Convert a WeChat article:

```powershell
python -m link2context "https://mp.weixin.qq.com/s/..." --out outputs/sample
```

Convert a Xiaohongshu note:

```powershell
python -m link2context "https://www.xiaohongshu.com/explore/..." --out outputs/xhs-sample
```

If a public request only returns a shell page, provide your own login cookie:

```powershell
python -m link2context "https://www.xiaohongshu.com/explore/..." --platform xiaohongshu --cookie-file .secrets\xiaohongshu.cookie --out outputs/xhs-sample
```

Cookies are used only as request headers. They are not written to `context.json`, `context.md`, or `manifest.json`. Do not commit cookie files.

## Open Source Direction

Lingqu is not a generic downloader or a simple web-to-Markdown converter. The long-term goal is a self-hostable, developer-friendly local content compilation pipeline:

- `Collect`: accept articles, social links, videos, image posts, PDFs, and web pages.
- `Normalize`: clean body text, media, citations, entities, timestamps, authors, and source metadata.
- `Connect`: extract entities, topics, claims, people, products, places, events, and relationships.
- `Retrieve`: query by topic, person, question, timeline, or relationship.
- `Act`: provide AI agents with trusted context, citation evidence, and local interest profiles.

Non-goals:

- No hosted account service.
- No platform login, risk-control, or access bypass.
- No automation for comments, likes, posts, or other write actions.
- No cookies, tokens, or private content in the repository.

For the complete Chinese documentation, see [README.md](README.md).

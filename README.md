# 灵渠 / Link2Context

[![CI](https://github.com/jian45154/link2context/actions/workflows/ci.yml/badge.svg)](https://github.com/jian45154/link2context/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/jian45154/link2context)](https://github.com/jian45154/link2context/releases)

Link2Context 是一个开源、本地优先的链接到上下文工具包，用于把文章、社媒链接、视频、图文和网页内容整理成可检索、可引用、可喂给 AI agent 的本地知识图谱输入。

一句话定位：**把收藏链接编译成 agent-ready context。**

当前定位是 GitHub-first 的开源 CLI / Python library，不做托管 SaaS 产品。现阶段重点是采集与标准化层：输入微信公众号文章链接或小红书笔记链接，输出适合进入知识图谱和 AI agent 的 `context.json` 和 `context.md`。

当前范围很窄：

- 支持公开微信公众号文章 URL。
- 支持公开小红书笔记 URL 的保守 HTML 解析。
- 抽取标题、作者、发布时间、摘要、正文、图片、视频占位信息。
- 输出统一 context schema，作为后续知识图谱入库输入。
- 图片 OCR 和视频 ASR 通过外部命令适配层执行并回写，暂不内置具体识别引擎。
- 不做评论采集、互动数据采集、平台绕过；批量 URL 处理和 Cookie 请求头已作为本地工作流入口支持。

## Project Status

当前是 alpha 阶段，适合本地自用、开发者二次开发和离线 fixture 回归测试。

- Stable enough: WeChat / Xiaohongshu context extraction, batch manifests, SQLite store, graph/export/query commands.
- Experimental: OCR/ASR command adapters, media cache repair, Agent Reach integration, graph/profile heuristics.
- Not supported: hosted service, account automation, platform bypass, comment/like/post collection.

## Repository Map

- `link2context/`: CLI、平台解析器、本地 store 和图谱逻辑。
- `tests/`: 离线 fixture 回归测试。
- `examples/`: 微信、小红书和媒体处理样例输入。
- `docs/`: 架构、目标、图谱、查询、生态扫描和发布检查文档。
- `.github/`: CI、Dependabot、issue templates 和 pull request template。

更多文档入口见 [docs/index.md](docs/index.md)，最小离线闭环见 [docs/quickstart.md](docs/quickstart.md)，导入导出契约见 [docs/export-contracts.md](docs/export-contracts.md)，GitHub 发布步骤见 [docs/github-publish.md](docs/github-publish.md)，版本变化见 [CHANGELOG.md](CHANGELOG.md)，后续方向见 [docs/roadmap.md](docs/roadmap.md)。

## Open Source Direction

灵渠不是普通下载器，也不是单纯网页转 Markdown。长期目标是提供一套可自托管、可二次开发的本地内容编译管线：

- `Collect`: 接收文章、社媒链接、视频、图文、PDF、网页等来源。
- `Normalize`: 清洗正文、媒体、引用、实体、时间、作者和来源。
- `Connect`: 抽取实体、主题、观点、人物、产品、地点、事件，建立知识图谱。
- `Retrieve`: 支持按主题、人物、问题、时间线和关系查询。
- `Act`: 给 AI agent 提供可信上下文、引用证据和本地兴趣画像。

非目标：

- 不提供托管账号服务。
- 不绕过平台登录、风控或访问限制。
- 不做评论、点赞、发帖等写操作自动化。
- 不把 Cookie、token 或私有内容提交到仓库。

近期技术路线：

1. 链接到 `context.json/context.md`
2. `context` 到实体/关系/主题抽取
3. 本地知识图谱数据库
4. 面向 agent 的查询接口
5. OCR、视频 ASR、时间轴和引用定位

## Usage

从源码安装本地开发版：

```powershell
python -m pip install -e ".[dev]"
```

运行测试：

```powershell
python -m pytest tests -q
```

查看版本：

```powershell
python -m link2context --version
python -m link2context.store --version
```

```powershell
python -m link2context "https://mp.weixin.qq.com/s/..." --out outputs/sample
```

小红书：

```powershell
python -m link2context "https://www.xiaohongshu.com/explore/..." --out outputs/xhs-sample
```

如果公开请求只返回壳页面，可以提供你自己的登录 Cookie：

```powershell
python -m link2context "https://www.xiaohongshu.com/explore/..." --platform xiaohongshu --cookie-file .secrets\xiaohongshu.cookie --out outputs/xhs-sample
```

Cookie 只作为请求头使用，不会写入 `context.json`、`context.md` 或 `manifest.json`。不要把 Cookie 文件提交到版本库。

显式指定平台：

```powershell
python -m link2context "https://www.xiaohongshu.com/explore/..." --platform xiaohongshu --out outputs/xhs-sample
```

可选后端：

```powershell
python -m link2context "https://www.xiaohongshu.com/explore/..." --platform xiaohongshu --backend native --out outputs/xhs-sample
python -m link2context "https://www.xiaohongshu.com/explore/..." --platform xiaohongshu --backend agent-reach --out outputs/xhs-sample
```

`native` 是默认后端，直接抓取页面 HTML 并做本地清洗。`agent-reach` 是预留集成点：如果本机安装了 Agent Reach 且对应平台后端可用，Link2Context 会记录后端状态；如果不可用，会安全回退到 `native` 并在 `quality.warnings` 中说明原因。当前小红书要真正走 Agent Reach，需先安装 OpenCLI 或 xiaohongshu-mcp 后端。

批量处理：

```powershell
python -m link2context --url-list examples/wechat_urls.txt --out outputs/batch
python -m link2context --verify-batch outputs/batch
python -m link2context --verify-batch outputs/batch --format json
python -m link2context --verify-batch outputs/batch --format commands
python -m link2context --failed-url-list outputs/batch > outputs/retry_urls.txt
python -m link2context --retry-failed outputs/batch --cookie-file .secrets\xiaohongshu.cookie --out outputs/retry
python -m link2context --retry-failed outputs/batch --out outputs/retry --format commands
```

`wechat_urls.txt` 格式：

```text
# One URL per line. Blank lines and comments are ignored.
https://mp.weixin.qq.com/s/...
https://mp.weixin.qq.com/s/...
```

批量输出：

```text
outputs/batch/
  manifest.json
  001-example/
    context.json
    context.md
  002-example/
    context.json
    context.md
```

`manifest.json` 会记录 `project`、`format`、`version`、`generated_at`、`count`、`succeeded`、`failed`、`ok`、`items`、`failures` 和 `recommended_next`；每个 item 会带 `file_details` 的 size/sha256，方便 agent 判断哪些链接已生成 context，哪些需要补 Cookie、重试或换后端，并确认输出文件没有被改动。

`--verify-batch` 会检查批量目录的 manifest 格式元数据、`generated_at` ISO 时间戳、统计和 `recommended_next` 是否一致，并确认成功项包含 `context.json/context.md`、失败项包含 `error.json`；报告会给出下一步命令，建议在 `ingest` 前先跑一次。`--format commands` 只输出推荐命令，方便 agent 或脚本直接接手。

`--failed-url-list` 会从批量 `manifest.json` 中提取失败 URL 并去重，输出可直接再次传给 `--url-list` 的纯文本列表，适合补 Cookie 或换后端后只重试失败链接。

`--retry-failed` 会读取失败 URL、在新输出目录写出 `retry_urls.txt`，并按普通 batch 流程重新抓取；默认输出重试摘要和后续 `verify-batch` / `ingest` 命令，`--format commands` 只输出后续命令，建议用新的 `--out` 目录，避免覆盖原始批量结果。

离线测试：

```powershell
python -m link2context --html examples/wechat_sample.html --url "https://mp.weixin.qq.com/s/example" --out outputs/sample
python -m link2context --html examples/xiaohongshu_sample.html --url "https://www.xiaohongshu.com/explore/example" --platform xiaohongshu --out outputs/xhs-sample
```

输出：

- `context.json`: 结构化上下文包。
- `context.md`: 可直接复制给 agent 的 Markdown。

## Local Context Store

把已经生成的 `context.json` 导入本地 SQLite：

```powershell
python -m link2context.store --db data\link2context.db import outputs\batch
```

如果想导入后立刻检查这个库是否适合给 agent 使用：

```powershell
python -m link2context.store --db data\link2context.db ingest outputs\batch
python -m link2context.store --db data\link2context.db ingest outputs\batch --format json
```

查看统计：

```powershell
python -m link2context.store --db data\link2context.db stats
```

检查本地仓库是否已经适合交给 agent 使用：

```powershell
python -m link2context.store --db data\link2context.db doctor
python -m link2context.store --db data\link2context.db doctor --format json
```

查看低质量或部分解析的资料：

```powershell
python -m link2context.store --db data\link2context.db quality
python -m link2context.store --db data\link2context.db quality --status partial
python -m link2context.store --db data\link2context.db quality --format json
```

导出图谱 JSON：

```powershell
python -m link2context.store --db data\link2context.db graph
python -m link2context.store --db data\link2context.db graph --format mermaid
python -m link2context.store --db data\link2context.db graph --include-terms
python -m link2context.store --db data\link2context.db dump-graph --out outputs\graph-csv
python -m link2context.store --db data\link2context.db verify-graph outputs\graph-csv
python -m link2context.store --db data\link2context.db dump-neo4j --out outputs\graph.cypher
python -m link2context.store --db data\link2context.db verify-neo4j outputs\graph.cypher
```

搜索已入库内容：

```powershell
python -m link2context.store --db data\link2context.db search "关键词"
```

打开某一条已入库资料的完整上下文：

```powershell
python -m link2context.store --db data\link2context.db doc "https://mp.weixin.qq.com/s/..."
python -m link2context.store --db data\link2context.db doc 1 --format json
```

给资料添加用户标签：

```powershell
python -m link2context.store --db data\link2context.db tag 1 知识管理 Agent
python -m link2context.store --db data\link2context.db tags
```

给资料添加用户笔记：

```powershell
python -m link2context.store --db data\link2context.db note 1 "这篇适合后续追问"
python -m link2context.store --db data\link2context.db notes
```

标记资料处理状态：

```powershell
python -m link2context.store --db data\link2context.db mark 1 later --note "今晚处理"
python -m link2context.store --db data\link2context.db statuses
python -m link2context.store --db data\link2context.db annotations
```

查找重复或疑似重复收藏：

```powershell
python -m link2context.store --db data\link2context.db duplicates
python -m link2context.store --db data\link2context.db duplicates --format json
```

查看平台、来源、图谱和媒体处理覆盖面：

```powershell
python -m link2context.store --db data\link2context.db coverage
python -m link2context.store --db data\link2context.db coverage --format json
```

打开收藏维护行动板：

```powershell
python -m link2context.store --db data\link2context.db curate
python -m link2context.store --db data\link2context.db curate --format json
```

打开某篇资料的 citation 证据：

```powershell
python -m link2context.store --db data\link2context.db citation 1
python -m link2context.store --db data\link2context.db citation 1 paragraph_12
python -m link2context.store --db data\link2context.db citation "https://mp.weixin.qq.com/s/..." paragraph_12 --format json
```

搜索全库 citation 证据：

```powershell
python -m link2context.store --db data\link2context.db evidence
python -m link2context.store --db data\link2context.db evidence "关键词"
python -m link2context.store --db data\link2context.db evidence "关键词" --format json
```

查找与某条资料共享实体的相关资料：

```powershell
python -m link2context.store --db data\link2context.db related 1
python -m link2context.store --db data\link2context.db related "https://mp.weixin.qq.com/s/..." --format json
```

按发布时间/导入时间查看已收藏内容：

```powershell
python -m link2context.store --db data\link2context.db timeline
python -m link2context.store --db data\link2context.db timeline --format json
```

查看图片/视频素材及处理状态：

```powershell
python -m link2context.store --db data\link2context.db media
python -m link2context.store --db data\link2context.db media --kind image --status not_processed
python -m link2context.store --db data\link2context.db media --format json
```

生成图片 OCR / 视频 ASR 处理队列：

```powershell
python -m link2context.store --db data\link2context.db queue
python -m link2context.store --db data\link2context.db queue --kind image --format jsonl
python -m link2context.store --db data\link2context.db queue --low-confidence --format jsonl
```

缓存远程图片/视频到本地并回写 `media.local_path`：

```powershell
python -m link2context.store --db data\link2context.db cache-media --kind image --out-dir outputs\media-cache
python -m link2context.store --db data\link2context.db cache-media --kind video --out-dir outputs\media-cache --overwrite
python -m link2context.store --db data\link2context.db export-media-fixes --out outputs\media-fixes.jsonl
python -m link2context.store --db data\link2context.db verify-media-fixes outputs\media-fixes.jsonl
python -m link2context.store --db data\link2context.db apply-media-fixes outputs\media-fixes.jsonl
python -m link2context.store --db data\link2context.db apply-media-fixes outputs\media-fixes.jsonl --force
```

调用外部 OCR / ASR 命令并写出回写结果：

```powershell
python -m link2context.store --db data\link2context.db media-text-presets --format markdown
python -m link2context.store --db data\link2context.db media-text-presets --preset-model models\ggml-small.bin --tool-path C:\Tools\sona.exe --format markdown
python -m link2context.store --db data\link2context.db media-text-presets --model-dir C:\Tools\vibe\models --format markdown
python -m link2context.store --db data\link2context.db prepare-media-model --url "https://example.com/ggml-small.bin" --out models\ggml-small.bin
python -m link2context.store --db data\link2context.db prepare-media-model --url "https://example.com/ggml-small.bin" --out models\ggml-small.bin --sha256 "<expected-sha256>" --execute
python -m link2context.store --db data\link2context.db run-media-text --kind image --out outputs\ocr-results.jsonl --command-template "your-ocr-command --url {input_url}" --model your-ocr --language zh --confidence 0.85
python -m link2context.store --db data\link2context.db run-media-text --kind image --out outputs\ocr-results.jsonl --command-template "your-ocr-command --url {input_url}" --model your-ocr --language zh --confidence 0.85 --apply --reindex
python -m link2context.store --db data\link2context.db run-media-text --low-confidence --kind image --out outputs\ocr-review.jsonl --command-template "your-ocr-command --url {input_url}" --apply --reindex
python -m link2context.store --db data\link2context.db run-media-text --kind image --out outputs\ocr-results.jsonl --preset tesseract --language chi_sim+eng --apply --reindex
python -m link2context.store --db data\link2context.db run-media-text --kind video --out outputs\asr-results.jsonl --preset sona --preset-model models\ggml-small.bin --apply --reindex
```

回写外部 OCR / ASR 结果：

```powershell
python -m link2context.store --db data\link2context.db apply-media-text outputs\ocr-results.jsonl
python -m link2context.store --db data\link2context.db apply-media-text outputs\ocr-results.jsonl --reindex
python -m link2context.store --db data\link2context.db apply-media-text outputs\asr-results.json --format json
python -m link2context.store --db data\link2context.db verify-media-text outputs\ocr-results.jsonl
python -m link2context.store --db data\link2context.db verify-media-text outputs\ocr-results.jsonl --require-reindex
```

把已回写媒体文本纳入图谱：

```powershell
python -m link2context.store --db data\link2context.db reindex-media-text
python -m link2context.store --db data\link2context.db reindex-media-text --format json
```

生成下一步行动清单：

```powershell
python -m link2context.store --db data\link2context.db actions
python -m link2context.store --db data\link2context.db actions --format json
```

生成 agent 可执行任务清单：

```powershell
python -m link2context.store --db data\link2context.db tasks
python -m link2context.store --db data\link2context.db tasks --format json
python -m link2context.store --db data\link2context.db tasks --kind query --format json
python -m link2context.store --db data\link2context.db tasks --source starter_query --format json
python -m link2context.store --db data\link2context.db tasks --kind query --format jsonl
python -m link2context.store --db data\link2context.db tasks --kind query --format commands
python -m link2context.store --db data\link2context.db tasks --kind media_cache --format commands
python -m link2context.store --db data\link2context.db tasks --kind media_cache --retry-mode retry_download --format commands
python -m link2context.store --db data\link2context.db tasks --kind media_cache --cache-status download_failed --format json
python -m link2context.store --db data\link2context.db tasks --kind media_review --format commands
python -m link2context.store --db data\link2context.db tasks --max-priority 2 --format json
python -m link2context.store --db data\link2context.db tasks --contains 知识管理 --format json
```

生成日常处理入口：

```powershell
python -m link2context.store --db data\link2context.db inbox
python -m link2context.store --db data\link2context.db inbox --format json
```

生成阶段复盘摘要：

```powershell
python -m link2context.store --db data\link2context.db digest
python -m link2context.store --db data\link2context.db digest --format json
```

生成一页式 agent 复盘入口：

```powershell
python -m link2context.store --db data\link2context.db review
python -m link2context.store --db data\link2context.db review --format json
```

生成给 agent 使用的带证据查询包：

```powershell
python -m link2context.store --db data\link2context.db query "关键词"
```

如果要直接复制给 agent，可输出 Markdown：

```powershell
python -m link2context.store --db data\link2context.db query "关键词" --format markdown
```

查看已抽取实体：

```powershell
python -m link2context.store --db data\link2context.db entities
```

查看主题/实体信号及证据：

```powershell
python -m link2context.store --db data\link2context.db topics
python -m link2context.store --db data\link2context.db topics --type term
python -m link2context.store --db data\link2context.db topics --format json
```

查看由共享实体形成的主题簇：

```powershell
python -m link2context.store --db data\link2context.db clusters
python -m link2context.store --db data\link2context.db clusters --min-docs 3
python -m link2context.store --db data\link2context.db clusters --format json
```

根据主题簇生成后续探索问题：

```powershell
python -m link2context.store --db data\link2context.db questions
python -m link2context.store --db data\link2context.db questions --limit 10
python -m link2context.store --db data\link2context.db questions --format json
```

查看来源账号和平台分布：

```powershell
python -m link2context.store --db data\link2context.db sources
python -m link2context.store --db data\link2context.db sources --format json
```

解释某个实体为什么出现在仓库里：

```powershell
python -m link2context.store --db data\link2context.db explain "Claude"
python -m link2context.store --db data\link2context.db explain "Claude" --format json
```

查看图谱关系边：

```powershell
python -m link2context.store --db data\link2context.db relations
python -m link2context.store --db data\link2context.db relations "Claude"
python -m link2context.store --db data\link2context.db relations "Claude" --predicate mentions --format json
```

生成保守兴趣画像：

```powershell
python -m link2context.store --db data\link2context.db profile
python -m link2context.store --db data\link2context.db profile --format markdown
```

生成给 agent 快速理解本地知识库的摘要：

```powershell
python -m link2context.store --db data\link2context.db brief
python -m link2context.store --db data\link2context.db brief --format json
```

导出一个完整的 agent handoff 包：

```powershell
python -m link2context.store --db data\link2context.db export --out outputs\agent-handoff
python -m link2context.store --db data\link2context.db verify-export outputs\agent-handoff
```

导出完整快照（agent handoff + JSONL backup + graph exports）：

```powershell
python -m link2context.store --db data\link2context.db snapshot --out outputs\snapshot
python -m link2context.store --db data\link2context.db verify-snapshot outputs\snapshot
python -m link2context.store --db data\restored.db import-snapshot outputs\snapshot
```

导出可给外部数据库/向量库使用的 JSONL 表：

```powershell
python -m link2context.store --db data\link2context.db dump-jsonl --out outputs\jsonl-dump
python -m link2context.store --db data\link2context.db verify-jsonl outputs\jsonl-dump
python -m link2context.store --db data\restored.db import-jsonl outputs\jsonl-dump
```

导出每篇收藏的 Markdown 文件：

```powershell
python -m link2context.store --db data\link2context.db dump-docs --out outputs\markdown-docs
python -m link2context.store --db data\link2context.db verify-docs outputs\markdown-docs
```

当前 store 是知识图谱前的结构化仓库，保存文档、媒体、引用、候选实体、文档-实体连接和基础关系，并能导出 `nodes/edges` JSON、Mermaid 或 CSV。`graph` 默认隐藏噪声较高的 `term` 实体，可用 `--include-terms` 导出完整候选实体。实体抽取与兴趣画像仍是规则型 MVP，只基于已导入内容聚合，不等同于完整语义理解。

`dump-graph` 会把同一套图谱导出为 `nodes.csv`、`edges.csv` 和 `manifest.json`，方便导入 Neo4j、Gephi 或其他图数据库/图分析工具；同样支持 `--include-terms`。

`verify-graph` 会读取图谱 CSV 导出的 `manifest.json`，检查 `nodes.csv` 和 `edges.csv` 是否缺失、大小、`sha256` 和数据行数是否匹配。

`dump-neo4j` 会把当前图谱导出为可执行的 Cypher 脚本，包含节点唯一约束、`Document`/`Entity`/`Literal` 节点和带原始 `predicate` 属性的关系边，适合直接导入 Neo4j 做后续探索；同时会生成 `graph.cypher.manifest.json` sidecar。

`verify-neo4j` 会检查 Cypher 脚本是否存在、非空、包含节点唯一约束、包含节点/关系 `MERGE` 语句；如果存在 sidecar manifest，还会校验脚本大小、`sha256`、节点数和关系数。

`doctor` 会检查本地库是否已有文档、citation、实体、关系和平台分布，并给出下一步建议；适合在 `brief`、`query` 或 `export` 前快速判断这个库是否足够给 agent 使用。

`quality` 会列出文档质量状态、warnings 和 missing fields，帮助决定哪些资料需要重抓、补 Cookie、补 OCR/ASR 或人工核查。

`ingest` 是 `import` 的更顺手版本：导入 `context.json` 后会立即输出 `doctor` 状态和下一步推荐命令；如果输入目录包含批量 `manifest.json`，会在 `Batch Checks` 中显示校验摘要，存在失败项或缺失/篡改文件时也会在 `Batch Warnings` 中提示，方便先补 Cookie、重试或换后端。

`timeline` 会按 `published_at` 优先、缺失时按 `imported_at` 输出收藏内容时间线，帮助 agent 判断资料新旧和用户兴趣变化。

`media` 会列出已入库图片/视频及处理状态，方便后续把 `not_processed` 的图片送 OCR、视频送 ASR。

`media-pipeline` 会汇总媒体处理链路状态，包括待处理、本地可处理、已回写文本、低置信度、缓存异常和 `media.text` 图谱索引情况，并给出 `media-text-presets`、`prepare-media-model`、队列验证和 next 命令生成等推荐命令；`export` 也会把同一报告写进 `media-pipeline.md/json` 和 `manifest.json`。

`queue` 会把待处理媒体整理成 OCR/ASR 队列，支持 Markdown、JSON 和 JSONL 输出，方便交给外部识别工具；`--low-confidence` 会改为输出低置信度媒体文本复核队列，每条都带 `result_template`，可直接填入新识别文本、模型、语言和置信度后交给 `apply-media-text` 回写。

`cache-media` 会下载队列中的远程图片/视频到本地目录，并回写 `media.local_path`；后续 `queue` 会把本地路径放进 `input_path`，`run-media-text` 的 `{input_source}` 会优先使用这个本地路径。缓存报告会列出文件大小、sha256、失败原因和可复跑的 retry 命令，适合批量媒体下载后继续补失败项；成功或失败状态也会持久化到 `media.cache_status/cache_error/cache_sha256/cache_bytes/cache_checked_at`，并随 `media`、`doc` 和 JSONL dump/import 保留。`export-media-fixes` 会把 `missing_url`、`download_failed`、`empty_response` 等失败项导出为可编辑 JSONL，只应用 `fixed_url` 和 `fixed_local_path`；改完后用 `verify-media-fixes` 检查 URL、本地文件和 `media_id`，再用 `apply-media-fixes` 回写。`apply-media-fixes` 默认会先校验，校验失败不会写库；只有明确加 `--force` 才会绕过校验。应用成功后报告会按修复类型给出 `next_commands`：只有 `fixed_url` 的项目提示重跑 `cache-media`，已有 `fixed_local_path` 的项目提示进入 `queue`/OCR/ASR。

`media-text-presets` 会列出内置 OCR/ASR preset、命令模板、本机可执行文件是否可见、模型文件是否就绪和可复制的 `run-media-text` 示例；默认会扫描 `models`、`outputs/models`、Vibe 模型目录和常见 Whisper 缓存目录，传 `--model-dir` 可追加扫描目录，传 `--preset-model` 和 `--tool-path` 可以在执行真实视频转写前预检 Sona 模型和可执行文件。`prepare-media-model` 用于把模型下载和 SHA-256 校验纳入项目流程，默认 dry-run；如果目标文件已存在，dry-run 会输出大小、SHA-256 和校验结果，只有加 `--execute` 才会下载并写入本地文件。`run-media-text` 会把队列逐条交给外部命令模板处理，模板可使用 `{input_url}`、`{input_path}`、`{input_source}`、`{kind}`、`{document_id}`、`{media_index}`、`{document_title}` 等字段；`{input_source}` 会优先使用已入库的本地路径，缺失时退回原始 URL。外部命令应把识别文本写到 stdout，Link2Context 会把 stdout 转成 `apply-media-text` 可读的 JSONL。也可以用 `--preset tesseract` 或 `--preset sona` 少写模板；`sona` 使用本机 Vibe/Sona 的 whisper.cpp 转写器，需要用 `--preset-model` 指向已下载的模型文件。加 `--apply --reindex` 可以形成“取队列 -> 执行 OCR/ASR -> 回写 -> 增量入图谱”的最小闭环。

`apply-media-text` 会读取外部 OCR/ASR 的 JSON 或 JSONL 结果，按 `document_id` + `media_index` 回写 `media.text` 和 `media.status`；如果结果包含 `model`、`language`/`lang`、`confidence`，也会保存在媒体记录里，方便后续判断 OCR/ASR 质量；不会修改原始 `context_json`。回写报告会列出本次仍低于 0.70 置信度的项目，这些项目也会继续出现在 `actions` 和 `curate` 的复核任务中。回写后的媒体文本会进入 `search` 和 `query` 的检索结果。加 `--reindex` 会在回写成功后立即重建本次回写文档的 `media.text` 图谱信号，让新识别文本进入 `topics`、`clusters`、`profile` 和 `graph`。`verify-media-text` 会用同一个结果文件核对数据库里的 `media.text/status/model/language/confidence` 是否已经按预期回写；加 `--require-reindex` 时还会检查涉及文档是否已有 `media.text` 图谱信号。

`media` 报告会把低于 0.70 置信度的 OCR/ASR 文本列入 `Low Confidence Text`，提示这些媒体文本适合人工复核或重跑识别。

`reindex-media-text` 会从已回写的 `media.text` 重建规则型实体和 `mentions` 关系，让 OCR/ASR 文本进入 `topics`、`clusters`、`profile` 和 `graph`；直接运行该命令会全量重建，`apply-media-text --reindex` 则只重建本次回写涉及的文档。

`actions` 会把 `doctor`、`quality` 和 `media` 的结果合成优先级清单，提示该导入、重抓、缓存媒体、处理媒体、复核低置信度 OCR/ASR 文本，还是导出 handoff 包；缺少本地文件的待处理媒体会指向 `cache-media --kind ...`，失败或缺 URL 的缓存项会改为指向 `export-media-fixes ...`，并在详情里用 `retry_mode=download|retry_download|manual_url_required` 区分正常下载、失败重试和缺 URL 人工处理，同时给出对应的 `apply-media-fixes ...` 回写命令；已有 `local_path` 但尚未处理的媒体会直接指向 `queue --kind ... --format jsonl`，这条动作会自然进入 `digest`、`inbox` 和 `review`；低置信度复核任务会指向 `queue --low-confidence --kind ... --format jsonl`，如果重跑后置信度仍低于阈值，复核任务会继续保留。

`tasks` 会把 `actions`、`curate` lanes 和 starter queries 合成机器可读 agent checklist，适合不用导出完整 handoff 包时直接交给 agent 执行下一步；可用 `--kind query`、`--kind media_cache`、`--kind media`、`--kind media_review`、`--kind handoff` 等筛选任务类型，也可用 `--source actions`、`--source curate`、`--source starter_query` 筛选任务来源，`--retry-mode retry_download` 或 `--cache-status download_failed` 可只取需要修复/重试的媒体缓存任务；失败媒体任务的 `--format commands` 会输出 `export-media-fixes ...`，编辑清单后按详情里的 `apply-media-fixes ...` 回写；已修复出本地文件的媒体任务会输出 `queue --kind ... --format jsonl`。`--max-priority 2` 可只取高优先级任务，`--contains 知识管理` 可按标题、详情、来源、缓存状态或命令关键词筛选；支持 Markdown、JSON、JSONL 和去重后的纯命令列表输出。

`inbox` 会把最近导入、质量问题、待 OCR/ASR 媒体、Top topics、主题簇和推荐动作放到一个日常 triage 视图里，适合每天先看“收藏夹里现在最该处理什么”。

`digest` 会汇总最近文档、Top topics、主题簇、后续探索问题、Top sources、质量分布和下一步动作，适合周期性复盘收藏内容。

`review` 会把 `doctor`、`digest`、`questions` 和 `actions` 合成一页式入口，适合导入后先看“现在这个本地知识库可以怎么用”。

`doc` 会按 URL 或数据库 id 打开单篇资料，返回 metadata、media、citation、实体和正文 Markdown，适合 agent 做单篇材料深读或核查引用。

`citation` 会按文档 id/URL 和可选 citation ref 打开精确证据段落，适合 agent 回答前核查引用。

`evidence` 会跨全库检索 citation 段落，并给出可继续用 `citation <id> <ref>` 精确核查的命令。

`related` 会按共享实体数量和置信度找相关资料，适合 agent 从一篇收藏扩展到同主题上下文；这是规则型相似度，不是语义向量检索。

`duplicates` 会按规范化 URL 和规范化标题查找重复/疑似重复收藏。小红书分享链接会忽略 `xsec_token`、`share_id` 等一次性参数；公众号短链按路径聚合，公众号复杂链接会保留 `__biz`、`mid`、`idx`、`sn` 等关键参数。结果只是候选线索，删除或合并前应人工确认。

`coverage` 会汇总平台分布、来源账号、citation 覆盖、图谱实体覆盖、媒体 OCR/ASR 处理进度、重复候选和质量缺口，适合判断下一步该继续导入、补小红书、补 OCR/ASR，还是清理低质量条目。

`curate` 会把收藏库拆成 `read_now`、`fix_quality`、`process_media`、`review_duplicates` 和 `agent_handoff` 几条行动 lane；其中 `process_media` 同时提示未处理媒体和低置信度 OCR/ASR 文本复核，适合每天快速决定下一步处理哪批收藏。

`tag` 会把用户自定义标签写入本地库，并同步成 `user_tag` 图谱实体和 `user_tagged_as` 关系边；`tags` 会按标签聚合文档，适合把个人判断补进“用户特有”的知识图谱。

`note` 会把用户短笔记写入本地库，并同步成 `user_note` 图谱关系边；`notes` 会按时间列出用户笔记，适合把“为什么收藏、后续怎么用”的判断补进本地知识库。

`mark` 会把资料标记为 `inbox`、`later`、`reading`、`read` 或 `archived`，并可附带状态备注；`statuses` 会按状态列出资料，适合维护收藏处理进度。这个用户状态独立于抽取质量 `quality_status`。

`annotations` 会按文档合并用户标签、用户笔记和处理状态，适合给 agent 一次性读取“我对这批收藏的个人判断”。

`search`、`timeline` 和 `brief` 会显示文档 id，方便继续调用 `doc <id>` 或 `related <id>`。

`sources` 会按平台和账号聚合文档数量、质量状态和最近文档，帮助判断用户主要从哪些来源收集内容。

`topics` 会按实体/主题聚合文档数和证据来源，适合快速扫描本地知识库里反复出现的概念。

`clusters` 会按共享实体把多篇资料组成主题簇，并提供 `explain` 和 `evidence` 后续命令，适合从“收藏夹里反复出现的问题”进入深挖。

`questions` 会从主题簇生成规则型后续问题和对应命令，适合把收藏内容转成 agent 的下一步研究入口。

`explain` 会围绕单个实体输出相关文档、citation 和关系边，适合追问“这个概念为什么出现在我的本地知识库里”。

`relations` 会列出图谱中的 subject-predicate-object 关系边，支持按实体和 predicate 过滤，适合检查某个概念与哪些文档/实体发生连接。

`profile` 会为实体和账号返回 `evidence_documents`，并在实体可匹配到段落或保守别名时返回 `evidence_citations`，方便追溯画像来源；实体项会显示平均置信度和来自 `media.text` 的文档数，帮助区分正文信号和 OCR/ASR 回写信号；同时输出最近文档、最近活跃实体和最近活跃账号，帮助 agent 判断用户兴趣的时间变化。也可以输出 Markdown，直接作为本地知识库的兴趣摘要。过泛英文词和 `Article/Image/Video/Markdown/JSON/URL/Content/Context` 等载体词会在画像输出层过滤，底层实体表仍保留原始抽取结果。

`brief` 会汇总仓库统计、平台分布、兴趣信号、用户标注、starter queries、主题簇、来源账号、最近文档和推荐查询命令，适合在新 agent 会话开始时直接粘贴。

`export` 会一次性写出 `handoff.md`、`auto-queue.commands.txt`、`auto-queue.jsonl`、`inbox.md/json`、`curate.md/json`、`duplicates.md/json`、`coverage.md/json`、`review.md/json`、`brief.md/json`、`starter-queries.md/json`、`doctor.md/json`、`quality.md/json`、`evidence.md/json`、`actions.md/json`、`agent-tasks.md/json`、`digest.md/json`、`sources.md/json`、`tags.md/json`、`notes.md/json`、`statuses.md/json`、`annotations.md/json`、`topics.md/json`、`clusters.md/json`、`questions.md/json`、`relations.md/json`、`profile.md/json`、`timeline.md/json`、`media-pipeline.md/json`、`queue.md/json`、`media.md/json`、`graph.json/mmd` 和 `manifest.json`，适合作为新 agent 会话或外部知识库导入的交接目录。`handoff.md` 会额外突出媒体处理、缓存修复和低置信度复核的 Hot Commands，并展示媒体处理链路状态；`manifest.json` 也会写入结构化 `hot_commands` 和 `media_pipeline`，其中 `hot_commands` 包含 `command`、`kind`、`priority`、`source`、`reason`、`automation` 和 `requires_review`，并用 `hot_command_groups.auto_queue/manual_review` 拆出自动排队和人工确认清单；`auto-queue.commands.txt` 和 `auto-queue.jsonl` 则只包含可自动排队的 OCR/ASR 命令。

`snapshot` 会同时生成 `agent-handoff/`、`jsonl-dump/`、`markdown-docs/`、`graph-csv/`、`graph.cypher` 和根目录 `snapshot.json`，适合作为一次完整备份、交接包、Markdown 知识库或图数据库导入包。

`verify-snapshot` 会检查根 `snapshot.json`，并继续校验 `agent-handoff/`、`jsonl-dump/`、`markdown-docs/`、`graph-csv/` 和 `graph.cypher`。

`import-snapshot` 会先校验完整 snapshot，再从其中的 `jsonl-dump/` 恢复当前 SQLite store，适合从完整快照重建本地知识库。

`dump-jsonl` 会导出 `documents`、`media`、`citations`、`entities`、`document_entities`、`document_tags`、`document_notes`、`document_status` 和 `relationships` 九张 JSONL 表，适合导入向量库、图数据库或其他 agent 工具。

`dump-docs` 会按文档导出独立 Markdown 文件和 `manifest.json`，文件内容复用 `doc` 的完整上下文，适合放进 Obsidian、文件夹知识库或其它 Markdown-first 工具。

`verify-docs` 会读取 Markdown 文档导出的 `manifest.json`，检查文件是否缺失、大小和 `sha256` 是否匹配。

`import-jsonl` 会先校验 JSONL dump，再把九张表恢复到当前 SQLite store，适合迁移、备份恢复或重建本地知识库。

`verify-jsonl` 会读取 JSONL dump 的 `manifest.json`，检查文件是否缺失、大小、`sha256` 和行数是否匹配。

`manifest.json` 会保留导出文件列表、每个文件的字节数和 `sha256`，方便确认 handoff 包完整性。

`verify-export` 会读取导出目录的 `manifest.json`，检查文件是否缺失、大小和 `sha256` 是否匹配。

`verify-auto-queue` 会检查 `auto-queue.commands.txt` 和 `auto-queue.jsonl` 是否存在、非空、命令顺序一致、条目都是 `automation=auto_queue` 且 `requires_review=false`，并校验 `reason` 中的 `local_path` 是否存在；建议外部 agent 运行自动 OCR/ASR 队列前先执行：

```powershell
python -m link2context.store --db data\link2context.db verify-auto-queue outputs\agent-handoff --base-dir .
```

`run-auto-queue` 只消费通过 `verify-auto-queue` 的执行清单；默认 dry-run 输出将执行的命令，显式加 `--execute` 才会逐条运行。报告会根据队列命令给出下一步 `run-media-text ... --apply --reindex` 命令，用于把 OCR/ASR 结果继续回写入库；不提供 next 配置时会保留占位模板，提供 `--next-preset` 或 `--next-command-template` 时会生成可直接复用的真实命令。加 `--write-next` 会写出 `auto-queue-next.commands.txt` 和 `auto-queue-next.jsonl`，并在存在 `manifest.json` 时更新 handoff manifest；JSONL 会标记 `requires_review=true`：

```powershell
python -m link2context.store --db data\link2context.db run-auto-queue outputs\agent-handoff --base-dir .
python -m link2context.store --db data\link2context.db run-auto-queue outputs\agent-handoff --base-dir . --execute
python -m link2context.store --db data\link2context.db run-auto-queue outputs\agent-handoff --base-dir . --next-preset sona --next-preset-model models\ggml-medium.bin --next-tool-path C:\Tools\sona.exe --next-language zh --next-out-dir outputs\media-text --write-next
python -m link2context.store --db data\link2context.db run-auto-queue outputs\agent-handoff --base-dir . --next-command-template "your-ocr-command --url {input_source}" --next-model your-ocr --next-language zh --next-confidence 0.85
python -m link2context.store --db data\link2context.db verify-auto-queue-next outputs\agent-handoff
python -m link2context.store --db data\link2context.db run-auto-queue-next outputs\agent-handoff
python -m link2context.store --db data\link2context.db run-auto-queue-next outputs\agent-handoff --execute
```

`verify-auto-queue-next` 会检查 `auto-queue-next.commands.txt` 和 `auto-queue-next.jsonl` 是否存在、非空、命令顺序一致，且每条 next command 都是 `run-media-text`、包含 `--out`、`--apply`、`--reindex`，JSONL 必须标记 `automation=manual_review` 和 `requires_review=true`；如果目录里有 `manifest.json`，还会校验 next 文件的 `sha256/size` 和 `auto_queue_next` 元数据。

`run-auto-queue-next` 会先运行 `verify-auto-queue-next`，默认只 dry-run 展示即将执行的 OCR/ASR 回写命令；只有显式加 `--execute` 且 preflight 通过时才会逐条执行。

`examples/media-pipeline/` 提供一个固定的媒体链路回归样例，使用 `fake_ocr.py` 代替真实 OCR/ASR 后端，覆盖 `media-pipeline -> queue -> run-auto-queue --write-next -> verify-auto-queue-next -> run-auto-queue-next -> verify-media-text`。

`query` 是关键词检索 MVP，会把输入拆成多个检索词，在已入库文档、实体、citation、已回写的媒体文本和用户标注中查找命中项，并返回适合 agent 消费的 JSON 或 Markdown 证据包。Citation、media evidence 和 user annotations 会带命中词或轻量 `score`，用于把更贴近查询的段落和个人判断排在前面；它还不是语义搜索。

## MVP Schema

```json
{
  "project": "Link2Context",
  "source": {
    "platform": "wechat_official_account | xiaohongshu",
    "url": "...",
    "fetched_at": "...",
    "identifiers": {}
  },
  "article": {
    "title": "...",
    "account_name": "...",
    "author": null,
    "published_at": "...",
    "summary": "...",
    "canonical_url": "..."
  },
  "content": {
    "html": "...",
    "markdown": "...",
    "plain_text": "..."
  },
  "media": {
    "cover_image": "...",
    "images": [],
    "videos": []
  },
  "agent_package": {
    "brief": "...",
    "key_points": [],
    "claims": [],
    "entities": [],
    "links": [],
    "citations": []
  },
  "quality": {
    "status": "ok",
    "warnings": [],
    "missing_fields": []
  }
}
```

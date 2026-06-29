# Graph MVP

Date: 2026-06-29

## Scope

当前图谱层是保守 MVP，用于把已生成的 `context.json` 导入本地 SQLite 后形成可查询的候选实体和基础关系。

它不是完整 NER，也不是 LLM 语义图谱。

## Extracted Entities

规则抽取以下实体：

- source account: `article.account_name`
- author: `article.author`
- hashtag: 正文或标题里的 `#tag`
- topic: 标题中的中文短语
- term: 正文或标题中的英文/产品词

每个实体包含：

- `name`
- `normalized_name`
- `type`
- `source`
- `confidence`

## Relationships

当前关系只记录基础来源关系：

- document `published_by` source account
- document `authored_by` author
- document `tagged_as` hashtag
- document `mentions` candidate entity

## Store Tables

SQLite store 现在包含：

- `documents`
- `media`
- `citations`
- `entities`
- `document_entities`
- `relationships`

## CLI

```powershell
python -m link2context.store --db data\link2context.db import outputs\batch
python -m link2context.store --db data\link2context.db stats
python -m link2context.store --db data\link2context.db entities
python -m link2context.store --db data\link2context.db graph
python -m link2context.store --db data\link2context.db graph --format mermaid
python -m link2context.store --db data\link2context.db graph --include-terms
python -m link2context.store --db data\link2context.db profile
python -m link2context.store --db data\link2context.db profile --format markdown
```

## Graph Export

`graph` 命令导出 JSON：

- `nodes`: document/entity/literal nodes
- `edges`: document-to-entity and relationship edges

当前导出是面向可视化或后续图数据库导入的中间格式，不是完整图数据库协议。

默认导出会隐藏噪声较高的 `term` 实体，只保留账号、作者、标签、标题主题等更稳定的节点。需要完整候选实体时使用 `--include-terms`。

`--format mermaid` 可以生成可直接粘贴到 Mermaid 渲染器里的第一视图。

## Interest Profile

`profile` 命令输出保守兴趣画像：

- `top_entities`
- `top_accounts`
- `by_platform`
- `recent_documents`
- `recent_entities`
- `recent_accounts`

`top_entities` 和 `top_accounts` 会带 `evidence_documents`，用于追溯每个画像条目来自哪些原始内容。实体项还会尽量返回 `evidence_citations`；citation 匹配支持少量保守别名，例如中文标题主题的 2 字以上连续片段、英文空格/连字符/驼峰变体，匹配不到时保留文档级证据。`top_entities` 会在文档数相同的候选中优先排序有 citation 支撑的实体，并返回 `evidence_citation_count`。实体项还包含 `avg_confidence` 和 `media_documents`，用于区分正文抽取信号和 OCR/ASR 回写后的 `media.text` 信号。

`recent_*` 字段按 `published_at` 优先、缺失时按 `imported_at` 排序，用于让 agent 判断最近收藏内容和近期活跃兴趣信号。

它只根据已导入 context 的实体、来源元数据和文档时间聚合，不生成缺少证据的人格判断或偏好推断。为了降低噪声，profile 输出层会过滤 `AI`、`Agent`、`Skill` 以及 `Article`、`Image`、`Video`、`Markdown`、`JSON`、`URL`、`Content`、`Context`、`Tool`、`Model`、`Page`、`Text`、`File`、`Web` 等过泛英文/载体词；底层实体表仍保留原始抽取结果，避免丢失数据。

`--format markdown` 可以生成可直接复制给 agent 或写入文档的兴趣画像摘要。

## Next Step

已补 `examples/media-pipeline/` 固定样例和端到端回归测试，覆盖 `media-pipeline -> queue -> run-auto-queue --write-next -> verify-auto-queue-next -> run-auto-queue-next -> verify-media-text`；`media-text-presets` 也能输出 Tesseract/Sona 模板和本机可执行文件状态。下一步应选一组真实图片/视频样本跑通本机 OCR/ASR，并补充失败重试和置信度复核规则。

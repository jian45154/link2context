# Agent Query MVP

Date: 2026-06-29

## Scope

`query` 命令从本地 SQLite store 中检索已导入内容，并返回适合 AI agent 使用的 JSON 证据包。

当前是关键词检索，不是语义搜索，也不调用外部 LLM。

查询会被拆成多个检索词，例如 `Claude Codex 知识图谱` 会变成 `["Claude", "Codex", "知识图谱"]`。

## CLI

```powershell
python -m link2context.store --db data\link2context.db query "关键词"
python -m link2context.store --db data\link2context.db query "关键词" --format markdown
```

## Output

JSON 输出包含：

- `query`
- `terms`
- `results`
- result metadata: title, url, platform, account, published_at, summary, quality
- `matched_terms`
- `matched_entities`
- `citations`

每条 citation 包含：

- `ref`
- `text`
- `source`
- `matched_terms`
- `score`

## Retrieval Sources

检索范围：

- document title
- summary
- plain text
- extracted entities
- citation text

## Next Step

当前 `matched_terms` 只标注 title/summary 命中的词；citation 命中会体现在 `citations[*].matched_terms` 字段。

Citation 排序使用轻量关键词分数：命中词越多、出现次数越多，排名越靠前。同分时按 citation `ref` 的自然段号排序，例如 `paragraph_27` 会排在 `paragraph_104` 前。

Markdown 输出用于直接复制给 agent，包含检索词、命中文档、匹配实体和 citation 证据。

下一步应考虑：

- query expansion / alias matching。
- 可选向量检索，但不要替代可追溯 citation。

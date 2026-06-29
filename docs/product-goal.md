# 灵渠 / Link2Context Open Source Goal

## Goal

建设一个开源、本地优先的 GitHub 项目，把用户主动收集的文章、链接、视频、图文和社媒内容转换成 agent-ready context，并作为本地知识图谱数据库的输入。

项目定位：

> Link2Context is an open-source link-to-context compiler for local AI agents.

## Core Problem

人们不断收藏内容，但收藏夹通常只保存链接，不保存理解、关系和可调用知识。结果是：

- 想不起自己收藏过什么。
- 内容之间没有连接。
- AI agent 无法直接使用这些材料。
- 视频、图片、长文里的信息沉没。

## Project Promise

灵渠把主动收集的内容转换成可检索、可引用、可追问、可被 agent 调用的本地知识图谱输入。

## Open Source Boundary

当前 MVP 只做第一层：

- 输入：微信文章、小红书笔记、URL 列表。
- 输出：统一的 `context.json` 和 `context.md`。
- 保留：图片 OCR、视频 ASR、实体、关系、citation、quality 字段。

暂不承诺：

- 全平台自动采集。
- 绕登录、绕风控、批量爬取。
- 自动理解所有图片和视频。
- 完整评论区和互动数据。
- 托管 SaaS、商业账号系统或闭源平台。

## Next Milestones

1. `Context Store`: 保存每条链接的结构化上下文。已具备 SQLite MVP。
2. `Entity Extractor`: 抽取账号、作者、标签、标题主题和英文/产品词。已具备规则型 MVP。
3. `Graph Store`: 建立实体与内容之间的关系。已具备文档-实体连接和基础关系表 MVP。
4. `Interest Profile`: 从用户收藏内容中形成兴趣画像。已具备证据型聚合 MVP。
5. `Agent Query`: 让 agent 能按问题检索用户的知识仓库。已具备关键词检索和 citation 证据包 MVP。

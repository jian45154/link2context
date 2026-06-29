# Quickstart

This quickstart uses offline fixtures only. It does not require network access, cookies, or live platform requests.

## Install

```powershell
python -m pip install -e ".[dev]"
```

## Generate Context Files

WeChat fixture:

```powershell
python -m link2context --html examples/wechat_sample.html --url "https://mp.weixin.qq.com/s/example" --out outputs/sample
```

Xiaohongshu fixture:

```powershell
python -m link2context --html examples/xiaohongshu_sample.html --url "https://www.xiaohongshu.com/explore/example" --platform xiaohongshu --out outputs/xhs-sample
```

Each command writes:

- `context.json`
- `context.md`

## Import Into The Local Store

```powershell
python -m link2context.store --db data/link2context.db ingest outputs/sample
python -m link2context.store --db data/link2context.db ingest outputs/xhs-sample
```

## Inspect The Store

```powershell
python -m link2context.store --db data/link2context.db doctor
python -m link2context.store --db data/link2context.db stats
python -m link2context.store --db data/link2context.db query "示例"
```

## Export An Agent Handoff

```powershell
python -m link2context.store --db data/link2context.db export --out outputs/agent-handoff
python -m link2context.store --db data/link2context.db verify-export outputs/agent-handoff
```

## Cleanup

Generated `data/` and `outputs/` directories are ignored by git.

from pathlib import Path

import link2context.cli as cli
from link2context.cli import build_context, detect_platform
from link2context.xiaohongshu import build_xiaohongshu_context
import json


def test_cli_offline_xiaohongshu_example_writes_context_files(tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "xhs-sample"
    monkeypatch.setattr(
        "sys.argv",
        [
            "link2context",
            "--html",
            "examples/xiaohongshu_sample.html",
            "--url",
            "https://www.xiaohongshu.com/explore/example",
            "--platform",
            "xiaohongshu",
            "--out",
            str(out_dir),
        ],
    )

    cli.main()

    context = json.loads((out_dir / "context.json").read_text(encoding="utf-8"))
    markdown = (out_dir / "context.md").read_text(encoding="utf-8")
    assert context["source"]["platform"] == "xiaohongshu"
    assert context["article"]["title"] == "小红书示例笔记"
    assert "# 小红书示例笔记" in markdown


def test_detect_platform_for_xiaohongshu() -> None:
    assert detect_platform("https://www.xiaohongshu.com/explore/abc123") == "xiaohongshu"
    assert detect_platform("https://xhslink.com/a/example") == "xiaohongshu"


def test_build_xiaohongshu_context_from_sample_html() -> None:
    html = Path("examples/xiaohongshu_sample.html").read_text(encoding="utf-8")

    context = build_xiaohongshu_context("https://www.xiaohongshu.com/explore/abc123", html)

    assert context["source"]["platform"] == "xiaohongshu"
    assert context["article"]["title"] == "小红书示例笔记"
    assert context["article"]["account_name"] == "灵渠测试用户"
    assert "第一段" in context["content"]["plain_text"]
    assert len(context["media"]["images"]) == 2
    assert len(context["media"]["videos"]) == 1
    assert context["quality"]["status"] == "ok"


def test_xiaohongshu_boilerplate_is_removed() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="INTP眼中ENFP的三大超一流特质 - 小红书">
        <meta name="description" content="正文内容#mbti 创作中心 业务合作 © 2014-2026 行吟信息科技（上海）有限公司 地址：上海市黄浦区马当路388号C座 电话：9501-3888">
      </head>
      <body>创作中心 业务合作 © 2014-2026 行吟信息科技（上海）有限公司</body>
    </html>
    """

    context = build_xiaohongshu_context("https://www.xiaohongshu.com/explore/abc123", html)

    assert context["article"]["title"] == "INTP眼中ENFP的三大超一流特质"
    assert context["article"]["summary"] == "正文内容#mbti"
    assert "行吟信息科技" not in context["content"]["plain_text"]


def test_build_context_routes_xiaohongshu() -> None:
    html = Path("examples/xiaohongshu_sample.html").read_text(encoding="utf-8")

    context = build_context("https://www.xiaohongshu.com/explore/abc123", html)

    assert context["source"]["platform"] == "xiaohongshu"


def test_agent_reach_backend_unavailable_falls_back(monkeypatch) -> None:
    html = Path("examples/xiaohongshu_sample.html").read_text(encoding="utf-8")

    monkeypatch.setattr(
        cli,
        "platform_backend_status",
        lambda platform: {
            "available": False,
            "active_backend": None,
            "reason": "not installed",
        },
    )

    context = build_context(
        "https://www.xiaohongshu.com/explore/abc123",
        html,
        backend="agent-reach",
    )

    assert context["source"]["backend"] == "native"
    assert any("agent-reach backend is unavailable" in warning for warning in context["quality"]["warnings"])

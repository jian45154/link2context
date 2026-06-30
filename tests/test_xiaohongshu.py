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


def test_xiaohongshu_partial_fixture_reports_missing_fields_and_warnings() -> None:
    html = Path("examples/xiaohongshu_partial.html").read_text(encoding="utf-8")

    context = build_xiaohongshu_context("https://www.xiaohongshu.com/explore/partial", html)

    assert context["quality"]["status"] == "empty"
    assert "Could not find an embedded Xiaohongshu JSON state; parsed meta tags and visible HTML only." in (
        context["quality"]["warnings"]
    )
    assert "Title was not found." in context["quality"]["warnings"]
    assert "Note text was empty after parsing." in context["quality"]["warnings"]
    assert {"title", "account_name", "plain_text"} <= set(context["quality"]["missing_fields"])
    assert context["media"]["images"] == []
    assert context["media"]["videos"] == []


def test_xiaohongshu_media_heavy_fixture_extracts_all_media() -> None:
    html = Path("examples/xiaohongshu_media_heavy.html").read_text(encoding="utf-8")

    context = build_xiaohongshu_context("https://www.xiaohongshu.com/explore/media-heavy", html)

    assert context["quality"]["status"] == "ok"
    assert context["quality"]["missing_fields"] == []
    assert len(context["media"]["images"]) == 5
    assert context["media"]["images"][0]["url"] == "https://example.com/xhs-media-cover.jpg"
    assert [image["index"] for image in context["media"]["images"]] == [1, 2, 3, 4, 5]
    assert len(context["media"]["videos"]) == 2
    assert [video["index"] for video in context["media"]["videos"]] == [1, 2]


def test_xiaohongshu_author_link_fallback_and_inline_image_filter() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="LibTV一定会上市 - 小红书">
        <meta name="description" content="别人干视频Agent是做生意的逻辑，冕神是上市的逻辑，无敌。 #小红书科技 #全新的科技">
        <meta property="og:image" content="https://example.com/xhs-cover.jpg">
      </head>
      <body>
        <a href="/user/profile/me">我</a>
        <a href="/user/profile/61556b15000000000201b291?xsec_source=pc_note">葬愛咸鱼</a>
        <a href="/user/profile/61556b15000000000201b291?xsec_source=pc_note">葬愛咸鱼</a>
        <a href="//beian.miit.gov.cn/">沪ICP备13030189号</a>
        <a href="/search_result?keyword=%E5%B0%8F%E7%BA%A2%E4%B9%A6%E7%A7%91%E6%8A%80">#小红书科技</a>
        <main>
          <p>LibTV一定会上市 - 小红书</p>
          <p>别人干视频Agent是做生意的逻辑，冕神是上市的逻辑，无敌。</p>
          <img src="data:image/png;base64,abc123">
          <img src="https://example.com/xhs-content.jpg">
        </main>
      </body>
    </html>
    """

    context = build_xiaohongshu_context("https://www.xiaohongshu.com/explore/abc123", html)

    assert context["article"]["account_name"] == "葬愛咸鱼"
    assert context["quality"]["missing_fields"] == []
    assert [image["url"] for image in context["media"]["images"]] == [
        "https://example.com/xhs-cover.jpg",
        "https://example.com/xhs-content.jpg",
    ]
    assert "LibTV一定会上市 - 小红书" not in context["content"]["plain_text"]
    assert context["content"]["plain_text"].count("别人干视频Agent是做生意的逻辑") == 1
    assert context["agent_package"]["links"] == [
        {
            "text": "葬愛咸鱼",
            "url": "/user/profile/61556b15000000000201b291?xsec_source=pc_note",
        },
        {
            "text": "#小红书科技",
            "url": "/search_result?keyword=%E5%B0%8F%E7%BA%A2%E4%B9%A6%E7%A7%91%E6%8A%80",
        },
    ]


def test_xiaohongshu_subtitle_tracks_can_populate_video_transcript() -> None:
    html = r"""
    <html>
      <head>
        <meta property="og:title" content="四个方法手把手教你怎么在澳洲找工作 - 小红书">
        <meta name="description" content="澳洲找工作四个方法，重点讲 networking 和内推。">
        <meta property="og:video" content="https://example.com/xhs-video.mp4">
      </head>
      <body>
        <p>澳洲找工作四个方法，重点讲 networking 和内推。</p>
        <script>
          window.__INITIAL_STATE__ = {"note":{"mediaV2":"{\"subtitles\":{\"en-US\":[{\"url\":\"https:\u002F\u002Fsns-subtitle-s10.xhscdn.com\u002Fsubtitle\u002Fen.srt?sign=abc&t=1\",\"language\":\"en-US\",\"format\":0,\"type\":0}],\"source\":[{\"url\":\"https:\u002F\u002Fsns-subtitle-s10.xhscdn.com\u002Fsubtitle\u002Fsource.srt?sign=def&t=1\",\"language\":\"zh-CN\",\"format\":0,\"type\":0}],\"zh-CN\":[{\"url\":\"https:\u002F\u002Fsns-subtitle-s10.xhscdn.com\u002Fsubtitle\u002Fzh.srt?sign=ghi&t=1\",\"language\":\"zh-CN\",\"format\":0,\"type\":0}]}}" }};
        </script>
      </body>
    </html>
    """
    srt_text = """1
00:00:00,000 --> 00:00:02,000
第一句字幕

2
00:00:02,000 --> 00:00:04,500
第二句字幕
"""
    fetched_urls: list[str] = []

    def fetch_subtitle(url: str) -> str:
        fetched_urls.append(url)
        return srt_text

    context = build_xiaohongshu_context(
        "https://www.xiaohongshu.com/explore/abc123",
        html,
        subtitle_fetcher=fetch_subtitle,
    )

    video = context["media"]["videos"][0]
    analysis = video["analysis"]
    assert video["status"] == "processed"
    assert analysis["status"] == "processed"
    assert analysis["language"] == "zh-CN"
    assert analysis["subtitle_track"]["role"] == "source"
    assert fetched_urls == [
        "https://sns-subtitle-s10.xhscdn.com/subtitle/source.srt?sign=def&t=1"
    ]
    assert [track["language"] for track in analysis["subtitle_tracks"]] == ["en-US", "zh-CN", "zh-CN"]
    assert analysis["transcript_text"] == "第一句字幕 第二句字幕"
    assert analysis["transcript"][0] == {
        "index": 1,
        "start": "00:00:00.000",
        "end": "00:00:02.000",
        "start_seconds": 0.0,
        "end_seconds": 2.0,
        "text": "第一句字幕",
    }
    assert analysis["timeline"][1]["text"] == "第二句字幕"
    assert "### video_1 Transcript" in cli.render_markdown(context)
    assert "第一句字幕 第二句字幕" in cli.render_markdown(context)


def test_xiaohongshu_image_list_extracts_carousel_and_filters_ui_fragments() -> None:
    html = r"""
    <html>
      <head>
        <meta property="og:title" content="ENFP的主体性：让渡与反杀，特殊的动态型存在 - 小红书">
        <meta name="description" content="有些塑造主体性的方式不是关紧城堡的门，而是绘制星图航路。#ENFP #主体性">
      </head>
      <body>
        <p>已关注</p>
        <p>1/15</p>
        <p>2天前 北京</p>
        <script>
          window.__INITIAL_STATE__ = {"note":{"imageList":[
            {"fileId":"notes_pre_post\u002Fone","urlPre":"http:\u002F\u002Fexample.com\u002Fone-prv.jpg","urlDefault":"http:\u002F\u002Fexample.com\u002Fone-dft.jpg","infoList":[{"imageScene":"WB_PRV","url":"http:\u002F\u002Fexample.com\u002Fone-prv.jpg"},{"imageScene":"WB_DFT","url":"http:\u002F\u002Fexample.com\u002Fone-dft.jpg"}]},
            {"fileId":"notes_pre_post\u002Ftwo","infoList":[{"imageScene":"WB_PRV","url":"http:\u002F\u002Fexample.com\u002Ftwo-prv.jpg"},{"imageScene":"WB_DFT","url":"http:\u002F\u002Fexample.com\u002Ftwo-dft.jpg"}]},
            {"fileId":"notes_pre_post\u002Fthree","urlPre":"http:\u002F\u002Fexample.com\u002Fthree-prv.jpg"}
          ]}};
        </script>
      </body>
    </html>
    """

    context = build_xiaohongshu_context("https://www.xiaohongshu.com/explore/abc123", html)

    assert [image["url"] for image in context["media"]["images"]] == [
        "http://example.com/one-dft.jpg",
        "http://example.com/two-dft.jpg",
        "http://example.com/three-prv.jpg",
    ]
    assert "已关注" not in context["content"]["plain_text"]
    assert "1/15" not in context["content"]["plain_text"]
    assert "2天前 北京" not in context["content"]["plain_text"]


def test_xiaohongshu_shortlink_extracts_embedded_note_id() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="AI自己做科研了，那么人干嘛？ - 小红书">
        <meta name="description" content="AI自己做科研了，那么人干嘛？#AI #AI科研">
      </head>
      <body>
        <p>AI自己做科研了，那么人干嘛？#AI #AI科研</p>
        <script>
          window.__INITIAL_STATE__ = {"note":{"firstNoteId":"6a3415da00000000070268e3","noteDetailMap":{"6a3415da00000000070268e3":{"note":{"noteId":"6a3415da00000000070268e3"}}},"serverRequestInfo":undefined}};
        </script>
      </body>
    </html>
    """

    context = build_xiaohongshu_context("http://xhslink.com/o/2pcIGXq4WLg", html)

    assert context["source"]["identifiers"] == {
        "path_id": "2pcIGXq4WLg",
        "note_id": "6a3415da00000000070268e3",
    }
    assert context["article"]["canonical_url"] == "https://www.xiaohongshu.com/explore/6a3415da00000000070268e3"


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

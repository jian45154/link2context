from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from link2context import __version__
from link2context.cli import (
    failed_url_report,
    read_cookie,
    read_url_list,
    render_retry_failed_markdown,
    render_verify_batch_markdown,
    retry_failed_batch,
    run_batch,
    slug_from_url,
    verify_batch,
)
import link2context.cli as cli
from link2context.wechat import build_wechat_context


def test_cli_version_uses_package_version(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.argv", ["link2context", "--version"])

    with pytest.raises(SystemExit) as exc:
        cli.parse_args()

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"link2context {__version__}"


def test_cli_help_lists_core_options(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.argv", ["link2context", "--help"])

    with pytest.raises(SystemExit) as exc:
        cli.parse_args()

    output = capsys.readouterr().out
    assert exc.value.code == 0
    assert "Convert social content URLs into agent-ready context packages." in output
    assert "--url-list" in output
    assert "--verify-batch" in output
    assert "--platform {auto,wechat,xiaohongshu}" in output


def test_cli_offline_wechat_example_writes_context_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_dir = tmp_path / "sample"
    monkeypatch.setattr(
        "sys.argv",
        [
            "link2context",
            "--html",
            "examples/wechat_sample.html",
            "--url",
            "https://mp.weixin.qq.com/s/example",
            "--out",
            str(out_dir),
        ],
    )

    cli.main()

    context = json.loads((out_dir / "context.json").read_text(encoding="utf-8"))
    markdown = (out_dir / "context.md").read_text(encoding="utf-8")
    assert context["source"]["platform"] == "wechat_official_account"
    assert context["article"]["title"] == "示例公众号文章"
    assert "# 示例公众号文章" in markdown


def test_build_wechat_context_from_sample_html() -> None:
    html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")

    context = build_wechat_context("https://mp.weixin.qq.com/s/example", html)

    assert context["source"]["platform"] == "wechat_official_account"
    assert context["article"]["title"] == "示例公众号文章"
    assert context["article"]["account_name"] == "灵渠测试号"
    assert "第一段" in context["content"]["plain_text"]
    assert len(context["media"]["images"]) == 1
    assert len(context["media"]["videos"]) == 1
    assert context["quality"]["status"] == "ok"


def test_read_url_list_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "urls.txt"
    path.write_text(
        "\n# comment\nhttps://mp.weixin.qq.com/s/one\n\nhttps://mp.weixin.qq.com/s/two\n",
        encoding="utf-8",
    )

    assert read_url_list(path) == [
        "https://mp.weixin.qq.com/s/one",
        "https://mp.weixin.qq.com/s/two",
    ]


def test_read_url_list_dedupes_and_normalizes_xhs_urls(tmp_path: Path) -> None:
    path = tmp_path / "urls.txt"
    path.write_text(
        "\nxiaohongshu.com/explore/one\nhttps://www.xiaohongshu.com/explore/two\nxiaohongshu.com/explore/one\n",
        encoding="utf-8",
    )

    assert read_url_list(path) == [
        "https://xiaohongshu.com/explore/one",
        "https://www.xiaohongshu.com/explore/two",
    ]


def test_run_batch_manifest_summarizes_success_and_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url_list = tmp_path / "urls.txt"
    url_list.write_text(
        "https://mp.weixin.qq.com/s/ok\nhttps://mp.weixin.qq.com/s/fail\n",
        encoding="utf-8",
    )
    sample_html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")

    def fake_fetch(url: str, cookie: str | None = None) -> str:
        if url.endswith("/fail"):
            raise RuntimeError("login required")
        return sample_html

    monkeypatch.setattr(cli, "fetch_url", fake_fetch)

    run_batch(url_list, tmp_path / "batch", "wechat", "native")

    manifest = json.loads((tmp_path / "batch" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["project"] == "Link2Context"
    assert manifest["format"] == "batch-context"
    assert manifest["version"] == 1
    assert manifest["generated_at"]
    assert manifest["count"] == 2
    assert manifest["succeeded"] == 1
    assert manifest["failed"] == 1
    assert manifest["ok"] is False
    assert manifest["items"][0]["status"] == "ok"
    assert set(manifest["items"][0]["file_details"]) == {"context.json", "context.md"}
    assert manifest["items"][0]["file_details"]["context.json"]["size_bytes"] > 0
    assert manifest["items"][0]["file_details"]["context.json"]["sha256"]
    assert manifest["items"][1]["status"] == "error"
    assert set(manifest["items"][1]["file_details"]) == {"error.json"}
    assert manifest["failures"] == [manifest["items"][1]]
    assert manifest["recommended_next"] == [
        f"python -m link2context --failed-url-list {tmp_path / 'batch'} > outputs/retry_urls.txt",
        f"python -m link2context --retry-failed {tmp_path / 'batch'} --out outputs/retry",
        f"python -m link2context.store --db data/link2context.db ingest {tmp_path / 'batch'}",
    ]
    assert (tmp_path / "batch" / "001-ok" / "context.json").exists()
    assert (tmp_path / "batch" / "002-fail" / "error.json").exists()


def test_verify_batch_passes_for_clean_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url_list = tmp_path / "urls.txt"
    url_list.write_text("https://mp.weixin.qq.com/s/ok\n", encoding="utf-8")
    sample_html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "fetch_url", lambda url, cookie=None: sample_html)
    run_batch(url_list, tmp_path / "batch", "wechat", "native")

    report = verify_batch(tmp_path / "batch")

    assert report["ok"] is True
    assert report["manifest"]["format"] == "batch-context"
    assert report["manifest"]["version"] == 1
    assert report["summary"] == {"count": 1, "succeeded": 1, "failed": 0}
    assert report["items"][0]["ok"] is True
    assert report["recommended_next"] == [
        f"python -m link2context.store --db data/link2context.db ingest {tmp_path / 'batch'}"
    ]


def test_verify_batch_fails_when_context_file_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url_list = tmp_path / "urls.txt"
    url_list.write_text("https://mp.weixin.qq.com/s/ok\n", encoding="utf-8")
    sample_html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "fetch_url", lambda url, cookie=None: sample_html)
    run_batch(url_list, tmp_path / "batch", "wechat", "native")
    (tmp_path / "batch" / "001-ok" / "context.md").unlink()

    report = verify_batch(tmp_path / "batch")
    markdown = render_verify_batch_markdown(report)

    assert report["ok"] is False
    assert "context.md is missing" in report["errors"][0]
    assert "context.md is missing" in markdown
    assert report["recommended_next"] == [
        f"python -m link2context.store --db data/link2context.db ingest {tmp_path / 'batch'}",
        f"python -m link2context --verify-batch {tmp_path / 'batch'}",
    ]
    assert "## Recommended Next" in markdown


def test_verify_batch_fails_when_context_file_is_modified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url_list = tmp_path / "urls.txt"
    url_list.write_text("https://mp.weixin.qq.com/s/ok\n", encoding="utf-8")
    sample_html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "fetch_url", lambda url, cookie=None: sample_html)
    run_batch(url_list, tmp_path / "batch", "wechat", "native")
    (tmp_path / "batch" / "001-ok" / "context.md").write_text("tampered\n", encoding="utf-8")

    report = verify_batch(tmp_path / "batch")

    assert report["ok"] is False
    assert "context.md does not match manifest detail" in report["errors"][0]


def test_verify_batch_recommends_retry_for_failed_items(tmp_path: Path) -> None:
    batch_dir = tmp_path / "batch with spaces"
    batch_dir.mkdir()
    fail_dir = batch_dir / "002-fail"
    fail_dir.mkdir()
    (fail_dir / "error.json").write_text('{"error":"login required"}', encoding="utf-8")
    manifest = {
        "project": "Link2Context",
        "format": "batch-context",
        "version": 1,
        "generated_at": "2026-06-29T00:00:00+00:00",
        "count": 1,
        "succeeded": 0,
        "failed": 1,
        "ok": False,
        "items": [
            {
                "index": 1,
                "url": "https://mp.weixin.qq.com/s/fail",
                "status": "error",
                "error": "login required",
                "output_dir": str(fail_dir),
            }
        ],
        "failures": [
            {
                "index": 1,
                "url": "https://mp.weixin.qq.com/s/fail",
                "status": "error",
                "error": "login required",
                "output_dir": str(fail_dir),
            }
        ],
        "recommended_next": [
            f'python -m link2context --failed-url-list "{batch_dir}" > outputs/retry_urls.txt',
            f'python -m link2context --retry-failed "{batch_dir}" --out outputs/retry',
        ],
    }
    (batch_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = verify_batch(batch_dir)
    markdown = render_verify_batch_markdown(report)
    quoted_batch_dir = f'"{batch_dir}"'

    assert report["recommended_next"] == [
        f"python -m link2context --failed-url-list {quoted_batch_dir} > outputs/retry_urls.txt",
        f"python -m link2context --retry-failed {quoted_batch_dir} --out outputs/retry",
    ]
    assert "--retry-failed" in markdown
    assert "\n".join(report["recommended_next"]).splitlines() == report["recommended_next"]


def test_verify_batch_fails_when_recommended_next_is_modified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url_list = tmp_path / "urls.txt"
    url_list.write_text("https://mp.weixin.qq.com/s/ok\n", encoding="utf-8")
    sample_html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "fetch_url", lambda url, cookie=None: sample_html)
    run_batch(url_list, tmp_path / "batch", "wechat", "native")
    manifest_path = tmp_path / "batch" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["recommended_next"] = ["python -m link2context wrong"]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = verify_batch(tmp_path / "batch")

    assert report["ok"] is False
    assert "manifest recommended_next does not match expected commands" in report["errors"]


def test_verify_batch_fails_for_wrong_manifest_metadata(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "project": "Other",
                "format": "unknown",
                "version": 99,
                "count": 0,
                "succeeded": 0,
                "failed": 0,
                "ok": True,
                "items": [],
                "failures": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = verify_batch(tmp_path)

    assert report["ok"] is False
    assert "manifest project is not Link2Context" in report["errors"]
    assert "manifest format is not batch-context" in report["errors"]
    assert "manifest version is not 1" in report["errors"]
    assert "manifest generated_at is missing" in report["errors"]


def test_verify_batch_fails_for_invalid_generated_at(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "project": "Link2Context",
                "format": "batch-context",
                "version": 1,
                "generated_at": "not-a-date",
                "count": 0,
                "succeeded": 0,
                "failed": 0,
                "ok": True,
                "items": [],
                "failures": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = verify_batch(tmp_path)

    assert report["ok"] is False
    assert "manifest generated_at is not valid ISO datetime" in report["errors"]


def test_failed_url_report_returns_unique_failed_urls(tmp_path: Path) -> None:
    manifest = {
        "project": "Link2Context",
        "format": "batch-context",
        "version": 1,
        "generated_at": "2026-06-29T00:00:00+00:00",
        "count": 3,
        "succeeded": 1,
        "failed": 2,
        "ok": False,
        "items": [
            {"index": 1, "url": "https://mp.weixin.qq.com/s/ok", "status": "ok"},
            {
                "index": 2,
                "url": "https://mp.weixin.qq.com/s/fail",
                "status": "error",
                "error": "login required",
                "output_dir": "002-fail",
            },
            {
                "index": 3,
                "url": "https://mp.weixin.qq.com/s/fail",
                "status": "error",
                "error": "retry failed",
                "output_dir": "003-fail",
            },
        ],
        "failures": [],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = failed_url_report(tmp_path)

    assert report["ok"] is True
    assert report["count"] == 1
    assert report["urls"] == ["https://mp.weixin.qq.com/s/fail"]
    assert report["items"][0]["error"] == "login required"


def test_retry_failed_batch_writes_retry_list_and_new_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_batch = tmp_path / "source"
    source_batch.mkdir()
    manifest = {
        "count": 2,
        "succeeded": 1,
        "failed": 1,
        "ok": False,
        "items": [
            {"index": 1, "url": "https://mp.weixin.qq.com/s/ok", "status": "ok"},
            {
                "index": 2,
                "url": "https://mp.weixin.qq.com/s/fail",
                "status": "error",
                "error": "login required",
                "output_dir": "002-fail",
            },
        ],
        "failures": [],
    }
    (source_batch / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    sample_html = Path("examples/wechat_sample.html").read_text(encoding="utf-8")
    fetched: list[str] = []

    def fake_fetch(url: str, cookie: str | None = None) -> str:
        fetched.append(url)
        return sample_html

    monkeypatch.setattr(cli, "fetch_url", fake_fetch)

    retry_dir = tmp_path / "retry with spaces"
    report = retry_failed_batch(source_batch, retry_dir, "wechat", "native")
    markdown = render_retry_failed_markdown(report)

    assert fetched == ["https://mp.weixin.qq.com/s/fail"]
    assert report["retried"] == 1
    assert report["succeeded"] == 1
    assert (retry_dir / "retry_urls.txt").read_text(encoding="utf-8") == "https://mp.weixin.qq.com/s/fail\n"
    retry_manifest = json.loads((retry_dir / "manifest.json").read_text(encoding="utf-8"))
    assert retry_manifest["project"] == "Link2Context"
    assert retry_manifest["format"] == "batch-context"
    assert retry_manifest["retry_source_batch"] == str(source_batch)
    assert retry_manifest["retry_url_list"] == str(retry_dir / "retry_urls.txt")
    assert retry_manifest["recommended_next"] == [
        f'python -m link2context.store --db data/link2context.db ingest "{retry_dir}"',
    ]
    assert report["recommended_next"] == [
        f'python -m link2context --verify-batch "{retry_dir}"',
        f'python -m link2context.store --db data/link2context.db ingest "{retry_dir}"',
    ]
    assert "\n".join(report["recommended_next"]).splitlines() == report["recommended_next"]
    assert "## Recommended Next" in markdown
    assert "--verify-batch" in markdown


def test_slug_from_url_has_stable_fallback() -> None:
    assert slug_from_url("https://mp.weixin.qq.com/s/example") == "example"
    assert slug_from_url("https://mp.weixin.qq.com/") == "social-post"


def test_short_fallback_page_is_partial() -> None:
    context = build_wechat_context(
        "https://mp.weixin.qq.com/s/example",
        "<html><body>：，。视频小程序赞，轻点两下取消赞在看，轻点两下取消在看</body></html>",
    )

    assert context["quality"]["status"] == "partial"
    assert "title" in context["quality"]["missing_fields"]


def test_wechat_partial_fixture_reports_missing_fields_and_warnings() -> None:
    html = Path("examples/wechat_partial.html").read_text(encoding="utf-8")

    context = build_wechat_context("https://mp.weixin.qq.com/s/partial", html)

    assert context["quality"]["status"] == "partial"
    assert "Title was not found." in context["quality"]["warnings"]
    assert any("unusually short" in warning for warning in context["quality"]["warnings"])
    assert {"title", "account_name", "published_at"} <= set(context["quality"]["missing_fields"])
    assert context["media"]["images"] == []
    assert context["media"]["videos"] == []


def test_wechat_media_heavy_fixture_extracts_all_media() -> None:
    html = Path("examples/wechat_media_heavy.html").read_text(encoding="utf-8")

    context = build_wechat_context("https://mp.weixin.qq.com/s/media-heavy", html)

    assert context["quality"]["status"] == "ok"
    assert context["quality"]["missing_fields"] == []
    assert len(context["media"]["images"]) == 3
    assert [image["index"] for image in context["media"]["images"]] == [1, 2, 3]
    assert len(context["media"]["videos"]) == 2
    assert [video["index"] for video in context["media"]["videos"]] == [1, 2]


def test_read_cookie_from_file(tmp_path: Path) -> None:
    path = tmp_path / "cookie.txt"
    path.write_text("a=1; b=2\n", encoding="utf-8")

    cookie = read_cookie(SimpleNamespace(cookie=None, cookie_file=str(path)))

    assert cookie == "a=1; b=2"


def test_read_cookie_rejects_two_sources(tmp_path: Path) -> None:
    path = tmp_path / "cookie.txt"
    path.write_text("a=1", encoding="utf-8")

    with pytest.raises(SystemExit):
        read_cookie(SimpleNamespace(cookie="b=2", cookie_file=str(path)))

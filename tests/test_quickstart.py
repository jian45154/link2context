from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def run_command(args: list[str]) -> str:
    result = subprocess.run(
        args,
        cwd=Path("."),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    assert result.returncode == 0, stdout + stderr
    return stdout


def test_quickstart_offline_context_store_query_and_handoff(tmp_path: Path) -> None:
    outputs_dir = tmp_path / "outputs"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sample_dir = outputs_dir / "sample"
    xhs_dir = outputs_dir / "xhs-sample"
    db_path = data_dir / "link2context.db"
    handoff_dir = outputs_dir / "agent-handoff"

    run_command(
        [
            sys.executable,
            "-m",
            "link2context",
            "--html",
            "examples/wechat_sample.html",
            "--url",
            "https://mp.weixin.qq.com/s/example",
            "--out",
            str(sample_dir),
        ]
    )
    run_command(
        [
            sys.executable,
            "-m",
            "link2context",
            "--html",
            "examples/xiaohongshu_sample.html",
            "--url",
            "https://www.xiaohongshu.com/explore/example",
            "--platform",
            "xiaohongshu",
            "--out",
            str(xhs_dir),
        ]
    )

    assert json.loads((sample_dir / "context.json").read_text(encoding="utf-8"))["source"]["platform"] == (
        "wechat_official_account"
    )
    assert json.loads((xhs_dir / "context.json").read_text(encoding="utf-8"))["source"]["platform"] == "xiaohongshu"
    assert (sample_dir / "context.md").exists()
    assert (xhs_dir / "context.md").exists()

    run_command([sys.executable, "-m", "link2context.store", "--db", str(db_path), "ingest", str(sample_dir)])
    run_command([sys.executable, "-m", "link2context.store", "--db", str(db_path), "ingest", str(xhs_dir)])
    run_command([sys.executable, "-m", "link2context.store", "--db", str(db_path), "doctor"])
    stats = run_command([sys.executable, "-m", "link2context.store", "--db", str(db_path), "stats"])
    query = run_command([sys.executable, "-m", "link2context.store", "--db", str(db_path), "query", "示例"])

    assert "documents" in stats.lower()
    assert "示例" in query

    run_command([sys.executable, "-m", "link2context.store", "--db", str(db_path), "export", "--out", str(handoff_dir)])
    verify = run_command([sys.executable, "-m", "link2context.store", "--db", str(db_path), "verify-export", str(handoff_dir)])

    assert (handoff_dir / "handoff.md").exists()
    assert (handoff_dir / "manifest.json").exists()
    assert "- OK: true" in verify

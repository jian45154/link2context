from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


def find_agent_reach() -> str | None:
    found = shutil.which("agent-reach")
    if found:
        return found

    local_bin = Path.home() / ".local" / "bin" / "agent-reach.exe"
    if local_bin.exists():
        return str(local_bin)

    return None


@lru_cache(maxsize=1)
def doctor() -> dict:
    executable = find_agent_reach()
    if not executable:
        return {
            "available": False,
            "error": "agent-reach executable was not found.",
        }

    result = subprocess.run(
        [executable, "doctor", "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if result.returncode != 0:
        return {
            "available": False,
            "executable": executable,
            "error": result.stderr.strip() or result.stdout.strip(),
        }

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "executable": executable,
            "error": f"Could not parse agent-reach doctor JSON: {exc}",
        }

    payload["_link2context"] = {
        "available": True,
        "executable": executable,
    }
    return payload


def platform_backend_status(platform: str) -> dict:
    payload = doctor()
    if not payload.get("_link2context", {}).get("available"):
        return {
            "available": False,
            "active_backend": None,
            "reason": payload.get("error", "agent-reach is unavailable."),
        }

    platform_status = payload.get(platform)
    if not isinstance(platform_status, dict):
        return {
            "available": False,
            "active_backend": None,
            "reason": f"agent-reach does not report platform {platform!r}.",
        }

    active_backend = platform_status.get("active_backend")
    return {
        "available": bool(active_backend),
        "active_backend": active_backend,
        "status": platform_status.get("status"),
        "reason": platform_status.get("message"),
    }

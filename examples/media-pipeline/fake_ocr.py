from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    print(f"MediaPipelineDemoText from {Path(source).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

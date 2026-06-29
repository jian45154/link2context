from __future__ import annotations

import argparse
import os
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a local .secrets cookie file for Link2Context.",
    )
    parser.add_argument(
        "--platform",
        default="xiaohongshu",
        help="Platform name used for .secrets/<platform>.cookie.",
    )
    parser.add_argument(
        "--path",
        help="Explicit cookie file path. Defaults to .secrets/<platform>.cookie.",
    )
    parser.add_argument(
        "--from-env",
        help="Environment variable containing the raw Cookie header value.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing cookie file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path) if args.path else Path(".secrets") / f"{args.platform}.cookie"
    if path.exists() and not args.force:
        raise SystemExit(f"{path} already exists. Use --force to overwrite it.")

    cookie = ""
    if args.from_env:
        cookie = os.environ.get(args.from_env, "").strip()
        if not cookie:
            raise SystemExit(f"Environment variable {args.from_env} is empty or missing.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cookie + ("\n" if cookie else ""), encoding="utf-8")

    if cookie:
        print(f"Wrote cookie file: {path}")
    else:
        print(f"Created empty cookie file: {path}")
        print("Paste the raw Cookie header value into this file before using --cookie-file.")


if __name__ == "__main__":
    main()

# Link2Context vX.Y.Z

## Highlights

- Short user-facing summary of the release.
- Key fixes, workflows, or compatibility changes worth calling out.

## Changes

- Added:
- Changed:
- Fixed:

## Verification

- `python -m compileall -q link2context tests`
- `python -m pytest tests -q`
- `python -m build`

## Compatibility

- Python: 3.10+
- Storage: local SQLite
- Network: live platform requests are optional; offline fixture workflows should continue to pass.

## Release Notes

- Do not include cookies, tokens, private exports, downloaded media, or local database files in release assets.
- Releases before `v1.0.0` are alpha/prerelease builds unless explicitly promoted.

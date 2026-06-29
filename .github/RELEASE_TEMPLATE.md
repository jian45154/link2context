# Link2Context vX.Y.Z

## Highlights

- 

## Verification

- `python -m compileall -q link2context tests`
- `python -m pytest tests -q`
- `python -m build`

## Compatibility

- Python: 3.10+
- Storage: local SQLite
- Network: live platform requests remain optional; offline fixture workflows should continue to pass.

## Notes

- Do not include cookies, tokens, private exports, downloaded media, or local database files in release assets.
- Releases before `v1.0.0` are alpha/prerelease builds unless explicitly promoted.

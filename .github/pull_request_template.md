## Summary

Describe the change and why it belongs in Link2Context.

## Verification

```powershell
python -m pip install -e ".[dev]" --dry-run
python -m pytest tests -q
```

## Scope check

- [ ] This keeps platform adapters read-only.
- [ ] This does not add platform bypass, posting, commenting, liking, or account actions.
- [ ] This does not commit cookies, tokens, private exports, downloaded media, or generated local stores.
- [ ] Fixture or documentation changes are included when behavior changes.

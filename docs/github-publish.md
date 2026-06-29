# GitHub Publishing

Use this when turning the local repository into a public GitHub project.

## Before Creating The Remote

Run the local release checks:

```powershell
python -m pip install -e ".[dev]" --dry-run
python -m compileall -q link2context tests
python -m pytest tests -q
python -m build
```

Confirm repository hygiene:

```powershell
git status --short --ignored
git log --oneline -1
```

Expected local state:

- The branch is `main`.
- Generated folders such as `dist/`, `outputs/`, `.pytest_cache/`, and `.secrets/` are ignored.
- No cookie, token, private export, downloaded media, or local SQLite database is staged.

## Create And Push

Create a new public GitHub repository named `Link2Context` or `link2context`.
Then connect this local repository:

```powershell
git remote add origin https://github.com/<owner>/<repo>.git
git push -u origin main
```

If using GitHub CLI:

```powershell
gh repo create <owner>/<repo> --public --source . --remote origin --push
```

Do not use `--public` until the hygiene checks above pass.

## After Push

- Confirm GitHub Actions CI runs on `main`.
- Confirm the README renders correctly.
- Confirm issue templates and the pull request template are visible.
- Add a short repository description: `Local-first link-to-context toolkit for AI agents.`
- Add topics such as `ai-agent`, `knowledge-graph`, `wechat`, `xiaohongshu`, `ocr`, and `asr`.

## First Release

After `main` is green, create a version tag:

```powershell
git tag -a v0.1.0 -m "Link2Context v0.1.0"
git push origin v0.1.0
```

The release workflow will run tests, build the package, create or update the GitHub release, and upload release assets. `v0.*` tags are treated as prereleases.

For future releases, run the `Release` workflow manually before pushing the tag when you want a remote build check without publishing assets.

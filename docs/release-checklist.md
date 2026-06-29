# Release Checklist

Use this checklist before publishing the repository or tagging a release.

## Local verification

```powershell
python -m pip install -e ".[dev]" --dry-run
python -m compileall -q link2context tests
python -m build
python -m pytest tests -q
python -m link2context --help
python -m link2context.store --help
```

## Version release

Tag policy:

- Use annotated SemVer tags with a leading `v`, such as `v0.1.1`.
- `v0.x.y` tags are alpha releases and the release workflow marks them as GitHub prereleases.
- `v1.0.0` and later tags are normal releases unless the workflow is changed deliberately.
- Do not move a published tag. Create a new patch tag instead.

Before tagging, update `CHANGELOG.md`, confirm `pyproject.toml` and `link2context.__version__` match, and use `.github/RELEASE_TEMPLATE.md` as the release note checklist.

To run a release dry-run from GitHub Actions, start the `Release` workflow manually. Manual runs build and test release assets without creating or updating a GitHub release.

For a normal tag release:

```powershell
git tag -a v0.1.1 -m "Link2Context v0.1.1"
git push origin v0.1.1
```

For tag pushes, the `Release` GitHub Actions workflow builds the package, runs tests, creates the GitHub release if needed, marks `v0.*` tags as prereleases, and uploads `dist/*` assets.

## Repository hygiene

- Confirm `git status --short --ignored` shows generated outputs as ignored.
- Confirm no cookies, tokens, private exports, or downloaded media are staged.
- Confirm `README.md`, `CHANGELOG.md`, `LICENSE`, `CONTRIBUTING.md`, and `SECURITY.md` are present.
- Confirm `.github/workflows/ci.yml` runs the same test command as local verification.
- Confirm `.github/workflows/release.yml` builds release assets for version tags.
- Confirm `.github/RELEASE_TEMPLATE.md` reflects the expected verification commands.
- Confirm `.github/dependabot.yml` tracks GitHub Actions and pip metadata updates.
- Confirm `.github/pull_request_template.md` and issue templates are present.
- Confirm `CODE_OF_CONDUCT.md` is present.
- Confirm `pyproject.toml` version matches `link2context.__version__`; this is covered by tests.
- Confirm local Markdown links resolve; this is covered by tests.
- Confirm README offline examples still write `context.json` and `context.md`; this is covered by tests.
- Confirm the quickstart offline context -> store -> query -> handoff workflow still runs; this is covered by tests.
- Confirm wheel and sdist build successfully with `python -m build`.
- Confirm the sdist includes public docs/examples and excludes local generated artifacts.

## Scope check

- The project is positioned as an open-source CLI / Python library, not a hosted SaaS product.
- Platform adapters remain read-only.
- OCR/ASR execution remains explicit and reviewable before `--execute`.
- Live platform behavior is covered by docs; tests should prefer offline fixtures.

## GitHub publish check

- Confirm the current branch is `main`.
- Confirm the target remote URL points to the intended GitHub repository.
- Push only after the repository hygiene checks pass.
- After pushing, confirm GitHub Actions CI runs on `main`.

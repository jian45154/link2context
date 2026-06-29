# Security Policy

Link2Context is local-first and read-only by design. It may use cookies or custom headers supplied by the operator for personal scraping sessions, but those secrets must stay outside the repository.

## Supported versions

The current `main` branch is the only supported development line until the project starts cutting releases.

## Reporting a vulnerability

Open a GitHub security advisory or contact the maintainer privately if a report includes:

- Cookie, token, or credential exposure.
- Accidental inclusion of private exports or downloaded media.
- Command execution behavior that can run untrusted input without explicit operator review.
- Platform adapter behavior that writes, posts, comments, likes, or bypasses access controls.

For ordinary parser bugs, extraction regressions, and fixture issues, use a normal GitHub issue.

## Secret handling

- Store cookies and request headers under `.secrets/` or another ignored local path.
- Do not paste cookies or tokens into issues, test fixtures, logs, or examples.
- Do not commit `data/`, `outputs/`, `work/`, `graphify-out/`, or `*.egg-info/`.
- Review generated `auto-queue` commands before running them with `--execute`.

## Platform boundaries

Contributions must keep platform adapters read-only. Link2Context should not add automated posting, commenting, liking, account actions, or access-control bypass logic.

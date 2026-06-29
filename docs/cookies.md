# Cookie Usage

Link2Context can attach an operator-supplied Cookie header when fetching live URLs. Use this only for accounts, sessions, and content you are allowed to access.

## When To Use A Cookie

Use `--cookie-file` when a public request only returns a login page, shell page, or incomplete content:

```powershell
python -m link2context "https://www.xiaohongshu.com/explore/..." --platform xiaohongshu --cookie-file .secrets\xiaohongshu.cookie --out outputs\xhs-sample
```

For batch retries:

```powershell
python -m link2context --retry-failed outputs\batch --cookie-file .secrets\xiaohongshu.cookie --out outputs\retry
```

## Create A Local Cookie File

Create an ignored local cookie file:

```powershell
python scripts\init_cookie_file.py --platform xiaohongshu
```

Then paste the raw Cookie header value into:

```text
.secrets\xiaohongshu.cookie
```

The file should contain only the header value, for example:

```text
a=1; b=2; c=3
```

You can also initialize it from an environment variable:

```powershell
$env:LINK2CONTEXT_COOKIE="a=1; b=2; c=3"
python scripts\init_cookie_file.py --platform xiaohongshu --from-env LINK2CONTEXT_COOKIE
```

## Manual Browser Copy

1. Open the target site in your browser and sign in normally.
2. Open developer tools and inspect a normal page request for that site.
3. Copy only the `Cookie` request header value.
4. Paste it into `.secrets\xiaohongshu.cookie`.
5. Run Link2Context with `--cookie-file`.

Do not commit cookie files, tokens, exported private content, local databases, or generated output. The repository `.gitignore` already excludes `.secrets/`, `data/`, and `outputs/`.

## Expiration And Refresh

Cookies can expire or be invalidated by the platform. Common causes include browser session expiry, explicit logout, password changes, account security checks, risk-control events, or platform-side session rotation.

Sometimes the cookie file still exists but one required session field is no longer valid. In that case live fetching may return a login page, shell page, very short output, or batch errors mentioning login or session requirements.

Link2Context does not refresh cookies, automate login, or keep a browser session alive. When a cookie stops working, copy a fresh `Cookie` request header from your browser, replace the contents of `.secrets\xiaohongshu.cookie`, and rerun the failed URLs with `--cookie-file`.

## Safety Notes

- Prefer `--cookie-file` over `--cookie` so the value is not stored in shell history.
- Rotate or delete the local cookie file when you are done.
- Link2Context uses the cookie only as a request header.
- Cookies are not written to `context.json`, `context.md`, batch manifests, or the SQLite store.
- This project does not automate login, bypass platform controls, or collect comments, likes, or posting actions.

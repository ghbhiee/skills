---
name: fileshare
description: Create temporary, login-free public links for local files, folders, Markdown, and HTML by uploading them to the user's self-hosted fileshare server. Use for any request to share a file, generate a temporary public link, host a Markdown page, or host an HTML/web app. Credentials live in scripts/config.json — never print or paste the token.
---

# Fileshare

Fileshare uploads local content to a self-hosted server and returns a clean, login-free public link.

- Uploads are authenticated with a token from `scripts/config.json`.
- View/download links need no login.
- Links look like `https://<host>/s/<token>`.
- Links expire after 7 days by default.
- Markdown renders as a styled web page.
- HTML files and folders with `index.html` run as web pages.

## Configuration

Credentials come from a JSON config file — **not** from environment variables.

Lookup order:

1. `scripts/config.json` (next to the scripts)
2. `~/.fileshare/config.json` (survives skill re-installs)

Create it from the template:

```bash
cp ~/.claude/skills/fileshare/scripts/config.example.json ~/.claude/skills/fileshare/scripts/config.json
```

```json
{
  "host": "https://fileshare.example.com",
  "token": "REPLACE_WITH_YOUR_FILESHARE_TOKEN",
  "ttl_days": 7
}
```

| Key | Required | Meaning |
|-----|----------|---------|
| `host` | yes | Base URL of your own fileshare server. The template value is a placeholder — the scripts refuse to run until you replace it. |
| `token` | yes | Admin upload token. Same value as `/opt/fileshare/token` on the server. |
| `ttl_days` | no | Default link lifetime. Server default is 7, max 90. |

`config.json` is gitignored. Never print it, paste it into chat, or commit it.

## Runtime Choice

Use the script that matches the current shell:

- Windows PowerShell: `scripts/share.ps1`
- Linux, macOS, WSL, Git Bash, MSYS: `scripts/share.sh`

## Windows Usage

```powershell
$s = "$env:USERPROFILE\.claude\skills\fileshare\scripts\share.ps1"
powershell -ExecutionPolicy Bypass -File $s C:\path\to\file.pdf
powershell -ExecutionPolicy Bypass -File $s C:\path\to\notes.md
powershell -ExecutionPolicy Bypass -File $s C:\path\to\app.html
powershell -ExecutionPolicy Bypass -File $s -Web C:\path\to\webapp
powershell -ExecutionPolicy Bypass -File $s -File C:\path\to\page.html
powershell -ExecutionPolicy Bypass -File $s -TtlDays 30 C:\path\to\file.pdf
powershell -ExecutionPolicy Bypass -File $s -List
powershell -ExecutionPolicy Bypass -File $s -Delete <share-token>
```

## Linux, macOS, WSL Usage

```bash
s=~/.claude/skills/fileshare/scripts/share.sh
bash $s /path/to/report.pdf
bash $s /path/to/notes.md
bash $s /path/to/app.html
bash $s /path/to/webapp/
bash $s --web /path/to/bundle.zip
bash $s --file /path/to/page.html
bash $s --ttl 30 /path/to/report.pdf
bash $s --list
bash $s --delete <share-token>
```

## Mode Selection

| Input | Default mode | Result |
|-------|--------------|--------|
| any regular file | `file` | inline for images/PDF/text, otherwise download with its real (e.g. Chinese) filename |
| `.md` / `.markdown` | `file` | rendered as a web page; `?raw=1` shows the source |
| `.html` / `.htm` | `web` | runs in the browser |
| directory | `web` | zipped and served; **must** contain `index.html` at the top level |
| `.zip` | `file` | plain download; pass `--web` / `-Web` to serve it as a site |

## Reporting Back

Give the user the returned URL plus the expiry line. Do not echo the config file, the token, or the `X-Token` header.

## Security

- Shared links are public until they expire.
- Only upload content intended for link holders to see.
- Shared HTML runs JavaScript on the fileshare origin, so upload only trusted pages.
- There is no public share-list endpoint; `--list` requires the admin token.

## Server

The backend that serves these links lives in [`server/`](server/) — Python stdlib HTTP service behind nginx, with systemd unit, cron cleanup, and a deploy script. See [`server/README.md`](server/README.md).

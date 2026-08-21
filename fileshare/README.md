# fileshare

Temporary, login-free public links for local files, folders, Markdown and HTML.

This project is two halves:

| Half | Where | What |
|------|-------|------|
| **Skill** (the point) | [`SKILL.md`](SKILL.md), [`scripts/`](scripts/) | What the agent reads and runs to publish a link |
| **Server** | [`server/`](server/) | The self-hosted backend those links point at — code, deploy scripts, tests, runbook |

You only need the server half if you are standing up your own instance. To just *use* fileshare, install the skill and fill in `scripts/config.json`.

## Install the skill

Hand one of these to your coding agent — **A** keeps the secret out of the conversation,
**B** trades that for one less round trip:

**A — install, fill in the config yourself:**

> Install the fileshare skill from https://github.com/ghbhiee/skills — copy the `fileshare/`
> directory into my agent skills folders, create `scripts/config.json` from the example, and
> tell me where to put my server host and admin token.

**B — values inline** (replace the placeholders; this puts the token in your transcript):

> Install the fileshare skill from https://github.com/ghbhiee/skills — copy the `fileshare/`
> directory into my agent skills folders. My server is `<https://files.example.com>` and the
> admin token is `<FILESHARE_ADMIN_TOKEN>`. Write both into `scripts/config.json`, verify the
> skill loads, and don't echo the token back to me.

Or do it by hand:

```bash
git clone https://github.com/ghbhiee/skills.git /tmp/skills
mkdir -p ~/.claude/skills
cp -r /tmp/skills/fileshare ~/.claude/skills/fileshare
cp ~/.claude/skills/fileshare/scripts/config.example.json ~/.claude/skills/fileshare/scripts/config.json
# then edit config.json and paste your token
```

## How it works

```
share.sh / share.ps1
   │  PUT /upload      (single file)        X-Token: <admin token>
   │  PUT /upload-web  (zip or .html)
   ▼
nginx (443, TLS)  ──proxy──►  server.py (127.0.0.1:8787)
   ▲                              │  writes DATA/<token>/{payload,.meta.json,.expires}
   │  X-Accel-Redirect            ▼
   └──────────────────────  returns {url, kind, name, size, expires}

GET /s/<token>  ──►  server.py decides file vs web vs rendered markdown
                     └─► X-Accel-Redirect /_filedata/<token>/...  (nginx serves the bytes)
```

- Share tokens are 24 hex chars from `secrets.token_hex(12)`.
- Expiry is a `.expires` epoch file per share; hourly cron removes dead shares, and a request to an expired share deletes it and returns `410`.
- Uploads stream to disk (`proxy_request_buffering off`), so large files do not sit in memory.

## API

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| `PUT`/`POST` | `/upload?name=<fn>[&ttl=<days>]` | `X-Token` | body is the raw file |
| `PUT`/`POST` | `/upload-web?name=<fn>[&ttl=<days>]` | `X-Token` | body is a zip (needs root `index.html`) or a single `.html` |
| `GET` | `/s/<token>[/<sub>]` | none | the public link |
| `GET` | `/api/list` | `X-Token` | live shares |
| `DELETE` | `/api/share/<token>` | `X-Token` | remove one share |
| `GET` | `/healthz` | none | liveness |
| `GET` | `/install/<file>` | none | permanent public install assets |

## Security model

- One shared admin token gates every write. There is no per-user auth, and no public listing.
- Read access is capability-based: whoever has the link can read it until it expires.
- Uploaded HTML executes on the fileshare origin. Since all shares share that origin, one malicious upload can script against another share's DOM only if a user visits it — treat upload rights as trusted.
- Path traversal is blocked on serve (`normpath` containment check) and on unzip (zip-slip guard).

## Working on the server

```bash
cd server
python3 -m unittest discover -s tests -v   # 31 stdlib-only integration tests
deploy/deploy.sh <ssh-host>                        # push to the live host
```

See [`server/README.md`](server/README.md) for the layout and [`server/docs/OPERATIONS.md`](server/docs/OPERATIONS.md) for the runbook.

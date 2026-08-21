# fileshare server

Self-hosted backend for the [fileshare skill](../SKILL.md). Python 3 standard library only (plus `python3-markdown` for Markdown rendering), fronted by nginx.

Reference deployment: Debian 12, Python 3.11, nginx 1.22, host `fileshare.example.com`.

## Layout

```
server/
├── src/server.py          the HTTP backend — listens on 127.0.0.1:8787
├── deploy/
│   ├── deploy.sh          run locally; pushes everything below over SSH
│   ├── cleanup.sh         → /opt/fileshare/cleanup.sh   expiry sweep
│   ├── fileshare.service  → /etc/systemd/system/        runs as www-data
│   ├── fileshare.cron     → /etc/cron.d/fileshare       hourly sweep + daily nginx reload
│   └── nginx.conf         → /etc/nginx/sites-available/fileshare
├── tests/test_server.py   integration tests against a real server process
└── docs/OPERATIONS.md     runbook
```

Created on the server, never in this repo:

| Path | What |
|------|------|
| `/opt/fileshare/token` | admin token, `0600 www-data`, generated on first deploy |
| `/var/www/fileshare/data/<share>/` | payload + `.meta.json` + `.expires` |
| `/var/www/fileshare/static/` | permanent public assets served at `/install/` |
| `/home/certs/<host>.cer` / `.key` | TLS cert, managed by acme.sh |

## Deploy

```bash
deploy/deploy.sh <ssh-host>                  # update an existing install
deploy/deploy.sh <ssh-host> fileshare.example.com   # first install / change the public base URL
```

Idempotent: it keeps an existing admin token, never touches `data/`, syntax-checks the sources before upload, and aborts the nginx reload if `nginx -t` fails.

After a first install, read the generated token over SSH and paste it into `fileshare/scripts/config.json` on the client side — not into chat:

```bash
ssh <ssh-host> cat /opt/fileshare/token
```

TLS is out of scope for the deploy script; the vhost expects an acme.sh cert already in `/home/certs/`, with the HTTP-01 webroot at `/var/www/acme`.

## Test

Stdlib only, no pytest. Boots `src/server.py` as a subprocess against a temp data dir and drives the real HTTP API — uploads, serving, redirects, expiry, the admin API, and the zip-slip and path-traversal guards.

```bash
cd fileshare/server && python3 -m unittest discover -s tests -v
```

nginx is not in the loop, so responses that would normally be handed off to it are asserted on the `X-Accel-Redirect` header rather than on a body. `TestCleanupScript` needs a working `bash` and skips itself if there is none.

## Configuration

All backend config is systemd `Environment=` in `deploy/fileshare.service`:

| Variable | Default | Meaning |
|----------|---------|---------|
| `FILESHARE_DATA` | `/var/www/fileshare/data` | share storage root |
| `FILESHARE_TOKEN_FILE` | `/opt/fileshare/token` | admin token file |
| `FILESHARE_BASE` | `https://fileshare.example.com` | public base URL used to build returned links |
| `FILESHARE_TTL_DAYS` | `7` | default link lifetime |
| `FILESHARE_MAX_TTL_DAYS` | `90` | ceiling for the per-upload `?ttl=` override |
| `FILESHARE_LISTEN` | `127.0.0.1` | bind address — keep it loopback, nginx is the only front door |
| `FILESHARE_PORT` | `8787` | backend port |
| `FILESHARE_MAX_BYTES` | `5368709120` (5 GiB) | per-upload size cap |

The API itself is documented in the [project README](../README.md#api).

## Design notes

- **Clean links.** `/s/<token>` is routed through the backend rather than served statically, so the backend can decide file-vs-web, render Markdown, set the real (UTF-8) download filename, and enforce expiry. It then hands off to nginx via `X-Accel-Redirect` so Python never streams the bytes.
- **Web apps.** A directory is zipped client-side; the backend rejects a zip without a root `index.html` and flattens a single wrapping top-level directory. A bare `.html` becomes `index.html`.
- **Expiry is enforced twice** — lazily on access (delete + `410`) and by the hourly cron sweep — so a stopped cron cannot leak expired content.
- **Uploads stream.** `proxy_request_buffering off` in nginx plus a fixed-length read loop in `_read_body_to`, with `Content-Length` required and checked against `FILESHARE_MAX_BYTES`.
- **Failed uploads clean up after themselves.** Every error path removes the half-written share directory, so a rejected zip leaves no orphan.

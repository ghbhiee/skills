# Operations runbook

Everything below assumes an SSH alias for the server, e.g. `ssh <ssh-host>`.

## Health

```bash
systemctl status fileshare
journalctl -u fileshare -n 50           # per-request logging is suppressed; expect only lifecycle lines
curl -fsS https://fileshare.example.com/healthz
```

## Inspect shares

```bash
curl -fsS -H "X-Token: $(cat /opt/fileshare/token)" http://127.0.0.1:8787/api/list | python3 -m json.tool
du -sh /var/www/fileshare/data          # disk used by live shares
ls -1 /var/www/fileshare/data | wc -l   # share count
```

From a client with the skill installed:

```bash
bash ~/.claude/skills/fileshare/scripts/share.sh --list
bash ~/.claude/skills/fileshare/scripts/share.sh --delete <share-token>
```

## Expiry

Shares expire twice over: lazily when someone requests an expired link (the directory is deleted and the request gets `410`), and by the hourly cron sweep.

```bash
/opt/fileshare/cleanup.sh               # force a sweep now
grep fileshare /etc/cron.d/fileshare    # confirm the schedule is installed
```

A share directory carries a `.expires` file holding an epoch timestamp. Directories missing that marker are removed once older than `FILESHARE_TTL_DAYS`.

To extend one share by hand:

```bash
echo $(( $(date +%s) + 30*86400 )) > /var/www/fileshare/data/<share-token>/.expires
```

## Rotate the admin token

```bash
ssh <ssh-host> 'python3 -c "import secrets;print(secrets.token_urlsafe(36))" > /opt/fileshare/token \
        && chown www-data:www-data /opt/fileshare/token && chmod 600 /opt/fileshare/token \
        && systemctl restart fileshare'
```

Then update `token` in every client's `scripts/config.json`. Existing share links keep working — they are not derived from the admin token.

## Deploy and roll back

```bash
deploy/deploy.sh <ssh-host>
```

Keep a copy before a risky change, and roll back by restoring it:

```bash
ssh <ssh-host> 'cp -a /opt/fileshare/server.py /opt/fileshare/server.py.bak'
ssh <ssh-host> 'cp -a /opt/fileshare/server.py.bak /opt/fileshare/server.py && systemctl restart fileshare'
```

`data/` is never touched by a deploy, so a rollback loses no shares.

## TLS

Certificates come from acme.sh (HTTP-01, webroot `/var/www/acme`) and land in `/home/certs/<host>.cer` / `.key`. The `/etc/cron.d/fileshare` entry reloads nginx daily so a renewed cert is picked up without manual work.

```bash
"/root/.acme.sh"/acme.sh --list
nginx -t && systemctl reload nginx
echo | openssl s_client -connect fileshare.example.com:443 2>/dev/null | openssl x509 -noout -dates
```

## Troubleshooting

| Symptom | Likely cause | Check |
|---------|--------------|-------|
| every upload returns `401` | client config holds a stale token | compare `scripts/config.json` against `/opt/fileshare/token` |
| link returns `404` right after upload | the share expired, or `FILESHARE_DATA` differs between the unit and cron | `ls /var/www/fileshare/data/<share-token>` |
| link returns `410` | expired as designed | re-upload |
| Markdown shows as a `<pre>` block | `python3-markdown` missing | `python3 -c 'import markdown'` |
| download starts instead of rendering | MIME type not in the inline allowlist | check `_INLINE_PREFIX` / `_INLINE_EXACT` in `src/server.py` |
| web app loads but assets 404 | zip had no root `index.html`, or asset paths are absolute | unzip and inspect the share directory |
| `502` from nginx | backend down | `systemctl status fileshare`, `journalctl -u fileshare -n 50` |
| large upload fails partway | hit `FILESHARE_MAX_BYTES`, or a proxy timeout | backend returns `file too large`; otherwise raise `proxy_read_timeout` |
| disk filling up | cron sweep not running | `/opt/fileshare/cleanup.sh` by hand, then check `/etc/cron.d/fileshare` |

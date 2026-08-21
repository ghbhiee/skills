#!/usr/bin/env bash
# Deploy / update the fileshare backend on a Debian-family host over SSH.
#
#   deploy/deploy.sh <ssh-host> [public-hostname]
#
#   deploy/deploy.sh <ssh-host>                    # update code on an existing install
#   deploy/deploy.sh <ssh-host> fileshare.example.com     # first install, or change public base URL
#
# Idempotent: safe to re-run. It never overwrites an existing admin token and
# never touches /var/www/fileshare/data.
#
# TLS certificates are NOT provisioned here — the nginx site expects
# /home/certs/<hostname>.cer + .key (acme.sh webroot mode, /var/www/acme).
set -euo pipefail

SSH_HOST="${1:?usage: deploy.sh <ssh-host> [public-hostname]}"
PUBLIC_HOST="${2:-}"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"

echo "==> uploading source to $SSH_HOST"
scp -q "$ROOT/src/server.py" "$SSH_HOST:/tmp/server.py"
scp -q "$DEPLOY_DIR/cleanup.sh" "$SSH_HOST:/tmp/cleanup.sh"
scp -q "$DEPLOY_DIR/fileshare.service" "$SSH_HOST:/tmp/fileshare.service"
scp -q "$DEPLOY_DIR/fileshare.cron" "$SSH_HOST:/tmp/fileshare.cron"
scp -q "$DEPLOY_DIR/nginx.conf" "$SSH_HOST:/tmp/nginx-fileshare.conf"

echo "==> installing on $SSH_HOST"
ssh "$SSH_HOST" PUBLIC_HOST="$PUBLIC_HOST" bash -s <<'REMOTE'
set -euo pipefail

# syntax-check with the target's own interpreters before touching anything live
python3 -m py_compile /tmp/server.py
rm -rf /tmp/__pycache__
bash -n /tmp/cleanup.sh

install -d -m 755 /opt/fileshare
install -d -o www-data -g www-data -m 755 /var/www/fileshare/data
install -d -m 755 /var/www/fileshare/static
install -d -m 755 /var/www/acme

# python-markdown renders shared .md files; without it they fall back to <pre>
if ! python3 -c 'import markdown' 2>/dev/null; then
  echo "  installing python3-markdown"
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-markdown
fi

install -m 755 /tmp/server.py  /opt/fileshare/server.py
install -m 755 /tmp/cleanup.sh /opt/fileshare/cleanup.sh

# admin token: generate once, never rotate silently
if [ ! -s /opt/fileshare/token ]; then
  umask 077
  python3 -c 'import secrets;print(secrets.token_urlsafe(36))' > /opt/fileshare/token
  chown www-data:www-data /opt/fileshare/token
  chmod 600 /opt/fileshare/token
  echo "  NEW admin token written to /opt/fileshare/token (read it over SSH, do not paste it around)"
else
  echo "  keeping existing /opt/fileshare/token"
fi

install -m 644 /tmp/fileshare.service /etc/systemd/system/fileshare.service
install -m 644 /tmp/fileshare.cron     /etc/cron.d/fileshare

if [ -n "${PUBLIC_HOST:-}" ]; then
  sed -i "s#Environment=FILESHARE_BASE=.*#Environment=FILESHARE_BASE=https://${PUBLIC_HOST}#" \
    /etc/systemd/system/fileshare.service
  sed -e "s/fileshare\.example\.com/${PUBLIC_HOST}/g" /tmp/nginx-fileshare.conf > /etc/nginx/sites-available/fileshare
else
  install -m 644 /tmp/nginx-fileshare.conf /etc/nginx/sites-available/fileshare
fi
ln -sfn /etc/nginx/sites-available/fileshare /etc/nginx/sites-enabled/fileshare

systemctl daemon-reload
systemctl enable --now fileshare.service
systemctl restart fileshare.service

if nginx -t; then
  systemctl reload nginx
else
  echo "  !! nginx config test failed — backend restarted, nginx left untouched" >&2
  exit 1
fi

rm -f /tmp/server.py /tmp/cleanup.sh /tmp/fileshare.service /tmp/fileshare.cron /tmp/nginx-fileshare.conf

sleep 1
echo "==> health: $(curl -fsS http://127.0.0.1:8787/healthz || echo FAILED)"
systemctl --no-pager --lines=0 status fileshare.service | head -4
REMOTE

echo "==> done"
echo "    read the admin token with:  ssh $SSH_HOST cat /opt/fileshare/token"
echo "    put it in fileshare/scripts/config.json on the client side"

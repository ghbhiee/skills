#!/usr/bin/env bash
# Share local file(s) or a web app through the fileshare service.
# Prints a clean, login-free public link.
#
#   share.sh <file>                 single file  -> https://<host>/s/<token>
#   share.sh <file.md>              markdown, rendered as a web page
#   share.sh <file.html>            self-contained page -> renders in browser
#   share.sh <dir>/                 multi-file web app (needs index.html)
#   share.sh --web <dir|zip|html>   force "web app" (rendered/served)
#   share.sh --file <anything>      force single-file download
#   share.sh --ttl <days> <path>    override link lifetime for this upload
#   share.sh --list                 list live shares (admin)
#   share.sh --delete <token>       delete one share (admin)
#
# Credentials come from a config file, never from the environment:
#   1. <this dir>/config.json          (created from config.example.json)
#   2. ~/.fileshare/config.json        (survives skill re-installs)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python_bin() {
  if command -v python3 >/dev/null 2>&1; then echo python3
  elif command -v python >/dev/null 2>&1; then echo python
  else return 1
  fi
}
PYTHON="$(python_bin || true)"
[ -z "$PYTHON" ] && { echo "ERROR: python3/python is required." >&2; exit 1; }

CONFIG_PATHS=("$SCRIPT_DIR/config.json" "$HOME/.fileshare/config.json")
CONFIG=""
for c in "${CONFIG_PATHS[@]}"; do
  [ -f "$c" ] && { CONFIG="$c"; break; }
done
if [ -z "$CONFIG" ]; then
  cat >&2 <<MSG
ERROR: no fileshare config found. Looked in:
  ${CONFIG_PATHS[0]}
  ${CONFIG_PATHS[1]}
Create one:
  cp "$SCRIPT_DIR/config.example.json" "$SCRIPT_DIR/config.json"
then put your token in it. Never paste the token into chat or commit it.
MSG
  exit 1
fi

read_config() {  # read_config <key> <default>
  "$PYTHON" - "$CONFIG" "$1" "$2" <<'PY'
import json, sys
path, key, default = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
except Exception as e:
    print(f"ERROR: cannot parse {path}: {e}", file=sys.stderr)
    sys.exit(1)
value = cfg.get(key)
if value is None or (isinstance(value, str) and not value.strip()):
    value = default
print(value)
PY
}

HOST="$(read_config host '')"
HOST="${HOST%/}"
case "$HOST" in
  ""|https://fileshare.example.com)
    echo "ERROR: set \"host\" in $CONFIG to your own fileshare server." >&2; exit 1 ;;
esac
TOKEN="$(read_config token '')"
CFG_TTL="$(read_config ttl_days '')"
case "$TOKEN" in
  ""|REPLACE_WITH_YOUR_FILESHARE_TOKEN)
    echo "ERROR: set \"token\" in $CONFIG (it is still the placeholder)." >&2; exit 1 ;;
esac

TTL="$CFG_TTL"
FORCE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --web)    FORCE=web;  shift ;;
    --file)   FORCE=file; shift ;;
    --ttl)    TTL="${2:?--ttl needs a number of days}"; shift 2 ;;
    --list)   curl -fsS -H "X-Token: $TOKEN" "$HOST/api/list" | "$PYTHON" -m json.tool; exit $? ;;
    --delete) tok="${2:?--delete needs a share token}"
              curl -fsS -X DELETE -H "X-Token: $TOKEN" "$HOST/api/share/$tok" | "$PYTHON" -m json.tool
              exit $? ;;
    --) shift; break ;;
    -*) echo "unknown option: $1" >&2; exit 1 ;;
    *) break ;;
  esac
done
[ $# -lt 1 ] && { echo "usage: share.sh [--web|--file] [--ttl <days>] <file|dir> [more...]" >&2; exit 1; }

QS_TTL=""
[ -n "$TTL" ] && QS_TTL="&ttl=$TTL"

urlencode() { "$PYTHON" -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$1"; }

zip_dir() {
  local src="$1" out="$2"
  "$PYTHON" - "$src" "$out" <<'PY'
from pathlib import Path
import sys, zipfile
src = Path(sys.argv[1])
out = Path(sys.argv[2])
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in src.rglob("*"):
        if any(part.startswith(".") for part in p.relative_to(src).parts):
            continue
        z.write(p, p.relative_to(src))
PY
}

show() { "$PYTHON" - "$1" <<'PY'
import json,sys
try: d=json.loads(sys.argv[1])
except Exception: print("unexpected response:",sys.argv[1],file=sys.stderr); sys.exit(1)
if not d.get("ok"): print("failed:",d.get("error","?"),file=sys.stderr); sys.exit(1)
mb=d.get("size",0)/1048576
print(d["url"])
print(f"  {d.get('kind')}: {d.get('name')}  {mb:.1f} MB  expires {d.get('expires','')} ({d.get('ttl_days')}d)")
PY
}

upload() {  # upload <path> <endpoint> <display-name>
  curl -fsS -T "$1" -H "X-Token: $TOKEN" "$HOST/$2?name=$(urlencode "$3")$QS_TTL"
}

rc=0
for f in "$@"; do
  [ -e "$f" ] || { echo "skip (no such path): $f" >&2; rc=1; continue; }
  mode="$FORCE"
  if [ -z "$mode" ]; then
    if [ -d "$f" ]; then mode=web
    elif [[ "$f" == *.html || "$f" == *.htm ]]; then mode=web
    else mode=file; fi
  fi

  base="$(basename "${f%/}")"
  if [ "$mode" = web ] && [ -d "$f" ]; then
    [ -f "$f/index.html" ] || { echo "skip (web app dir needs index.html): $f" >&2; rc=1; continue; }
    tmp="$(mktemp -u).zip"
    zip_dir "$f" "$tmp"
    resp="$(upload "$tmp" upload-web "$base")" || { echo "ERROR uploading: $f" >&2; rm -f "$tmp"; rc=1; continue; }
    rm -f "$tmp"
  elif [ "$mode" = web ]; then
    resp="$(upload "$f" upload-web "$base")" || { echo "ERROR uploading: $f" >&2; rc=1; continue; }
  else
    resp="$(upload "$f" upload "$base")" || { echo "ERROR uploading: $f" >&2; rc=1; continue; }
  fi
  show "$resp" || rc=1
done
exit $rc

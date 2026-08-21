#!/usr/bin/env bash
# Delete expired shares. A share dir holds a .expires file with an epoch ts;
# if it's in the past, the whole dir is removed. Dirs without the marker are
# removed once older than the TTL as a fallback.
set -euo pipefail
DATA="${FILESHARE_DATA:-/var/www/fileshare/data}"
TTL_DAYS="${FILESHARE_TTL_DAYS:-7}"
now="$(date +%s)"
[ -d "$DATA" ] || exit 0
for d in "$DATA"/*/; do
  [ -d "$d" ] || continue
  exp_f="${d}.expires"
  if [ -f "$exp_f" ]; then
    exp="$(cat "$exp_f" 2>/dev/null || echo 0)"
    case "$exp" in (*[!0-9]*|"") exp=0 ;; esac
    if [ "$exp" -lt "$now" ]; then rm -rf "$d"; fi
  else
    if [ -n "$(find "$d" -maxdepth 0 -mtime "+${TTL_DAYS}" 2>/dev/null)" ]; then rm -rf "$d"; fi
  fi
done

#!/usr/bin/env python3
"""Fileshare backend.

Routes all share requests so links can be clean token-only URLs and so single
self-contained .html uploads render as web apps (Claude-artifact style), while
nginx still serves the actual bytes via X-Accel-Redirect.

Layout on disk:  DATA_DIR/<token>/
    <realfile>            (kind=file)   or   index.html + assets (kind=web)
    .meta.json           {"kind": "file"|"web", "name": "<real name>"}
    .expires             epoch seconds

Endpoints:
  POST|PUT /upload?name=<fn>[&ttl=<days>]      X-Token  body=file     -> {url, ...}
  POST|PUT /upload-web?name=<fn>[&ttl=<days>]  X-Token  body=zip|html -> {url, ...}
  GET      /s/<token>[/<sub>]                            -> the file/app  (public, no auth)
  GET      /api/list             X-Token                -> live shares
  DELETE   /api/share/<token>    X-Token                -> delete
  GET      /healthz
"""
from __future__ import annotations

import html
import json
import mimetypes
import os
import re
import secrets
import shutil
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import markdown as _markdown
except Exception:  # pragma: no cover
    _markdown = None

DATA_DIR = os.environ.get("FILESHARE_DATA", "/var/www/fileshare/data")
TOKEN_FILE = os.environ.get("FILESHARE_TOKEN_FILE", "/opt/fileshare/token")
PUBLIC_BASE = os.environ.get("FILESHARE_BASE", "https://fileshare.example.com").rstrip("/")
TTL_DAYS = int(os.environ.get("FILESHARE_TTL_DAYS", "7"))
MAX_TTL_DAYS = int(os.environ.get("FILESHARE_MAX_TTL_DAYS", "90"))
LISTEN_HOST = os.environ.get("FILESHARE_LISTEN", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("FILESHARE_PORT", "8787"))
MAX_BYTES = int(os.environ.get("FILESHARE_MAX_BYTES", str(5 * 1024 ** 3)))  # 5 GiB
INTERNAL = "/_filedata"  # nginx internal location aliased to DATA_DIR

with open(TOKEN_FILE, encoding="utf-8") as _f:
    ADMIN_TOKEN = _f.read().strip()

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-() 一-鿿]+")
# types shown inline in the browser instead of being downloaded
_INLINE_PREFIX = ("image/", "video/", "audio/", "text/")
_INLINE_EXACT = {"application/pdf", "text/html", "application/json", "image/svg+xml"}

MD_TEMPLATE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:#1f2328;font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
.md{max-width:820px;margin:0 auto;padding:2.4rem 1.2rem 5rem;word-wrap:break-word}
.md h1,.md h2{border-bottom:1px solid #d8dee4;padding-bottom:.3em;margin-top:1.6em}
.md h1{font-size:2em}.md h2{font-size:1.5em}.md h3{font-size:1.25em}
.md a{color:#0969da;text-decoration:none}.md a:hover{text-decoration:underline}
.md code{background:rgba(129,139,152,.18);padding:.2em .4em;border-radius:6px;font:.88em ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.md pre{background:#f6f8fa;padding:1rem;border-radius:8px;overflow:auto}
.md pre code{background:none;padding:0;font-size:.85em}
.md blockquote{margin:0;padding:0 1em;color:#59636e;border-left:.25em solid #d0d7de}
.md table{border-collapse:collapse;display:block;overflow:auto;width:max-content;max-width:100%}
.md th,.md td{border:1px solid #d0d7de;padding:.5em .9em}
.md tr:nth-child(2n){background:#f6f8fa}
.md img{max-width:100%}
.md hr{height:1px;border:0;background:#d8dee4;margin:1.8em 0}
.foot{max-width:820px;margin:0 auto;padding:0 1.2rem 2rem;font-size:.8em;color:#8b949e}
.foot a{color:#8b949e}
@media (prefers-color-scheme:dark){
 body{background:#0d1117;color:#e6edf3}
 .md h1,.md h2{border-color:#21262d}
 .md a{color:#4493f8}.md pre{background:#161b22}
 .md blockquote{color:#9198a1;border-color:#3d444d}
 .md th,.md td{border-color:#3d444d}.md tr:nth-child(2n){background:#161b22}
 .md hr{background:#21262d}}
</style></head>
<body><article class="md">__BODY__</article>
<div class="foot">rendered markdown · <a href="?raw=1">view source</a></div>
</body></html>"""


def safe_filename(name: str | None) -> str:
    name = os.path.basename((name or "").strip()) or "file"
    name = _SAFE_NAME.sub("_", name).strip("._ ") or "file"
    return name[:200]


def parse_ttl(raw: str | None) -> int | None:
    """Optional ?ttl=<days> upload override, clamped to 1..MAX_TTL_DAYS."""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        days = int(str(raw).strip())
    except ValueError:
        raise ValueError("ttl must be an integer number of days")
    return max(1, min(days, MAX_TTL_DAYS))


def new_token() -> str:
    return secrets.token_hex(12)


def ctype_for(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def is_inline(ctype: str) -> bool:
    return ctype in _INLINE_EXACT or ctype.startswith(_INLINE_PREFIX)


def read_meta(d: str) -> dict:
    try:
        return json.load(open(os.path.join(d, ".meta.json"), encoding="utf-8"))
    except Exception:
        # backward-compat: infer from the single non-dot file in the dir
        files = [x for x in os.listdir(d) if not x.startswith(".")] if os.path.isdir(d) else []
        if "index.html" in files:
            return {"kind": "web", "name": "web app"}
        if len(files) == 1:
            return {"kind": "file", "name": files[0]}
        return {"kind": "file", "name": files[0] if files else "file"}


def expiry_of(d: str) -> int:
    try:
        return int(open(os.path.join(d, ".expires"), encoding="utf-8").read().strip())
    except Exception:
        return 0


class Handler(BaseHTTPRequestHandler):
    server_version = "fileshare/2.0"
    protocol_version = "HTTP/1.1"

    # --- low-level helpers --------------------------------------------
    def _send(self, code: int, headers: dict | None = None, body: bytes = b""):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code: int, obj: dict):
        self._send(code, {"Content-Type": "application/json; charset=utf-8"},
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _query(self) -> dict:
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def _authed(self) -> bool:
        tok = self.headers.get("X-Token") or self._query().get("token", [""])[0]
        return bool(tok) and secrets.compare_digest(tok, ADMIN_TOKEN)

    # --- HTTP verbs ---------------------------------------------------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.rstrip("/") in ("/healthz", "/api/healthz"):
            return self._json(200, {"ok": True})
        if path.rstrip("/") == "/api/list":
            return self._list()
        if path == "/s" or path == "/s/":
            return self._json(404, {"ok": False, "error": "not found"})
        if path.startswith("/s/"):
            return self._serve(path)
        return self._json(404, {"ok": False, "error": "not found"})

    def do_DELETE(self):
        if not self._authed():
            return self._json(401, {"ok": False, "error": "bad token"})
        m = re.match(r"^/api/share/([a-f0-9]{8,40})$", urllib.parse.urlparse(self.path).path)
        if not m:
            return self._json(404, {"ok": False, "error": "not found"})
        d = os.path.join(DATA_DIR, m.group(1))
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            return self._json(200, {"ok": True, "deleted": m.group(1)})
        return self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        self._upload(web=urllib.parse.urlparse(self.path).path.startswith("/upload-web"))

    def do_PUT(self):
        self._upload(web=urllib.parse.urlparse(self.path).path.startswith("/upload-web"))

    # --- listing (admin) ----------------------------------------------
    def _list(self):
        if not self._authed():
            return self._json(401, {"ok": False, "error": "bad token"})
        now = int(time.time())
        shares = []
        for tok in sorted(os.listdir(DATA_DIR) if os.path.isdir(DATA_DIR) else []):
            d = os.path.join(DATA_DIR, tok)
            if not os.path.isdir(d) or not re.fullmatch(r"[a-f0-9]{8,40}", tok):
                continue
            meta = read_meta(d)
            exp = expiry_of(d)
            size = 0
            for root, _dirs, files in os.walk(d):
                for f in files:
                    if f.startswith("."):
                        continue
                    try:
                        size += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            slash = "/" if meta.get("kind") == "web" else ""
            shares.append({
                "token": tok,
                "url": f"{PUBLIC_BASE}/s/{tok}{slash}",
                "kind": meta.get("kind", "file"),
                "name": meta.get("name", ""),
                "size": size,
                "expires_epoch": exp,
                "expires": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(exp)) if exp else "",
                "expired": bool(exp and exp < now),
            })
        shares.sort(key=lambda x: x["expires_epoch"], reverse=True)
        return self._json(200, {"ok": True, "count": len(shares), "shares": shares})

    # --- serving (public) ---------------------------------------------
    def _serve(self, path: str):
        rest = path[len("/s/"):]
        token, _, sub = rest.partition("/")
        if not re.fullmatch(r"[a-f0-9]{8,40}", token):
            return self._json(404, {"ok": False, "error": "not found"})
        d = os.path.join(DATA_DIR, token)
        if not os.path.isdir(d):
            return self._json(404, {"ok": False, "error": "not found or expired"})
        exp = expiry_of(d)
        if exp and time.time() > exp:
            shutil.rmtree(d, ignore_errors=True)
            return self._send(410, {"Content-Type": "text/plain; charset=utf-8"},
                              "This share has expired.\n".encode())
        meta = read_meta(d)
        sub = urllib.parse.unquote(sub)

        if meta.get("kind") == "web":
            # web app: index.html at the root needs a trailing slash so relative
            # asset URLs resolve correctly
            if sub == "" and not path.endswith("/"):
                return self._send(301, {"Location": f"/s/{token}/"})
            target = sub if sub else "index.html"
            return self._xaccel(token, d, target, force_inline=True)

        # single file: clean URL /s/<token> serves it directly
        name = meta.get("name") or read_meta(d).get("name")
        if name and name.lower().endswith((".md", ".markdown")) and "raw" not in self._query():
            return self._render_markdown(d, name)
        return self._xaccel(token, d, name, download_name=name)

    def _render_markdown(self, d, name):
        path = os.path.join(d, name)
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            return self._json(404, {"ok": False, "error": "not found"})
        if _markdown is not None:
            try:
                body = _markdown.markdown(
                    text, extensions=["extra", "sane_lists", "toc"], output_format="html5")
            except Exception:
                body = "<pre>" + html.escape(text) + "</pre>"
        else:
            body = "<pre>" + html.escape(text) + "</pre>"
        title = os.path.splitext(name)[0]
        page = MD_TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__BODY__", body)
        return self._send(200, {"Content-Type": "text/html; charset=utf-8"}, page.encode("utf-8"))

    def _xaccel(self, token, d, relpath, force_inline=False, download_name=None):
        # guard against path traversal
        relpath = relpath.lstrip("/")
        full = os.path.normpath(os.path.join(d, relpath))
        if not (full == d or full.startswith(d + os.sep)) or not os.path.isfile(full):
            return self._json(404, {"ok": False, "error": "not found"})
        ctype = ctype_for(full)
        disp = "inline" if (force_inline or is_inline(ctype)) else "attachment"
        headers = {"Content-Type": ctype}
        if download_name:
            enc = urllib.parse.quote(download_name)
            headers["Content-Disposition"] = f"{disp}; filename*=UTF-8''{enc}"
        # X-Accel-Redirect path must be URL-encoded; nginx decodes to find the file
        accel = INTERNAL + "/" + token + "/" + urllib.parse.quote(os.path.relpath(full, d))
        headers["X-Accel-Redirect"] = accel
        return self._send(200, headers)

    # --- upload (admin) -----------------------------------------------
    def _read_body_to(self, dest_path: str) -> int:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("missing/zero Content-Length")
        if length > MAX_BYTES:
            raise ValueError("file too large")
        written = 0
        with open(dest_path, "wb") as out:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(262144, remaining))
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                remaining -= len(chunk)
        if written != length:
            raise ValueError("upload truncated")
        return written

    def _finish_share(self, token, kind, name, size, ttl_days=None):
        d = os.path.join(DATA_DIR, token)
        ttl = TTL_DAYS if ttl_days is None else ttl_days
        json.dump({"kind": kind, "name": name},
                  open(os.path.join(d, ".meta.json"), "w", encoding="utf-8"), ensure_ascii=False)
        exp = int(time.time()) + ttl * 86400
        open(os.path.join(d, ".expires"), "w", encoding="utf-8").write(str(exp))
        slash = "/" if kind == "web" else ""
        return self._json(200, {
            "ok": True,
            "url": f"{PUBLIC_BASE}/s/{token}{slash}",
            "token": token, "name": name, "kind": kind, "size": size,
            "ttl_days": ttl, "expires_epoch": exp,
            "expires": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(exp)),
        })

    def _upload(self, web: bool):
        if not self._authed():
            return self._json(401, {"ok": False, "error": "bad token"})
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        raw_name = q.get("name", [None])[0] or self.headers.get("X-Filename") or "file"
        name = safe_filename(urllib.parse.unquote(raw_name))
        try:
            ttl = parse_ttl(q.get("ttl", [None])[0])
        except ValueError as e:
            return self._json(400, {"ok": False, "error": str(e)})
        token = new_token()
        d = os.path.join(DATA_DIR, token)
        os.makedirs(d, exist_ok=True)

        try:
            if not web:
                size = self._read_body_to(os.path.join(d, name))
                return self._finish_share(token, "file", name, size, ttl)

            # web app: body is a .zip (multi-file) or a single .html
            tmp = os.path.join(d, ".upload.tmp")
            size = self._read_body_to(tmp)
            with open(tmp, "rb") as f:
                magic = f.read(4)
            if magic[:2] == b"PK":  # zip
                self._unzip_into(tmp, d)
                os.remove(tmp)
                if not os.path.isfile(os.path.join(d, "index.html")):
                    shutil.rmtree(d, ignore_errors=True)
                    return self._json(400, {"ok": False, "error": "zip has no index.html at root"})
                label = name if name != "file" else "web app"
                return self._finish_share(token, "web", label, size, ttl)
            else:  # treat as a single html document
                os.replace(tmp, os.path.join(d, "index.html"))
                return self._finish_share(token, "web", name if name.endswith((".html", ".htm")) else "index.html", size, ttl)
        except ValueError as e:
            shutil.rmtree(d, ignore_errors=True)
            return self._json(400, {"ok": False, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(d, ignore_errors=True)
            return self._json(500, {"ok": False, "error": f"upload failed: {e}"})

    @staticmethod
    def _unzip_into(zip_path: str, dest: str):
        with zipfile.ZipFile(zip_path) as z:
            for member in z.namelist():
                # zip-slip guard
                target = os.path.normpath(os.path.join(dest, member))
                if not (target == dest or target.startswith(dest + os.sep)):
                    raise ValueError("unsafe zip entry")
            z.extractall(dest)
        # if everything sits under a single top dir, flatten it up one level
        entries = [e for e in os.listdir(dest) if not e.startswith(".")]
        if len(entries) == 1 and os.path.isdir(os.path.join(dest, entries[0])):
            inner = os.path.join(dest, entries[0])
            if os.path.isfile(os.path.join(inner, "index.html")):
                for e in os.listdir(inner):
                    shutil.move(os.path.join(inner, e), os.path.join(dest, e))
                os.rmdir(inner)

    def log_message(self, *args):
        pass


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    mimetypes.add_type("application/javascript", ".mjs")
    mimetypes.add_type("text/html", ".html")
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

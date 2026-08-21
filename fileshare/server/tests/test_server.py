"""Integration tests for the fileshare backend.

Boots src/server.py as a subprocess against a temp data dir and token file,
then drives the real HTTP API. Stdlib only.

    python -m unittest discover -s fileshare/server/tests -v

nginx is not in the loop here, so responses that would normally be handed off
to it assert on the X-Accel-Redirect header rather than on a body.
"""
import http.client
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "src" / "server.py"
TOKEN = "test-admin-token"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerTestCase(unittest.TestCase):
    """Shared fixture: one server process for the whole class."""

    ttl_days = 7
    max_ttl_days = 90

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="fileshare-test-")
        cls.data = os.path.join(cls.tmp, "data")
        os.makedirs(cls.data)
        cls.token_file = os.path.join(cls.tmp, "token")
        with open(cls.token_file, "w", encoding="utf-8") as f:
            f.write(TOKEN + "\n")

        cls.port = free_port()
        env = dict(
            os.environ,
            FILESHARE_DATA=cls.data,
            FILESHARE_TOKEN_FILE=cls.token_file,
            FILESHARE_BASE="https://example.test",
            FILESHARE_TTL_DAYS=str(cls.ttl_days),
            FILESHARE_MAX_TTL_DAYS=str(cls.max_ttl_days),
            FILESHARE_LISTEN="127.0.0.1",
            FILESHARE_PORT=str(cls.port),
        )
        cls.proc = subprocess.Popen(
            [sys.executable, str(SERVER)], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        cls._wait_ready()

    @classmethod
    def _wait_ready(cls, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                err = cls.proc.stderr.read().decode("utf-8", "replace")
                raise RuntimeError(f"server exited early:\n{err}")
            try:
                status, _, body = cls._raw("GET", "/healthz")
                if status == 200 and json.loads(body)["ok"]:
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("server did not become ready")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.proc.stdout.close()
        cls.proc.stderr.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # --- HTTP helpers -------------------------------------------------
    @classmethod
    def _raw(cls, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=15)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def request(self, method, path, body=None, token=None):
        headers = {}
        if body is not None:
            headers["Content-Length"] = str(len(body))
        if token is not None:
            headers["X-Token"] = token
        return self._raw(method, path, body, headers)

    def upload(self, name, payload, endpoint="upload", ttl=None, token=TOKEN):
        path = f"/{endpoint}?name={name}"
        if ttl is not None:
            path += f"&ttl={ttl}"
        status, headers, body = self.request("PUT", path, payload, token=token)
        return status, headers, json.loads(body) if body else {}

    def upload_ok(self, *args, **kwargs):
        status, _, payload = self.upload(*args, **kwargs)
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"], payload)
        return payload

    @staticmethod
    def zip_bytes(entries):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for arcname, content in entries.items():
                z.writestr(arcname, content)
        return buf.getvalue()

    def share_dir(self, payload):
        return os.path.join(self.data, payload["token"])


class TestHealthAndAuth(ServerTestCase):
    def test_healthz_is_public(self):
        status, _, body = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})

    def test_upload_without_token_is_rejected(self):
        status, _, payload = self.upload("x.txt", b"hi", token=None)
        self.assertEqual(status, 401)
        self.assertFalse(payload["ok"])

    def test_upload_with_wrong_token_is_rejected(self):
        status, _, payload = self.upload("x.txt", b"hi", token="not-the-token")
        self.assertEqual(status, 401)

    def test_list_and_delete_require_the_token(self):
        self.assertEqual(self.request("GET", "/api/list")[0], 401)
        self.assertEqual(self.request("DELETE", "/api/share/" + "a" * 24)[0], 401)

    def test_unknown_path_is_404(self):
        self.assertEqual(self.request("GET", "/nope")[0], 404)


class TestFileShares(ServerTestCase):
    def test_upload_returns_a_link_and_metadata(self):
        payload = self.upload_ok("report.pdf", b"%PDF-1.4 fake")
        self.assertEqual(payload["kind"], "file")
        self.assertEqual(payload["name"], "report.pdf")
        self.assertEqual(payload["size"], len(b"%PDF-1.4 fake"))
        self.assertEqual(payload["ttl_days"], self.ttl_days)
        self.assertEqual(payload["url"], f"https://example.test/s/{payload['token']}")
        self.assertTrue(os.path.isfile(os.path.join(self.share_dir(payload), "report.pdf")))

    def test_serving_hands_off_to_nginx_with_the_real_filename(self):
        payload = self.upload_ok("%E6%8A%A5%E5%91%8A.pdf", b"data")  # 报告.pdf
        status, headers, _ = self.request("GET", f"/s/{payload['token']}")
        self.assertEqual(status, 200)
        self.assertEqual(
            headers["X-Accel-Redirect"],
            f"/_filedata/{payload['token']}/%E6%8A%A5%E5%91%8A.pdf",
        )
        self.assertIn("filename*=UTF-8''", headers["Content-Disposition"])
        self.assertTrue(headers["Content-Disposition"].startswith("inline"))

    def test_non_viewable_types_download_instead_of_rendering(self):
        payload = self.upload_ok("archive.zip", b"PK\x03\x04rest")
        _, headers, _ = self.request("GET", f"/s/{payload['token']}")
        self.assertTrue(headers["Content-Disposition"].startswith("attachment"))

    def test_markdown_renders_as_a_page(self):
        payload = self.upload_ok("notes.md", "# 标题\n\n正文\n".encode("utf-8"))
        status, headers, body = self.request("GET", f"/s/{payload['token']}")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("标题", text)
        self.assertIn("<title>notes</title>", text)

    def test_markdown_raw_query_serves_the_source(self):
        payload = self.upload_ok("notes.md", b"# hi\n")
        status, headers, _ = self.request("GET", f"/s/{payload['token']}?raw=1")
        self.assertEqual(status, 200)
        self.assertIn("X-Accel-Redirect", headers)

    def test_unknown_share_token_is_404(self):
        self.assertEqual(self.request("GET", "/s/" + "0" * 24)[0], 404)

    def test_malformed_share_token_is_404(self):
        self.assertEqual(self.request("GET", "/s/not-hex")[0], 404)


class TestWebShares(ServerTestCase):
    def test_zip_with_index_becomes_a_web_app(self):
        payload = self.upload_ok(
            "site", self.zip_bytes({"index.html": "<h1>hi</h1>", "app.js": "1"}),
            endpoint="upload-web")
        self.assertEqual(payload["kind"], "web")
        self.assertTrue(payload["url"].endswith("/"))

    def test_web_root_redirects_so_relative_assets_resolve(self):
        payload = self.upload_ok("site", self.zip_bytes({"index.html": "<h1>hi</h1>"}),
                                 endpoint="upload-web")
        status, headers, _ = self.request("GET", f"/s/{payload['token']}")
        self.assertEqual(status, 301)
        self.assertEqual(headers["Location"], f"/s/{payload['token']}/")

    def test_web_serves_index_and_assets(self):
        payload = self.upload_ok(
            "site", self.zip_bytes({"index.html": "<h1>hi</h1>", "app.js": "1"}),
            endpoint="upload-web")
        tok = payload["token"]
        _, headers, _ = self.request("GET", f"/s/{tok}/")
        self.assertEqual(headers["X-Accel-Redirect"], f"/_filedata/{tok}/index.html")
        _, headers, _ = self.request("GET", f"/s/{tok}/app.js")
        self.assertEqual(headers["X-Accel-Redirect"], f"/_filedata/{tok}/app.js")

    def test_single_html_becomes_the_index(self):
        payload = self.upload_ok("page.html", b"<h1>solo</h1>", endpoint="upload-web")
        self.assertEqual(payload["kind"], "web")
        self.assertTrue(os.path.isfile(os.path.join(self.share_dir(payload), "index.html")))

    def test_single_wrapping_directory_is_flattened(self):
        payload = self.upload_ok(
            "site", self.zip_bytes({"site/index.html": "<h1>hi</h1>", "site/a.css": "b{}"}),
            endpoint="upload-web")
        d = self.share_dir(payload)
        self.assertTrue(os.path.isfile(os.path.join(d, "index.html")))
        self.assertFalse(os.path.isdir(os.path.join(d, "site")))

    def test_zip_without_index_is_rejected_and_leaves_nothing_behind(self):
        before = sorted(os.listdir(self.data))
        status, _, payload = self.upload("site", self.zip_bytes({"readme.txt": "x"}),
                                         endpoint="upload-web")
        self.assertEqual(status, 400)
        self.assertIn("index.html", payload["error"])
        self.assertEqual(sorted(os.listdir(self.data)), before)


class TestSecurity(ServerTestCase):
    def test_zip_slip_entry_is_rejected(self):
        before = sorted(os.listdir(self.data))
        status, _, payload = self.upload(
            "evil", self.zip_bytes({"../escaped.html": "pwned", "index.html": "x"}),
            endpoint="upload-web")
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escaped.html")))
        self.assertEqual(sorted(os.listdir(self.data)), before)

    def test_path_traversal_out_of_a_web_share_is_404(self):
        payload = self.upload_ok("site", self.zip_bytes({"index.html": "<h1>hi</h1>"}),
                                 endpoint="upload-web")
        secret = os.path.join(self.tmp, "token")
        self.assertTrue(os.path.isfile(secret))
        status, _, _ = self.request("GET", f"/s/{payload['token']}/..%2F..%2Ftoken")
        self.assertEqual(status, 404)

    def test_dangerous_characters_are_stripped_from_the_stored_name(self):
        payload = self.upload_ok("..%2F..%2Fetc%2Fpasswd", b"x")
        self.assertNotIn("/", payload["name"])
        self.assertNotIn("..", payload["name"])
        self.assertEqual(os.listdir(self.share_dir(payload)),
                         sorted(os.listdir(self.share_dir(payload))))

    def test_upload_without_content_length_is_rejected(self):
        status, _, body = self._raw("PUT", "/upload?name=x.txt", b"",
                                    {"X-Token": TOKEN, "Content-Length": "0"})
        self.assertEqual(status, 400)
        self.assertIn("Content-Length", json.loads(body)["error"])


class TestExpiry(ServerTestCase):
    def test_default_ttl_is_applied(self):
        payload = self.upload_ok("a.txt", b"x")
        self.assertEqual(payload["ttl_days"], self.ttl_days)
        expected = int(time.time()) + self.ttl_days * 86400
        self.assertLess(abs(payload["expires_epoch"] - expected), 30)

    def test_ttl_override_is_honoured(self):
        payload = self.upload_ok("a.txt", b"x", ttl=30)
        self.assertEqual(payload["ttl_days"], 30)

    def test_ttl_override_is_clamped(self):
        self.assertEqual(self.upload_ok("a.txt", b"x", ttl=9999)["ttl_days"], self.max_ttl_days)
        self.assertEqual(self.upload_ok("a.txt", b"x", ttl=0)["ttl_days"], 1)

    def test_non_numeric_ttl_is_rejected(self):
        status, _, payload = self.upload("a.txt", b"x", ttl="soon")
        self.assertEqual(status, 400)
        self.assertIn("ttl", payload["error"])

    def test_expired_share_is_gone_on_access(self):
        payload = self.upload_ok("a.txt", b"x")
        d = self.share_dir(payload)
        with open(os.path.join(d, ".expires"), "w", encoding="utf-8") as f:
            f.write(str(int(time.time()) - 1))
        status, _, body = self.request("GET", f"/s/{payload['token']}")
        self.assertEqual(status, 410)
        self.assertIn(b"expired", body)
        self.assertFalse(os.path.isdir(d))


class TestAdminApi(ServerTestCase):
    def test_list_reports_live_shares(self):
        a = self.upload_ok("a.txt", b"hello")
        b = self.upload_ok("site", self.zip_bytes({"index.html": "<h1>x</h1>"}),
                           endpoint="upload-web")
        status, _, body = self.request("GET", "/api/list", token=TOKEN)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        by_token = {s["token"]: s for s in payload["shares"]}
        self.assertIn(a["token"], by_token)
        self.assertIn(b["token"], by_token)
        self.assertEqual(by_token[a["token"]]["kind"], "file")
        self.assertEqual(by_token[a["token"]]["name"], "a.txt")
        self.assertEqual(by_token[a["token"]]["size"], 5)
        self.assertFalse(by_token[a["token"]]["expired"])
        self.assertEqual(by_token[b["token"]]["kind"], "web")
        self.assertTrue(by_token[b["token"]]["url"].endswith("/"))

    def test_delete_removes_the_share(self):
        payload = self.upload_ok("a.txt", b"x")
        status, _, body = self.request("DELETE", f"/api/share/{payload['token']}", token=TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["deleted"], payload["token"])
        self.assertFalse(os.path.isdir(self.share_dir(payload)))
        self.assertEqual(self.request("GET", f"/s/{payload['token']}")[0], 404)

    def test_delete_of_an_unknown_share_is_404(self):
        status, _, _ = self.request("DELETE", "/api/share/" + "0" * 24, token=TOKEN)
        self.assertEqual(status, 404)


def find_bash():
    """A bash that can actually run a POSIX script.

    On Windows, PATH lookup often lands on System32\bash.exe (the WSL shim),
    which exits 1 without output when no distro is installed. Probe candidates
    and take the first one that really works.
    """
    candidates = [os.environ.get("SHELL"), shutil.which("bash")]
    if sys.platform == "win32":
        candidates += [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ]
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        try:
            probe = subprocess.run([candidate, "-c", "printf ok"],
                                   capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and probe.stdout.strip() == b"ok":
            return candidate
    return None


class TestCleanupScript(unittest.TestCase):
    """cleanup.sh is the belt to the server's braces; exercise it directly."""

    script = Path(__file__).resolve().parents[1] / "deploy" / "cleanup.sh"

    @classmethod
    def setUpClass(cls):
        cls.bash = find_bash()
        if not cls.bash:
            raise unittest.SkipTest("no working bash available")

    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="fileshare-cleanup-")
        self.addCleanup(shutil.rmtree, self.data, True)

    def make_share(self, name, expires_in):
        d = os.path.join(self.data, name)
        os.makedirs(d)
        with open(os.path.join(d, "payload.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        with open(os.path.join(d, ".expires"), "w", encoding="utf-8") as f:
            f.write(str(int(time.time()) + expires_in))
        return d

    def posix_path(self, path):
        r"""bash on Windows (git-bash/msys) needs /c/... rather than C:\..."""
        if sys.platform != "win32":
            return path
        out = subprocess.run([self.bash, "-c", 'cygpath -u "$1"', "--", path],
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or path

    def run_cleanup(self):
        return subprocess.run(
            [self.bash, str(self.script)],
            env=dict(os.environ, FILESHARE_DATA=self.posix_path(self.data)),
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )

    def test_expired_shares_are_removed_and_live_ones_kept(self):
        if not shutil.which("bash"):
            self.skipTest("bash not available")
        dead = self.make_share("aaaaaaaaaaaaaaaaaaaaaaaa", -3600)
        live = self.make_share("bbbbbbbbbbbbbbbbbbbbbbbb", 3600)
        result = self.run_cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.isdir(dead))
        self.assertTrue(os.path.isdir(live))


if __name__ == "__main__":
    unittest.main()

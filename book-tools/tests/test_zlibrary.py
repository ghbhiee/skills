import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from Zlibrary import Zlibrary, ZlibraryAPIError


def response(status=200, content_type="application/json", payload=None):
    result = Mock()
    result.status_code = status
    result.headers = {"content-type": content_type}
    result.json.return_value = payload if payload is not None else {"success": 1}
    return result


class ZlibraryDomainTests(unittest.TestCase):
    @patch("Zlibrary.requests.get")
    def test_domain_probe_skips_html_and_selects_json_endpoint(self, get):
        get.side_effect = [
            response(status=404, content_type="text/html"),
            response(payload={"success": 1, "domains": []}),
        ]

        client = Zlibrary()

        self.assertEqual(client.getDomain(), "z-lib.sk")
        self.assertEqual(get.call_count, 2)

    @patch("Zlibrary.requests.request")
    def test_non_json_api_response_raises_descriptive_error(self, request):
        request.return_value = response(status=404, content_type="text/html")
        client = Zlibrary(domain="https://z-lib.id")

        with self.assertRaisesRegex(ZlibraryAPIError, "HTTP 404"):
            client.loginWithToken("123", "invalid")

    @patch("Zlibrary.requests.request")
    def test_malformed_json_is_not_exposed_as_requests_traceback(self, request):
        bad = response()
        bad.json.side_effect = ValueError("not JSON")
        request.return_value = bad
        client = Zlibrary(domain="z-library.ec")

        with self.assertRaisesRegex(ZlibraryAPIError, "malformed JSON"):
            client.loginWithToken("123", "invalid")


if __name__ == "__main__":
    unittest.main()

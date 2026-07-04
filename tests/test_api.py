import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

os.environ["APPDATA"] = str(Path.cwd() / ".test-appdata")

from api import deepseek
from api import deepseek_official


def platform_config(key, default=None):
    return {
        "DEEPSEEK_AUTH": "Bearer test-token",
        "DEEPSEEK_COOKIE": "",
        "DEEPSEEK_BASE": "https://platform.deepseek.com",
    }.get(key, default)


def response(status=200, payload=None, content_type="application/json"):
    result = Mock()
    result.status_code = status
    result.ok = 200 <= status < 400
    result.headers = {"Content-Type": content_type}
    result.json.return_value = payload
    return result


class PlatformApiTests(unittest.TestCase):
    def setUp(self):
        config = patch.object(deepseek.config_manager, "get", side_effect=platform_config)
        config.start()
        self.addCleanup(config.stop)

    def test_retry_returns_final_status_for_classification(self):
        adapter = deepseek._SESSION.get_adapter("https://")
        self.assertFalse(adapter.max_retries.raise_on_status)

    def test_rate_limit_is_not_retried(self):
        adapter = deepseek._SESSION.get_adapter("https://")
        self.assertNotIn(429, adapter.max_retries.status_forcelist)
        self.assertFalse(adapter.max_retries.respect_retry_after_header)
        self.assertFalse(adapter.max_retries.is_retry("GET", 429, has_retry_after=True))

    def test_platform_compatibility_headers_are_preserved(self):
        headers = deepseek._headers()
        self.assertIn("Chrome/147", headers["user-agent"])
        self.assertEqual(headers["x-app-version"], "20240425.0")
        self.assertEqual(headers["sec-ch-ua-platform"], '"Windows"')

    @patch.object(deepseek._SESSION, "get")
    def test_valid_response_and_query_params(self, get):
        get.return_value = response(200, {"data": {"biz_data": {"days": []}}})
        self.assertEqual(deepseek.get_usage_amount(7, 2026), {"days": []})
        self.assertEqual(get.call_args.kwargs["params"], {"month": 7, "year": 2026})

    @patch.object(deepseek._SESSION, "get")
    def test_auth_error_is_classified(self, get):
        get.return_value = response(401, {})
        with self.assertRaises(deepseek.APIError) as caught:
            deepseek.get_user_summary()
        self.assertEqual(caught.exception.code, "AUTH_EXPIRED")

    @patch.object(deepseek._SESSION, "get")
    def test_non_json_response_is_rejected(self, get):
        get.return_value = response(200, {}, "text/html")
        with self.assertRaises(deepseek.APIError) as caught:
            deepseek.get_user_summary()
        self.assertEqual(caught.exception.code, "INVALID_RESPONSE")

    @patch.object(deepseek._SESSION, "get")
    def test_html_429_is_classified_as_platform_block(self, get):
        get.return_value = response(429, {}, "text/html; charset=utf-8")
        with self.assertRaises(deepseek.APIError) as caught:
            deepseek.get_user_summary()
        self.assertEqual(caught.exception.code, "PLATFORM_BLOCKED")

    @patch.object(deepseek._SESSION, "get", side_effect=requests.Timeout())
    def test_timeout_is_classified(self, _get):
        with self.assertRaises(deepseek.APIError) as caught:
            deepseek.get_user_summary()
        self.assertEqual(caught.exception.code, "NETWORK_TIMEOUT")

    @patch.object(deepseek._SESSION, "get")
    def test_missing_auth_is_rejected_before_request(self, get):
        with patch.object(deepseek.config_manager, "get", return_value=""):
            with self.assertRaises(deepseek.APIError) as caught:
                deepseek.get_user_summary()
        self.assertEqual(caught.exception.code, "NOT_CONFIGURED")
        get.assert_not_called()


class OfficialApiTests(unittest.TestCase):
    @patch("api.deepseek_official.config_manager.get", return_value="fake-key")
    @patch.object(deepseek_official._SESSION, "get")
    def test_balance_uses_bearer_api_key(self, get, _config):
        get.return_value = response(200, {"balance_infos": []})
        deepseek_official.get_balance()
        self.assertEqual(get.call_args.kwargs["headers"]["authorization"], "Bearer fake-key")


if __name__ == "__main__":
    unittest.main()

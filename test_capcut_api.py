import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

import capcut_api


class CapcutApiClientTests(unittest.TestCase):
    def test_get_products_logs_request_when_api_debug_enabled(self):
        client = capcut_api.CapcutApiClient("http://node12.zampto.net:20291/api", "sk_test_key_1234")

        with patch.dict(capcut_api.os.environ, {"API_DEBUG": "1"}, clear=False), patch.object(
            capcut_api.subprocess, "run"
        ) as run_mock, patch("builtins.print") as print_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"success": true, "products": []}',
                stderr="",
            )

            client.get_products()

        printed = "\n".join(" ".join(str(arg) for arg in call.args) for call in print_mock.call_args_list)
        self.assertIn("http://node12.zampto.net:20291/api/products", printed)
        self.assertIn("GET", printed)
        self.assertIn("sk_t...1234", printed)
        self.assertNotIn("sk_test_key_1234", printed)

    def test_get_products_logs_truncated_response_when_api_debug_enabled(self):
        client = capcut_api.CapcutApiClient("http://node12.zampto.net:20291/api", "sk_test_key_1234")
        long_name = "CapCut-" + ("X" * 1500)

        with patch.dict(capcut_api.os.environ, {"API_DEBUG": "1"}, clear=False), patch.object(
            capcut_api.subprocess, "run"
        ) as run_mock, patch("builtins.print") as print_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps({"success": True, "products": [{"id": "cc_1", "name": long_name}]}),
                stderr="",
            )

            client.get_products()

        printed = "\n".join(" ".join(str(arg) for arg in call.args) for call in print_mock.call_args_list)
        self.assertIn("[CapcutApiClient] response", printed)
        self.assertIn('"products":[{"id":"cc_1","name":"CapCut-', printed)
        self.assertIn("...(truncated)", printed)

    def test_get_products_falls_back_to_urllib_when_no_powershell_is_available(self):
        client = capcut_api.CapcutApiClient("http://node12.zampto.net:20291/api", "sk-test")
        response = MagicMock()
        response.read.return_value = b'{"success": true, "products": [{"name": "CapCut Pro"}]}'
        response.__enter__.return_value = response
        response.__exit__.return_value = None

        with patch.object(capcut_api.shutil, "which", side_effect=[None, None, None]), patch.object(
            capcut_api.os.path, "exists", return_value=False
        ), patch.object(capcut_api.subprocess, "run") as run_mock, patch.object(
            capcut_api.urllib.request, "urlopen", return_value=response
        ) as urlopen_mock:
            data = client.get_products()

        self.assertEqual(data["products"][0]["name"], "CapCut Pro")
        self.assertFalse(run_mock.called)
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "http://node12.zampto.net:20291/api/products")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.headers["X-api-key"], "sk-test")

    def test_get_products_falls_back_to_absolute_powershell_path_when_not_on_path(self):
        client = capcut_api.CapcutApiClient("http://node12.zampto.net:20291/api", "sk-test")

        with patch.object(capcut_api.shutil, "which", side_effect=[None, None, None]), patch.object(
            capcut_api.os.path, "exists", return_value=True
        ), patch.object(capcut_api.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"success": true, "products": []}',
                stderr="",
            )

            client.get_products()

        self.assertEqual(
            run_mock.call_args.kwargs["args"][0].lower(),
            r"c:\windows\system32\windowspowershell\v1.0\powershell.exe",
        )

    def test_get_products_uses_api_key_header(self):
        client = capcut_api.CapcutApiClient("http://node12.zampto.net:20291/api", "sk-test")

        with patch.object(capcut_api.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"success": true, "products": []}',
                stderr="",
            )

            data = client.get_products()

        self.assertEqual(data["products"], [])
        command = " ".join(run_mock.call_args.kwargs["args"])
        self.assertIn("Invoke-RestMethod", command)
        self.assertIn("/products", command)
        self.assertIn("X-API-Key", command)

    def test_get_balance_returns_json(self):
        client = capcut_api.CapcutApiClient("http://node12.zampto.net:20291/api", "sk-test")

        with patch.object(capcut_api.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"success": true, "balance": 150000}',
                stderr="",
            )

            data = client.get_balance()

        self.assertEqual(data["balance"], 150000)

    def test_buy_product_posts_expected_body(self):
        client = capcut_api.CapcutApiClient("http://node12.zampto.net:20291/api", "sk-test")

        with patch.object(capcut_api.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"success": true, "order": {"accounts": ["acc|pass"]}}',
                stderr="",
            )

            data = client.buy_product("cc_1", 2)

        self.assertEqual(data["order"]["accounts"], ["acc|pass"])
        command = " ".join(run_mock.call_args.kwargs["args"])
        self.assertIn("-Method Post", command)
        self.assertIn('"product_id":"cc_1"', command)
        self.assertIn('"quantity":2', command)

    def test_request_json_raises_when_response_is_not_json(self):
        client = capcut_api.CapcutApiClient("http://node12.zampto.net:20291/api", "sk-test")

        with patch.object(capcut_api.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="not-json",
                stderr="",
            )

            with self.assertRaisesRegex(capcut_api.CapcutApiError, "Invalid CapCut API response"):
                client.get_products()

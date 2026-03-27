import subprocess
import unittest
from unittest.mock import patch

import capcut_api


class CapcutApiClientTests(unittest.TestCase):
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

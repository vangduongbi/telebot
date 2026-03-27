import subprocess
import unittest
from unittest.mock import patch

import supplier_api


class SupplierApiClientTests(unittest.TestCase):
    def test_get_balance_uses_powershell_and_parses_json(self):
        client = supplier_api.SupplierApiClient("https://sumistore.me/api", "TAPI-KEY")

        with patch.object(supplier_api.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"success": true, "balance": 7000}',
                stderr="",
            )

            data = client.get_balance()

        self.assertEqual(data["balance"], 7000)
        command = " ".join(run_mock.call_args.kwargs["args"])
        self.assertIn("Invoke-RestMethod", command)
        self.assertIn("tele-balance", command)
        self.assertIn("X-Tele-API-ID", command)

    def test_buy_product_posts_json_body(self):
        client = supplier_api.SupplierApiClient("https://sumistore.me/api", "TAPI-KEY")

        with patch.object(supplier_api.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"success": true, "raw_accounts": ["acc|pass"]}',
                stderr="",
            )

            data = client.buy_product("SP-GEF55PBV", 2)

        self.assertEqual(data["raw_accounts"], ["acc|pass"])
        command = " ".join(run_mock.call_args.kwargs["args"])
        self.assertIn("-Method Post", command)
        self.assertIn('"id":"SP-GEF55PBV"', command)
        self.assertIn('"quantity":2', command)

    def test_request_json_raises_when_powershell_fails(self):
        client = supplier_api.SupplierApiClient("https://sumistore.me/api", "TAPI-KEY")

        with patch.object(supplier_api.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="403 blocked",
            )

            with self.assertRaisesRegex(supplier_api.SupplierApiError, "403 blocked"):
                client.get_balance()

    def test_request_json_raises_when_response_is_not_json(self):
        client = supplier_api.SupplierApiClient("https://sumistore.me/api", "TAPI-KEY")

        with patch.object(supplier_api.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="not-json",
                stderr="",
            )

            with self.assertRaisesRegex(supplier_api.SupplierApiError, "Invalid supplier response"):
                client.get_balance()

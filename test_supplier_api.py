import subprocess
import unittest
from unittest.mock import MagicMock, patch

import supplier_api


class SupplierApiClientTests(unittest.TestCase):
    def test_get_balance_logs_request_when_api_debug_enabled(self):
        client = supplier_api.SupplierApiClient("https://sumistore.me/api", "TAPI-KEY-1234")

        with patch.dict(supplier_api.os.environ, {"API_DEBUG": "1"}, clear=False), patch.object(
            supplier_api.subprocess, "run"
        ) as run_mock, patch("builtins.print") as print_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"success": true, "balance": 7000}',
                stderr="",
            )

            client.get_balance()

        printed = "\n".join(" ".join(str(arg) for arg in call.args) for call in print_mock.call_args_list)
        self.assertIn("https://sumistore.me/api/tele-balance", printed)
        self.assertIn("GET", printed)
        self.assertIn("TAPI...1234", printed)
        self.assertNotIn("TAPI-KEY-1234", printed)

    def test_get_balance_logs_response_payload_when_api_debug_enabled(self):
        client = supplier_api.SupplierApiClient("https://sumistore.me/api", "TAPI-KEY-1234")

        with patch.dict(supplier_api.os.environ, {"API_DEBUG": "1"}, clear=False), patch.object(
            supplier_api.subprocess, "run"
        ) as run_mock, patch("builtins.print") as print_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"success": true, "balance": 7000, "meta": {"currency": "VND"}}',
                stderr="",
            )

            client.get_balance()

        printed = "\n".join(" ".join(str(arg) for arg in call.args) for call in print_mock.call_args_list)
        self.assertIn("[SupplierApiClient] response", printed)
        self.assertIn('"balance":7000', printed)
        self.assertIn('"meta":{"currency":"VND"}', printed)

    def test_get_balance_falls_back_to_urllib_when_no_powershell_is_available(self):
        client = supplier_api.SupplierApiClient("https://sumistore.me/api", "TAPI-KEY")
        response = MagicMock()
        response.read.return_value = b'{"success": true, "balance": 7000}'
        response.__enter__.return_value = response
        response.__exit__.return_value = None

        with patch.object(supplier_api.shutil, "which", side_effect=[None, None, None]), patch.object(
            supplier_api.os.path, "exists", return_value=False
        ), patch.object(supplier_api.subprocess, "run") as run_mock, patch.object(
            supplier_api.urllib.request, "urlopen", return_value=response
        ) as urlopen_mock:
            data = client.get_balance()

        self.assertEqual(data["balance"], 7000)
        self.assertFalse(run_mock.called)
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://sumistore.me/api/tele-balance")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.headers["X-tele-api-id"], "TAPI-KEY")

    def test_get_balance_falls_back_to_absolute_powershell_path_when_not_on_path(self):
        client = supplier_api.SupplierApiClient("https://sumistore.me/api", "TAPI-KEY")

        with patch.object(supplier_api.shutil, "which", side_effect=[None, None, None]), patch.object(
            supplier_api.os.path, "exists", return_value=True
        ), patch.object(supplier_api.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"success": true, "balance": 7000}',
                stderr="",
            )

            client.get_balance()

        self.assertEqual(
            run_mock.call_args.kwargs["args"][0].lower(),
            r"c:\windows\system32\windowspowershell\v1.0\powershell.exe",
        )

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

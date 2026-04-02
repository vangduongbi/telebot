import unittest

import supplier_runtime


class SupplierRuntimeTests(unittest.TestCase):
    def test_resolve_provider_merges_protocol_defaults_with_overrides(self):
        resolved = supplier_runtime.resolve_provider_config(
            {
                "code": "node12",
                "name": "Node12",
                "protocol": "node_api",
                "base_url": "http://node12.zampto.net:20291/api",
                "api_key": "sk-test",
                "overrides_json": '{"buy_path":"/custom-buy","buy_product_id_field":"id"}',
                "is_active": 1,
            }
        )

        self.assertEqual(resolved["protocol"], "node_api")
        self.assertEqual(resolved["base_url"], "http://node12.zampto.net:20291/api")
        self.assertEqual(resolved["auth_header"], "X-API-Key")
        self.assertEqual(resolved["buy_path"], "/custom-buy")
        self.assertEqual(resolved["buy_product_id_field"], "id")
        self.assertEqual(resolved["buy_quantity_field"], "quantity")

    def test_sumistore_available_units_uses_balance_divided_by_sale_price(self):
        calls = []

        def fake_request(method, path, body=None):
            calls.append((method, path, body))
            if path == "/tele-products/SP-1":
                return {
                    "success": True,
                    "product": {"id": "SP-1", "api_enabled": True, "sale_price": 3000, "stock": 100},
                }
            if path == "/tele-balance":
                return {"success": True, "balance": 10000}
            raise AssertionError(path)

        runtime = supplier_runtime.SupplierRuntime(
            {
                "code": "sumi",
                "name": "Sumi",
                "protocol": "sumistore",
                "base_url": "https://sumistore.me/api",
                "api_key": "api-test",
                "overrides_json": "{}",
                "is_active": 1,
            },
            request_json=fake_request,
        )

        available = runtime.get_available_units("SP-1")

        self.assertEqual(available, 3)
        self.assertEqual(
            calls,
            [
                ("GET", "/tele-products/SP-1", None),
                ("GET", "/tele-balance", None),
            ],
        )

    def test_node_api_available_units_uses_override_paths_and_caps_by_stock(self):
        calls = []

        def fake_request(method, path, body=None):
            calls.append((method, path, body))
            if path == "/catalog":
                return {
                    "success": True,
                    "products": [{"id": "grok_1", "name": "Grok 1", "price": 5000, "stock": 2}],
                }
            if path == "/wallet":
                return {"success": True, "balance": 40000}
            raise AssertionError(path)

        runtime = supplier_runtime.SupplierRuntime(
            {
                "code": "node12",
                "name": "Node12",
                "protocol": "node_api",
                "base_url": "http://node12.zampto.net:20291/api",
                "api_key": "sk-test",
                "overrides_json": '{"products_path":"/catalog","balance_path":"/wallet"}',
                "is_active": 1,
            },
            request_json=fake_request,
        )

        available = runtime.get_available_units("grok_1")

        self.assertEqual(available, 2)
        self.assertEqual(
            calls,
            [
                ("GET", "/catalog", None),
                ("GET", "/wallet", None),
            ],
        )

    def test_extract_delivered_accounts_returns_normalized_list(self):
        sumistore_runtime = supplier_runtime.SupplierRuntime(
            {
                "code": "sumi",
                "name": "Sumi",
                "protocol": "sumistore",
                "base_url": "https://sumistore.me/api",
                "api_key": "api-test",
                "overrides_json": "{}",
                "is_active": 1,
            },
            request_json=lambda method, path, body=None: {"success": True},
        )
        node_runtime = supplier_runtime.SupplierRuntime(
            {
                "code": "node12",
                "name": "Node12",
                "protocol": "node_api",
                "base_url": "http://node12.zampto.net:20291/api",
                "api_key": "sk-test",
                "overrides_json": "{}",
                "is_active": 1,
            },
            request_json=lambda method, path, body=None: {"success": True},
        )

        supplier_accounts = sumistore_runtime.extract_delivered_accounts(
            {"raw_accounts": ["mail@example.com|pass"]}
        )
        node_accounts = node_runtime.extract_delivered_accounts(
            {"order": {"accounts": ["grok@example.com|pass"]}}
        )

        self.assertEqual(supplier_accounts, ["mail@example.com|pass"])
        self.assertEqual(node_accounts, ["grok@example.com|pass"])


if __name__ == "__main__":
    unittest.main()

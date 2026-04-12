import os
import tempfile
import unittest

import database
import repositories
import services


class SQLiteServiceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "shop.db")
        database.init_db(self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()


class OrderCreationTests(SQLiteServiceTestCase):
    def test_create_pending_order_reserves_requested_stock(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "GPT", 100000)
        repo.add_stock_items("prod_1", ["a", "b", "c"], batch_id="batch-1")

        service = services.ShopService(self.db_path)
        order = service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id="prod_1",
            qty=2,
        )

        counts = repo.count_stock_by_status("prod_1")

        self.assertEqual(order["status"], "pending_payment")
        self.assertEqual(order["product_id"], "prod_1")
        self.assertEqual(order["qty"], 2)
        self.assertEqual(order["unit_price"], 100000)
        self.assertEqual(order["total_amount"], 200000)
        self.assertEqual(counts["reserved"], 2)
        self.assertEqual(counts["available"], 1)

    def test_create_pending_order_rejects_quantity_above_available_stock(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "GPT", 100000)
        repo.add_stock_items("prod_1", ["a"], batch_id="batch-1")

        service = services.ShopService(self.db_path)

        with self.assertRaisesRegex(ValueError, "Not enough stock"):
            service.create_pending_order(
                user_id=10,
                username="@buyer",
                full_name="Buyer",
                product_id="prod_1",
                qty=2,
            )


class PaymentSuccessTests(SQLiteServiceTestCase):
    def test_mark_paid_and_delivered_moves_reserved_stock_to_sold(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "GPT", 100000)
        repo.add_stock_items("prod_1", ["a"], batch_id="batch-1")

        service = services.ShopService(self.db_path)
        order = service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id="prod_1",
            qty=1,
        )

        delivered = service.mark_payment_paid(
            order_id=order["id"],
            payos_ref="123456",
            amount_paid=100000,
        )

        order_row = repo.get_order(order["id"])
        counts = repo.count_stock_by_status("prod_1")
        items = repo.list_order_items(order["id"])

        self.assertEqual(order_row["status"], "delivered")
        self.assertEqual(order_row["payos_ref"], "123456")
        self.assertEqual(counts["sold"], 1)
        self.assertEqual(counts["reserved"], 0)
        self.assertEqual(len(items), 1)
        self.assertEqual(delivered["accounts"], [items[0]["delivered_content"]])

    def test_mark_supplier_paid_creates_delivered_items_without_local_stock(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("GPT Supplier", "100.000Ä‘")
        service.update_product_fulfillment_mode(product["id"], "supplier_api")
        service.update_product_supplier_product_id(product["id"], "SP-GEF55PBV")

        order = service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id=product["id"],
            qty=1,
        )

        delivered = service.mark_supplier_payment_paid(
            order_id=order["id"],
            payos_ref="999888",
            amount_paid=100000,
            delivered_accounts=["mail@example.com|pass"],
        )

        repo = repositories.Repository(self.db_path)
        order_row = repo.get_order(order["id"])
        counts = repo.count_stock_by_status(product["id"])
        items = repo.list_order_items(order["id"])

        self.assertEqual(order_row["status"], "delivered")
        self.assertEqual(counts["sold"], 1)
        self.assertEqual(items[0]["delivered_content"], "mail@example.com|pass")
        self.assertEqual(delivered["accounts"], ["mail@example.com|pass"])


class PaymentFailureTests(SQLiteServiceTestCase):
    def test_cancel_pending_order_releases_reserved_stock(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "GPT", 100000)
        repo.add_stock_items("prod_1", ["a", "b", "c"], batch_id="batch-1")

        service = services.ShopService(self.db_path)
        order = service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id="prod_1",
            qty=2,
        )

        service.cancel_pending_order(order["id"], reason="payment timeout")

        order_row = repo.get_order(order["id"])
        counts = repo.count_stock_by_status("prod_1")

        self.assertEqual(order_row["status"], "cancelled")
        self.assertEqual(order_row["note"], "payment timeout")
        self.assertEqual(counts["reserved"], 0)
        self.assertEqual(counts["available"], 3)


class AdminProductServiceTests(SQLiteServiceTestCase):
    def test_create_product_parses_price_text_and_persists(self):
        service = services.ShopService(self.db_path)

        product = service.create_product("GPT Plus", "100.000đ")

        repo = repositories.Repository(self.db_path)
        stored = repo.get_product(product["id"])
        self.assertEqual(stored["name"], "GPT Plus")
        self.assertEqual(stored["price"], 100000)
        self.assertEqual(stored["is_active"], 1)

    def test_update_product_name_and_price(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Old Name", "50.000đ")

        service.update_product_name(product["id"], "New Name")
        service.update_product_price(product["id"], "75.000đ")

        repo = repositories.Repository(self.db_path)
        stored = repo.get_product(product["id"])
        self.assertEqual(stored["name"], "New Name")
        self.assertEqual(stored["price"], 75000)

    def test_add_stock_items_ignores_blank_lines(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Stocked", 10000)

        added = service.add_product_stock(
            product["id"],
            "acc-1\n\n  \nacc-2\n",
        )

        repo = repositories.Repository(self.db_path)
        counts = repo.count_stock_by_status(product["id"])
        self.assertEqual(added, 2)
        self.assertEqual(counts["available"], 2)

    def test_deactivate_product_hides_it_from_active_listing(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Hidden", 10000)

        service.deactivate_product(product["id"])

        active_ids = [row["id"] for row in service.list_active_products()]
        self.assertNotIn(product["id"], active_ids)

    def test_update_product_fulfillment_mode_and_supplier_product_id(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Supplier Product", "30.000Ä‘")

        service.update_product_fulfillment_mode(product["id"], "supplier_api")
        service.update_product_supplier_product_id(product["id"], "SP-GEF55PBV")

        stored = repositories.Repository(self.db_path).get_product(product["id"])
        self.assertEqual(stored["fulfillment_mode"], "supplier_api")
        self.assertEqual(stored["supplier_product_id"], "SP-GEF55PBV")

    def test_update_product_sales_mode(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Contact Product", "30.000Ä‘")

        service.update_product_sales_mode(product["id"], "contact_only")

        stored = repositories.Repository(self.db_path).get_product(product["id"])
        self.assertEqual(stored["sales_mode"], "contact_only")


    def test_update_product_supplier_provider(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("CapCut Product", "30.000Ã„â€˜")
        service.create_supplier_provider(
            "capcut_default",
            "CapCut Default",
            "node_api",
            "http://node12.zampto.net:20291/api",
            "sk-test",
        )

        service.update_product_supplier_provider(product["id"], "capcut_default")

        stored = repositories.Repository(self.db_path).get_product(product["id"])
        self.assertEqual(stored["supplier_provider"], "capcut_default")


    def test_update_product_description(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Product With Description", "30.000đ")

        service.update_product_description(product["id"], "Product override")

        stored = repositories.Repository(self.db_path).get_product(product["id"])
        self.assertEqual(stored["description"], "Product override")

    def test_clear_available_stock_removes_only_available_items(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Stocked", "30.000Ä‘")
        service.add_product_stock(product["id"], "acc-1\nacc-2\nacc-3")
        order = service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id=product["id"],
            qty=1,
        )
        service.mark_payment_paid(order["id"], "PAY-1", 30000)

        deleted_count = service.clear_available_stock(product["id"])
        counts = repositories.Repository(self.db_path).count_stock_by_status(product["id"])

        self.assertEqual(deleted_count, 2)
        self.assertEqual(counts["available"], 0)
        self.assertEqual(counts["sold"], 1)
        self.assertEqual(counts["reserved"], 0)

    def test_delete_product_deletes_clean_product(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Clean", "30.000Ä‘")

        summary = service.delete_product(product["id"])

        self.assertTrue(summary["deleted"])
        self.assertEqual(summary["product_name"], "Clean")
        self.assertIsNone(repositories.Repository(self.db_path).get_product(product["id"]))

    def test_delete_product_skips_product_with_history(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Stocked", "30.000Ä‘")
        service.add_product_stock(product["id"], "acc-1")

        summary = service.delete_product(product["id"])

        self.assertFalse(summary["deleted"])
        self.assertEqual(summary["product_name"], "Stocked")
        self.assertEqual(summary["reason"], "has_history")
        self.assertIsNotNone(repositories.Repository(self.db_path).get_product(product["id"]))


class SupplierProviderServiceTests(SQLiteServiceTestCase):
    def test_create_supplier_provider_validates_required_fields(self):
        service = services.ShopService(self.db_path)

        with self.assertRaisesRegex(ValueError, "Provider code is required"):
            service.create_supplier_provider("", "Node12", "node_api", "http://node12.zampto.net:20291/api")

        with self.assertRaisesRegex(ValueError, "Provider name is required"):
            service.create_supplier_provider("node12", "", "node_api", "http://node12.zampto.net:20291/api")

        with self.assertRaisesRegex(ValueError, "Provider protocol is required"):
            service.create_supplier_provider("node12", "Node12", "", "http://node12.zampto.net:20291/api")

        with self.assertRaisesRegex(ValueError, "Provider base URL is required"):
            service.create_supplier_provider("node12", "Node12", "node_api", "")

        with self.assertRaisesRegex(ValueError, "Invalid overrides JSON"):
            service.create_supplier_provider(
                "node12",
                "Node12",
                "node_api",
                "http://node12.zampto.net:20291/api",
                overrides_json="{invalid",
            )

    def test_list_supplier_providers_returns_created_provider(self):
        service = services.ShopService(self.db_path)

        service.create_supplier_provider(
            "node12",
            "Node12",
            "node_api",
            "http://node12.zampto.net:20291/api",
            "sk-test",
            '{"products_path":"/products"}',
        )

        rows = service.list_supplier_providers()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "node12")
        self.assertEqual(rows[0]["protocol"], "node_api")

    def test_update_product_supplier_provider_requires_existing_provider(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Provider Product", "30.000đ")

        with self.assertRaisesRegex(ValueError, "Supplier provider does not exist"):
            service.update_product_supplier_provider(product["id"], "node12")

    def test_delete_supplier_provider_rejects_when_products_still_reference_it(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Provider Product", "30.000đ")
        service.create_supplier_provider(
            "node12",
            "Node12",
            "node_api",
            "http://node12.zampto.net:20291/api",
        )
        service.update_product_supplier_provider(product["id"], "node12")

        with self.assertRaisesRegex(ValueError, "Supplier provider is still in use"):
            service.delete_supplier_provider("node12")


class CategoryServiceTests(SQLiteServiceTestCase):
    def test_create_category_and_assign_product(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("GPT Plus", "100.000đ")

        category = service.create_category("Tài khoản ChatGPT")
        service.assign_product_category(product["id"], category["id"])

        products = service.list_products_for_category(category["id"])
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["id"], product["id"])

    def test_list_active_categories_returns_created_category(self):
        service = services.ShopService(self.db_path)

        category = service.create_category("Google AI")
        categories = service.list_active_categories()

        self.assertTrue(any(row["id"] == category["id"] for row in categories))

    def test_list_products_for_category_none_returns_all_active_products(self):
        service = services.ShopService(self.db_path)
        first = service.create_product("A", "10.000đ")
        second = service.create_product("B", "20.000đ")

        products = service.list_products_for_category(None)

        product_ids = {row["id"] for row in products}
        self.assertIn(first["id"], product_ids)
        self.assertIn(second["id"], product_ids)


    def test_update_category_name_and_toggle_active(self):
        service = services.ShopService(self.db_path)
        category = service.create_category("Old Name")

        service.update_category_name(category["id"], "New Name")
        service.set_category_active(category["id"], False)

        active_ids = {row["id"] for row in service.list_active_categories()}
        manageable = service.list_manageable_categories()

        self.assertNotIn(category["id"], active_ids)
        self.assertTrue(
            any(
                row["id"] == category["id"]
                and row["name"] == "New Name"
                and row["is_active"] == 0
                for row in manageable
            )
        )

    def test_delete_category_clears_product_assignments_and_hides_category(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("GPT Plus", "100.000Ä‘")
        category = service.create_category("ChatGPT")
        service.assign_product_category(product["id"], category["id"])

        service.delete_category(category["id"])

        stored_product = repositories.Repository(self.db_path).get_product(product["id"])
        active_ids = {row["id"] for row in service.list_active_categories()}
        manageable_ids = {row["id"] for row in service.list_manageable_categories()}

        self.assertIsNone(stored_product["category_id"])
        self.assertNotIn(category["id"], active_ids)
        self.assertNotIn(category["id"], manageable_ids)


    def test_create_category_accepts_description(self):
        service = services.ShopService(self.db_path)

        category = service.create_category("Google AI", "Shared category note")

        self.assertEqual(category["description"], "Shared category note")

    def test_update_category_description(self):
        service = services.ShopService(self.db_path)
        category = service.create_category("Google AI")

        updated = service.update_category_description(category["id"], "Updated category note")

        self.assertEqual(updated["description"], "Updated category note")

    def test_get_resolved_product_description_prefers_product_description(self):
        service = services.ShopService(self.db_path)
        category = service.create_category("Google AI", "Category note")
        product = service.create_product("Google AI Pro", "30.000đ")
        service.assign_product_category(product["id"], category["id"])
        service.update_product_description(product["id"], "Product override")

        description = service.get_resolved_product_description(product["id"])

        self.assertEqual(description, "Product override")

    def test_get_resolved_product_description_falls_back_to_category(self):
        service = services.ShopService(self.db_path)
        category = service.create_category("Google AI", "Category note")
        product = service.create_product("Google AI Pro", "30.000đ")
        service.assign_product_category(product["id"], category["id"])

        description = service.get_resolved_product_description(product["id"])

        self.assertEqual(description, "Category note")

    def test_get_resolved_product_description_returns_empty_when_no_description_exists(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("No Description", "10.000đ")

        description = service.get_resolved_product_description(product["id"])

        self.assertEqual(description, "")


    def test_delete_category_products_deletes_all_clean_products(self):
        service = services.ShopService(self.db_path)
        category = service.create_category("Cat A")
        prod1 = service.create_product("P1", "1.000đ")
        prod2 = service.create_product("P2", "2.000đ")
        service.assign_product_category(prod1["id"], category["id"])
        service.assign_product_category(prod2["id"], category["id"])

        summary = service.delete_category_products(category["id"])
        repo = repositories.Repository(self.db_path)

        self.assertEqual(summary["deleted_count"], 2)
        self.assertEqual(set(summary["deleted_names"]), {"P1", "P2"})
        self.assertEqual(summary["skipped_names"], [])
        self.assertIsNone(repo.get_product(prod1["id"]))
        self.assertIsNone(repo.get_product(prod2["id"]))

    def test_delete_category_products_skips_product_with_stock_history(self):
        service = services.ShopService(self.db_path)
        category = service.create_category("Cat A")
        clean = service.create_product("Clean", "1.000đ")
        stocked = service.create_product("Stocked", "2.000đ")
        service.assign_product_category(clean["id"], category["id"])
        service.assign_product_category(stocked["id"], category["id"])

        repo = repositories.Repository(self.db_path)
        repo.add_stock_items(stocked["id"], ["email|pass"], "batch-1")

        summary = service.delete_category_products(category["id"])

        self.assertEqual(summary["deleted_count"], 1)
        self.assertEqual(summary["deleted_names"], ["Clean"])
        self.assertEqual(summary["skipped_names"], ["Stocked"])
        self.assertIsNone(repo.get_product(clean["id"]))
        self.assertIsNotNone(repo.get_product(stocked["id"]))

    def test_delete_category_products_skips_product_with_order_history(self):
        service = services.ShopService(self.db_path)
        category = service.create_category("Cat A")
        clean = service.create_product("Clean", "1.000đ")
        ordered = service.create_product("Ordered", "2.000đ")
        service.assign_product_category(clean["id"], category["id"])
        service.assign_product_category(ordered["id"], category["id"])

        repo = repositories.Repository(self.db_path)
        repo.create_order(
            order_id="ORD-1",
            order_code=100001,
            user_id=1,
            username="@u",
            full_name="User",
            product_id=ordered["id"],
            qty=1,
            unit_price=2000,
            total_amount=2000,
            status="pending_payment",
            payos_ref=None,
            note=None,
            created_at=123,
        )

        summary = service.delete_category_products(category["id"])

        self.assertEqual(summary["deleted_count"], 1)
        self.assertEqual(summary["deleted_names"], ["Clean"])
        self.assertEqual(summary["skipped_names"], ["Ordered"])
        self.assertIsNone(repo.get_product(clean["id"]))
        self.assertIsNotNone(repo.get_product(ordered["id"]))

    def test_delete_category_products_returns_zero_for_empty_category(self):
        service = services.ShopService(self.db_path)
        category = service.create_category("Empty")

        summary = service.delete_category_products(category["id"])

        self.assertEqual(summary["deleted_count"], 0)
        self.assertEqual(summary["deleted_names"], [])
        self.assertEqual(summary["skipped_names"], [])

    def test_delete_category_products_raises_for_missing_category(self):
        service = services.ShopService(self.db_path)

        with self.assertRaisesRegex(ValueError, "Category does not exist"):
            service.delete_category_products("cat_missing")


class CapcutSyncServiceTests(SQLiteServiceTestCase):
    def test_sync_capcut_products_creates_category_and_new_products(self):
        service = services.ShopService(self.db_path)

        summary = service.sync_capcut_products(
            [
                {"id": "cc_1", "name": "CapCut Pro 1 tháng", "price": 30000, "stock": 40},
                {"id": "x_1", "name": "Netflix 1 tháng", "price": 50000, "stock": 5},
            ]
        )

        categories = service.list_active_categories()
        category = next(row for row in categories if row["name"] == "Tài khoản CapCut")
        products = service.list_products_for_category(category["id"])

        self.assertEqual(summary["created"], 1)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["hidden"], 0)
        self.assertEqual(len(summary["errors"]), 0)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["name"], "CapCut Pro 1 tháng")
        self.assertEqual(products[0]["price"], 30000)
        self.assertEqual(products[0]["fulfillment_mode"], "supplier_api")
        self.assertEqual(products[0]["supplier_provider"], "capcut_default")
        self.assertEqual(products[0]["supplier_product_id"], "cc_1")

    def test_sync_capcut_products_updates_name_but_keeps_existing_price(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("Old CapCut Name", "99.000đ")
        service.create_supplier_provider(
            "capcut_default",
            "CapCut Default",
            "node_api",
            "http://node12.zampto.net:20291/api",
            "sk-test",
        )
        service.update_product_fulfillment_mode(product["id"], "supplier_api")
        service.update_product_supplier_provider(product["id"], "capcut_default")
        service.update_product_supplier_product_id(product["id"], "cc_1")

        summary = service.sync_capcut_products(
            [{"id": "cc_1", "name": "CapCut Premium 1 tháng", "price": 30000, "stock": 40}]
        )

        stored = repositories.Repository(self.db_path).get_product(product["id"])
        self.assertEqual(summary["created"], 0)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(stored["name"], "CapCut Premium 1 tháng")
        self.assertEqual(stored["price"], 99000)
        self.assertEqual(stored["is_active"], 1)

    def test_sync_capcut_products_hides_removed_products(self):
        service = services.ShopService(self.db_path)
        product = service.create_product("CapCut Old", "30.000đ")
        service.create_supplier_provider(
            "capcut_default",
            "CapCut Default",
            "node_api",
            "http://node12.zampto.net:20291/api",
            "sk-test",
        )
        service.update_product_fulfillment_mode(product["id"], "supplier_api")
        service.update_product_supplier_provider(product["id"], "capcut_default")
        service.update_product_supplier_product_id(product["id"], "cc_old")

        summary = service.sync_capcut_products(
            [{"id": "cc_1", "name": "CapCut New", "price": 35000, "stock": 10}]
        )

        stored = repositories.Repository(self.db_path).get_product(product["id"])
        self.assertEqual(summary["hidden"], 1)
        self.assertEqual(stored["is_active"], 0)


class AppConfigServiceTests(SQLiteServiceTestCase):
    def test_set_and_get_payos_config(self):
        service = services.ShopService(self.db_path)

        service.set_payos_config("client", "api", "checksum")

        self.assertEqual(
            service.get_payos_config(),
            {
                "client_id": "client",
                "api_key": "api",
                "checksum_key": "checksum",
            },
        )

    def test_clear_payos_config_removes_all_values(self):
        service = services.ShopService(self.db_path)
        service.set_payos_config("client", "api", "checksum")

        service.clear_payos_config()

        self.assertEqual(service.get_payos_config(), {})


class OrderLookupServiceTests(SQLiteServiceTestCase):
    def test_get_order_details_includes_delivered_accounts(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "GPT", 100000)
        repo.add_stock_items("prod_1", ["acc-1", "acc-2"], batch_id="batch-1")

        service = services.ShopService(self.db_path)
        order = service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id="prod_1",
            qty=2,
        )
        service.mark_payment_paid(order["id"], "123456", 200000)

        details = service.get_order_details(order["id"])

        self.assertIsNotNone(details)
        self.assertEqual(details["order"]["id"], order["id"])
        self.assertEqual(details["order"]["status"], "delivered")
        self.assertEqual(details["accounts"], ["acc-1", "acc-2"])

    def test_get_order_details_returns_none_for_unknown_order(self):
        service = services.ShopService(self.db_path)

        self.assertIsNone(service.get_order_details("ORD-UNKNOWN"))


if __name__ == "__main__":
    unittest.main()

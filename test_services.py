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

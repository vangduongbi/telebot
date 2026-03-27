import os
import tempfile
import unittest
import sqlite3

import database
import repositories
import migration


def rows_as_dicts(rows):
    return [dict(row) for row in rows]


def get_table_columns(conn, table_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row["name"] for row in rows]


def get_table_sql(conn, table_name):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row["sql"]


def insert_product(conn, product_id="prod_1"):
    conn.execute(
        """
        INSERT INTO products (id, name, price, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (product_id, "Product", 100000, 1, 1, 1),
    )


def insert_order(conn, order_id="ORD-1", order_code=1001):
    conn.execute(
        """
        INSERT INTO orders (
            id, order_code, user_id, username, full_name, product_id,
            qty, unit_price, total_amount, status, payos_ref, note,
            created_at, paid_at, delivered_at, cancelled_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            order_code,
            1,
            "@user",
            "User",
            "prod_1",
            1,
            100000,
            100000,
            "pending_payment",
            None,
            None,
            1,
            None,
            None,
            None,
        ),
    )


def insert_stock_item(conn, stock_item_id=None, status="available"):
    sql = (
        """
        INSERT INTO stock_items (
            id, product_id, content, status, batch_id,
            reserved_for_order_id, disabled_reason, created_at,
            updated_at, sold_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if stock_item_id is not None
        else """
        INSERT INTO stock_items (
            product_id, content, status, batch_id,
            reserved_for_order_id, disabled_reason, created_at,
            updated_at, sold_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    )
    params = (
        (stock_item_id, "prod_1", "acct-1", status, None, None, None, 1, 1, None)
        if stock_item_id is not None
        else ("prod_1", "acct-1", status, None, None, None, 1, 1, None)
    )
    conn.execute(sql, params)


class SQLiteTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "shop.db")
        database.init_db(self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()


class DatabaseSchemaTests(SQLiteTestCase):
    def test_init_db_creates_expected_tables(self):
        conn = database.get_connection(self.db_path)
        try:
            table_names = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

            expected_columns = {
                "products": [
                    "id",
                    "name",
                    "price",
                    "category_id",
                    "fulfillment_mode",
                    "supplier_product_id",
                    "supplier_provider",
                    "sales_mode",
                    "is_active",
                    "created_at",
                    "updated_at",
                ],
                "categories": [
                    "id",
                    "name",
                    "is_active",
                    "is_deleted",
                    "created_at",
                    "updated_at",
                ],
                "stock_items": [
                    "id",
                    "product_id",
                    "content",
                    "status",
                    "batch_id",
                    "reserved_for_order_id",
                    "disabled_reason",
                    "created_at",
                    "updated_at",
                    "sold_at",
                ],
                "orders": [
                    "id",
                    "order_code",
                    "user_id",
                    "username",
                    "full_name",
                    "product_id",
                    "qty",
                    "unit_price",
                    "total_amount",
                    "status",
                    "payos_ref",
                    "note",
                    "created_at",
                    "paid_at",
                    "delivered_at",
                    "cancelled_at",
                ],
                "order_items": [
                    "id",
                    "order_id",
                    "stock_item_id",
                    "delivered_content",
                    "created_at",
                ],
                "payments": [
                    "id",
                    "order_id",
                    "payos_order_code",
                    "amount",
                    "status",
                    "raw_reference",
                    "created_at",
                    "updated_at",
                ],
                "app_config": [
                    "key",
                    "value",
                    "updated_at",
                ],
            }

            for table_name, expected_columns in expected_columns.items():
                with self.subTest(table=table_name):
                    self.assertIn(table_name, table_names)
                    self.assertEqual(
                        get_table_columns(conn, table_name),
                        expected_columns,
                    )
        finally:
            conn.close()


class ConfigMigrationTests(SQLiteTestCase):
    def test_migrate_json_copies_payos_config_into_app_config(self):
        migration.migrate_json_to_sqlite(
            {
                "products": {},
                "orders": {},
                "config": {
                    "payos": {
                        "client_id": "client-1",
                        "api_key": "api-1",
                        "checksum_key": "checksum-1",
                    }
                },
            },
            self.db_path,
        )

        conn = database.get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT key, value FROM app_config ORDER BY key"
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(
            rows_as_dicts(rows),
            [
                {"key": "payos.api_key", "value": "api-1"},
                {"key": "payos.checksum_key", "value": "checksum-1"},
                {"key": "payos.client_id", "value": "client-1"},
            ],
        )


class ProductRepositoryTests(SQLiteTestCase):
    def test_create_product_persists_integer_price(self):
        repo = repositories.Repository(self.db_path)

        repo.create_product("prod_1", "Product A", 100000)

        row = repo.get_product("prod_1")

        self.assertEqual(row["id"], "prod_1")
        self.assertEqual(row["name"], "Product A")
        self.assertEqual(row["price"], 100000)
        self.assertIsNone(row["supplier_provider"])

    def test_update_product_supplier_provider(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "Product A", 100000)

        row = repo.update_product_supplier_provider("prod_1", "capcut_api")

        self.assertEqual(row["supplier_provider"], "capcut_api")

    def test_get_product_by_supplier_mapping(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "Product A", 100000)
        repo.update_product_supplier_provider("prod_1", "capcut_api")
        repo.update_product_supplier_product_id("prod_1", "cc_1")

        row = repo.get_product_by_supplier_mapping("capcut_api", "cc_1")

        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "prod_1")

    def test_list_products_by_supplier_provider(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "CapCut A", 100000)
        repo.create_product("prod_2", "CapCut B", 120000)
        repo.update_product_supplier_provider("prod_1", "capcut_api")
        repo.update_product_supplier_provider("prod_2", "sumistore")

        rows = repo.list_products_by_supplier_provider("capcut_api")

        self.assertEqual([row["id"] for row in rows], ["prod_1"])

    def test_add_stock_items_persists_one_row_per_content(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "Product A", 100000)

        rows = repo.add_stock_items("prod_1", ["acct-1", "acct-2", "acct-3"], "batch-1")
        counts = repo.count_stock_by_status("prod_1")

        self.assertEqual(len(rows), 3)
        self.assertEqual([row["content"] for row in rows], ["acct-1", "acct-2", "acct-3"])
        self.assertEqual(counts["available"], 3)
        self.assertEqual(counts["reserved"], 0)
        self.assertEqual(counts["sold"], 0)
        self.assertEqual(counts["disabled"], 0)
        self.assertEqual(counts["total"], 3)

    def test_add_stock_items_rejects_string_input(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "Product A", 100000)

        with self.assertRaises(ValueError):
            repo.add_stock_items("prod_1", "acct-1", "batch-1")

    def test_create_order_rejects_string_reserved_stock_item_ids(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "Product A", 100000)

        with self.assertRaises(ValueError):
            repo.create_order(
                order_id="ORD-1",
                order_code=1001,
                user_id=42,
                username="@buyer",
                full_name="Buyer",
                product_id="prod_1",
                qty=1,
                unit_price=100000,
                total_amount=100000,
                reserved_stock_item_ids="1",
            )

    def test_create_order_persists_order_details(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "Product A", 100000)

        order = repo.create_order(
            order_id="ORD-1",
            order_code=1001,
            user_id=42,
            username="@buyer",
            full_name="Buyer",
            product_id="prod_1",
            qty=2,
            unit_price=100000,
            total_amount=200000,
            note="first order",
        )
        stored = repo.get_order("ORD-1")

        self.assertEqual(order["id"], "ORD-1")
        self.assertEqual(stored["order_code"], 1001)
        self.assertEqual(stored["user_id"], 42)
        self.assertEqual(stored["username"], "@buyer")
        self.assertEqual(stored["full_name"], "Buyer")
        self.assertEqual(stored["product_id"], "prod_1")
        self.assertEqual(stored["qty"], 2)
        self.assertEqual(stored["unit_price"], 100000)
        self.assertEqual(stored["total_amount"], 200000)
        self.assertEqual(stored["status"], "pending_payment")
        self.assertEqual(stored["note"], "first order")

    def test_list_reserved_stock_for_order_returns_reserved_rows(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "Product A", 100000)
        stock_rows = repo.add_stock_items("prod_1", ["acct-1", "acct-2"], "batch-1")

        repo.create_order(
            order_id="ORD-1",
            order_code=1001,
            user_id=42,
            username="@buyer",
            full_name="Buyer",
            product_id="prod_1",
            qty=2,
            unit_price=100000,
            total_amount=200000,
            reserved_stock_item_ids=[row["id"] for row in stock_rows],
        )

        reserved_rows = repo.list_reserved_stock_for_order("ORD-1")
        counts = repo.count_stock_by_status("prod_1")

        self.assertEqual([row["content"] for row in reserved_rows], ["acct-1", "acct-2"])
        self.assertTrue(all(row["status"] == "reserved" for row in reserved_rows))
        self.assertTrue(all(row["reserved_for_order_id"] == "ORD-1" for row in reserved_rows))
        self.assertEqual(counts["available"], 0)
        self.assertEqual(counts["reserved"], 2)

    def test_create_order_rolls_back_when_partial_reservation_fails(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "Product A", 100000)
        stock_rows = repo.add_stock_items("prod_1", ["acct-1", "acct-2"], "batch-1")

        with self.assertRaises(ValueError):
            repo.create_order(
                order_id="ORD-1",
                order_code=1001,
                user_id=42,
                username="@buyer",
                full_name="Buyer",
                product_id="prod_1",
                qty=2,
                unit_price=100000,
                total_amount=200000,
                reserved_stock_item_ids=[stock_rows[0]["id"], 999999],
            )

        self.assertIsNone(repo.get_order("ORD-1"))
        counts = repo.count_stock_by_status("prod_1")
        self.assertEqual(counts["available"], 2)
        self.assertEqual(counts["reserved"], 0)

    def test_create_order_rejects_duplicate_reservation_ids(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "Product A", 100000)
        stock_rows = repo.add_stock_items("prod_1", ["acct-1", "acct-2"], "batch-1")

        with self.assertRaises(ValueError):
            repo.create_order(
                order_id="ORD-2",
                order_code=1002,
                user_id=42,
                username="@buyer",
                full_name="Buyer",
                product_id="prod_1",
                qty=2,
                unit_price=100000,
                total_amount=200000,
                reserved_stock_item_ids=[stock_rows[0]["id"], stock_rows[0]["id"]],
            )

        self.assertIsNone(repo.get_order("ORD-2"))
        counts = repo.count_stock_by_status("prod_1")
        reserved_rows = repo.list_reserved_stock_for_order("ORD-2")
        self.assertEqual(counts["available"], 2)
        self.assertEqual(counts["reserved"], 0)
        self.assertEqual(reserved_rows, [])

    def test_schema_includes_status_constraints(self):
        conn = database.get_connection(self.db_path)
        try:
            stock_sql = get_table_sql(conn, "stock_items")
            order_sql = get_table_sql(conn, "orders")

            stock_status_values = ("available", "reserved", "sold", "disabled")
            order_status_values = (
                "pending_payment",
                "paid",
                "delivered",
                "paid_delivery_failed",
                "cancelled",
                "failed",
            )

            with self.subTest(table="stock_items"):
                self.assertIn("CHECK", stock_sql)
                for value in stock_status_values:
                    self.assertIn(value, stock_sql)

            with self.subTest(table="orders"):
                self.assertIn("CHECK", order_sql)
                for value in order_status_values:
                    self.assertIn(value, order_sql)
        finally:
            conn.close()

    def test_invalid_status_values_raise_integrity_error(self):
        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn)

            cases = [
                (
                    "stock_items",
                    """
                    INSERT INTO stock_items (
                        product_id, content, status, batch_id,
                        reserved_for_order_id, disabled_reason, created_at,
                        updated_at, sold_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("prod_1", "acct-1", "broken", None, None, None, 1, 1, None),
                ),
                (
                    "orders",
                    """
                    INSERT INTO orders (
                        id, order_code, user_id, username, full_name, product_id,
                        qty, unit_price, total_amount, status, payos_ref, note,
                        created_at, paid_at, delivered_at, cancelled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ORD-2",
                        1002,
                        1,
                        "@user",
                        "User",
                        "prod_1",
                        1,
                        100000,
                        100000,
                        "invalid",
                        None,
                        None,
                        1,
                        None,
                        None,
                        None,
                    ),
                ),
            ]

            for table_name, sql, params in cases:
                with self.subTest(table=table_name):
                    with self.assertRaises(sqlite3.IntegrityError):
                        conn.execute(sql, params)
        finally:
            conn.close()

    def test_duplicate_order_code_raises_integrity_error(self):
        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn)
            insert_order(conn, order_id="ORD-1", order_code=1001)

            with self.assertRaises(sqlite3.IntegrityError):
                insert_order(conn, order_id="ORD-2", order_code=1001)
        finally:
            conn.close()

    def test_missing_foreign_keys_raise_integrity_error(self):
        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn)
            insert_order(conn)
            insert_stock_item(conn, stock_item_id=1)

            cases = [
                (
                    "missing_order",
                    """
                    INSERT INTO order_items (
                        order_id, stock_item_id, delivered_content, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    ("ORD-missing", 1, "acct-1", 1),
                ),
                (
                    "missing_stock_item",
                    """
                    INSERT INTO order_items (
                        order_id, stock_item_id, delivered_content, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    ("ORD-1", 999, "acct-1", 1),
                ),
            ]

            for case_name, sql, params in cases:
                with self.subTest(case=case_name):
                    with self.assertRaises(sqlite3.IntegrityError):
                        conn.execute(sql, params)
        finally:
            conn.close()

    def test_invalid_reserved_for_order_id_raises_integrity_error(self):
        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO stock_items (
                        product_id, content, status, batch_id,
                        reserved_for_order_id, disabled_reason, created_at,
                        updated_at, sold_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("prod_1", "acct-1", "reserved", None, "ORD-missing", None, 1, 1, None),
                )
        finally:
            conn.close()


class MigrationTests(SQLiteTestCase):
    def test_migrate_json_creates_products_stock_and_orders(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["a|b", "c|d"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["a|b"],
                    "time": 123,
                }
            },
        }

        migration.migrate_json_to_sqlite(sample, self.db_path)

        repo = repositories.Repository(self.db_path)
        conn = database.get_connection(self.db_path)
        try:
            self.assertEqual(repo.get_product("prod_1")["price"], 100000)
            self.assertEqual(repo.count_stock_by_status("prod_1")["available"], 2)
            self.assertEqual(repo.get_order("ORD-1")["status"], "delivered")

            order_items = conn.execute(
                "SELECT delivered_content FROM order_items WHERE order_id = ? ORDER BY id",
                ("ORD-1",),
            ).fetchall()
            self.assertEqual([row["delivered_content"] for row in order_items], ["a|b"])
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM order_items WHERE order_id = ?",
                    ("ORD-1",),
                ).fetchone()["count"],
                1,
            )
        finally:
            conn.close()

    def test_migrate_json_creates_fallback_stock_for_delivered_accounts_when_no_stock_exists(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": [],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 2,
                    "accounts": ["a|b", "c|d"],
                    "time": 123,
                }
            },
        }

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            counts = repositories.Repository(self.db_path).count_stock_by_status("prod_1")
            order_items = conn.execute(
                "SELECT delivered_content, stock_item_id FROM order_items WHERE order_id = ? ORDER BY id",
                ("ORD-1",),
            ).fetchall()

            self.assertEqual(counts["available"], 0)
            self.assertEqual(counts["sold"], 2)
            self.assertEqual([row["delivered_content"] for row in order_items], ["a|b", "c|d"])
            self.assertEqual(len({row["stock_item_id"] for row in order_items}), 2)
        finally:
            conn.close()

    def test_migrate_json_generates_unique_order_codes_from_full_legacy_order_ids(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["acct-1", "acct-2", "acct-3"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u1",
                    "full_name": "User1",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["acct-1"],
                    "time": 123,
                },
                "WEB-1": {
                    "order_id": "WEB-1",
                    "user_id": 2,
                    "username": "@u2",
                    "full_name": "User2",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["acct-2"],
                    "time": 124,
                },
                "INV-XYZ": {
                    "order_id": "INV-XYZ",
                    "user_id": 3,
                    "username": "@u3",
                    "full_name": "User3",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["acct-3"],
                    "time": 125,
                },
            },
        }

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            initial_codes = {
                row["id"]: row["order_code"]
                for row in conn.execute(
                    "SELECT id, order_code FROM orders ORDER BY id"
                ).fetchall()
            }
            initial_order_items = {
                row["order_id"]: row["delivered_content"]
                for row in conn.execute(
                    "SELECT order_id, delivered_content FROM order_items ORDER BY id"
                ).fetchall()
            }

            migration.migrate_json_to_sqlite(sample, self.db_path)

            rerun_codes = {
                row["id"]: row["order_code"]
                for row in conn.execute(
                    "SELECT id, order_code FROM orders ORDER BY id"
                ).fetchall()
            }

            self.assertEqual(initial_codes, rerun_codes)
            self.assertEqual(len(set(initial_codes.values())), 3)
            self.assertNotEqual(initial_codes["ORD-1"], initial_codes["WEB-1"])
            self.assertNotEqual(initial_codes["ORD-1"], initial_codes["INV-XYZ"])
            self.assertNotEqual(initial_codes["WEB-1"], initial_codes["INV-XYZ"])
            self.assertEqual(
                initial_order_items,
                {
                    "ORD-1": "acct-1",
                    "WEB-1": "acct-2",
                    "INV-XYZ": "acct-3",
                },
            )
        finally:
            conn.close()

    def test_migrate_json_uses_payos_ref_for_order_codes_and_resolves_collisions(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["acct-1", "acct-2"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u1",
                    "full_name": "User1",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["acct-1"],
                    "time": 123,
                    "payos_ref": "7777",
                },
                "WEB-1": {
                    "order_id": "WEB-1",
                    "user_id": 2,
                    "username": "@u2",
                    "full_name": "User2",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["acct-2"],
                    "time": 124,
                    "payos_ref": "7777",
                },
            },
        }

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT id, order_code
                FROM orders
                ORDER BY id
                """
            ).fetchall()

            self.assertEqual([row["id"] for row in rows], ["ORD-1", "WEB-1"])
            self.assertEqual([row["order_code"] for row in rows], [7777, 7778])
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM order_items WHERE order_id = ?",
                    ("ORD-1",),
                ).fetchone()["count"],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM order_items WHERE order_id = ?",
                    ("WEB-1",),
                ).fetchone()["count"],
                1,
            )
        finally:
            conn.close()

    def test_migrate_json_backfills_missing_stock_by_content_with_mismatched_existing_rows(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["legacy-a", "legacy-b"],
                }
            },
            "orders": {},
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn)
            insert_stock_item(conn)
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)
        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            available_rows = conn.execute(
                """
                SELECT content
                FROM stock_items
                WHERE product_id = ? AND status = 'available'
                ORDER BY id
                """,
                ("prod_1",),
            ).fetchall()

            self.assertEqual([row["content"] for row in available_rows], ["acct-1", "legacy-a", "legacy-b"])
            self.assertEqual(
                repositories.Repository(self.db_path).count_stock_by_status("prod_1")["available"],
                3,
            )
        finally:
            conn.close()

    def test_migrate_json_backfills_duplicate_stock_content_by_content_not_count(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["legacy-a", "legacy-a"],
                }
            },
            "orders": {},
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn)
            insert_stock_item(conn)
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            available_rows = conn.execute(
                """
                SELECT content
                FROM stock_items
                WHERE product_id = ? AND status = 'available'
                ORDER BY id
                """,
                ("prod_1",),
            ).fetchall()

            self.assertEqual([row["content"] for row in available_rows], ["acct-1", "legacy-a", "legacy-a"])
            self.assertEqual(
                repositories.Repository(self.db_path).count_stock_by_status("prod_1")["available"],
                3,
            )
        finally:
            conn.close()

    def test_migrate_json_uses_fallback_when_available_stock_content_does_not_match(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["current-account|current-pass"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["delivered-account|delivered-pass"],
                    "time": 123,
                }
            },
        }

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            counts = repositories.Repository(self.db_path).count_stock_by_status("prod_1")
            current_row = conn.execute(
                "SELECT id, content, status FROM stock_items WHERE product_id = ? AND content = ?",
                ("prod_1", "current-account|current-pass"),
            ).fetchone()
            order_item_row = conn.execute(
                """
                SELECT oi.stock_item_id, oi.delivered_content, si.content, si.status
                FROM order_items oi
                JOIN stock_items si ON si.id = oi.stock_item_id
                WHERE oi.order_id = ?
                """,
                ("ORD-1",),
            ).fetchone()

            self.assertEqual(counts["available"], 1)
            self.assertEqual(counts["sold"], 1)
            self.assertEqual(current_row["status"], "available")
            self.assertEqual(order_item_row["delivered_content"], "delivered-account|delivered-pass")
            self.assertEqual(order_item_row["content"], "delivered-account|delivered-pass")
            self.assertEqual(order_item_row["status"], "sold")
            self.assertNotEqual(order_item_row["stock_item_id"], current_row["id"])
        finally:
            conn.close()

    def test_migrate_json_uses_distinct_available_stock_rows_for_duplicate_accounts(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["shared", "shared"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 2,
                    "accounts": ["shared", "shared"],
                    "time": 123,
                }
            },
        }

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            counts = repositories.Repository(self.db_path).count_stock_by_status("prod_1")
            order_items = conn.execute(
                """
                SELECT delivered_content, stock_item_id
                FROM order_items
                WHERE order_id = ?
                ORDER BY id
                """,
                ("ORD-1",),
            ).fetchall()
            orphan_rows = conn.execute(
                """
                SELECT id
                FROM stock_items
                WHERE batch_id = ?
                """,
                ("migration:order:ORD-1",),
            ).fetchall()

            self.assertEqual(counts["available"], 2)
            self.assertEqual([row["delivered_content"] for row in order_items], ["shared", "shared"])
            self.assertEqual(len({row["stock_item_id"] for row in order_items}), 2)
            self.assertEqual(orphan_rows, [])
        finally:
            conn.close()

    def test_migrate_json_repairs_stale_order_codes_from_old_versioned_database(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["acct-1", "acct-2"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u1",
                    "full_name": "User1",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["acct-1"],
                    "time": 123,
                    "payos_ref": "7777",
                },
                "WEB-1": {
                    "order_id": "WEB-1",
                    "user_id": 2,
                    "username": "@u2",
                    "full_name": "User2",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["acct-2"],
                    "time": 124,
                    "payos_ref": "7777",
                },
            },
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn, product_id="prod_1")
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "prod_1", "acct-1", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (2, "prod_1", "acct-2", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO orders (
                    id, order_code, user_id, username, full_name, product_id,
                    qty, unit_price, total_amount, status, payos_ref, note,
                    created_at, paid_at, delivered_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("OTHER-1", 7777, 99, "@other", "Other", "prod_1", 1, 100000, 100000, "pending_payment", None, None, 1, None, None, None),
            )
            conn.execute(
                """
                INSERT INTO orders (
                    id, order_code, user_id, username, full_name, product_id,
                    qty, unit_price, total_amount, status, payos_ref, note,
                    created_at, paid_at, delivered_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("ORD-1", 1111, 1, "@u1", "User1", "prod_1", 1, 100000, 100000, "delivered", "7777", None, 1, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO orders (
                    id, order_code, user_id, username, full_name, product_id,
                    qty, unit_price, total_amount, status, payos_ref, note,
                    created_at, paid_at, delivered_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("WEB-1", 2222, 2, "@u2", "User2", "prod_1", 1, 100000, 100000, "delivered", "7777", None, 2, 2, 2, None),
            )
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 1, "acct-1", 1),
            )
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("WEB-1", 2, "acct-2", 2),
            )
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)
        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT id, order_code
                FROM orders
                ORDER BY id
                """
            ).fetchall()
            version = conn.execute("PRAGMA user_version").fetchone()[0]

            self.assertEqual([row["id"] for row in rows], ["ORD-1", "OTHER-1", "WEB-1"])
            self.assertEqual([row["order_code"] for row in rows], [7778, 7777, 7779])
            self.assertEqual(version, 2)
        finally:
            conn.close()

    def test_migrate_json_cleans_stray_order_items_for_pending_order(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["acct-1"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u1",
                    "full_name": "User1",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": [],
                    "time": 123,
                }
            },
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn, product_id="prod_1")
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "prod_1", "acct-1", "sold", "migration:order:ORD-1", None, None, 1, 1, 1),
            )
            conn.execute(
                """
                INSERT INTO orders (
                    id, order_code, user_id, username, full_name, product_id,
                    qty, unit_price, total_amount, status, payos_ref, note,
                    created_at, paid_at, delivered_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("ORD-1", 1111, 1, "@u1", "User1", "prod_1", 1, 100000, 100000, "delivered", None, None, 1, 1, 1, 1),
            )
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 1, "acct-1", 1),
            )
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            order_items_count = conn.execute(
                "SELECT COUNT(*) AS count FROM order_items WHERE order_id = ?",
                ("ORD-1",),
            ).fetchone()["count"]
            order_row = conn.execute(
                """
                SELECT status, paid_at, delivered_at, cancelled_at
                FROM orders
                WHERE id = ?
                """,
                ("ORD-1",),
            ).fetchone()
            orphan_rows = conn.execute(
                """
                SELECT id
                FROM stock_items
                WHERE batch_id LIKE 'migration:order:%'
                """,
            ).fetchall()

            self.assertEqual(order_items_count, 0)
            self.assertEqual(order_row["status"], "pending_payment")
            self.assertIsNone(order_row["paid_at"])
            self.assertIsNone(order_row["delivered_at"])
            self.assertIsNone(order_row["cancelled_at"])
            self.assertEqual(orphan_rows, [])
        finally:
            conn.close()

    def test_migrate_json_repairs_stale_order_lifecycle_when_order_items_are_already_correct(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["acct-1"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u1",
                    "full_name": "User1",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["acct-1"],
                    "time": 123,
                    "payos_ref": "8888",
                }
            },
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn, product_id="prod_1")
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "prod_1", "acct-1", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO orders (
                    id, order_code, user_id, username, full_name, product_id,
                    qty, unit_price, total_amount, status, payos_ref, note,
                    created_at, paid_at, delivered_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("ORD-1", 8888, 1, "@u1", "User1", "prod_1", 1, 100000, 100000, "pending_payment", "8888", None, 1, None, None, None),
            )
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 1, "acct-1", 1),
            )
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            order_row = conn.execute(
                """
                SELECT status, paid_at, delivered_at, cancelled_at
                FROM orders
                WHERE id = ?
                """,
                ("ORD-1",),
            ).fetchone()
            order_items_count = conn.execute(
                "SELECT COUNT(*) AS count FROM order_items WHERE order_id = ?",
                ("ORD-1",),
            ).fetchone()["count"]

            self.assertEqual(order_row["status"], "delivered")
            self.assertEqual(order_row["paid_at"], 1)
            self.assertEqual(order_row["delivered_at"], 1)
            self.assertIsNone(order_row["cancelled_at"])
            self.assertEqual(order_items_count, 1)
        finally:
            conn.close()

    def test_migrate_json_repairs_partial_dataset_when_products_and_orders_exist_but_stock_or_order_items_missing(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["legacy-a", "legacy-b"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["legacy-a"],
                    "time": 123,
                }
            },
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn)
            insert_order(conn)
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            counts = repositories.Repository(self.db_path).count_stock_by_status("prod_1")
            available_rows = conn.execute(
                """
                SELECT content
                FROM stock_items
                WHERE product_id = ? AND status = 'available'
                ORDER BY id
                """,
                ("prod_1",),
            ).fetchall()
            order_items = conn.execute(
                """
                SELECT delivered_content
                FROM order_items
                WHERE order_id = ?
                ORDER BY id
                """,
                ("ORD-1",),
            ).fetchall()

            self.assertEqual([row["content"] for row in available_rows], ["legacy-a", "legacy-b"])
            self.assertEqual(counts["available"], 2)
            self.assertEqual([row["delivered_content"] for row in order_items], ["legacy-a"])
        finally:
            conn.close()

    def test_migrate_json_repairs_partial_db_then_reruns_idempotently(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["shared", "shared"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 2,
                    "accounts": ["shared", "shared"],
                    "time": 123,
                }
            },
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn)
            insert_order(conn)
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            counts = repositories.Repository(self.db_path).count_stock_by_status("prod_1")
            order_items = conn.execute(
                """
                SELECT delivered_content, stock_item_id
                FROM order_items
                WHERE order_id = ?
                ORDER BY id
                """,
                ("ORD-1",),
            ).fetchall()
            available_rows = conn.execute(
                """
                SELECT content
                FROM stock_items
                WHERE product_id = ? AND status = 'available'
                ORDER BY id
                """,
                ("prod_1",),
            ).fetchall()

            self.assertEqual(counts["available"], 2)
            self.assertEqual([row["content"] for row in available_rows], ["shared", "shared"])
            self.assertEqual([row["delivered_content"] for row in order_items], ["shared", "shared"])
            self.assertEqual(len({row["stock_item_id"] for row in order_items}), 2)
            self.assertEqual(len(order_items), 2)
        finally:
            conn.close()

    def test_migrate_json_repairs_reused_stock_item_references_even_when_counts_match(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["shared", "shared"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 2,
                    "accounts": ["shared", "shared"],
                    "time": 123,
                }
            },
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn)
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "prod_1", "shared", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (2, "prod_1", "shared", "available", None, None, None, 1, 1, None),
            )
            insert_order(conn)
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 1, "shared", 1),
            )
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 1, "shared", 1),
            )
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            counts = repositories.Repository(self.db_path).count_stock_by_status("prod_1")
            order_items = conn.execute(
                """
                SELECT delivered_content, stock_item_id
                FROM order_items
                WHERE order_id = ?
                ORDER BY id
                """,
                ("ORD-1",),
            ).fetchall()

            self.assertEqual(counts["available"], 2)
            self.assertEqual([row["delivered_content"] for row in order_items], ["shared", "shared"])
            self.assertEqual(len({row["stock_item_id"] for row in order_items}), 2)
        finally:
            conn.close()

    def test_migrate_json_repairs_wrong_product_stock_reference(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "Product 1",
                    "price": "100.000đ",
                    "stock": ["shared"],
                },
                "prod_2": {
                    "name": "Product 2",
                    "price": "200.000đ",
                    "stock": ["shared"],
                },
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "Product 1",
                    "qty": 1,
                    "accounts": ["shared"],
                    "time": 123,
                }
            },
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn, product_id="prod_1")
            conn.execute(
                """
                INSERT INTO products (id, name, price, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("prod_2", "Product 2", 200000, 1, 1, 1),
            )
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "prod_1", "shared", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (2, "prod_2", "shared", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO orders (
                    id, order_code, user_id, username, full_name, product_id,
                    qty, unit_price, total_amount, status, payos_ref, note,
                    created_at, paid_at, delivered_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("ORD-1", 1001, 1, "@u", "User", "prod_1", 1, 100000, 100000, "delivered", None, None, 1, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 2, "shared", 1),
            )
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)
        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            order_item = conn.execute(
                """
                SELECT oi.stock_item_id, si.product_id, si.content
                FROM order_items oi
                JOIN stock_items si ON si.id = oi.stock_item_id
                WHERE oi.order_id = ?
                """,
                ("ORD-1",),
            ).fetchone()

            self.assertEqual(order_item["product_id"], "prod_1")
            self.assertEqual(order_item["content"], "shared")
            self.assertEqual(order_item["stock_item_id"], 1)
        finally:
            conn.close()

    def test_migrate_json_repairs_wrong_product_reference_on_old_versioned_database(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "Product 1",
                    "price": "100.000đ",
                    "stock": ["shared"],
                },
                "prod_2": {
                    "name": "Product 2",
                    "price": "200.000đ",
                    "stock": ["shared"],
                },
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "Product 1",
                    "qty": 1,
                    "accounts": ["shared"],
                    "time": 123,
                }
            },
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn, product_id="prod_1")
            conn.execute(
                """
                INSERT INTO products (id, name, price, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("prod_2", "Product 2", 200000, 1, 1, 1),
            )
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "prod_1", "shared", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (2, "prod_2", "shared", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO orders (
                    id, order_code, user_id, username, full_name, product_id,
                    qty, unit_price, total_amount, status, payos_ref, note,
                    created_at, paid_at, delivered_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("ORD-1", 1001, 1, "@u", "User", "prod_1", 1, 100000, 100000, "delivered", None, None, 1, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 2, "shared", 1),
            )
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            order_item = conn.execute(
                """
                SELECT oi.stock_item_id, si.product_id, si.content
                FROM order_items oi
                JOIN stock_items si ON si.id = oi.stock_item_id
                WHERE oi.order_id = ?
                """,
                ("ORD-1",),
            ).fetchone()
            version = conn.execute("PRAGMA user_version").fetchone()[0]

            self.assertEqual(order_item["product_id"], "prod_1")
            self.assertEqual(order_item["stock_item_id"], 1)
            self.assertEqual(order_item["content"], "shared")
            self.assertEqual(version, 2)
        finally:
            conn.close()

    def test_migrate_json_upgrades_versioned_complete_database_without_changing_data(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "Product 1",
                    "price": "100.000đ",
                    "stock": ["shared"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "Product 1",
                    "qty": 1,
                    "accounts": ["shared"],
                    "time": 123,
                }
            },
        }

        canonical_order_code = migration._order_code_for("ORD-1", {})

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn, product_id="prod_1")
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "prod_1", "shared", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO orders (
                    id, order_code, user_id, username, full_name, product_id,
                    qty, unit_price, total_amount, status, payos_ref, note,
                    created_at, paid_at, delivered_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("ORD-1", canonical_order_code, 1, "@u", "User", "prod_1", 1, 100000, 100000, "delivered", None, None, 1, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 1, "shared", 1),
            )
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
            before_snapshot = {
                "products": rows_as_dicts(conn.execute(
                    "SELECT id, name, price, is_active, created_at, updated_at FROM products ORDER BY id"
                ).fetchall()),
                "orders": rows_as_dicts(conn.execute(
                    """
                    SELECT id, order_code, user_id, username, full_name, product_id,
                           qty, unit_price, total_amount, status, payos_ref, note,
                           created_at, paid_at, delivered_at, cancelled_at
                    FROM orders
                    ORDER BY id
                    """
                ).fetchall()),
                "order_items": rows_as_dicts(conn.execute(
                    """
                    SELECT id, order_id, stock_item_id, delivered_content, created_at
                    FROM order_items
                    ORDER BY id
                    """
                ).fetchall()),
                "stock_items": rows_as_dicts(conn.execute(
                    """
                    SELECT id, product_id, content, status, batch_id,
                           reserved_for_order_id, disabled_reason, created_at,
                           updated_at, sold_at
                    FROM stock_items
                    ORDER BY id
                    """
                ).fetchall()),
            }
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            counts = repositories.Repository(self.db_path).count_stock_by_status("prod_1")
            order_items = conn.execute(
                """
                SELECT delivered_content, stock_item_id
                FROM order_items
                WHERE order_id = ?
                ORDER BY id
                """,
                ("ORD-1",),
            ).fetchall()
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            products_count = conn.execute(
                "SELECT COUNT(*) AS count FROM products"
            ).fetchone()["count"]
            orders_count = conn.execute(
                "SELECT COUNT(*) AS count FROM orders"
            ).fetchone()["count"]
            order_items_count = conn.execute(
                "SELECT COUNT(*) AS count FROM order_items"
            ).fetchone()["count"]
            stock_items_count = conn.execute(
                "SELECT COUNT(*) AS count FROM stock_items"
            ).fetchone()["count"]
            after_snapshot = {
                "products": rows_as_dicts(conn.execute(
                    "SELECT id, name, price, is_active, created_at, updated_at FROM products ORDER BY id"
                ).fetchall()),
                "orders": rows_as_dicts(conn.execute(
                    """
                    SELECT id, order_code, user_id, username, full_name, product_id,
                           qty, unit_price, total_amount, status, payos_ref, note,
                           created_at, paid_at, delivered_at, cancelled_at
                    FROM orders
                    ORDER BY id
                    """
                ).fetchall()),
                "order_items": rows_as_dicts(conn.execute(
                    """
                    SELECT id, order_id, stock_item_id, delivered_content, created_at
                    FROM order_items
                    ORDER BY id
                    """
                ).fetchall()),
                "stock_items": rows_as_dicts(conn.execute(
                    """
                    SELECT id, product_id, content, status, batch_id,
                           reserved_for_order_id, disabled_reason, created_at,
                           updated_at, sold_at
                    FROM stock_items
                    ORDER BY id
                    """
                ).fetchall()),
            }

            self.assertEqual(counts["available"], 1)
            self.assertEqual([row["delivered_content"] for row in order_items], ["shared"])
            self.assertEqual([row["stock_item_id"] for row in order_items], [1])
            self.assertEqual(products_count, 1)
            self.assertEqual(orders_count, 1)
            self.assertEqual(order_items_count, 1)
            self.assertEqual(stock_items_count, 1)
            self.assertEqual(version, 2)
            self.assertEqual(before_snapshot["products"], after_snapshot["products"])
            self.assertEqual(before_snapshot["orders"], after_snapshot["orders"])
            self.assertEqual(before_snapshot["order_items"], after_snapshot["order_items"])
            self.assertEqual(before_snapshot["stock_items"], after_snapshot["stock_items"])
        finally:
            conn.close()

    def test_migrate_json_cleans_orphan_migration_stock_rows_on_complete_database(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "Product 1",
                    "price": "100.000đ",
                    "stock": ["shared"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "Product 1",
                    "qty": 1,
                    "accounts": ["shared"],
                    "time": 123,
                }
            },
        }

        canonical_order_code = migration._order_code_for("ORD-1", {})

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn, product_id="prod_1")
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "prod_1", "shared", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO orders (
                    id, order_code, user_id, username, full_name, product_id,
                    qty, unit_price, total_amount, status, payos_ref, note,
                    created_at, paid_at, delivered_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("ORD-1", canonical_order_code, 1, "@u", "User", "prod_1", 1, 100000, 100000, "delivered", None, None, 1, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 1, "shared", 1),
            )
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (2, "prod_1", "orphaned", "sold", "migration:order:ORD-1", None, None, 1, 1, 1),
            )
            conn.execute("PRAGMA user_version = 2")
            conn.commit()
            before_snapshot = {
                "products": rows_as_dicts(conn.execute(
                    "SELECT id, name, price, is_active, created_at, updated_at FROM products ORDER BY id"
                ).fetchall()),
                "orders": rows_as_dicts(conn.execute(
                    """
                    SELECT id, order_code, user_id, username, full_name, product_id,
                           qty, unit_price, total_amount, status, payos_ref, note,
                           created_at, paid_at, delivered_at, cancelled_at
                    FROM orders
                    ORDER BY id
                    """
                ).fetchall()),
                "order_items": rows_as_dicts(conn.execute(
                    """
                    SELECT id, order_id, stock_item_id, delivered_content, created_at
                    FROM order_items
                    ORDER BY id
                    """
                ).fetchall()),
                "stock_items": rows_as_dicts(conn.execute(
                    """
                    SELECT id, product_id, content, status, batch_id,
                           reserved_for_order_id, disabled_reason, created_at,
                           updated_at, sold_at
                    FROM stock_items
                    WHERE batch_id IS NULL
                    ORDER BY id
                    """
                ).fetchall()),
            }
            before_total_stock_items = conn.execute(
                "SELECT COUNT(*) AS count FROM stock_items"
            ).fetchone()["count"]
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            orphan_rows = conn.execute(
                """
                SELECT id
                FROM stock_items
                WHERE batch_id LIKE 'migration:order:%'
                """,
            ).fetchall()
            after_snapshot = {
                "products": rows_as_dicts(conn.execute(
                    "SELECT id, name, price, is_active, created_at, updated_at FROM products ORDER BY id"
                ).fetchall()),
                "orders": rows_as_dicts(conn.execute(
                    """
                    SELECT id, order_code, user_id, username, full_name, product_id,
                           qty, unit_price, total_amount, status, payos_ref, note,
                           created_at, paid_at, delivered_at, cancelled_at
                    FROM orders
                    ORDER BY id
                    """
                ).fetchall()),
                "order_items": rows_as_dicts(conn.execute(
                    """
                    SELECT id, order_id, stock_item_id, delivered_content, created_at
                    FROM order_items
                    ORDER BY id
                    """
                ).fetchall()),
                "stock_items": rows_as_dicts(conn.execute(
                    """
                    SELECT id, product_id, content, status, batch_id,
                           reserved_for_order_id, disabled_reason, created_at,
                           updated_at, sold_at
                    FROM stock_items
                    WHERE batch_id IS NULL
                    ORDER BY id
                    """
                ).fetchall()),
            }
            after_total_stock_items = conn.execute(
                "SELECT COUNT(*) AS count FROM stock_items"
            ).fetchone()["count"]
            version = conn.execute("PRAGMA user_version").fetchone()[0]

            self.assertEqual(orphan_rows, [])
            self.assertEqual(before_snapshot, after_snapshot)
            self.assertEqual(before_total_stock_items, 2)
            self.assertEqual(after_total_stock_items, 1)
            self.assertEqual(version, 2)
        finally:
            conn.close()

    def test_migrate_json_repairs_cross_order_stock_item_reuse(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["shared", "shared"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u1",
                    "full_name": "User1",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["shared"],
                    "time": 123,
                },
                "ORD-2": {
                    "order_id": "ORD-2",
                    "user_id": 2,
                    "username": "@u2",
                    "full_name": "User2",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["shared"],
                    "time": 124,
                },
            },
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn)
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "prod_1", "shared", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (2, "prod_1", "shared", "available", None, None, None, 1, 1, None),
            )
            insert_order(conn, order_id="ORD-1", order_code=1001)
            insert_order(conn, order_id="ORD-2", order_code=1002)
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 1, "shared", 1),
            )
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-2", 1, "shared", 1),
            )
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)
        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            orphan_rows = conn.execute(
                """
                SELECT id
                FROM stock_items
                WHERE batch_id = ?
                """,
                ("migration:order:ORD-1",),
            ).fetchall()
            order_items = conn.execute(
                """
                SELECT order_id, delivered_content, stock_item_id
                FROM order_items
                WHERE order_id IN (?, ?)
                ORDER BY order_id, id
                """,
                ("ORD-1", "ORD-2"),
            ).fetchall()

            self.assertEqual([row["order_id"] for row in order_items], ["ORD-1", "ORD-2"])
            self.assertEqual([row["delivered_content"] for row in order_items], ["shared", "shared"])
            self.assertEqual(len({row["stock_item_id"] for row in order_items}), 2)
            self.assertEqual(orphan_rows, [])
        finally:
            conn.close()

    def test_migrate_json_trims_surplus_order_items_on_repair(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["shared", "shared"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["shared"],
                    "time": 123,
                }
            },
        }

        conn = database.get_connection(self.db_path)
        try:
            insert_product(conn)
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "prod_1", "shared", "available", None, None, None, 1, 1, None),
            )
            conn.execute(
                """
                INSERT INTO stock_items (
                    id, product_id, content, status, batch_id,
                    reserved_for_order_id, disabled_reason, created_at,
                    updated_at, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (2, "prod_1", "shared", "available", None, None, None, 1, 1, None),
            )
            insert_order(conn, order_id="ORD-1", order_code=1001)
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 1, "shared", 1),
            )
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, stock_item_id, delivered_content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("ORD-1", 2, "shared", 1),
            )
            conn.commit()
        finally:
            conn.close()

        migration.migrate_json_to_sqlite(sample, self.db_path)
        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            order_items = conn.execute(
                """
                SELECT delivered_content, stock_item_id
                FROM order_items
                WHERE order_id = ?
                ORDER BY id
                """,
                ("ORD-1",),
            ).fetchall()

            self.assertEqual(len(order_items), 1)
            self.assertEqual([row["delivered_content"] for row in order_items], ["shared"])
            self.assertEqual(len({row["stock_item_id"] for row in order_items}), 1)
        finally:
            conn.close()

    def test_migrate_json_is_idempotent_on_rerun(self):
        sample = {
            "products": {
                "prod_1": {
                    "name": "GPT",
                    "price": "100.000đ",
                    "stock": ["a|b", "c|d"],
                }
            },
            "orders": {
                "ORD-1": {
                    "order_id": "ORD-1",
                    "user_id": 1,
                    "username": "@u",
                    "full_name": "User",
                    "product_id": "prod_1",
                    "product_name": "GPT",
                    "qty": 1,
                    "accounts": ["a|b"],
                    "time": 123,
                }
            },
        }

        migration.migrate_json_to_sqlite(sample, self.db_path)
        migration.migrate_json_to_sqlite(sample, self.db_path)

        conn = database.get_connection(self.db_path)
        try:
            counts = repositories.Repository(self.db_path).count_stock_by_status("prod_1")
            product_count = conn.execute(
                "SELECT COUNT(*) AS count FROM products"
            ).fetchone()["count"]
            order_count = conn.execute(
                "SELECT COUNT(*) AS count FROM orders"
            ).fetchone()["count"]
            order_item_count = conn.execute(
                "SELECT COUNT(*) AS count FROM order_items"
            ).fetchone()["count"]

            self.assertEqual(product_count, 1)
            self.assertEqual(order_count, 1)
            self.assertEqual(order_item_count, 1)
            self.assertEqual(counts["available"], 2)
        finally:
            conn.close()

import time

import database


class Repository:
    def __init__(self, db_path="shop.db"):
        self.db_path = db_path

    def _now(self):
        return int(time.time())

    def create_product(self, product_id, name, price):
        now = self._now()
        with database.transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO products (
                    id, name, price, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?)
                """,
                (product_id, name, int(price), now, now),
            )
            return conn.execute(
                "SELECT * FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()

    def list_active_products(self):
        conn = database.get_connection(self.db_path)
        try:
            return conn.execute(
                """
                SELECT *
                FROM products
                WHERE is_active = 1
                ORDER BY id
                """
            ).fetchall()
        finally:
            conn.close()

    def get_product(self, product_id):
        conn = database.get_connection(self.db_path)
        try:
            return conn.execute(
                "SELECT * FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()
        finally:
            conn.close()

    def update_product_name(self, product_id, name):
        now = self._now()
        with database.transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE products
                SET name = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, now, product_id),
            )
            return conn.execute(
                "SELECT * FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()

    def update_product_price(self, product_id, price):
        now = self._now()
        with database.transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE products
                SET price = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(price), now, product_id),
            )
            return conn.execute(
                "SELECT * FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()

    def deactivate_product(self, product_id):
        now = self._now()
        with database.transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE products
                SET is_active = 0, updated_at = ?
                WHERE id = ?
                """,
                (now, product_id),
            )
            return conn.execute(
                "SELECT * FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()

    def add_stock_items(self, product_id, contents, batch_id):
        if isinstance(contents, (str, bytes, bytearray)):
            raise ValueError("contents must be an iterable of stock item strings")

        contents = list(contents)
        if not contents:
            return []

        now = self._now()
        rows = []
        with database.transaction(self.db_path) as conn:
            for content in contents:
                cursor = conn.execute(
                    """
                    INSERT INTO stock_items (
                        product_id, content, status, batch_id,
                        reserved_for_order_id, disabled_reason, created_at,
                        updated_at, sold_at
                    ) VALUES (?, ?, 'available', ?, NULL, NULL, ?, ?, NULL)
                    """,
                    (product_id, content, batch_id, now, now),
                )
                rows.append(
                    conn.execute(
                        "SELECT * FROM stock_items WHERE id = ?",
                        (cursor.lastrowid,),
                    ).fetchone()
                )
        return rows

    def count_stock_by_status(self, product_id):
        counts = {
            "available": 0,
            "reserved": 0,
            "sold": 0,
            "disabled": 0,
        }
        conn = database.get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM stock_items
                WHERE product_id = ?
                GROUP BY status
                """,
                (product_id,),
            ).fetchall()
            for row in rows:
                counts[row["status"]] = row["count"]
        finally:
            conn.close()
        counts["total"] = sum(counts.values())
        return counts

    def list_available_stock(self, product_id, limit=None):
        conn = database.get_connection(self.db_path)
        try:
            sql = """
                SELECT *
                FROM stock_items
                WHERE product_id = ? AND status = 'available'
                ORDER BY id
            """
            params = [product_id]
            if limit is not None:
                sql += " LIMIT ?"
                params.append(int(limit))
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def create_order(
        self,
        order_id,
        order_code,
        user_id,
        username,
        full_name,
        product_id,
        qty,
        unit_price,
        total_amount,
        status="pending_payment",
        payos_ref=None,
        note=None,
        created_at=None,
        paid_at=None,
        delivered_at=None,
        cancelled_at=None,
        reserved_stock_item_ids=None,
    ):
        if isinstance(reserved_stock_item_ids, (str, bytes, bytearray)):
            raise ValueError("reserved_stock_item_ids must be an iterable of stock item IDs")

        reserved_stock_item_ids = list(reserved_stock_item_ids or [])
        if len(set(reserved_stock_item_ids)) != len(reserved_stock_item_ids):
            raise ValueError("reserved_stock_item_ids contains duplicate IDs")
        created_at = self._now() if created_at is None else created_at

        with database.transaction(self.db_path) as conn:
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
                    user_id,
                    username,
                    full_name,
                    product_id,
                    qty,
                    unit_price,
                    total_amount,
                    status,
                    payos_ref,
                    note,
                    created_at,
                    paid_at,
                    delivered_at,
                    cancelled_at,
                ),
            )

            if reserved_stock_item_ids:
                placeholders = ",".join("?" for _ in reserved_stock_item_ids)
                params = [order_id, created_at, *reserved_stock_item_ids, product_id]
                cursor = conn.execute(
                    f"""
                    UPDATE stock_items
                    SET status = 'reserved',
                        reserved_for_order_id = ?,
                        updated_at = ?
                    WHERE id IN ({placeholders})
                        AND product_id = ?
                        AND status = 'available'
                    """,
                    params,
                )
                if cursor.rowcount != len(reserved_stock_item_ids):
                    raise ValueError("Unable to reserve all requested stock items")

            return conn.execute(
                "SELECT * FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()

    def get_order(self, order_id):
        conn = database.get_connection(self.db_path)
        try:
            return conn.execute(
                "SELECT * FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
        finally:
            conn.close()

    def list_reserved_stock_for_order(self, order_id):
        conn = database.get_connection(self.db_path)
        try:
            return conn.execute(
                """
                SELECT *
                FROM stock_items
                WHERE reserved_for_order_id = ? AND status = 'reserved'
                ORDER BY id
                """,
                (order_id,),
            ).fetchall()
        finally:
            conn.close()

    def list_order_items(self, order_id):
        conn = database.get_connection(self.db_path)
        try:
            return conn.execute(
                """
                SELECT *
                FROM order_items
                WHERE order_id = ?
                ORDER BY id
                """,
                (order_id,),
            ).fetchall()
        finally:
            conn.close()

    def complete_paid_order(self, order_id, payos_ref, amount_paid, reserved_items):
        now = self._now()
        with database.transaction(self.db_path) as conn:
            for row in reserved_items:
                conn.execute(
                    """
                    UPDATE stock_items
                    SET status = 'sold',
                        updated_at = ?,
                        sold_at = ?
                    WHERE id = ?
                    """,
                    (now, now, row["id"]),
                )
                conn.execute(
                    """
                    INSERT INTO order_items (
                        order_id, stock_item_id, delivered_content, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (order_id, row["id"], row["content"], now),
                )

            conn.execute(
                """
                UPDATE orders
                SET status = 'delivered',
                    payos_ref = ?,
                    paid_at = ?,
                    delivered_at = ?
                WHERE id = ?
                """,
                (str(payos_ref), now, now, order_id),
            )
            conn.execute(
                """
                INSERT INTO payments (
                    order_id, payos_order_code, amount, status, raw_reference,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (order_id, str(payos_ref), amount_paid, "paid", None, now, now),
            )

    def cancel_order_and_release_stock(self, order_id, reason):
        now = self._now()
        with database.transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE stock_items
                SET status = 'available',
                    reserved_for_order_id = NULL,
                    updated_at = ?
                WHERE reserved_for_order_id = ? AND status = 'reserved'
                """,
                (now, order_id),
            )
            conn.execute(
                """
                UPDATE orders
                SET status = 'cancelled',
                    note = ?,
                    cancelled_at = ?,
                    paid_at = NULL,
                    delivered_at = NULL
                WHERE id = ?
                """,
                (reason, now, order_id),
            )

    def set_config_value(self, key, value):
        now = self._now()
        with database.transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_config (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE
                SET value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def delete_config_prefix(self, prefix):
        with database.transaction(self.db_path) as conn:
            conn.execute(
                "DELETE FROM app_config WHERE key LIKE ?",
                (f"{prefix}%",),
            )

    def get_config_values(self, prefix):
        conn = database.get_connection(self.db_path)
        try:
            return conn.execute(
                """
                SELECT key, value
                FROM app_config
                WHERE key LIKE ?
                ORDER BY key
                """,
                (f"{prefix}%",),
            ).fetchall()
        finally:
            conn.close()

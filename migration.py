import time
import zlib
from collections import Counter, defaultdict

import database


MIGRATION_VERSION = 3

COMPATIBILITY_PROVIDER_DEFAULTS = {
    "sumistore_default": {
        "name": "SumiStore Default",
        "protocol": "sumistore",
        "base_url": "https://sumistore.me/api",
        "api_key": "TAPI-XD2CGJRB398MTAFBDYHO",
    },
    "capcut_default": {
        "name": "CapCut Default",
        "protocol": "node_api",
        "base_url": "http://node12.zampto.net:20291/api",
        "api_key": "sk_4cc3773eeab08fc6c32aee2d4e0461f67b6a206077b5f818",
    },
}

LEGACY_PROVIDER_REMAP = {
    "sumistore": "sumistore_default",
    "capcut_api": "capcut_default",
}


def parse_price_to_int(price_text):
    digits = "".join(ch for ch in str(price_text) if ch.isdigit())
    return int(digits or "0")


def _order_code_for(order_id, order_data, existing_order_codes=None):
    payos_ref = order_data.get("payos_ref")
    if payos_ref is not None:
        try:
            candidate = int(payos_ref)
        except (TypeError, ValueError):
            pass
        else:
            if existing_order_codes is not None:
                while candidate in existing_order_codes:
                    candidate = (candidate + 1) & 0x7FFFFFFF
                existing_order_codes.add(candidate)
            return candidate

    candidate = zlib.crc32(str(order_id).encode("utf-8")) & 0x7FFFFFFF
    if existing_order_codes is not None:
        while candidate in existing_order_codes:
            candidate = (candidate + 1) & 0x7FFFFFFF
        existing_order_codes.add(candidate)
    return candidate


def _resolved_order_codes_for_data(conn, orders):
    resolved_codes = {}
    occupied_codes = {
        row["order_code"]
        for row in conn.execute(
            """
            SELECT order_code
            FROM orders
            """
        ).fetchall()
    }

    for order_id, order_data in orders.items():
        current_row = conn.execute(
            "SELECT order_code FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        current_code = current_row["order_code"] if current_row is not None else None
        candidate = _order_code_for(order_id, order_data)
        while candidate in occupied_codes and candidate != current_code:
            candidate = (candidate + 1) & 0x7FFFFFFF
        resolved_codes[order_id] = candidate
        if current_code is not None:
            occupied_codes.discard(current_code)
        occupied_codes.add(candidate)

    return resolved_codes


def _expected_order_lifecycle(order_data, created_at):
    accounts = list(order_data.get("accounts") or [])
    delivered = bool(accounts)
    return {
        "status": "delivered" if delivered else "pending_payment",
        "paid_at": created_at if delivered or order_data.get("payos_ref") is not None else None,
        "delivered_at": created_at if delivered else None,
        "cancelled_at": None,
    }


def _is_already_migrated(conn):
    row = conn.execute("PRAGMA user_version").fetchone()
    return bool(row[0]) and row[0] >= MIGRATION_VERSION


def _mark_migrated(conn):
    conn.execute(f"PRAGMA user_version = {MIGRATION_VERSION}")


def _counter_fits(existing_counts, required_counts):
    return all(existing_counts.get(content, 0) >= count for content, count in required_counts.items())


def _migration_complete_for_data(conn, data):
    products = data.get("products", {}) or {}
    orders = data.get("orders", {}) or {}
    payos_config = data.get("config", {}).get("payos", {}) or {}
    resolved_order_codes = _resolved_order_codes_for_data(conn, orders)

    for product_id, product_data in products.items():
        if conn.execute(
            "SELECT 1 FROM products WHERE id = ?",
            (product_id,),
        ).fetchone() is None:
            return False
        available_counts = Counter(
            row["content"]
            for row in conn.execute(
                """
                SELECT content
                FROM stock_items
                WHERE product_id = ? AND status = 'available'
                """,
                (product_id,),
            ).fetchall()
        )
        if not _counter_fits(available_counts, Counter(product_data.get("stock") or [])):
            return False

    for order_id in orders:
        row = conn.execute(
            """
            SELECT order_code, created_at, status, paid_at, delivered_at, cancelled_at
            FROM orders
            WHERE id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            return False
        if row["order_code"] != resolved_order_codes.get(order_id):
            return False
        expected_lifecycle = _expected_order_lifecycle(orders[order_id], row["created_at"])
        if (
            row["status"] != expected_lifecycle["status"]
            or row["paid_at"] != expected_lifecycle["paid_at"]
            or row["delivered_at"] != expected_lifecycle["delivered_at"]
            or row["cancelled_at"] != expected_lifecycle["cancelled_at"]
        ):
            return False
        required_accounts = list(orders[order_id].get("accounts") or [])
        rows = conn.execute(
            """
            SELECT oi.delivered_content, oi.stock_item_id, si.product_id, si.content
            FROM order_items oi
            JOIN stock_items si ON si.id = oi.stock_item_id
            WHERE oi.order_id = ?
            ORDER BY oi.id
            """,
            (order_id,),
        ).fetchall()
        if len(rows) != len(required_accounts):
            return False
        if Counter(row["delivered_content"] for row in rows) != Counter(required_accounts):
            return False
        if any(
            row["product_id"] != orders[order_id]["product_id"]
            or row["content"] != row["delivered_content"]
            for row in rows
        ):
            return False
        if len({row["stock_item_id"] for row in rows}) != len(rows):
            return False

    all_order_item_stock_ids = [
        row["stock_item_id"]
        for row in conn.execute(
            """
            SELECT stock_item_id
            FROM order_items
            """
        ).fetchall()
    ]
    if len(all_order_item_stock_ids) != len(set(all_order_item_stock_ids)):
        return False

    if payos_config:
        rows = conn.execute(
            """
            SELECT key, value
            FROM app_config
            WHERE key LIKE 'payos.%'
            ORDER BY key
            """
        ).fetchall()
        expected = {
            "payos.client_id": payos_config.get("client_id"),
            "payos.api_key": payos_config.get("api_key"),
            "payos.checksum_key": payos_config.get("checksum_key"),
        }
        actual = {row["key"]: row["value"] for row in rows}
        if actual != expected:
            return False

    return bool(products or orders or payos_config)


def _available_stock_rows_by_content(conn, product_id):
    rows_by_content = defaultdict(list)
    rows = conn.execute(
        """
        SELECT id, content
        FROM stock_items
        WHERE product_id = ? AND status = 'available'
        ORDER BY id
        """,
        (product_id,),
    ).fetchall()
    for row in rows:
        content = row["content"]
        rows_by_content[content].append(row["id"])
    return rows_by_content


def _claim_matching_stock_item(conn, product_id, content, used_stock_item_ids):
    available_rows_by_content = _available_stock_rows_by_content(conn, product_id)
    for stock_item_id in available_rows_by_content.get(content, []):
        if stock_item_id not in used_stock_item_ids:
            used_stock_item_ids.add(stock_item_id)
            return stock_item_id
    return None


def _cleanup_orphaned_migration_stock_items(conn):
    conn.execute(
        """
        DELETE FROM stock_items
        WHERE batch_id LIKE 'migration:order:%'
            AND status = 'sold'
            AND id NOT IN (
                SELECT stock_item_id
                FROM order_items
            )
        """
    )


def _seed_compatibility_supplier_providers(conn):
    legacy_provider_values = {
        row["supplier_provider"]
        for row in conn.execute(
            """
            SELECT DISTINCT supplier_provider
            FROM products
            WHERE supplier_provider IS NOT NULL AND supplier_provider != ''
            """
        ).fetchall()
    }

    now = int(time.time())
    for legacy_provider, provider_code in LEGACY_PROVIDER_REMAP.items():
        if legacy_provider not in legacy_provider_values:
            continue
        config = COMPATIBILITY_PROVIDER_DEFAULTS[provider_code]
        conn.execute(
            """
            INSERT INTO supplier_providers (
                code, name, protocol, base_url, api_key, overrides_json,
                is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, '{}', 1, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name = excluded.name,
                protocol = excluded.protocol,
                base_url = excluded.base_url,
                api_key = excluded.api_key,
                updated_at = excluded.updated_at
            """,
            (
                provider_code,
                config["name"],
                config["protocol"],
                config["base_url"],
                config["api_key"],
                now,
                now,
            ),
        )


def _remap_legacy_product_supplier_provider_codes(conn):
    for legacy_provider, provider_code in LEGACY_PROVIDER_REMAP.items():
        conn.execute(
            """
            UPDATE products
            SET supplier_provider = ?
            WHERE supplier_provider = ?
            """,
            (provider_code, legacy_provider),
        )


def migrate_json_to_sqlite(data, db_path="shop.db"):
    database.init_db(db_path)
    with database.transaction(db_path) as conn:
        _cleanup_orphaned_migration_stock_items(conn)
        _seed_compatibility_supplier_providers(conn)
        _remap_legacy_product_supplier_provider_codes(conn)
        if _migration_complete_for_data(conn, data):
            if not _is_already_migrated(conn):
                _mark_migrated(conn)
            return

        now = int(time.time())
        products = data.get("products", {}) or {}
        orders = data.get("orders", {}) or {}
        payos_config = data.get("config", {}).get("payos", {}) or {}
        resolved_order_codes = _resolved_order_codes_for_data(conn, orders)
        used_stock_item_ids = set()

        for product_id, product_data in products.items():
            if conn.execute(
                "SELECT 1 FROM products WHERE id = ?",
                (product_id,),
            ).fetchone() is None:
                conn.execute(
                    """
                    INSERT INTO products (
                        id, name, price, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (
                        product_id,
                        product_data.get("name"),
                        parse_price_to_int(product_data.get("price")),
                        now,
                        now,
                    ),
                )

            available_rows_by_content = _available_stock_rows_by_content(conn, product_id)
            for content in list(product_data.get("stock") or []):
                bucket = available_rows_by_content.get(content, [])
                if bucket:
                    bucket.pop(0)
                    continue
                conn.execute(
                    """
                    INSERT INTO stock_items (
                        product_id, content, status, batch_id,
                        reserved_for_order_id, disabled_reason, created_at,
                        updated_at, sold_at
                    ) VALUES (?, ?, 'available', ?, NULL, NULL, ?, ?, NULL)
                    """,
                    (
                        product_id,
                        content,
                        f"migration:{product_id}",
                        now,
                        now,
                    ),
                )

        for order_id, order_data in orders.items():
            order_exists = conn.execute(
                "SELECT 1 FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone() is not None

            accounts = list(order_data.get("accounts") or [])
            created_at = order_data.get("time") or now
            delivered = bool(accounts)
            product_id = order_data.get("product_id")
            if conn.execute(
                "SELECT 1 FROM products WHERE id = ?",
                (product_id,),
            ).fetchone() is None:
                conn.execute(
                    """
                    INSERT INTO products (
                        id, name, price, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, 0, ?, ?)
                    """,
                    (
                        product_id,
                        order_data.get("product_name") or f"Legacy Product {product_id}",
                        0,
                        created_at,
                        created_at,
                    ),
                )
            if not order_exists:
                unit_price = parse_price_to_int(
                    products.get(product_id, {}).get("price")
                )
                total_amount = unit_price * int(order_data.get("qty") or 0)
                lifecycle = _expected_order_lifecycle(order_data, created_at)

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
                        resolved_order_codes.get(order_id),
                        order_data.get("user_id"),
                        order_data.get("username"),
                        order_data.get("full_name"),
                        product_id,
                        order_data.get("qty"),
                        unit_price,
                        total_amount,
                        lifecycle["status"],
                        str(order_data.get("payos_ref")) if order_data.get("payos_ref") is not None else None,
                        None,
                        created_at,
                        lifecycle["paid_at"],
                        lifecycle["delivered_at"],
                        None,
                    ),
                )
            else:
                current_row = conn.execute(
                    """
                    SELECT order_code, created_at, status, paid_at, delivered_at, cancelled_at
                    FROM orders
                    WHERE id = ?
                    """,
                    (order_id,),
                ).fetchone()
                current_order_code = current_row["order_code"]
                resolved_order_code = resolved_order_codes.get(order_id)
                expected_lifecycle = _expected_order_lifecycle(order_data, current_row["created_at"])
                if (
                    current_order_code != resolved_order_code
                    or current_row["status"] != expected_lifecycle["status"]
                    or current_row["paid_at"] != expected_lifecycle["paid_at"]
                    or current_row["delivered_at"] != expected_lifecycle["delivered_at"]
                    or current_row["cancelled_at"] != expected_lifecycle["cancelled_at"]
                ):
                    conn.execute(
                        """
                        UPDATE orders
                        SET order_code = ?,
                            status = ?,
                            paid_at = ?,
                            delivered_at = ?,
                            cancelled_at = ?
                        WHERE id = ?
                        """,
                        (
                            resolved_order_code,
                            expected_lifecycle["status"],
                            expected_lifecycle["paid_at"],
                            expected_lifecycle["delivered_at"],
                            expected_lifecycle["cancelled_at"],
                            order_id,
                        ),
                    )

            if not delivered:
                conn.execute(
                    """
                    UPDATE orders
                    SET status = 'pending_payment',
                        paid_at = NULL,
                        delivered_at = NULL,
                        cancelled_at = NULL
                    WHERE id = ?
                    """,
                    (order_id,),
                )
                conn.execute(
                    "DELETE FROM order_items WHERE order_id = ?",
                    (order_id,),
                )
                _cleanup_orphaned_migration_stock_items(conn)
                continue

            existing_order_items = conn.execute(
                """
                SELECT id, delivered_content, stock_item_id
                FROM order_items
                WHERE order_id = ?
                ORDER BY id
                """,
                (order_id,),
            ).fetchall()

            for index, account in enumerate(accounts):
                existing_row = existing_order_items[index] if index < len(existing_order_items) else None
                if existing_row and existing_row["delivered_content"] == account and existing_row["stock_item_id"] not in used_stock_item_ids:
                    stock_row = conn.execute(
                        "SELECT product_id, content FROM stock_items WHERE id = ?",
                        (existing_row["stock_item_id"],),
                    ).fetchone()
                    if (
                        stock_row is not None
                        and stock_row["content"] == account
                        and stock_row["product_id"] == order_data.get("product_id")
                    ):
                        used_stock_item_ids.add(existing_row["stock_item_id"])
                        continue

                stock_item_id = _claim_matching_stock_item(
                    conn,
                    order_data.get("product_id"),
                    account,
                    used_stock_item_ids,
                )
                if stock_item_id is None:
                    cursor = conn.execute(
                        """
                        INSERT INTO stock_items (
                            product_id, content, status, batch_id,
                            reserved_for_order_id, disabled_reason, created_at,
                            updated_at, sold_at
                        ) VALUES (?, ?, 'sold', ?, ?, NULL, ?, ?, ?)
                        """,
                        (
                            order_data.get("product_id"),
                            account,
                            f"migration:order:{order_id}",
                            order_id,
                            created_at,
                            created_at,
                            created_at,
                        ),
                    )
                    stock_item_id = cursor.lastrowid
                used_stock_item_ids.add(stock_item_id)

                if existing_row:
                    conn.execute(
                        """
                        UPDATE order_items
                        SET stock_item_id = ?, delivered_content = ?
                        WHERE id = ?
                        """,
                        (stock_item_id, account, existing_row["id"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO order_items (
                            order_id, stock_item_id, delivered_content, created_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (order_id, stock_item_id, account, created_at),
                    )

            if len(existing_order_items) > len(accounts):
                for extra_row in existing_order_items[len(accounts):]:
                    conn.execute(
                        "DELETE FROM order_items WHERE id = ?",
                        (extra_row["id"],),
                    )

            _cleanup_orphaned_migration_stock_items(conn)

        if payos_config:
            config_entries = {
                "payos.client_id": payos_config.get("client_id", ""),
                "payos.api_key": payos_config.get("api_key", ""),
                "payos.checksum_key": payos_config.get("checksum_key", ""),
            }
            for key, value in config_entries.items():
                conn.execute(
                    """
                    INSERT INTO app_config (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE
                    SET value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (key, str(value), now),
                )

        _mark_migrated(conn)

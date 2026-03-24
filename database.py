from contextlib import contextmanager
import sqlite3


def get_connection(db_path="shop.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path="shop.db"):
    conn = get_connection(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stock_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'reserved', 'sold', 'disabled')),
                batch_id TEXT,
                reserved_for_order_id TEXT,
                disabled_reason TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                sold_at INTEGER,
                FOREIGN KEY (product_id) REFERENCES products(id),
                FOREIGN KEY (reserved_for_order_id) REFERENCES orders(id)
            );

            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                order_code INTEGER NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                product_id TEXT NOT NULL,
                qty INTEGER NOT NULL,
                unit_price INTEGER NOT NULL,
                total_amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_payment' CHECK (status IN ('pending_payment', 'paid', 'delivered', 'paid_delivery_failed', 'cancelled', 'failed')),
                payos_ref TEXT,
                note TEXT,
                created_at INTEGER NOT NULL,
                paid_at INTEGER,
                delivered_at INTEGER,
                cancelled_at INTEGER,
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                stock_item_id INTEGER NOT NULL,
                delivered_content TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (stock_item_id) REFERENCES stock_items(id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                payos_order_code TEXT,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL,
                raw_reference TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            );

            CREATE TABLE IF NOT EXISTS app_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


@contextmanager
def transaction(db_path="shop.db"):
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

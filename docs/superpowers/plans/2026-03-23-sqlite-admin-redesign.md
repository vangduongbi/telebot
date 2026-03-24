# SQLite Admin Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace JSON-based stock and order persistence with a SQLite-backed design that supports reliable inventory reservation, order management, and Telegram admin workflows for a bot handling 20-100 orders per day.

**Architecture:** Introduce a small SQLite persistence layer and service layer while keeping Telegram polling as the runtime model. Migrate data from `data.json`, route purchase and admin flows through service methods, and use explicit order and stock states to prevent inventory drift.

**Tech Stack:** Python, SQLite (`sqlite3`), pyTelegramBotAPI, PayOS, unittest, temporary-file SQLite tests

---

## File Structure

### Existing files to modify

- `bot.py`
  Keep Telegram handlers and callback entrypoints, but reduce direct data mutation and route through services.
- `test_bot.py`
  Replace or expand current tests to cover SQLite-backed purchase behavior.
- `data.json`
  Keep only as migration input and fallback seed data during rollout.

### New files to create

- `database.py`
  SQLite connection helpers, schema creation, transaction entrypoints.
- `repositories.py`
  Narrow database access helpers for products, stock, orders, and payments.
- `services.py`
  Business logic for create product, import stock, reserve stock, payment success/failure handling, order search, and delivery recovery.
- `migration.py`
  One-time import from `data.json` into SQLite.
- `test_database.py`
  Schema and transaction tests.
- `test_services.py`
  Core order lifecycle and inventory behavior tests.
- `shop.db`
  SQLite runtime database file created during execution, not committed.

## Implementation Notes

- Store prices as integer VND values.
- Keep Telegram token and PayOS credentials behavior unchanged during the first pass unless config extraction is explicitly added as a follow-up task.
- Use `sqlite3.Row` so service code can access columns by name.
- Use transactions for reserve, sell, cancel, and release flows.
- This workspace is not currently a git repository, so commit steps are written as checkpoints. If git is initialized later, convert each checkpoint into a commit.

### Task 1: Add SQLite schema bootstrap

**Files:**
- Create: `database.py`
- Test: `test_database.py`

- [ ] **Step 1: Write the failing schema test**

```python
import os
import tempfile
import unittest

import database


class DatabaseSchemaTests(unittest.TestCase):
    def test_init_db_creates_expected_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "shop.db")

            database.init_db(db_path)
            conn = database.get_connection(db_path)

            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {row["name"] for row in rows}

            self.assertTrue({"products", "stock_items", "orders", "order_items", "payments"}.issubset(table_names))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_database.DatabaseSchemaTests.test_init_db_creates_expected_tables -v`
Expected: FAIL because `database.py` or `init_db` does not exist yet

- [ ] **Step 3: Write minimal schema implementation**

```python
import sqlite3


def get_connection(db_path="shop.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path="shop.db"):
    conn = get_connection(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (...);
        CREATE TABLE IF NOT EXISTS stock_items (...);
        CREATE TABLE IF NOT EXISTS orders (...);
        CREATE TABLE IF NOT EXISTS order_items (...);
        CREATE TABLE IF NOT EXISTS payments (...);
        """
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_database.DatabaseSchemaTests.test_init_db_creates_expected_tables -v`
Expected: PASS

- [ ] **Step 5: Checkpoint**

Checkpoint files: `database.py`, `test_database.py`

### Task 2: Add transaction-safe repository helpers

**Files:**
- Modify: `database.py`
- Create: `repositories.py`
- Modify: `test_database.py`

- [ ] **Step 1: Write the failing repository test for creating a product**

```python
import repositories


class ProductRepositoryTests(unittest.TestCase):
    def test_create_product_persists_integer_price(self):
        repo = repositories.Repository(self.db_path)
        repo.create_product("prod_1", "Product A", 100000)

        row = repo.get_product("prod_1")

        self.assertEqual(row["name"], "Product A")
        self.assertEqual(row["price"], 100000)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_database.ProductRepositoryTests.test_create_product_persists_integer_price -v`
Expected: FAIL because `Repository` does not exist yet

- [ ] **Step 3: Write minimal repository implementation**

```python
class Repository:
    def __init__(self, db_path="shop.db"):
        self.db_path = db_path

    def create_product(self, product_id, name, price):
        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO products (id, name, price, is_active, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
                (product_id, name, price, now, now),
            )

    def get_product(self, product_id):
        with get_connection(self.db_path) as conn:
            return conn.execute(
                "SELECT * FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_database.ProductRepositoryTests.test_create_product_persists_integer_price -v`
Expected: PASS

- [ ] **Step 5: Extend repository coverage**

Add and verify tests for:
- `add_stock_items`
- `count_stock_by_status`
- `create_order`
- `list_reserved_stock_for_order`

- [ ] **Step 6: Checkpoint**

Checkpoint files: `database.py`, `repositories.py`, `test_database.py`

### Task 3: Add migration from `data.json`

**Files:**
- Create: `migration.py`
- Modify: `test_database.py`

- [ ] **Step 1: Write the failing migration test**

```python
import json
import migration


class MigrationTests(unittest.TestCase):
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
        self.assertEqual(repo.count_stock_by_status("prod_1")["available"], 2)
        self.assertIsNotNone(repo.get_order("ORD-1"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_database.MigrationTests.test_migrate_json_creates_products_stock_and_orders -v`
Expected: FAIL because migration logic does not exist yet

- [ ] **Step 3: Write minimal migration implementation**

```python
def parse_price_to_int(price_text):
    return int("".join(ch for ch in price_text if ch.isdigit()) or "0")


def migrate_json_to_sqlite(data, db_path="shop.db"):
    database.init_db(db_path)
    repo = repositories.Repository(db_path)
    # insert products
    # insert stock rows as available
    # insert legacy orders
    # insert order_items for delivered accounts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_database.MigrationTests.test_migrate_json_creates_products_stock_and_orders -v`
Expected: PASS

- [ ] **Step 5: Add idempotency test**

Add a second test ensuring the migration does not duplicate rows when guarded and rerun intentionally.

- [ ] **Step 6: Checkpoint**

Checkpoint files: `migration.py`, `test_database.py`

### Task 4: Add service for creating pending orders and reserving stock

**Files:**
- Create: `services.py`
- Create: `test_services.py`
- Modify: `repositories.py`

- [ ] **Step 1: Write the failing order reservation test**

```python
import services


class OrderCreationTests(unittest.TestCase):
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
        self.assertEqual(counts["reserved"], 2)
        self.assertEqual(counts["available"], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_services.OrderCreationTests.test_create_pending_order_reserves_requested_stock -v`
Expected: FAIL because `ShopService` or reserve logic does not exist yet

- [ ] **Step 3: Write minimal service implementation**

```python
class ShopService:
    def __init__(self, db_path="shop.db"):
        self.repo = repositories.Repository(db_path)

    def create_pending_order(self, user_id, username, full_name, product_id, qty):
        product = self.repo.get_product(product_id)
        available = self.repo.list_available_stock(product_id, qty)
        if len(available) < qty:
            raise ValueError("Not enough stock")
        return self.repo.create_order_and_reserve_stock(
            user_id=user_id,
            username=username,
            full_name=full_name,
            product=product,
            qty=qty,
            stock_rows=available,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_services.OrderCreationTests.test_create_pending_order_reserves_requested_stock -v`
Expected: PASS

- [ ] **Step 5: Add insufficient-stock test**

Add a second test asserting `ValueError` when requested quantity exceeds `available`.

- [ ] **Step 6: Checkpoint**

Checkpoint files: `services.py`, `repositories.py`, `test_services.py`

### Task 5: Add service for payment success and delivery item creation

**Files:**
- Modify: `services.py`
- Modify: `repositories.py`
- Modify: `test_services.py`

- [ ] **Step 1: Write the failing payment success test**

```python
class PaymentSuccessTests(unittest.TestCase):
    def test_mark_paid_and_delivered_moves_reserved_stock_to_sold(self):
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

        repo = repositories.Repository(self.db_path)
        order_row = repo.get_order(order["id"])
        counts = repo.count_stock_by_status("prod_1")
        items = repo.list_order_items(order["id"])

        self.assertEqual(order_row["status"], "delivered")
        self.assertEqual(counts["sold"], 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(delivered["accounts"], [items[0]["delivered_content"]])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_services.PaymentSuccessTests.test_mark_paid_and_delivered_moves_reserved_stock_to_sold -v`
Expected: FAIL because payment success handling is not implemented

- [ ] **Step 3: Write minimal payment success implementation**

```python
def mark_payment_paid(self, order_id, payos_ref, amount_paid):
    order = self.repo.get_order(order_id)
    reserved_items = self.repo.list_reserved_stock_for_order(order_id)
    if order["status"] != "pending_payment":
        raise ValueError("Order not pending")
    if len(reserved_items) != order["qty"]:
        raise ValueError("Reserved stock mismatch")
    self.repo.complete_paid_order(order_id, payos_ref, amount_paid, reserved_items)
    return {"order_id": order_id, "accounts": [row["content"] for row in reserved_items]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_services.PaymentSuccessTests.test_mark_paid_and_delivered_moves_reserved_stock_to_sold -v`
Expected: PASS

- [ ] **Step 5: Add mismatch guard test**

Add a second test asserting the method raises an error if reserved stock count does not match `qty`.

- [ ] **Step 6: Checkpoint**

Checkpoint files: `services.py`, `repositories.py`, `test_services.py`

### Task 6: Add service for payment failure and stock release

**Files:**
- Modify: `services.py`
- Modify: `repositories.py`
- Modify: `test_services.py`

- [ ] **Step 1: Write the failing payment cancellation test**

```python
class PaymentFailureTests(unittest.TestCase):
    def test_cancel_pending_order_releases_reserved_stock(self):
        service = services.ShopService(self.db_path)
        order = service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id="prod_1",
            qty=2,
        )

        service.cancel_pending_order(order["id"], reason="payment timeout")

        repo = repositories.Repository(self.db_path)
        order_row = repo.get_order(order["id"])
        counts = repo.count_stock_by_status("prod_1")

        self.assertEqual(order_row["status"], "cancelled")
        self.assertEqual(counts["reserved"], 0)
        self.assertEqual(counts["available"], 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_services.PaymentFailureTests.test_cancel_pending_order_releases_reserved_stock -v`
Expected: FAIL because cancellation logic is not implemented

- [ ] **Step 3: Write minimal cancellation implementation**

```python
def cancel_pending_order(self, order_id, reason):
    order = self.repo.get_order(order_id)
    if order["status"] != "pending_payment":
        raise ValueError("Only pending orders can be cancelled")
    self.repo.cancel_order_and_release_stock(order_id, reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_services.PaymentFailureTests.test_cancel_pending_order_releases_reserved_stock -v`
Expected: PASS

- [ ] **Step 5: Add status guard test**

Add a second test asserting the method rejects cancellation for already delivered orders.

- [ ] **Step 6: Checkpoint**

Checkpoint files: `services.py`, `repositories.py`, `test_services.py`

### Task 7: Add service for admin stock queries and order search

**Files:**
- Modify: `services.py`
- Modify: `repositories.py`
- Modify: `test_services.py`

- [ ] **Step 1: Write the failing admin search tests**

```python
class AdminQueryTests(unittest.TestCase):
    def test_find_order_by_user_id_returns_recent_orders(self):
        service = services.ShopService(self.db_path)
        result = service.find_orders_by_user_id(10)
        self.assertEqual([row["user_id"] for row in result], [10])

    def test_get_stock_summary_returns_counts_by_status(self):
        service = services.ShopService(self.db_path)
        summary = service.get_stock_summary("prod_1")
        self.assertEqual(summary["available"], 3)
        self.assertEqual(summary["reserved"], 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_services.AdminQueryTests -v`
Expected: FAIL because query helpers are not implemented yet

- [ ] **Step 3: Write minimal admin query implementation**

```python
def find_orders_by_user_id(self, user_id):
    return self.repo.find_orders_by_user_id(user_id)


def find_orders_by_username(self, username):
    return self.repo.find_orders_by_username(username)


def get_stock_summary(self, product_id):
    return self.repo.count_stock_by_status(product_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_services.AdminQueryTests -v`
Expected: PASS

- [ ] **Step 5: Extend coverage**

Add tests for:
- `find_order_by_internal_id`
- `list_recent_orders`
- `list_recent_stock_items`

- [ ] **Step 6: Checkpoint**

Checkpoint files: `services.py`, `repositories.py`, `test_services.py`

### Task 8: Add service for re-delivery of paid orders

**Files:**
- Modify: `services.py`
- Modify: `repositories.py`
- Modify: `test_services.py`

- [ ] **Step 1: Write the failing re-delivery test**

```python
class RedeliveryTests(unittest.TestCase):
    def test_redeliver_order_reuses_existing_order_items(self):
        service = services.ShopService(self.db_path)
        order = service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id="prod_1",
            qty=1,
        )
        service.mark_payment_paid(order["id"], "123", 100000)

        redelivery = service.redeliver_order(order["id"])

        self.assertEqual(len(redelivery["accounts"]), 1)
        self.assertEqual(redelivery["accounts"], [row["delivered_content"] for row in repositories.Repository(self.db_path).list_order_items(order["id"])])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_services.RedeliveryTests.test_redeliver_order_reuses_existing_order_items -v`
Expected: FAIL because re-delivery logic is not implemented

- [ ] **Step 3: Write minimal re-delivery implementation**

```python
def redeliver_order(self, order_id):
    order = self.repo.get_order(order_id)
    if order["status"] not in {"delivered", "paid_delivery_failed"}:
        raise ValueError("Order is not eligible for re-delivery")
    items = self.repo.list_order_items(order_id)
    return {"order_id": order_id, "accounts": [row["delivered_content"] for row in items]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_services.RedeliveryTests.test_redeliver_order_reuses_existing_order_items -v`
Expected: PASS

- [ ] **Step 5: Add guard test**

Add a second test asserting re-delivery is rejected for `pending_payment` orders.

- [ ] **Step 6: Checkpoint**

Checkpoint files: `services.py`, `repositories.py`, `test_services.py`

### Task 9: Wire purchase flow in `bot.py` to SQLite services

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Write the failing bot-level purchase test**

```python
class BotPurchaseFlowTests(unittest.TestCase):
    def test_process_purchase_uses_service_created_order(self):
        with patch.object(bot, "shop_service", fake_service):
            bot.process_purchase(self.user, self.chat_id, "prod_1", 1)

        self.assertEqual(fake_service.created_orders[0]["product_id"], "prod_1")
        self.assertEqual(len(bot.bot.messages), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_bot.BotPurchaseFlowTests.test_process_purchase_uses_service_created_order -v`
Expected: FAIL because `bot.py` still uses JSON-backed stock logic

- [ ] **Step 3: Write minimal wiring implementation**

```python
shop_service = services.ShopService(DB_PATH)


def process_purchase(user, chat_id, product_id, qty):
    order = shop_service.create_pending_order(
        user_id=user.id,
        username=f"@{user.username}" if user.username else None,
        full_name=f"{user.first_name} {user.last_name or ''}".strip(),
        product_id=product_id,
        qty=qty,
    )
    # create payment link from order totals
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_bot.BotPurchaseFlowTests.test_process_purchase_uses_service_created_order -v`
Expected: PASS

- [ ] **Step 5: Extend coverage**

Add tests for:
- out-of-stock handling via service exception
- missing PayOS config handling
- success path message contents

- [ ] **Step 6: Checkpoint**

Checkpoint files: `bot.py`, `test_bot.py`

### Task 10: Wire payment polling and fulfillment in `bot.py` to SQLite services

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Write the failing polling success test**

```python
class PollPaymentTests(unittest.TestCase):
    def test_paid_status_calls_service_and_sends_accounts(self):
        with patch.object(bot, "shop_service", fake_service):
            bot.poll_payment_status(123456, self.user, self.chat_id, "prod_1", 1)

        self.assertEqual(fake_service.paid_calls[0]["order_code"], 123456)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_bot.PollPaymentTests.test_paid_status_calls_service_and_sends_accounts -v`
Expected: FAIL because payment polling still calls old JSON fulfillment logic

- [ ] **Step 3: Write minimal polling integration**

```python
def poll_payment_status(order_code, user, chat_id, product_id, qty):
    payment_info = payos_client.payment_requests.get(order_code)
    if payment_info.status == "PAID":
        result = shop_service.mark_payment_paid_by_order_code(
            order_code=order_code,
            amount_paid=payment_info.amount,
        )
        send_delivered_accounts(chat_id, result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_bot.PollPaymentTests.test_paid_status_calls_service_and_sends_accounts -v`
Expected: PASS

- [ ] **Step 5: Add failure-path tests**

Add tests for:
- cancelled payment releases stock
- Telegram send error moves order to `paid_delivery_failed`

- [ ] **Step 6: Checkpoint**

Checkpoint files: `bot.py`, `test_bot.py`

### Task 11: Replace admin product and stock flows with SQLite-backed handlers

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`
- Modify: `services.py`

- [ ] **Step 1: Write the failing admin product test**

```python
class AdminStockFlowTests(unittest.TestCase):
    def test_admin_create_product_uses_service(self):
        message = SimpleNamespace(text="Netflix | 60000", chat=SimpleNamespace(id=1))
        with patch.object(bot, "shop_service", fake_service):
            bot.admin_process_create_prod(message)

        self.assertEqual(fake_service.created_products[0]["name"], "Netflix")
        self.assertEqual(fake_service.created_products[0]["price"], 60000)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_bot.AdminStockFlowTests.test_admin_create_product_uses_service -v`
Expected: FAIL because admin handlers still mutate `db` directly

- [ ] **Step 3: Write minimal SQLite-backed admin stock implementation**

```python
def admin_process_create_prod(message):
    name, price_text = ...
    price = services.parse_price_to_int(price_text)
    product = shop_service.create_product(name=name, price=price)
    bot.send_message(message.chat.id, ...)


def process_admin_add(message, product_id):
    lines = ...
    imported = shop_service.import_stock(product_id, lines)
    bot.send_message(message.chat.id, ...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_bot.AdminStockFlowTests.test_admin_create_product_uses_service -v`
Expected: PASS

- [ ] **Step 5: Extend coverage**

Add tests for:
- product price update
- stock import summary
- stock count display in admin menu

- [ ] **Step 6: Checkpoint**

Checkpoint files: `bot.py`, `test_bot.py`, `services.py`

### Task 12: Add admin order lookup and re-delivery commands

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`
- Modify: `services.py`

- [ ] **Step 1: Write the failing admin order lookup tests**

```python
class AdminOrderFlowTests(unittest.TestCase):
    def test_order_command_renders_order_detail(self):
        with patch.object(bot, "shop_service", fake_service):
            message = SimpleNamespace(text="/order ORD-123", chat=SimpleNamespace(id=1), from_user=SimpleNamespace(id=1993247449))
            bot.handle_order_lookup(message)

        self.assertIn("ORD-123", bot.bot.messages[0][1])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_bot.AdminOrderFlowTests -v`
Expected: FAIL because order lookup handlers do not exist yet

- [ ] **Step 3: Write minimal admin order command implementation**

```python
@bot.message_handler(commands=["order"])
def handle_order_lookup(message):
    ensure_admin(message)
    _, order_id = message.text.split(maxsplit=1)
    order = shop_service.get_order_detail(order_id)
    bot.send_message(message.chat.id, format_order_detail(order), parse_mode="Markdown")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_bot.AdminOrderFlowTests -v`
Expected: PASS

- [ ] **Step 5: Extend coverage**

Add tests for:
- `/orders_user <id>`
- `/orders_username <username>`
- `/redeliver <order_id>`

- [ ] **Step 6: Checkpoint**

Checkpoint files: `bot.py`, `test_bot.py`, `services.py`

### Task 13: Add operational alerts and low-stock checks

**Files:**
- Modify: `services.py`
- Modify: `bot.py`
- Modify: `test_services.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Write the failing low-stock test**

```python
class AlertTests(unittest.TestCase):
    def test_get_low_stock_products_returns_only_products_below_threshold(self):
        service = services.ShopService(self.db_path)
        result = service.get_low_stock_products(threshold=2)
        self.assertEqual([row["product_id"] for row in result], ["prod_1"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_services.AlertTests.test_get_low_stock_products_returns_only_products_below_threshold -v`
Expected: FAIL because low-stock query is not implemented

- [ ] **Step 3: Write minimal alert implementation**

```python
def get_low_stock_products(self, threshold):
    return self.repo.find_products_below_available_threshold(threshold)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_services.AlertTests.test_get_low_stock_products_returns_only_products_below_threshold -v`
Expected: PASS

- [ ] **Step 5: Add bot command coverage**

Add bot-level tests and implementation for:
- `/lowstock`
- admin notification when a paid order enters `paid_delivery_failed`

- [ ] **Step 6: Checkpoint**

Checkpoint files: `services.py`, `bot.py`, `test_services.py`, `test_bot.py`

### Task 14: Remove JSON persistence from runtime paths

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`
- Modify: `migration.py`

- [ ] **Step 1: Write the failing regression test**

```python
class RuntimePersistenceTests(unittest.TestCase):
    def test_runtime_does_not_mutate_json_db(self):
        self.assertFalse(hasattr(bot, "db"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest test_bot.RuntimePersistenceTests.test_runtime_does_not_mutate_json_db -v`
Expected: FAIL because `bot.py` still loads and saves `db`

- [ ] **Step 3: Write minimal cleanup implementation**

```python
DB_PATH = "shop.db"
database.init_db(DB_PATH)

# keep data.json only for migration entrypoints
# remove load_data/save_data/db runtime globals
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest test_bot.RuntimePersistenceTests.test_runtime_does_not_mutate_json_db -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `python -m unittest -v`
Expected: PASS across `test_database.py`, `test_services.py`, and `test_bot.py`

- [ ] **Step 6: Final checkpoint**

Checkpoint files:
- `bot.py`
- `database.py`
- `repositories.py`
- `services.py`
- `migration.py`
- `test_bot.py`
- `test_database.py`
- `test_services.py`

## Verification Checklist

- [ ] SQLite schema initializes successfully on an empty database
- [ ] Product prices are stored as integers
- [ ] Bulk stock import creates one row per stock item
- [ ] Creating a pending order reserves stock atomically
- [ ] Payment success marks stock as sold and writes `order_items`
- [ ] Payment cancellation releases reserved stock
- [ ] Admin stock summaries return correct status counts
- [ ] Admin order lookup works by order ID, user ID, and username
- [ ] Re-delivery returns previously delivered items without allocating new stock
- [ ] Low-stock queries and admin alerts work
- [ ] `bot.py` no longer mutates JSON runtime state

## Execution Notes

- Initialize the SQLite file once at startup before Telegram polling begins.
- Keep `data.json` available until migration has been verified on production-like data.
- If PayOS order code lookup by internal order is easier operationally, add an index or helper method early rather than overloading Telegram handler logic.
- Prefer small incremental merges or checkpoints per task rather than a single large rewrite.

# CapCut Supplier Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-aware CapCut supplier integration that can sync all `CapCut` products from the new API into the `Tài khoản CapCut` category, compute live availability as `min(balance // api_price, api_stock)`, and fulfill paid orders automatically through the supplier API.

**Architecture:** Extend the existing supplier-product model with a `supplier_provider` field so the current `supplier_api` flow can support both the existing Sumistore supplier and the new CapCut API cleanly. Add a dedicated CapCut API client plus a sync service and `/admin` action, while keeping bot selling prices independent from supplier prices after first import.

**Tech Stack:** Python, SQLite (`sqlite3`), pyTelegramBotAPI, PowerShell-backed HTTP calls, unittest, temporary SQLite databases

---

## File Structure

### Existing files to modify

- `database.py`
  Add `supplier_provider` to the `products` schema and migration bootstrap.
- `repositories.py`
  Add read/write helpers for `supplier_provider`, provider-based product lookup, and bulk sync support.
- `services.py`
  Add CapCut sync orchestration and provider-aware product updates.
- `bot.py`
  Add `/admin` sync entrypoint, customer/admin runtime availability logic, and provider-aware purchase flow.
- `test_database.py`
  Extend schema and repository coverage for the new provider field.
- `test_services.py`
  Add sync and provider-aware service tests.
- `test_bot.py`
  Add admin sync flow, customer availability, and purchase behavior tests.
- `supplier_api.py`
  Keep current Sumistore client intact unless a shared abstraction is extracted.

### New files to create

- `capcut_api.py`
  PowerShell-backed client for `GET /api/products`, `GET /api/balance`, and `POST /api/buy`.
- `test_capcut_api.py`
  API client tests for auth header, JSON parsing, and error handling.

## Implementation Notes

- Match synced CapCut products by:
  - `supplier_provider = 'capcut_api'`
  - `supplier_product_id = <api id>`
- New CapCut products take their first bot selling price from the supplier API price.
- Existing CapCut products keep their current bot selling price on later syncs.
- Product names for CapCut always update from the API on sync.
- CapCut products removed from the API should be hidden with `is_active = 0`, not deleted.
- Category `Tài khoản CapCut` should be created automatically if missing and reactivated if currently hidden.
- Runtime availability for CapCut must use:
  - `balance_units = balance // api_price`
  - `available = min(balance_units, api_stock)`
- If the API fails or required fields are missing, availability falls back to `0`.

### Task 1: Add provider field to product schema

**Files:**
- Modify: `database.py`
- Modify: `test_database.py`

- [ ] **Step 1: Write the failing schema test**

```python
class DatabaseSchemaTests(SQLiteTestCase):
    def test_init_db_creates_expected_tables(self):
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
        }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.14 -m unittest test_database.DatabaseSchemaTests.test_init_db_creates_expected_tables -v`
Expected: FAIL because `supplier_provider` does not exist yet

- [ ] **Step 3: Add minimal schema support**

Implement in `database.py`:

```python
CREATE TABLE IF NOT EXISTS products (
    ...
    supplier_product_id TEXT,
    supplier_provider TEXT,
    sales_mode TEXT NOT NULL DEFAULT 'normal',
    ...
)
```

And bootstrap upgrade:

```python
if "supplier_provider" not in product_columns:
    conn.execute(
        "ALTER TABLE products ADD COLUMN supplier_provider TEXT"
    )
```

- [ ] **Step 4: Run schema tests**

Run: `py -3.14 -m unittest test_database.DatabaseSchemaTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database.py test_database.py
git commit -m "feat: add supplier provider field to products"
```

### Task 2: Add repository helpers for provider-aware products

**Files:**
- Modify: `repositories.py`
- Modify: `test_database.py`

- [ ] **Step 1: Write failing repository tests**

Add tests for:

```python
def test_create_product_defaults_supplier_provider_to_none(self):
    repo = repositories.Repository(self.db_path)
    product = repo.create_product("prod_1", "CapCut 1 month", 30000)
    self.assertIsNone(product["supplier_provider"])

def test_update_product_supplier_provider(self):
    repo = repositories.Repository(self.db_path)
    repo.create_product("prod_1", "CapCut 1 month", 30000)
    stored = repo.update_product_supplier_provider("prod_1", "capcut_api")
    self.assertEqual(stored["supplier_provider"], "capcut_api")

def test_list_products_by_supplier_provider(self):
    ...
```

- [ ] **Step 2: Run repository tests to confirm failure**

Run: `py -3.14 -m unittest test_database.ProductRepositoryTests -v`
Expected: FAIL because provider helpers do not exist

- [ ] **Step 3: Implement repository helpers**

Add:

```python
def update_product_supplier_provider(self, product_id, supplier_provider):
    ...

def list_products_by_supplier_provider(self, supplier_provider):
    ...

def get_product_by_supplier_mapping(self, supplier_provider, supplier_product_id):
    ...
```

Ensure `create_product()` stores `supplier_provider = NULL`.

- [ ] **Step 4: Run repository tests**

Run: `py -3.14 -m unittest test_database.ProductRepositoryTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add repositories.py test_database.py
git commit -m "feat: add provider-aware product repository helpers"
```

### Task 3: Add CapCut API client

**Files:**
- Create: `capcut_api.py`
- Create: `test_capcut_api.py`

- [ ] **Step 1: Write failing API client tests**

```python
class CapcutApiClientTests(unittest.TestCase):
    def test_get_products_uses_api_key_header(self):
        ...

    def test_get_balance_returns_json(self):
        ...

    def test_buy_product_posts_expected_body(self):
        ...
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `py -3.14 -m unittest test_capcut_api -v`
Expected: FAIL because `capcut_api.py` does not exist

- [ ] **Step 3: Implement the client**

Implement PowerShell-backed requests similar to the current supplier client:

```python
class CapcutApiClient:
    def get_products(self):
        return self._request_json("GET", "/products")

    def get_balance(self):
        return self._request_json("GET", "/balance")

    def buy_product(self, product_id, quantity):
        return self._request_json(
            "POST",
            "/buy",
            body={"product_id": product_id, "quantity": quantity},
        )
```

Use:

```python
headers = {"X-API-Key": api_key}
```

- [ ] **Step 4: Run API client tests**

Run: `py -3.14 -m unittest test_capcut_api -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add capcut_api.py test_capcut_api.py
git commit -m "feat: add CapCut supplier API client"
```

### Task 4: Add provider-aware product service methods

**Files:**
- Modify: `services.py`
- Modify: `test_services.py`

- [ ] **Step 1: Write failing service tests**

Add tests for:

```python
def test_update_product_supplier_provider(self):
    service = services.ShopService(self.db_path)
    product = service.create_product("CapCut", "30.000đ")
    service.update_product_supplier_provider(product["id"], "capcut_api")
    stored = repositories.Repository(self.db_path).get_product(product["id"])
    self.assertEqual(stored["supplier_provider"], "capcut_api")
```

Also validate invalid providers raise `ValueError`.

- [ ] **Step 2: Run service tests to confirm failure**

Run: `py -3.14 -m unittest test_services.AdminProductServiceTests -v`
Expected: FAIL because the service method does not exist

- [ ] **Step 3: Implement minimal service methods**

Add in `services.py`:

```python
def update_product_supplier_provider(self, product_id, supplier_provider):
    if supplier_provider not in {None, "sumistore", "capcut_api"}:
        raise ValueError("Invalid supplier provider")
    ...
```

- [ ] **Step 4: Run service tests**

Run: `py -3.14 -m unittest test_services.AdminProductServiceTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services.py test_services.py
git commit -m "feat: add provider-aware product service methods"
```

### Task 5: Add CapCut sync service

**Files:**
- Modify: `services.py`
- Modify: `repositories.py`
- Modify: `test_services.py`

- [ ] **Step 1: Write failing sync tests**

Add tests for:

```python
def test_sync_capcut_products_creates_category_and_new_products(self):
    ...

def test_sync_capcut_products_updates_name_but_keeps_existing_price(self):
    ...

def test_sync_capcut_products_hides_removed_products(self):
    ...
```

Use a fake API payload with:

```python
[
    {"id": "cc_1", "name": "CapCut Pro 1 tháng", "price": 30000, "stock": 40},
    {"id": "cc_2", "name": "CapCut Pro 1 năm", "price": 120000, "stock": 10},
]
```

- [ ] **Step 2: Run sync tests to confirm failure**

Run: `py -3.14 -m unittest test_services -v`
Expected: FAIL because sync service does not exist

- [ ] **Step 3: Implement sync service**

Add a method such as:

```python
def sync_capcut_products(self, api_products):
    category = self.ensure_capcut_category()
    ...
    return {
        "created": created_count,
        "updated": updated_count,
        "hidden": hidden_count,
        "errors": errors,
    }
```

Rules:
- filter `CapCut` by case-insensitive name match
- set `fulfillment_mode = supplier_api`
- set `supplier_provider = capcut_api`
- set `supplier_product_id = api id`
- assign category
- new product price = API price
- existing product price unchanged
- existing name updated from API
- hide removed products

- [ ] **Step 4: Run sync tests**

Run: `py -3.14 -m unittest test_services -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services.py repositories.py test_services.py
git commit -m "feat: add CapCut product sync service"
```

### Task 6: Add runtime availability calculation for CapCut

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Write failing runtime tests**

Add tests for:

```python
def test_get_runtime_product_uses_min_of_balance_units_and_api_stock_for_capcut(self):
    # balance 70000, api price 30000 => 2 units, api stock 10 => available 2
    ...

def test_get_runtime_product_caps_by_api_stock_for_capcut(self):
    # balance 300000, api price 30000 => 10 units, api stock 3 => available 3
    ...
```

- [ ] **Step 2: Run bot tests to confirm failure**

Run: `py -3.14 -m unittest test_bot.SupplierProcessPurchaseTests -v`
Expected: FAIL because CapCut provider logic is not implemented

- [ ] **Step 3: Implement provider-aware runtime availability**

In `bot.py`, branch by:

```python
if fulfillment_mode == "supplier_api":
    if supplier_provider == "sumistore":
        available = ...
    elif supplier_provider == "capcut_api":
        available = min(balance // api_price, api_stock)
```

Factor the provider-specific logic into helpers so `bot.py` does not become one large conditional block.

- [ ] **Step 4: Run bot runtime tests**

Run: `py -3.14 -m unittest test_bot.SupplierProcessPurchaseTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py test_bot.py
git commit -m "feat: add CapCut runtime availability calculation"
```

### Task 7: Add CapCut supplier pre-check and purchase flow

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Write failing purchase-flow tests**

Add tests for:

```python
def test_process_purchase_capcut_blocks_when_balance_units_below_qty(self):
    ...

def test_process_purchase_capcut_blocks_when_api_stock_below_qty(self):
    ...

def test_complete_paid_order_capcut_buys_from_api_and_delivers(self):
    ...
```

- [ ] **Step 2: Run purchase-flow tests to confirm failure**

Run: `py -3.14 -m unittest test_bot.SupplierProcessPurchaseTests -v`
Expected: FAIL because provider-aware buy flow does not exist

- [ ] **Step 3: Implement provider-aware supplier flow**

Use provider-specific clients in:

- pre-check
- post-payment buy
- account extraction

Normalize the CapCut buy response:

```python
response["order"]["accounts"]
```

into the existing internal delivered account list.

- [ ] **Step 4: Run purchase-flow tests**

Run: `py -3.14 -m unittest test_bot.SupplierProcessPurchaseTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py test_bot.py
git commit -m "feat: add CapCut supplier fulfillment flow"
```

### Task 8: Add `/admin` sync button and summary message

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Write failing admin flow tests**

Add tests for:

```python
def test_show_admin_menu_includes_sync_capcut_button(self):
    ...

def test_admin_sync_capcut_creates_category_and_reports_summary(self):
    ...
```

- [ ] **Step 2: Run admin flow tests to confirm failure**

Run: `py -3.14 -m unittest test_bot.SQLiteAdminFlowTests -v`
Expected: FAIL because the sync button does not exist

- [ ] **Step 3: Implement admin UI**

In `bot.py`:

- add button `🔄 Sync CapCut`
- add callback handler
- call the CapCut sync service
- report summary:

```text
✅ Đồng bộ CapCut hoàn tất
Đã tạo: X
Đã cập nhật: Y
Đã ẩn: Z
Lỗi: N
```

- [ ] **Step 4: Run admin flow tests**

Run: `py -3.14 -m unittest test_bot.SQLiteAdminFlowTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py test_bot.py
git commit -m "feat: add admin CapCut sync action"
```

### Task 9: Full regression verification

**Files:**
- Modify: `test_database.py`
- Modify: `test_services.py`
- Modify: `test_bot.py`
- Create: `test_capcut_api.py`

- [ ] **Step 1: Run focused suites**

Run:

```bash
py -3.14 -m unittest test_database.DatabaseSchemaTests test_services.AdminProductServiceTests test_services.CategoryServiceTests -v
py -3.14 -m unittest test_capcut_api -v
py -3.14 -m unittest test_bot.SQLiteAdminFlowTests test_bot.SupplierProcessPurchaseTests -v
```

Expected: PASS

- [ ] **Step 2: Run the full suite**

Run:

```bash
py -3.14 -m unittest test_database test_services test_bot test_supplier_api test_capcut_api -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add test_database.py test_services.py test_bot.py test_capcut_api.py
git commit -m "test: cover CapCut sync and provider flow"
```

### Task 10: Manual operator validation notes

**Files:**
- Modify: `docs/superpowers/specs/2026-03-27-capcut-sync-design.md`
- Modify: `README.md` if present

- [ ] **Step 1: Document manual validation steps**

Add a short operator checklist:

1. Open `/admin`
2. Press `🔄 Sync CapCut`
3. Verify category `Tài khoản CapCut` exists
4. Verify imported products appear with category assignment
5. Verify removed API products are hidden
6. Verify one CapCut product shows:
   - price from bot
   - stock from `min(balance // api_price, api_stock)`
7. Place a test order and confirm supplier fulfillment

- [ ] **Step 2: Run one final git status check**

Run:

```bash
git status --short
```

Expected: only intentional changes remain

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-03-27-capcut-sync-design.md README.md
git commit -m "docs: add CapCut sync operator checklist"
```

# Category And Product Description Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add editable descriptions for categories and products, then show the resolved description to customers on the quantity-selection screen with product-level overrides taking precedence over category-level text.

**Architecture:** Extend the existing SQLite schema with `description` columns on `categories` and `products`, expose CRUD helpers through `repositories.py` and `services.py`, and wire new Telegram admin flows for create/edit operations. Replace the hardcoded Google AI Pro quantity-step note with a generic runtime resolver that uses `product.description` first and falls back to `category.description`.

**Tech Stack:** Python, SQLite (`sqlite3`), pyTelegramBotAPI, unittest, temporary SQLite test databases

---

## File Structure

### Existing files to modify

- `database.py`
  Add `description` columns to `categories` and `products`, plus schema upgrade logic.
- `repositories.py`
  Persist and update category/product descriptions.
- `services.py`
  Add service methods for create/update description flows and resolved-description lookup.
- `bot.py`
  Add admin next-step flows for category/product descriptions and render the resolved description on the customer quantity screen.
- `test_database.py`
  Extend schema and repository coverage for description fields.
- `test_services.py`
  Cover description CRUD and precedence logic.
- `test_bot.py`
  Cover admin create/edit flows and quantity-screen rendering.

### Existing behavior to remove or replace

- `bot.py`
  Remove the hardcoded Google AI Pro quantity-step note helper path and replace it with DB-backed description resolution.

## Implementation Notes

- `categories.description` and `products.description` should default to `''`.
- Admin entering `-` must clear the description to `''`.
- Product description precedence:
  1. `products.description`
  2. `categories.description`
  3. no description block
- Description line breaks should be preserved exactly as stored.
- Quantity-step rendering must not block purchases if description lookup fails; fail open to the existing flow.

### Task 1: Add schema support for descriptions

**Files:**
- Modify: `database.py`
- Modify: `test_database.py`

- [ ] **Step 1: Write the failing schema test**

Add assertions to `test_init_db_creates_expected_tables` so the expected columns include:

```python
"products": [
    "id",
    "name",
    "price",
    "category_id",
    "description",
    "fulfillment_mode",
    ...
],
"categories": [
    "id",
    "name",
    "description",
    "is_active",
    ...
],
```

- [ ] **Step 2: Run schema tests to confirm failure**

Run: `py -3.14 -m unittest test_database.DatabaseSchemaTests -v`
Expected: FAIL because the description columns do not exist yet

- [ ] **Step 3: Implement minimal schema changes**

Update `database.py`:

```python
CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    ...
)

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    category_id TEXT,
    description TEXT NOT NULL DEFAULT '',
    fulfillment_mode TEXT NOT NULL DEFAULT 'local_stock',
    ...
)
```

Add migration guards:

```python
if "description" not in product_columns:
    conn.execute("ALTER TABLE products ADD COLUMN description TEXT NOT NULL DEFAULT ''")

if "description" not in category_columns:
    conn.execute("ALTER TABLE categories ADD COLUMN description TEXT NOT NULL DEFAULT ''")
```

- [ ] **Step 4: Run schema tests**

Run: `py -3.14 -m unittest test_database.DatabaseSchemaTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database.py test_database.py
git commit -m "feat: add description fields to products and categories"
```

### Task 2: Add repository helpers for category and product descriptions

**Files:**
- Modify: `repositories.py`
- Modify: `test_database.py`

- [ ] **Step 1: Write failing repository tests**

Add tests like:

```python
def test_create_category_persists_description(self):
    repo = repositories.Repository(self.db_path)
    category = repo.create_category("cat_1", "Google AI", "Shared note")
    self.assertEqual(category["description"], "Shared note")

def test_update_category_description(self):
    repo = repositories.Repository(self.db_path)
    repo.create_category("cat_1", "Google AI", "")
    updated = repo.update_category_description("cat_1", "New note")
    self.assertEqual(updated["description"], "New note")

def test_update_product_description(self):
    repo = repositories.Repository(self.db_path)
    repo.create_product("prod_1", "Product A", 100000)
    updated = repo.update_product_description("prod_1", "Product note")
    self.assertEqual(updated["description"], "Product note")
```

- [ ] **Step 2: Run repository tests to confirm failure**

Run: `py -3.14 -m unittest test_database.ProductRepositoryTests -v`
Expected: FAIL because description helpers do not exist

- [ ] **Step 3: Implement repository helpers**

Add or update:

```python
def create_category(self, category_id, name, description=""):
    ...

def update_category_description(self, category_id, description):
    ...

def update_product_description(self, product_id, description):
    ...
```

Ensure category/product fetch methods return the new `description` field.

- [ ] **Step 4: Run repository tests**

Run: `py -3.14 -m unittest test_database.ProductRepositoryTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add repositories.py test_database.py
git commit -m "feat: add repository support for descriptions"
```

### Task 3: Add service methods and precedence logic

**Files:**
- Modify: `services.py`
- Modify: `test_services.py`

- [ ] **Step 1: Write failing service tests**

Add tests like:

```python
def test_create_category_accepts_description(self):
    service = services.ShopService(self.db_path)
    category = service.create_category("Google AI", "Shared category note")
    self.assertEqual(category["description"], "Shared category note")

def test_update_category_description(self):
    ...

def test_update_product_description(self):
    ...

def test_get_resolved_product_description_prefers_product_description(self):
    ...

def test_get_resolved_product_description_falls_back_to_category(self):
    ...
```

- [ ] **Step 2: Run service tests to confirm failure**

Run: `py -3.14 -m unittest test_services -v`
Expected: FAIL because the new service methods do not exist yet

- [ ] **Step 3: Implement minimal service logic**

Update `services.py`:

```python
def create_category(self, name, description=""):
    category_name = str(name or "").strip()
    category_description = str(description or "").strip()
    ...

def update_category_description(self, category_id, description):
    ...

def update_product_description(self, product_id, description):
    ...

def get_resolved_product_description(self, product_id):
    product = self.repo.get_product(product_id)
    if product is None:
        raise ValueError("Product does not exist")
    if str(product["description"] or "").strip():
        return product["description"]
    category_id = product["category_id"]
    if not category_id:
        return ""
    category = self.repo.get_category(category_id)
    if category is None:
        return ""
    return str(category["description"] or "")
```

- [ ] **Step 4: Run service tests**

Run: `py -3.14 -m unittest test_services -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services.py test_services.py
git commit -m "feat: add description service flow"
```

### Task 4: Add admin flow for category creation with description

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Write failing bot tests**

Add tests for:

```python
def test_admin_create_category_prompts_for_description_after_name(self):
    ...

def test_admin_process_create_category_saves_description(self):
    ...

def test_admin_process_create_category_allows_dash_to_clear_description(self):
    ...
```

- [ ] **Step 2: Run focused bot tests to confirm failure**

Run: `py -3.14 -m unittest test_bot.CategoryBotFlowTests -v`
Expected: FAIL because category creation only captures a name today

- [ ] **Step 3: Implement create-category description flow**

Update `bot.py`:
- keep `admin_create_category` prompt for the name
- change `admin_process_create_category` so it:
  - validates/stores the name temporarily
  - prompts for multi-line description
  - registers a new next-step handler such as `admin_process_create_category_description`
- implement:

```python
def admin_process_create_category_description(message, category_name):
    raw = message.text or ""
    description = "" if raw.strip() == "-" else raw.strip()
    category = shop_service.create_category(category_name, description)
    ...
```

- [ ] **Step 4: Run focused bot tests**

Run: `py -3.14 -m unittest test_bot.CategoryBotFlowTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py test_bot.py
git commit -m "feat: add category description creation flow"
```

### Task 5: Add admin editing for category descriptions

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Write failing bot tests**

Add coverage for:

```python
def test_admin_category_detail_shows_description_status(self):
    ...

def test_admin_edit_category_description_updates_sqlite(self):
    ...

def test_admin_edit_category_description_dash_clears_description(self):
    ...
```

- [ ] **Step 2: Run focused bot tests to confirm failure**

Run: `py -3.14 -m unittest test_bot.CategoryBotFlowTests -v`
Expected: FAIL because no category-description edit action exists

- [ ] **Step 3: Implement category description editing**

Update `show_admin_category_detail()` to add:

```python
InlineKeyboardButton("📝 Sửa mô tả", callback_data=f"admin_editcategorydesc_{category_id}")
```

Add callback handling plus next-step handler:

```python
def admin_process_edit_category_description(message, category_id):
    raw = message.text or ""
    description = "" if raw.strip() == "-" else raw.strip()
    category = shop_service.update_category_description(category_id, description)
    ...
```

Show compact state in category detail:
- `Mô tả: Chưa thiết lập`
- or `Mô tả: Đã thiết lập`

- [ ] **Step 4: Run focused bot tests**

Run: `py -3.14 -m unittest test_bot.CategoryBotFlowTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py test_bot.py
git commit -m "feat: add category description editing"
```

### Task 6: Add admin editing for product descriptions

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Write failing bot tests**

Add coverage for:

```python
def test_admin_product_detail_shows_description_status(self):
    ...

def test_admin_edit_product_description_updates_sqlite(self):
    ...

def test_admin_edit_product_description_dash_clears_description(self):
    ...
```

- [ ] **Step 2: Run focused bot tests to confirm failure**

Run: `py -3.14 -m unittest test_bot.SQLiteAdminFlowTests -v`
Expected: FAIL because product description editing does not exist

- [ ] **Step 3: Implement product description editing**

Update product detail screen to add:

```python
InlineKeyboardButton("📝 Sửa mô tả", callback_data=f"admin_editdesc_{product_id}")
```

Add callback and next-step handler:

```python
def admin_process_edit_product_description(message, product_id):
    raw = message.text or ""
    description = "" if raw.strip() == "-" else raw.strip()
    product = shop_service.update_product_description(product_id, description)
    ...
```

Show compact state in product detail:
- `Mô tả riêng: Chưa thiết lập`
- or `Mô tả riêng: Đã thiết lập`

- [ ] **Step 4: Run focused bot tests**

Run: `py -3.14 -m unittest test_bot.SQLiteAdminFlowTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py test_bot.py
git commit -m "feat: add product description editing"
```

### Task 7: Replace hardcoded quantity note with resolved DB descriptions

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Write failing customer-flow tests**

Add tests for:

```python
def test_quantity_screen_uses_category_description_when_product_description_is_empty(self):
    ...

def test_quantity_screen_prefers_product_description_over_category_description(self):
    ...

def test_quantity_screen_omits_description_when_both_are_empty(self):
    ...
```

Update or remove the Google AI Pro special-case test so it now asserts DB-driven behavior instead of hardcoded behavior.

- [ ] **Step 2: Run focused user-flow tests to confirm failure**

Run: `py -3.14 -m unittest test_bot.UserHomeFlowTests -v`
Expected: FAIL because the quantity screen still uses the hardcoded note path

- [ ] **Step 3: Implement resolved description rendering**

In `bot.py`:
- remove the hardcoded Google AI Pro note helper path
- resolve description via service:

```python
description = shop_service.get_resolved_product_description(product_id)
description_block = f"\n\n{description}" if description else ""
```

Inject it into the quantity-selection text between stock line and quantity prompt.

- [ ] **Step 4: Run focused user-flow tests**

Run: `py -3.14 -m unittest test_bot.UserHomeFlowTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py test_bot.py
git commit -m "feat: render quantity-step descriptions from sqlite"
```

### Task 8: Full regression verification

**Files:**
- Modify: `test_database.py`
- Modify: `test_services.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Run the full suite**

Run: `py -3.14 -m unittest test_database test_services test_bot test_supplier_api test_capcut_api -v`
Expected: PASS

- [ ] **Step 2: Inspect for any remaining hardcoded quantity-note logic**

Run: `rg -n "Google AI Pro|2fa.live|Mã 2FA|Bảo hành 7 ngày" bot.py test_bot.py`
Expected: only test fixtures or admin-configurable seed text remain, not hardcoded rendering logic

- [ ] **Step 3: Commit final cleanup**

```bash
git add bot.py test_database.py test_services.py test_bot.py
git commit -m "test: cover category and product description flows"
```

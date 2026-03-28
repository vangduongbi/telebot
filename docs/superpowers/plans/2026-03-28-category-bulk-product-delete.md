# Category Bulk Product Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin action that hard-deletes all eligible products in a category while safely skipping products that already have order or stock history.

**Architecture:** Extend the repository with safe hard-delete helpers and history checks, add a service method that performs selective deletion and returns a structured summary, then wire new Telegram admin confirmation and result screens into the existing category-detail flow. Keep category deletion behavior unchanged and constrain the new action to product cleanup only.

**Tech Stack:** Python, SQLite (`sqlite3`), pyTelegramBotAPI, unittest, temporary SQLite test databases

---

## File Structure

### Existing files to modify

- `repositories.py`
  Add helpers to list products for category cleanup, detect whether a product has blocking history, and hard-delete eligible products.
- `services.py`
  Add a selective bulk-delete service that validates the category, deletes only safe products, and returns a deletion summary.
- `bot.py`
  Add a new admin button on category detail, a confirmation screen, and a result summary screen for the bulk-delete action.
- `test_database.py`
  Cover repository history checks and hard-delete behavior.
- `test_services.py`
  Cover selective deletion, skip behavior, empty categories, and missing categories.
- `test_bot.py`
  Cover the new button, confirmation flow, and result summary rendering.

### Existing behavior to preserve

- `services.py::delete_category`
  Must continue to only delete the category record logically and move products to uncategorized.
- `bot.py` category management
  Existing rename, description, hide/show, and delete-category flows must continue to work.

## Implementation Notes

- A product is eligible for hard deletion only if:
  - there are no rows in `orders` where `product_id = ?`
  - there are no rows in `stock_items` where `product_id = ?`
- If a product has stock history, treat it as non-deletable even if there are no orders.
- Mixed categories must be handled partially:
  - delete eligible products
  - skip protected products
  - report both outcomes
- The category itself remains after this action.
- The new action should operate on products currently assigned to the category, including inactive products if they are still attached to that category.

## Suggested Test Targets

- `test_database.ProductRepositoryTests`
- `test_services.CategoryServiceTests`
- `test_bot.CategoryBotFlowTests`

### Task 1: Add repository support for safe hard delete

**Files:**
- Modify: `repositories.py`
- Modify: `test_database.py`

- [ ] **Step 1: Write failing repository tests**

Add tests in `test_database.ProductRepositoryTests` for:

```python
def test_product_has_history_false_for_clean_product(self):
    repo = repositories.Repository(self.db_path)
    repo.create_product("prod_clean", "Clean product", 1000)
    self.assertFalse(repo.product_has_history("prod_clean"))

def test_product_has_history_true_when_stock_exists(self):
    repo = repositories.Repository(self.db_path)
    repo.create_product("prod_stock", "Stocked product", 1000)
    repo.add_stock_items("prod_stock", ["email|pass"], batch_id="batch-1")
    self.assertTrue(repo.product_has_history("prod_stock"))

def test_product_has_history_true_when_order_exists(self):
    repo = repositories.Repository(self.db_path)
    repo.create_product("prod_order", "Ordered product", 1000)
    repo.create_order(
        order_id="ORD-1",
        order_code=100001,
        user_id=1,
        username="@u",
        full_name="User",
        product_id="prod_order",
        qty=1,
        unit_price=1000,
        total_amount=1000,
        status="pending_payment",
        payos_ref=None,
        note=None,
        created_at=123,
    )
    self.assertTrue(repo.product_has_history("prod_order"))

def test_delete_product_hard_removes_clean_product(self):
    repo = repositories.Repository(self.db_path)
    repo.create_product("prod_clean", "Clean product", 1000)
    repo.delete_product_hard("prod_clean")
    self.assertIsNone(repo.get_product("prod_clean"))
```

- [ ] **Step 2: Run repository tests to confirm failure**

Run: `py -3.14 -m unittest test_database.ProductRepositoryTests -v`

Expected:
- FAIL because `product_has_history` and `delete_product_hard` do not exist yet

- [ ] **Step 3: Implement minimal repository helpers**

Add helpers to `repositories.py`:

```python
def list_products_for_category_management(self, category_id):
    conn = database.get_connection(self.db_path)
    try:
        return conn.execute(
            """
            SELECT *
            FROM products
            WHERE category_id = ?
            ORDER BY id
            """,
            (category_id,),
        ).fetchall()
    finally:
        conn.close()

def product_has_history(self, product_id):
    conn = database.get_connection(self.db_path)
    try:
        has_order = conn.execute(
            "SELECT 1 FROM orders WHERE product_id = ? LIMIT 1",
            (product_id,),
        ).fetchone()
        if has_order is not None:
            return True
        has_stock = conn.execute(
            "SELECT 1 FROM stock_items WHERE product_id = ? LIMIT 1",
            (product_id,),
        ).fetchone()
        return has_stock is not None
    finally:
        conn.close()

def delete_product_hard(self, product_id):
    with database.transaction(self.db_path) as conn:
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
```

- [ ] **Step 4: Run repository tests**

Run: `py -3.14 -m unittest test_database.ProductRepositoryTests -v`

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add repositories.py test_database.py
git commit -m "feat: add repository support for safe bulk product deletion"
```

### Task 2: Add selective category product deletion service

**Files:**
- Modify: `services.py`
- Modify: `test_services.py`

- [ ] **Step 1: Write failing service tests**

Add tests in `test_services.CategoryServiceTests` for:

```python
def test_delete_category_products_deletes_all_clean_products(self):
    service = services.ShopService(self.db_path)
    category = service.create_category("Cat A")
    prod1 = service.create_product("P1", "1.000đ")
    prod2 = service.create_product("P2", "2.000đ")
    service.assign_product_category(prod1["id"], category["id"])
    service.assign_product_category(prod2["id"], category["id"])

    summary = service.delete_category_products(category["id"])

    self.assertEqual(summary["deleted_count"], 2)
    self.assertEqual(summary["skipped_names"], [])

def test_delete_category_products_skips_product_with_stock_history(self):
    ...

def test_delete_category_products_skips_product_with_order_history(self):
    ...

def test_delete_category_products_returns_zero_for_empty_category(self):
    ...

def test_delete_category_products_raises_for_missing_category(self):
    ...
```

- [ ] **Step 2: Run service tests to confirm failure**

Run: `py -3.14 -m unittest test_services.CategoryServiceTests -v`

Expected:
- FAIL because `delete_category_products` does not exist yet

- [ ] **Step 3: Implement minimal service logic**

Add to `services.py`:

```python
def delete_category_products(self, category_id):
    category = self.repo.get_category(category_id)
    if category is None:
        raise ValueError("Category does not exist")

    products = self.repo.list_products_for_category_management(category_id)
    deleted_names = []
    skipped_names = []

    for product in products:
        if self.repo.product_has_history(product["id"]):
            skipped_names.append(product["name"])
            continue
        self.repo.delete_product_hard(product["id"])
        deleted_names.append(product["name"])

    return {
        "deleted_count": len(deleted_names),
        "deleted_names": deleted_names,
        "skipped_names": skipped_names,
    }
```

Keep the implementation simple first. If later tests reveal transaction coupling issues, move the loop into a single repository transaction in a follow-up edit within the same task.

- [ ] **Step 4: Run service tests**

Run: `py -3.14 -m unittest test_services.CategoryServiceTests -v`

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add services.py test_services.py
git commit -m "feat: add selective category product deletion service"
```

### Task 3: Add admin confirmation and result flow

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [ ] **Step 1: Write failing bot tests**

Add tests in `test_bot.CategoryBotFlowTests` for:

```python
def test_category_detail_shows_bulk_delete_button(self):
    ...
    self.assertIn("🧹 Xóa toàn bộ sản phẩm", text_or_markup_dump)

def test_show_bulk_delete_confirmation(self):
    ...
    self.assertIn("xóa cứng", sent_text.lower())
    self.assertIn("admin_confirmdeletecategoryproducts_", callback_data)

def test_confirm_bulk_delete_shows_summary_with_skipped_names(self):
    ...
    self.assertIn("Đã xóa: 1", sent_text)
    self.assertIn("Bỏ qua: 1", sent_text)
    self.assertIn("Protected Product", sent_text)
```

- [ ] **Step 2: Run bot tests to confirm failure**

Run: `py -3.14 -m unittest test_bot.CategoryBotFlowTests -v`

Expected:
- FAIL because the new button/callbacks/screens do not exist yet

- [ ] **Step 3: Implement minimal bot flow**

Update `bot.py`:

1. In `show_admin_category_detail(...)`, add:

```python
markup.add(
    InlineKeyboardButton(
        "🧹 Xóa toàn bộ sản phẩm",
        callback_data=f"admin_deletecategoryproducts_{category_id}",
    )
)
```

2. Add a confirmation renderer:

```python
def show_category_products_delete_confirmation(chat_id, message_id, category_id):
    ...
```

3. Add callback handlers:

```python
if call.data.startswith("admin_deletecategoryproducts_"):
    ...

if call.data.startswith("admin_confirmdeletecategoryproducts_"):
    summary = shop_service.delete_category_products(category_id)
    ...
```

4. Render a summary like:

```python
lines = [
    "🧹 Đã xử lý xóa sản phẩm trong category.",
    f"Đã xóa: {summary['deleted_count']}",
    f"Bỏ qua: {len(summary['skipped_names'])}",
]
if summary["skipped_names"]:
    lines.append("")
    lines.append("Sản phẩm bị bỏ qua:")
    lines.extend(f"• {name}" for name in summary["skipped_names"])
```

- [ ] **Step 4: Run bot tests**

Run: `py -3.14 -m unittest test_bot.CategoryBotFlowTests -v`

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py test_bot.py
git commit -m "feat: add admin bulk delete for category products"
```

### Task 4: Run focused regression tests and full suite

**Files:**
- Modify: `test_database.py` if any follow-up assertions are missing
- Modify: `test_services.py` if any follow-up assertions are missing
- Modify: `test_bot.py` if any follow-up assertions are missing

- [ ] **Step 1: Run focused regression tests**

Run:

```bash
py -3.14 -m unittest test_database.ProductRepositoryTests test_services.CategoryServiceTests test_bot.CategoryBotFlowTests -v
```

Expected:
- PASS

- [ ] **Step 2: Run full regression suite**

Run:

```bash
py -3.14 -m unittest test_database test_services test_bot test_supplier_api test_capcut_api -v
```

Expected:
- PASS

- [ ] **Step 3: Make any final wording or assertion fixes**

Only make minimal fixes required by failing tests or clearly broken admin text. Do not expand scope.

- [ ] **Step 4: Re-run the full regression suite**

Run:

```bash
py -3.14 -m unittest test_database test_services test_bot test_supplier_api test_capcut_api -v
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add test_database.py test_services.py test_bot.py repositories.py services.py bot.py
git commit -m "test: cover category bulk product deletion flow"
```

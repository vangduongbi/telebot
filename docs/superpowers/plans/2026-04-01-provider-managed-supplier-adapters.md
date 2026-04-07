# Provider-Managed Supplier Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add admin-managed supplier providers with protocol-based adapters so each product can choose a provider and remote `product_id`, while existing Sumistore and Node API products continue working after migration.

**Architecture:** Persist provider definitions in a new `supplier_providers` table, keep `products.supplier_provider` as the provider code reference, and route supplier-backed operations through a small runtime adapter layer that resolves `protocol defaults + provider overrides`. Extend the Telegram admin flows so operators can CRUD providers, assign providers to products, and maintain product supplier IDs without changing code for each new product.

**Tech Stack:** Python, SQLite (`sqlite3`), pyTelegramBotAPI, unittest, existing PowerShell-backed HTTP clients, temporary SQLite databases

---

## File Structure

### Existing files to modify

- `database.py`
  - add `supplier_providers` schema bootstrap.
- `migration.py`
  - add compatibility seeding and legacy provider remapping.
- `repositories.py`
  - add provider CRUD, lookup, listing, and usage-check helpers.
- `services.py`
  - add provider validation, product-provider assignment, and provider-aware sync compatibility helpers.
- `bot.py`
  - add admin provider management UI and product provider assignment flows.
  - replace hardcoded runtime provider branching with provider resolution.
- `test_database.py`
  - cover schema, repository, and migration behavior for provider configs.
- `test_services.py`
  - cover provider management rules and product-provider assignment behavior.
- `test_bot.py`
  - cover admin provider CRUD, product provider selection, and provider-aware runtime behavior.

### New files to create

- `supplier_runtime.py`
  - provider registry, protocol defaults, override merging, and runtime adapter selection.
- `test_supplier_runtime.py`
  - direct tests for protocol resolution, override behavior, and account extraction.

## Implementation Notes

- Preserve `products.supplier_provider` as the database column name, but change its meaning from legacy type to provider code.
- Seed compatibility providers:
  - `sumistore_default`
  - `capcut_default`
- Remap legacy product values:
  - `sumistore` -> `sumistore_default`
  - `capcut_api` -> `capcut_default`
- Keep the first provider override set small:
  - `products_path`
  - `balance_path`
  - `buy_path`
  - `auth_header`
  - `auth_query_param`
  - `buy_product_id_field`
  - `buy_quantity_field`
- Treat `capcut_api.py` as the initial implementation of the `node_api` protocol rather than renaming files immediately.
- Do not allow deleting a provider that is still referenced by any product.
- Customer-facing runtime failures should remain generic even when admin-facing messages are precise.

## Task 1: Add provider schema and migration compatibility

**Files:**
- Modify: `database.py`
- Modify: `migration.py`
- Modify: `test_database.py`

- [x] **Step 1: Write failing schema and migration tests**

Add tests for:

```python
class DatabaseSchemaTests(SQLiteTestCase):
    def test_init_db_creates_supplier_providers_table(self):
        ...

class ConfigMigrationTests(SQLiteTestCase):
    def test_migrate_json_seeds_compatibility_supplier_providers(self):
        ...

    def test_migrate_json_remaps_legacy_product_supplier_provider_values(self):
        ...
```

- [x] **Step 2: Run tests to verify failure**

Run: `py -3.14 -m unittest test_database.DatabaseSchemaTests test_database.ConfigMigrationTests -v`
Expected: FAIL because `supplier_providers` and legacy remapping do not exist yet

- [x] **Step 3: Add minimal schema and migration support**

Implement in `database.py`:

```python
CREATE TABLE IF NOT EXISTS supplier_providers (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    protocol TEXT NOT NULL,
    base_url TEXT NOT NULL,
    api_key TEXT,
    overrides_json TEXT NOT NULL DEFAULT '{}',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
```

Implement in `migration.py`:

```python
def _seed_compatibility_provider(...):
    ...

def _remap_legacy_product_provider_codes(...):
    ...
```

- [x] **Step 4: Run tests to verify green**

Run: `py -3.14 -m unittest test_database.DatabaseSchemaTests test_database.ConfigMigrationTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database.py migration.py test_database.py
git commit -m "feat: add supplier provider schema and migration"
```

## Task 2: Add repository support for provider configs

**Files:**
- Modify: `repositories.py`
- Modify: `test_database.py`

- [x] **Step 1: Write failing repository tests**

Add tests for:

```python
class ProductRepositoryTests(SQLiteTestCase):
    def test_create_supplier_provider_persists_row(self):
        ...

    def test_update_supplier_provider_fields(self):
        ...

    def test_list_supplier_providers_orders_by_name(self):
        ...

    def test_count_products_by_supplier_provider_code(self):
        ...
```

- [x] **Step 2: Run tests to verify failure**

Run: `py -3.14 -m unittest test_database.ProductRepositoryTests -v`
Expected: FAIL because provider repository helpers do not exist

- [x] **Step 3: Implement repository helpers**

Add methods such as:

```python
def create_supplier_provider(self, code, name, protocol, base_url, api_key, overrides_json, is_active=1):
    ...

def get_supplier_provider(self, code):
    ...

def list_supplier_providers(self, include_inactive=True):
    ...

def update_supplier_provider_name(self, code, name):
    ...

def update_supplier_provider_protocol(self, code, protocol):
    ...

def update_supplier_provider_base_url(self, code, base_url):
    ...

def update_supplier_provider_api_key(self, code, api_key):
    ...

def update_supplier_provider_overrides(self, code, overrides_json):
    ...

def set_supplier_provider_active(self, code, is_active):
    ...

def delete_supplier_provider(self, code):
    ...

def count_products_by_supplier_provider(self, code):
    ...
```

- [x] **Step 4: Run repository tests**

Run: `py -3.14 -m unittest test_database.ProductRepositoryTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add repositories.py test_database.py
git commit -m "feat: add supplier provider repository helpers"
```

## Task 3: Add service validation and product-provider assignment

**Files:**
- Modify: `services.py`
- Modify: `test_services.py`

- [x] **Step 1: Write failing service tests**

Add tests for:

```python
class SupplierProviderServiceTests(SQLiteServiceTestCase):
    def test_create_supplier_provider_validates_required_fields(self):
        ...

    def test_update_product_supplier_provider_requires_existing_provider(self):
        ...

    def test_delete_supplier_provider_rejects_when_products_still_reference_it(self):
        ...

    def test_list_supplier_providers_returns_created_provider(self):
        ...
```

- [x] **Step 2: Run tests to verify failure**

Run: `py -3.14 -m unittest test_services.SupplierProviderServiceTests test_services.AdminProductServiceTests -v`
Expected: FAIL because provider-aware service methods and validations do not exist

- [x] **Step 3: Implement minimal service layer**

Add service methods such as:

```python
def list_supplier_providers(self, include_inactive=True):
    ...

def create_supplier_provider(self, code, name, protocol, base_url, api_key="", overrides_json="{}"):
    ...

def update_supplier_provider_name(self, code, name):
    ...

def update_supplier_provider_protocol(self, code, protocol):
    ...

def update_supplier_provider_base_url(self, code, base_url):
    ...

def update_supplier_provider_api_key(self, code, api_key):
    ...

def update_supplier_provider_overrides(self, code, overrides_json):
    ...

def set_supplier_provider_active(self, code, is_active):
    ...

def delete_supplier_provider(self, code):
    ...
```

And update:

```python
def update_product_supplier_provider(self, product_id, supplier_provider):
    ...
```

so it accepts `None` or an existing provider code instead of a hardcoded set.

- [x] **Step 4: Run service tests**

Run: `py -3.14 -m unittest test_services.SupplierProviderServiceTests test_services.AdminProductServiceTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services.py test_services.py
git commit -m "feat: add supplier provider service rules"
```

## Task 4: Add supplier runtime registry and protocol adapters

**Files:**
- Create: `supplier_runtime.py`
- Create: `test_supplier_runtime.py`

- [x] **Step 1: Write failing runtime tests**

Add tests for:

```python
class SupplierRuntimeTests(unittest.TestCase):
    def test_resolve_provider_merges_protocol_defaults_with_overrides(self):
        ...

    def test_sumistore_protocol_uses_supplier_api_client(self):
        ...

    def test_node_api_protocol_uses_capcut_client_with_override_paths(self):
        ...

    def test_extract_delivered_accounts_returns_normalized_list(self):
        ...
```

- [x] **Step 2: Run tests to verify failure**

Run: `py -3.14 -m unittest test_supplier_runtime -v`
Expected: FAIL because `supplier_runtime.py` does not exist

- [x] **Step 3: Implement minimal runtime facade**

Implement:

```python
PROTOCOL_DEFAULTS = {
    "sumistore": {...},
    "node_api": {...},
}

def resolve_provider_config(provider_row):
    ...

class SupplierRuntime:
    def __init__(self, provider_row):
        ...

    def get_available_units(self, supplier_product_id):
        ...

    def check_purchase_ready(self, supplier_product_id, qty):
        ...

    def buy_product(self, supplier_product_id, qty):
        ...
```

Use the existing clients:

```python
from supplier_api import SupplierApiClient, SupplierApiError
from capcut_api import CapcutApiClient, CapcutApiError
```

- [x] **Step 4: Run runtime tests**

Run: `py -3.14 -m unittest test_supplier_runtime -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add supplier_runtime.py test_supplier_runtime.py
git commit -m "feat: add supplier runtime provider registry"
```

## Task 5: Refactor bot runtime to use provider configs

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [x] **Step 1: Write failing bot runtime tests**

Add tests for:

```python
def test_get_runtime_product_uses_configured_provider_for_node_api(self):
    ...

def test_check_supplier_purchase_ready_uses_provider_code_not_legacy_branch(self):
    ...

def test_complete_paid_order_uses_provider_runtime_buy_and_delivery_mapping(self):
    ...

def test_supplier_product_with_inactive_provider_is_unavailable(self):
    ...
```

- [x] **Step 2: Run tests to verify failure**

Run: `py -3.14 -m unittest test_bot.SupplierProcessPurchaseTests -v`
Expected: FAIL because `bot.py` still branches directly on legacy provider strings

- [x] **Step 3: Implement runtime integration**

Refactor helpers in `bot.py`:

```python
from supplier_runtime import SupplierRuntime, resolve_provider_config

def get_supplier_provider_config(product_like):
    ...

def get_supplier_runtime(product_like):
    ...
```

Replace direct `capcut_api` / `sumistore` branching inside:

- `get_runtime_product()`
- `list_runtime_products()`
- `check_supplier_purchase_ready()`
- `complete_paid_order()`

- [x] **Step 4: Run bot runtime tests**

Run: `py -3.14 -m unittest test_bot.SupplierProcessPurchaseTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py test_bot.py
git commit -m "refactor: route supplier fulfillment through provider runtime"
```

## Task 6: Add admin provider management flows

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`

- [x] **Step 1: Write failing admin flow tests**

Add tests for:

```python
def test_show_admin_menu_includes_manage_providers_button(self):
    ...

def test_admin_manage_providers_opens_provider_list(self):
    ...

def test_admin_process_create_supplier_provider_persists_provider(self):
    ...

def test_admin_toggle_supplier_provider_updates_status(self):
    ...
```

- [x] **Step 2: Run tests to verify failure**

Run: `py -3.14 -m unittest test_bot.SQLiteAdminFlowTests -v`
Expected: FAIL because provider admin callbacks and handlers do not exist yet

- [x] **Step 3: Implement minimal admin provider UI**

Add to `bot.py`:

- admin menu button `🔌 Quản lý Provider API`
- provider list screen
- provider detail screen
- create provider prompt
- edit prompts for name, protocol, base URL, API key, overrides
- toggle active callback
- delete callback guarded by usage count

Prefer small helper functions:

```python
def show_admin_provider_menu(...):
    ...

def show_admin_provider_detail(...):
    ...

def admin_process_create_supplier_provider(...):
    ...
```

- [x] **Step 4: Run admin flow tests**

Run: `py -3.14 -m unittest test_bot.SQLiteAdminFlowTests -v`
Expected: PASS for the new provider-management coverage

- [ ] **Step 5: Commit**

```bash
git add bot.py test_bot.py
git commit -m "feat: add admin supplier provider management"
```

## Task 7: Expand product supplier config UI to choose provider

**Files:**
- Modify: `bot.py`
- Modify: `test_bot.py`
- Modify: `test_services.py`

- [x] **Step 1: Write failing product config tests**

Add tests for:

```python
def test_show_product_supplier_config_displays_provider_and_protocol(self):
    ...

def test_admin_select_supplier_provider_assigns_provider_to_product(self):
    ...

def test_admin_process_supplier_product_id_keeps_existing_provider(self):
    ...
```

- [x] **Step 2: Run tests to verify failure**

Run: `py -3.14 -m unittest test_bot.SQLiteAdminFlowTests test_services.AdminProductServiceTests -v`
Expected: FAIL because product supplier config only supports fulfillment mode and raw supplier ID

- [x] **Step 3: Implement product provider assignment flow**

Update `show_product_supplier_config()` to include:

- provider display
- protocol display
- button to choose provider
- button to edit supplier product ID

Add callbacks and handlers such as:

```python
def show_product_supplier_provider_picker(...):
    ...

def admin_set_product_supplier_provider(...):
    ...
```

- [x] **Step 4: Run tests**

Run: `py -3.14 -m unittest test_bot.SQLiteAdminFlowTests test_services.AdminProductServiceTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py test_bot.py test_services.py
git commit -m "feat: allow assigning providers to products"
```

## Task 8: Keep existing CapCut sync compatible with provider codes

**Files:**
- Modify: `services.py`
- Modify: `bot.py`
- Modify: `test_services.py`
- Modify: `test_bot.py`

- [x] **Step 1: Write failing compatibility tests**

Add tests for:

```python
def test_sync_capcut_products_uses_seeded_capcut_default_provider(self):
    ...

def test_admin_sync_capcut_reports_summary_after_provider_migration(self):
    ...
```

- [x] **Step 2: Run tests to verify failure**

Run: `py -3.14 -m unittest test_services.CapcutSyncServiceTests test_bot.SQLiteAdminFlowTests -v`
Expected: FAIL because CapCut sync still hardcodes the legacy provider value

- [x] **Step 3: Implement compatibility update**

Adjust sync logic so it uses the compatibility provider code:

```python
CAPCUT_COMPAT_PROVIDER_CODE = "capcut_default"
```

and ensure the provider exists before syncing or reusing products.

- [x] **Step 4: Run compatibility tests**

Run: `py -3.14 -m unittest test_services.CapcutSyncServiceTests test_bot.SQLiteAdminFlowTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services.py bot.py test_services.py test_bot.py
git commit -m "refactor: keep capcut sync compatible with provider configs"
```

## Task 9: Run regression verification

**Files:**
- Modify: `docs/superpowers/plans/2026-04-01-provider-managed-supplier-adapters.md`
  - check off completed steps during execution only

- [x] **Step 1: Run focused regression suites**

Run:

```bash
py -3.14 -m unittest test_database.DatabaseSchemaTests test_database.ConfigMigrationTests test_database.ProductRepositoryTests -v
py -3.14 -m unittest test_services.SupplierProviderServiceTests test_services.CapcutSyncServiceTests test_services.AdminProductServiceTests -v
py -3.14 -m unittest test_supplier_runtime -v
py -3.14 -m unittest test_bot.SQLiteAdminFlowTests test_bot.SupplierProcessPurchaseTests -v
```

Expected: PASS

- [x] **Step 2: Run broader project regression**

Run:

```bash
py -3.14 -m unittest test_database test_services test_bot test_supplier_api test_capcut_api -v
```

Expected: PASS with no new provider-related regressions

- [ ] **Step 3: Perform manual admin smoke review**

Verify in Telegram admin flows:

- provider list opens
- provider create/edit works
- product can choose provider
- product supplier ID persists
- supplier-backed availability still renders

- [x] **Step 4: Update plan checklist status**

Mark completed steps in this file only after the tests and smoke checks succeed.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-04-01-provider-managed-supplier-adapters.md
git commit -m "docs: finalize provider managed supplier adapter plan"
```

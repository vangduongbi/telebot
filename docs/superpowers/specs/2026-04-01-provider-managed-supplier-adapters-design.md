# Provider-Managed Supplier Adapters Design

**Date:** 2026-04-01

**Status:** Approved in chat, written for file review

## Goal

Upgrade supplier-backed fulfillment so each product can be linked to an admin-managed provider configuration instead of hardcoded provider types. Admin should be able to add, edit, disable, and delete provider definitions, assign a provider and remote `product_id` to each product, and let the bot choose the correct API behavior at runtime based on the configured provider protocol.

## User Requirements

- Add an admin area to manage supplier providers.
- Each provider must be configurable with:
  - display name
  - unique provider code
  - base URL
  - API key
  - protocol or adapter type
  - protocol-specific overrides
  - active or inactive status
- Each product must be configurable with:
  - provider selection
  - remote supplier `product_id`
- Adding new products later should not require code changes if the provider protocol is already supported.
- Providers may use different endpoint paths, headers, auth conventions, and request shapes.
- Admin should be able to override protocol defaults for a specific provider.
- Existing supplier-backed products must keep working after migration.
- The bot should reject invalid configuration early and give clear admin-facing errors.

## Scope

This design covers:

- provider persistence and migration
- admin CRUD flows for providers
- product-to-provider assignment
- runtime provider resolution for stock, balance, pre-check, and purchase
- protocol adapter defaults with provider-level overrides
- compatibility with existing `sumistore` and `capcut_api` style behavior

This design does not cover:

- arbitrary scripting or custom code uploaded through admin
- a web dashboard outside Telegram
- provider-specific analytics beyond operational messages

## Current Problems

The current code stores supplier integration decisions in a single product field:

- `supplier_provider` is treated as a hardcoded type such as `sumistore` or `capcut_api`

This causes several limitations:

- adding a new provider often requires code changes
- provider credentials are not modeled as first-class admin-managed data
- the same protocol cannot be reused cleanly across multiple providers
- per-provider endpoint or header differences cannot be expressed safely
- product setup is incomplete because `supplier_product_id` exists but provider configuration is still mostly hardcoded

## Recommended Approach

### Option 1: Hardcode more provider branches in bot logic

This is the fastest short-term path but does not meet the requirement that future products and providers should be manageable from admin without code changes.

### Option 2: Fully manual request templates per provider

This is maximally flexible but too easy to misconfigure. It would make admin UX noisy and runtime validation much harder.

### Option 3: Protocol adapter defaults plus provider overrides

This is the recommended approach.

Each provider selects a supported `protocol` such as:

- `sumistore`
- `node_api`

The code owns the protocol adapter implementation and its safe defaults. Admin can then override selected request fields per provider, such as:

- products path
- balance path
- buy path
- auth header name
- auth query param name
- request field names like `product_id` and `quantity`

This keeps the runtime controlled, testable, and extensible while still allowing provider-specific variations.

## Architecture

The supplier layer should move from "product chooses hardcoded provider type" to "product references a provider configuration that resolves into a protocol adapter at runtime."

Key runtime pieces:

1. `supplier provider config`
   - persisted admin-managed configuration
   - referenced by product

2. `protocol adapter`
   - code-defined behavior for one protocol family
   - knows default endpoints, auth style, response mapping, and purchase request shape

3. `resolved provider config`
   - produced by merging protocol defaults with provider overrides
   - used by runtime purchase and stock flows

4. `supplier runtime facade`
   - entry point used by bot logic
   - loads the product's provider
   - selects the adapter by protocol
   - performs product lookup, availability calculation, pre-check, and purchase through a uniform interface

This lets the rest of the bot ask supplier-backed questions without caring which provider is behind the product.

## Data Model

### New table: `supplier_providers`

Required fields:

- `code` TEXT PRIMARY KEY
- `name` TEXT NOT NULL
- `protocol` TEXT NOT NULL
- `base_url` TEXT NOT NULL
- `api_key` TEXT
- `overrides_json` TEXT NOT NULL DEFAULT `'{}'`
- `is_active` INTEGER NOT NULL DEFAULT `1`
- `created_at` INTEGER NOT NULL
- `updated_at` INTEGER NOT NULL

Notes:

- `code` is the stable value stored on products.
- `overrides_json` stores a JSON object only, never freeform text templates.
- `api_key` may be blank for public endpoints, but runtime validation should fail for actions that need auth.

### Existing table: `products`

Keep:

- `fulfillment_mode`
- `supplier_product_id`
- `supplier_provider`

Change meaning of `supplier_provider`:

- from hardcoded provider type
- to provider code referencing `supplier_providers.code`

This avoids a disruptive product schema rename while still letting the code treat the field as a real provider reference.

## Migration Strategy

Migration must be safe for existing live products.

Steps:

1. Create `supplier_providers` if it does not already exist.
2. Seed compatibility providers when legacy values are present:
   - `sumistore_default`
   - `capcut_default`
3. Convert product mappings:
   - legacy `sumistore` -> `sumistore_default`
   - legacy `capcut_api` -> `capcut_default`
4. Preserve each product's existing `supplier_product_id`.
5. Leave local-stock products unchanged.

Seed defaults:

- `sumistore_default`
  - protocol: `sumistore`
  - base URL: current Sumistore base URL
  - API key: current Sumistore API key
- `capcut_default`
  - protocol: `node_api`
  - base URL: current Node API base URL
  - API key: current Node API key

Migration should be idempotent and safe to run multiple times.

## Provider Configuration Model

Each protocol defines supported default keys. The initial override set should stay intentionally small:

- `products_path`
- `balance_path`
- `buy_path`
- `auth_header`
- `auth_query_param`
- `buy_product_id_field`
- `buy_quantity_field`

Possible future keys can be added later without changing the core model.

Admin should edit overrides as compact JSON. Example:

```json
{
  "products_path": "/products",
  "balance_path": "/balance",
  "buy_path": "/buy",
  "auth_header": "X-API-Key",
  "buy_product_id_field": "product_id",
  "buy_quantity_field": "quantity"
}
```

Validation rules:

- must parse as JSON
- must be an object
- unknown keys should be rejected or clearly warned, depending on implementation choice
- values must be strings for the first version

## Admin UX

Add a new admin entry:

- `🔌 Quản lý Provider API`

Provider list screen:

- show active and inactive providers
- show provider name, code, protocol, and status
- open detail view per provider

Provider detail screen should show:

- name
- code
- protocol
- base URL
- API key masked in display
- overrides summary
- active or inactive state

Provider actions:

- `➕ Thêm provider`
- `✏️ Sửa tên`
- `🔧 Sửa protocol`
- `🌐 Sửa base URL`
- `🔑 Sửa API key`
- `🧩 Sửa overrides`
- `🟢 Bật/Tắt`
- `🗑️ Xóa`
- `🔙 Quay lại`

Product supplier config screen should be expanded to include:

- current fulfillment mode
- current provider
- current protocol
- current supplier `product_id`

Product actions:

- choose provider from configured providers
- edit `supplier_product_id`
- optionally test supplier setup for this product

Admin product detail should display:

- `Provider: <provider name or code>`
- `Protocol: <protocol>`
- `Supplier ID: <supplier_product_id>`

## Runtime Flow

When a supplier-backed product is used:

1. Load the product row.
2. Read `supplier_provider` as provider code.
3. Load provider config from `supplier_providers`.
4. Reject if provider does not exist or is inactive.
5. Load protocol defaults for `provider.protocol`.
6. Merge defaults with `overrides_json`.
7. Instantiate the protocol adapter with resolved config.
8. Use the adapter for:
   - product lookup
   - runtime availability
   - purchase pre-check
   - post-payment purchase

This should replace direct branching on `capcut_api` versus `sumistore` in the bot runtime.

## Protocol Adapter Contract

Each supported protocol adapter should expose one internal interface with behavior such as:

- `get_products()`
- `get_balance()`
- `get_product_detail(product_id)` if the protocol supports detail endpoints
- `get_available_units(product_id)`
- `check_purchase_ready(product_id, quantity)`
- `buy_product(product_id, quantity)`
- `extract_delivered_accounts(purchase_response)`

Not every adapter must use the same remote endpoints internally, but they should produce a consistent internal shape for the bot.

## Compatibility Rules

The first implementation should preserve behavior for existing integrations:

- Sumistore products keep their current purchase and balance logic
- Node API products keep their current balance and product-list driven stock logic
- Existing products mapped through legacy values continue working after migration through seeded default providers

Compatibility is more important than a perfect abstraction in the first pass.

## Validation and Error Handling

Admin-side validation:

- provider code must be unique and non-empty
- name must be non-empty
- protocol must be one of the supported adapters
- base URL must be non-empty
- overrides must be valid JSON object
- provider cannot be deleted while referenced by any product

Runtime failures that must produce clear messages:

- provider not found
- provider inactive
- unsupported protocol
- missing or invalid provider config
- supplier product ID missing
- remote product not found
- supplier balance too low
- supplier stock too low
- invalid remote response

Customer-facing failures should stay generic and safe. Admin-facing logs or messages can be more precise.

## Testing Strategy

Tests should cover four layers.

### Migration tests

- creates `supplier_providers`
- seeds compatibility providers correctly
- remaps legacy product provider values
- leaves local products unchanged
- remains idempotent

### Repository and service tests

- create, update, list, disable, and delete providers
- reject invalid provider config
- block deleting a provider that is still used by products
- assign provider to product and persist `supplier_product_id`

### Bot admin tests

- show provider management entry in admin menu
- create provider through admin flow
- edit provider fields through admin flow
- choose provider for a product
- update product supplier ID
- show provider details in product admin screen

### Runtime adapter tests

- product with Sumistore provider uses Sumistore adapter
- product with Node API provider uses Node API adapter
- availability uses the correct provider config
- purchase uses the correct request mapping and account extraction
- inactive or missing provider blocks supplier fulfillment safely

## File Impact

Expected main change areas:

- `migration.py`
  - create and seed provider table
- `repositories.py`
  - provider CRUD and lookup helpers
- `services.py`
  - provider validation and product-provider assignment helpers
- `bot.py`
  - admin provider management flows
  - product supplier config updates
  - runtime provider resolution
- supplier client modules
  - adapt existing clients or add a shared protocol-resolution layer
- tests
  - migration, service, and bot coverage for provider management and runtime routing

## Risks

- admin UX can become too complex if too many provider fields are exposed at once
- over-flexible overrides can make runtime debugging harder
- migration mistakes could break existing supplier-backed products
- masking API keys in admin must not prevent updates or confuse operators

Mitigations:

- keep the first override set intentionally small
- seed compatibility providers for legacy mappings
- keep protocol adapters code-defined and test-driven
- reject invalid configuration before runtime where possible

## Out of Scope for This Change

- arbitrary per-provider custom scripts
- protocol discovery from OpenAPI or remote docs
- provider health dashboards
- bulk reassignment of products across providers beyond basic admin editing


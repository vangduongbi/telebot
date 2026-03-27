# CapCut Supplier Sync Design

**Date:** 2026-03-27

**Status:** Approved in chat, written for file review

## Goal

Import and maintain all supplier products whose names contain `CapCut`, place them under a dedicated category named `Tài khoản CapCut`, and sell them through the existing Telegram bot using the same paid-order supplier fulfillment flow already used for other API-backed products.

## User Requirements

- Create the category `Tài khoản CapCut` automatically if it does not already exist.
- Pull every supplier product whose name contains `CapCut`.
- Keep a separate selling price inside the bot.
- For newly imported CapCut products, initialize the bot selling price to the API price.
- On later syncs, always update the product name from the API.
- If a previously synced CapCut product is no longer returned by the API, hide it automatically.
- Customer stock display must be calculated as:
  - `balance_units = supplier_balance // supplier_price`
  - `available = min(balance_units, supplier_stock)`
- Customer purchase flow should stay automatic:
  - pre-check supplier readiness before payment
  - buy from supplier after payment success
  - cancel and report failure immediately if supplier fulfillment fails

## API Contract

Base URL:

- `http://node12.zampto.net:20291/api`

Authentication:

- Header: `X-API-Key: <key>`

Relevant endpoints:

- `GET /api/products`
  - Returns all products with at least:
    - `id`
    - `name`
    - `price`
    - `stock`
- `GET /api/balance`
  - Returns current wallet balance
- `POST /api/buy`
  - Request body:
    - `product_id`
    - `quantity`
  - Returns delivered accounts inside `order.accounts`

## Recommended Approach

### Option 1: Add a second supplier provider layer

Add provider-aware supplier handling so the existing supplier-backed product flow can support both:

- `sumistore`
- `capcut_api`

This is the recommended approach because it reuses the current fulfillment pattern without hardcoding CapCut as a special one-off path.

### Option 2: Hardcode CapCut sync and purchase logic separately

This is faster in the short term but would duplicate balance checks, purchase logic, and runtime stock calculation. It would make the code harder to maintain.

### Option 3: Import CapCut as normal local-stock products

This would break the requirement for live supplier-backed stock and automatic post-payment purchase, so it is not suitable.

## Data Model Changes

Extend `products` with one new field:

- `supplier_provider` TEXT NULL

Meaning:

- `NULL` for local stock products
- `sumistore` for the current supplier integration
- `capcut_api` for the new CapCut integration

Existing relevant fields continue to apply:

- `fulfillment_mode`
- `supplier_product_id`
- `price`
- `category_id`
- `is_active`

The existing `fulfillment_mode = supplier_api` remains the switch that tells the bot a product is fulfilled externally. `supplier_provider` determines which API client and response mapping to use.

## Category Rules

The sync process owns one category:

- `Tài khoản CapCut`

Rules:

- If it does not exist, create it.
- If it exists but is hidden, reactivate it.
- Every synced CapCut product must be assigned to this category.

## Sync Rules

Admin flow:

- Add a new `/admin` button: `🔄 Sync CapCut`

When pressed:

1. Call `GET /api/products`
2. Filter products whose `name` contains `CapCut`
3. Ensure category `Tài khoản CapCut` exists
4. For each CapCut API product:
   - If a bot product already exists with:
     - `supplier_provider = capcut_api`
     - `supplier_product_id = api_product.id`
     then:
     - update the bot product name from API
     - keep the existing bot selling price
     - ensure `fulfillment_mode = supplier_api`
     - ensure `category_id = Tài khoản CapCut`
     - ensure `is_active = 1`
   - Otherwise create a new bot product:
     - `name = api name`
     - `price = api price`
     - `fulfillment_mode = supplier_api`
     - `supplier_provider = capcut_api`
     - `supplier_product_id = api id`
     - `category_id = Tài khoản CapCut`
     - `is_active = 1`
5. Find existing bot products where:
   - `supplier_provider = capcut_api`
   - but `supplier_product_id` is no longer in the API CapCut result set
   and hide them by setting `is_active = 0`
6. Return a summary to admin:
   - created count
   - updated count
   - hidden count
   - errors if any

## Runtime Stock Display

For CapCut products:

1. Load the live supplier product detail from `/api/products`
2. Read:
   - `price`
   - `stock`
3. Load wallet balance from `/api/balance`
4. Compute:
   - `balance_units = balance // api_price`
   - `available = min(balance_units, api_stock)`

This runtime value is the displayed stock and the pre-check stock source.

If the API fails, returns invalid data, or the price is zero or missing:

- treat the product as temporarily unavailable
- show `available = 0`

## Customer Purchase Flow

CapCut products use the existing supplier purchase lifecycle with provider-specific API calls:

1. Customer selects a CapCut product
2. Bot performs pre-check before creating payment:
   - product exists in supplier list
   - supplier stock is enough
   - supplier balance is enough for requested quantity
3. If pre-check fails:
   - block purchase
   - show temporary unavailability message
4. If pre-check passes:
   - create PayOS order as usual using the bot selling price
5. After payment succeeds:
   - call `POST /api/buy`
   - persist delivered accounts to SQLite order items
   - send the accounts to the customer
6. If supplier buy fails:
   - cancel the pending order
   - notify the customer immediately

## Provider Abstraction

Add a provider-aware supplier layer instead of encoding CapCut logic directly inside bot handlers.

Expected responsibilities:

- fetch balance
- fetch products or product detail
- compute runtime availability
- pre-check purchase readiness
- buy product
- normalize delivered accounts into the existing internal delivery shape

This keeps the current `sumistore` integration intact while allowing `capcut_api` to plug into the same order lifecycle.

## Admin UX

New admin capability:

- `🔄 Sync CapCut`

Recommended admin feedback:

- start message: syncing in progress
- result message example:
  - `Đã tạo: X`
  - `Đã cập nhật: Y`
  - `Đã ẩn: Z`
  - `Lỗi: N`

This button should be safe to run multiple times.

## Error Handling

### Sync errors

- If the API is unreachable:
  - do not modify existing products
  - report the sync failure to admin
- If a single product row is malformed:
  - skip that row
  - include it in the error summary

### Runtime purchase errors

- If supplier pre-check fails:
  - do not create payment
- If supplier buy fails after customer payment:
  - cancel the pending order immediately
  - report failure to customer

## Testing

Required test coverage:

- schema migration adds `supplier_provider`
- service/repository sync logic:
  - create category if missing
  - create new CapCut products
  - update existing product names
  - keep existing selling price on updates
  - hide removed CapCut products
- runtime availability:
  - `available = min(balance // api_price, api_stock)`
  - fallback to zero on API failure
- admin flow:
  - sync button appears in `/admin`
  - sync summary is shown
- purchase flow:
  - CapCut products pre-check supplier balance and stock
  - payment success triggers supplier purchase
  - supplier failure cancels order

## Out of Scope

- Automatic price markup formulas
- Manual CapCut edit dashboard beyond existing product edit screens
- Multi-category placement for CapCut products
- Rich media delivery formatting specific to CapCut

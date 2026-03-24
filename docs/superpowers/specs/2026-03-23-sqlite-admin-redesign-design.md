# SQLite Admin Redesign Design

**Date:** 2026-03-23

**Status:** Approved in chat, written for file review

## Goal

Upgrade the current JSON-based Telegram bot to a SQLite-backed design that supports reliable stock management and order management for an operation handling roughly 20-100 orders per day.

## Current Problems

The bot currently stores products, stock, orders, and PayOS configuration in `data.json`. This creates several operational risks:

- Stock is stored as in-memory lists, so concurrent operations can drift inventory.
- Orders and stock changes are not protected by transactions.
- Admin flows are limited to basic product creation and stock import.
- It is difficult to query orders by customer, status, or payment reference.
- There is no clear state model for inventory reservation, sale, cancellation, or delivery retries.

## Scope

This redesign covers:

- Migration from JSON persistence to SQLite
- Product, stock, order, and payment persistence redesign
- Admin capabilities for stock and order management inside Telegram
- Safer order lifecycle handling around PayOS polling and delivery
- Operational alerts for low stock and failed fulfillment

This redesign does not include:

- A web admin dashboard
- PostgreSQL or other external databases
- Rich media broadcast or CRM features
- A dedicated admin audit log table

## Architecture

The bot should be split into three logical layers:

1. `handlers`
Receive Telegram commands, callbacks, and follow-up messages. Handlers should validate permissions and call services. They should not contain SQL or inventory mutation logic.

2. `services`
Own business rules such as creating orders, reserving stock, confirming payment, delivering accounts, cancelling orders, re-delivering failed orders, and generating admin summaries.

3. `repository` or `db`
Own SQLite access, schema setup, transactions, and query helpers. This layer should expose narrow methods instead of leaking raw SQL through handlers.

This can start inside the existing codebase with a few new files while keeping the current runtime model of one polling bot process.

## SQLite Schema

### `products`

- `id` TEXT PRIMARY KEY
- `name` TEXT NOT NULL
- `price` INTEGER NOT NULL
- `is_active` INTEGER NOT NULL DEFAULT 1
- `created_at` INTEGER NOT NULL
- `updated_at` INTEGER NOT NULL

Notes:

- Store price as integer VND, not formatted strings like `100.000đ`.
- Product IDs may continue using the existing `prod_...` shape for continuity.

### `stock_items`

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `product_id` TEXT NOT NULL
- `content` TEXT NOT NULL
- `status` TEXT NOT NULL
- `batch_id` TEXT
- `reserved_for_order_id` TEXT
- `disabled_reason` TEXT
- `created_at` INTEGER NOT NULL
- `updated_at` INTEGER NOT NULL
- `sold_at` INTEGER

Allowed `status` values:

- `available`
- `reserved`
- `sold`
- `disabled`

Notes:

- Each inventory item is stored as its own row.
- `content` stores the account or credential payload that is currently stored as plain strings in JSON.
- `batch_id` groups imported stock for troubleshooting and reporting.

### `orders`

- `id` TEXT PRIMARY KEY
- `order_code` INTEGER NOT NULL UNIQUE
- `user_id` INTEGER NOT NULL
- `username` TEXT
- `full_name` TEXT
- `product_id` TEXT NOT NULL
- `qty` INTEGER NOT NULL
- `unit_price` INTEGER NOT NULL
- `total_amount` INTEGER NOT NULL
- `status` TEXT NOT NULL
- `payos_ref` TEXT
- `note` TEXT
- `created_at` INTEGER NOT NULL
- `paid_at` INTEGER
- `delivered_at` INTEGER
- `cancelled_at` INTEGER

Allowed `status` values:

- `pending_payment`
- `paid`
- `delivered`
- `paid_delivery_failed`
- `cancelled`
- `failed`

### `order_items`

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `order_id` TEXT NOT NULL
- `stock_item_id` INTEGER NOT NULL
- `delivered_content` TEXT NOT NULL
- `created_at` INTEGER NOT NULL

Notes:

- This preserves the exact delivered payload even if stock rows later change state.

### `payments`

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `order_id` TEXT NOT NULL
- `payos_order_code` TEXT
- `amount` INTEGER NOT NULL
- `status` TEXT NOT NULL
- `raw_reference` TEXT
- `created_at` INTEGER NOT NULL
- `updated_at` INTEGER NOT NULL

Notes:

- `raw_reference` may store the raw PayOS payload or a compact JSON snapshot for troubleshooting.

## Data Migration

The current `data.json` should be treated as a one-time migration source.

Migration rules:

- `products[*].name` -> `products.name`
- `products[*].price` formatted string -> integer `price`
- Each string in `products[*].stock` -> one `stock_items` row with status `available`
- Existing `orders` entries -> `orders` rows
- Existing delivered account values in JSON orders -> `order_items`
- PayOS config can remain file-based for now or move into a separate config store later

Migration should be idempotent or guarded so it cannot duplicate rows if run twice accidentally.

## Admin Features

### 1. Stock Management

Required admin capabilities:

- Create product
- Update product name
- Update product price
- Import stock in bulk
- View stock counts by product
- View stock breakdown by status
- View recent stock rows for a product
- Disable a faulty stock item without deleting it

Best-practice behavior:

- Bulk import should trim empty lines.
- Bulk import should allow batch grouping.
- Price edits should affect only future orders, not past orders.
- Stock should never be physically deleted during normal operation.

### 2. Order Management

Required admin capabilities:

- View recent orders
- Search order by internal order ID
- Search orders by Telegram user ID
- Search orders by username
- Filter orders by status
- Open order detail

Order detail should show:

- Internal order ID
- PayOS order reference
- Customer Telegram identity
- Product
- Quantity
- Amount paid
- Status
- Delivery timestamps
- Delivered items
- Optional note

### 3. Post-Payment Operations

Required admin capabilities:

- Re-deliver an already paid order if Telegram delivery failed
- Cancel an unpaid order and release reserved stock
- Mark or note edge cases that need manual follow-up

Rules:

- Do not manually mark unpaid orders as delivered without an explicit admin-only flow.
- Re-delivery should reuse already linked `order_items` rather than allocate new stock.

### 4. Operational Alerts

Required alerts:

- Low stock per product
- Paid orders that failed delivery
- Orders stuck in `pending_payment` beyond a threshold
- Payment success detected but reserved stock missing or inconsistent

Alerts should go to `ADMIN_IDS`.

## Order Lifecycle

### Customer starts purchase

1. Validate requested quantity against `available` stock.
2. Create an `orders` row with status `pending_payment`.
3. Reserve the required number of `stock_items` rows by switching them from `available` to `reserved`.
4. Save a payment record or initial payment context.
5. Create the PayOS payment link.

These steps must be transaction-safe where inventory is mutated.

### Payment succeeds

1. Re-fetch the order and confirm status is still `pending_payment`.
2. Confirm reserved stock still exists for the order.
3. Change reserved stock items to `sold`.
4. Create `order_items` rows from those stock items.
5. Mark the order as `paid`, then `delivered` after Telegram send succeeds.
6. Persist payment success details.

If Telegram send fails after payment success:

- Keep sold stock linked to the order.
- Move the order into `paid_delivery_failed`.
- Notify admins so they can use a re-delivery command.

### Payment fails or expires

1. Mark the order as `cancelled` or `failed`.
2. Return all reserved stock items to `available`.
3. Persist payment status changes.

## Transaction Rules

The following operations must use SQLite transactions:

- Create order + reserve stock
- Payment success + mark stock sold + create delivered order items
- Cancel order + release reserved stock
- Manual admin stock disabling if it affects active reservations

No handler should directly mutate inventory lists or order state outside service methods.

## Telegram Admin UX

The admin surface should remain Telegram-first.

Recommended additions:

- `/admin_stock`
- `/admin_orders`
- `/order <id>`
- `/orders_user <telegram_id>`
- `/orders_username <username>`
- `/lowstock`

Inline keyboard navigation is acceptable as long as the flows remain short and recoverable.

## Error Handling

The bot should explicitly handle:

- Invalid or missing products
- Quantity requests above available stock
- PayOS API errors when creating payment links
- Polling errors when checking payment status
- Telegram delivery errors when sending purchased accounts
- SQLite locking or transaction failures

Operational principle:

- Prefer recoverable states over silent exceptions.
- Silent `except:` blocks should be removed or narrowed.

## Security and Data Handling

The current repository contains sensitive bot and payment credentials in source-controlled files. This should be corrected during the redesign.

Recommended changes:

- Move Telegram token to environment variables
- Move PayOS credentials to environment variables or a local config file excluded from sharing
- Keep SQLite database file outside casual copy/share paths when possible

Sensitive account payloads are still stored in the database, so system access to the host remains high risk.

## Testing Strategy

Implementation should be test-driven.

Minimum test coverage should include:

- Product creation and price parsing
- Bulk stock import
- Order creation reserves correct stock count
- Payment success marks stock sold and creates `order_items`
- Payment failure releases reserved stock
- Re-delivery flow reuses existing delivered items
- Search and filter queries for admin order lookup

SQLite tests should use isolated temporary databases.

## Rollout Plan

Recommended rollout sequence:

1. Add SQLite schema and repository layer
2. Add one-time migration from `data.json`
3. Move purchase and delivery flow to SQLite
4. Replace stock admin flows with SQLite-backed handlers
5. Replace order admin flows with SQLite-backed handlers
6. Add alerts and delivery recovery commands
7. Remove or deprecate JSON persistence

## Open Decisions Already Resolved

Resolved during design:

- Use SQLite instead of continuing with JSON
- Focus on stock management and order management first
- Exclude a dedicated `admin_logs` table from scope
- Keep admin operations inside Telegram instead of adding a web dashboard

## Success Criteria

This redesign is successful when:

- Inventory is no longer stored as mutable JSON lists
- Orders and stock remain consistent under normal admin and customer flows
- Admin can inspect stock levels and order states from Telegram
- Paid orders can be recovered if delivery to Telegram fails
- Low-stock and operational failure conditions are visible to admins

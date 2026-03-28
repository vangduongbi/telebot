# Category Bulk Product Delete Design

## Goal

Add an admin action that deletes all eligible products inside a category in one step.

The key requirement is safety:
- hard-delete only products that have never had order history or stock history
- skip products that have any historical data tied to them
- report back exactly what was deleted and what was skipped

This gives admins a fast cleanup tool for unused product groups without breaking order integrity or foreign-key constraints.

## Requirements

- Add a new admin action on the category detail screen:
  - `🧹 Xóa toàn bộ sản phẩm`
- The action must operate only on products currently assigned to that category
- A product is eligible for hard deletion only if it has:
  - no rows in `orders`
  - no rows in `stock_items`
  - no rows in `order_items` through stock history
- Products with any order or stock history must not be deleted
- The action must delete eligible products and skip ineligible ones in the same run
- After completion, the bot must show:
  - how many products were deleted
  - which product names were skipped
- The category itself must remain intact
- Existing category delete behavior remains unchanged

## Why Selective Deletion Is Required

The current schema keeps historical relationships between:
- `products`
- `orders`
- `stock_items`
- `order_items`

Hard-deleting a product that already has related history would either fail on foreign-key constraints or damage auditability and customer history.

Because of that, bulk deletion must behave like a safe cleanup operation, not a forced purge.

## Admin UX

### Category Detail Screen

Add a new button to the category detail screen:
- `🧹 Xóa toàn bộ sản phẩm`

This button belongs alongside the existing category management actions and should be clearly separate from:
- delete category
- hide/show category
- rename/edit description

### Confirmation Screen

Tapping the bulk-delete button should open a confirmation screen that clearly states:
- this is a hard delete for products
- only products without order/stock history will be removed
- products with history will be skipped

Suggested wording intent:
- emphasize that this action affects products inside the category
- explain that history-protected products will remain

Buttons:
- `✅ Xóa`
- `❌ Hủy`

### Result Screen

After execution, the bot should show a result summary such as:
- deleted count
- skipped count
- skipped product names

If nothing could be deleted:
- say so explicitly
- still show the skipped products when present

The result screen should include an easy way back to the category detail view.

## Data And Service Design

### Repository Responsibilities

Add repository support for:
- listing all products inside a category for deletion analysis
- checking whether a product has any historical references
- hard-deleting a product row

Recommended helpers:
- `list_products_for_category_management(category_id)`
- `product_has_history(product_id)`
- `delete_product_hard(product_id)`

`product_has_history(product_id)` should return true if any of these exist:
- `orders.product_id = product_id`
- `stock_items.product_id = product_id`

Checking `order_items` directly is not required if `stock_items` exists, because any delivered stock-linked history already implies stock history, but the implementation may still include a direct defensive check if helpful.

### Service Responsibilities

Add a service method such as:
- `delete_category_products(category_id)`

This service should:
1. verify the category exists
2. collect all products in the category
3. split them into:
   - deletable
   - skipped
4. hard-delete only the deletable products
5. return a summary payload

Recommended return shape:
- `deleted_count`
- `deleted_names`
- `skipped_names`

This keeps business rules in the service layer and keeps Telegram handlers simple.

## Bot Handler Changes

Add new category callbacks for:
- opening bulk-delete confirmation
- confirming category product deletion

The category detail handler should expose the new button.

The confirm handler should:
- call the service
- build a readable admin summary
- show a back button to the category

If the category no longer exists:
- reuse the current admin not-found pattern

## Error Handling

- Missing category:
  - show the existing category-not-found admin response
- Empty category:
  - allow the action, but report `0` deleted and no skipped products
- Mixed category contents:
  - delete what is safe
  - skip the rest
  - never fail the whole operation just because one or more products are protected by history
- Repository/service errors:
  - fail safely and keep the category/products unchanged if the transaction cannot complete

## Transaction And Integrity Rules

Hard deletes should happen in a transaction.

Expected behavior:
- if one eligible product delete fails unexpectedly, the deletion transaction should roll back rather than leaving the run half-applied in an unclear state
- products skipped for history are not part of the delete transaction problem space; they should simply remain untouched

This keeps the operation predictable and easier to reason about.

## Testing

Add or update tests for:
- category detail screen shows the new bulk-delete button
- confirmation screen wording and callbacks
- deleting products in a category when all are eligible
- skipping products with order history
- skipping products with stock history
- mixed case deletes eligible products and reports skipped names
- empty category returns a zero-delete summary
- missing category raises or reports the expected admin error path

## Non-Goals

- Force-deleting products with historical records
- Deleting categories as part of this action
- Auto-hiding skipped products
- Bulk deletion across multiple categories at once
- Restoring deleted products

## Recommended Rollout

1. Add repository helpers for history checks and hard delete
2. Add service method for selective bulk deletion
3. Add Telegram admin button and confirmation flow
4. Add summary rendering after execution
5. Add regression tests for safe delete and skip behavior

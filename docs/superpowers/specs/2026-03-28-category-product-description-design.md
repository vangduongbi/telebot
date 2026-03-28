# Category And Product Description Design

## Goal

Add editable descriptions at both the category level and the product level, then show the resolved description to customers at the quantity-selection step.

This should let admins:
- set one shared description for a whole category
- override that shared description for a specific product
- manage both descriptions directly from Telegram admin flows

This should let customers:
- see the correct guidance or policy text right before they choose quantity
- get product-specific wording when it exists
- otherwise fall back to the category description

## Requirements

- Add a `description` field to `categories`
- Add a `description` field to `products`
- Support multi-line freeform text for both
- Support clearing a description by entering `-`
- Show the description during the `buy_<product_id>` quantity-selection screen
- Use this precedence:
  1. `product.description`
  2. `category.description`
  3. nothing
- Keep all current payment, supplier, stock, and category flows working
- Replace the current hardcoded Google AI Pro quantity-step note with the new DB-backed description system

## Data Model

### Categories

Extend `categories` with:
- `description TEXT NOT NULL DEFAULT ''`

### Products

Extend `products` with:
- `description TEXT NOT NULL DEFAULT ''`

### Migration

Database upgrade rules:
- if `categories.description` does not exist, add it with default `''`
- if `products.description` does not exist, add it with default `''`
- existing rows remain valid without manual intervention

This keeps current data intact and makes the new behavior opt-in.

## Admin UX

### Create Category

New flow:
1. Admin taps `➕ Thêm category mới`
2. Bot asks for the category name
3. Bot asks for the category description
4. Admin sends:
   - multi-line description text to save it
   - or `-` to leave it empty
5. Bot creates the category and confirms success

### Edit Category

Category detail screen should expose:
- `✏️ Sửa tên`
- `📝 Sửa mô tả`
- existing toggle/delete actions

`📝 Sửa mô tả` flow:
1. Admin taps `📝 Sửa mô tả`
2. Bot prompts for the new multi-line description
3. Admin sends:
   - text to update the description
   - `-` to clear it
4. Bot confirms the update and returns to the category view or admin menu

### Edit Product

Product detail screen should expose:
- `📝 Sửa mô tả`

`📝 Sửa mô tả` flow:
1. Admin taps `📝 Sửa mô tả`
2. Bot prompts for the new multi-line description
3. Admin sends:
   - text to save an override for this product
   - `-` to clear it
4. Bot confirms the update

This gives product-level overrides without changing category-level text.

## Customer UX

When a customer taps a product and reaches the quantity-selection screen, the bot currently shows:
- product name
- stock line
- quantity buttons

This screen should be updated to show:
- product name
- stock line
- resolved description, if one exists
- the quantity prompt

Resolved description logic:
1. look at `product.description`
2. if empty, look at the product's category and use `category.description`
3. if both are empty, show no description block

The description should preserve line breaks exactly as the admin entered them.

## Google AI Pro Note Migration

The current special-case note for Google AI Pro should be removed from hardcoded bot logic.

Recommended replacement:
- move that note into `product.description` for the Google AI Pro product
- or into the relevant category description if multiple related products should share it

After this feature lands, all future quantity-step notes should be configured from admin instead of added in code.

## Repository And Service Changes

### Repository

Add read/write support for:
- creating categories with descriptions
- updating category descriptions
- creating products with descriptions defaulting to empty
- updating product descriptions

### Service Layer

Add methods for:
- `create_category(name, description="")`
- `update_category_description(category_id, description)`
- `update_product_description(product_id, description)`
- `get_resolved_product_description(product_id)` or equivalent helper logic

Service rules:
- trim outer whitespace on save
- convert `-` to empty string in admin handlers before persistence
- raise if the category or product does not exist

## Bot Handler Changes

### State / Next-step handling

Add next-step flows for:
- category creation description input
- category description edit
- product description edit

### Category detail screen

Show a short summary of whether the category currently has a description:
- either display the text directly if short
- or display a compact indicator such as `Mô tả: Đã thiết lập`

### Product detail screen

Show whether the product has its own description override and keep existing product management actions.

### Quantity selection screen

Build the final text using the resolved description instead of any hardcoded product-specific note.

## Error Handling

- If admin tries to edit a missing category or product, show the existing not-found admin error pattern
- If a description is empty after trimming and not entered as `-`, store it as empty
- If the quantity screen cannot resolve a category, simply fall back to no description
- Do not block purchasing when description resolution fails; fail open to the existing purchase flow

## Testing

Add or update tests for:
- database schema upgrade adds both description columns
- category creation with description
- category description update
- product description update
- clearing description with `-`
- quantity screen uses category description when product description is empty
- quantity screen prefers product description over category description
- quantity screen shows no description when both are empty
- removing the hardcoded Google AI Pro special-case path

## Non-Goals

- Rich-text formatting controls for descriptions
- Media attachments in descriptions
- Multiple description variants by customer segment
- Category descriptions shown in product list or category list screens

## Recommended Rollout

1. Add schema and repository/service support
2. Add admin create/edit flows for category descriptions
3. Add admin product description editing
4. Switch quantity-step rendering to resolved DB descriptions
5. Remove hardcoded Google AI Pro note
6. Seed or manually configure the first real descriptions through admin

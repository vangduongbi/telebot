import time
import uuid

import migration
import repositories


class ShopService:
    def __init__(self, db_path="shop.db"):
        self.repo = repositories.Repository(db_path)

    def _new_order_id(self):
        return "ORD-" + str(uuid.uuid4())[:8].upper()

    def _new_order_code(self):
        return int(str(int(time.time() * 1000))[-9:])

    def _new_product_id(self):
        return "prod_" + str(int(time.time()))

    def _new_category_id(self):
        return "cat_" + str(int(time.time()))

    def _contains_capcut(self, name):
        return "capcut" in str(name or "").casefold()

    def list_active_products(self):
        return self.repo.list_active_products()

    def list_inactive_products(self):
        return self.repo.list_inactive_products()

    def list_products_for_category(self, category_id):
        return self.repo.list_products_by_category(category_id)

    def list_active_categories(self):
        return self.repo.list_active_categories()

    def list_manageable_categories(self):
        return self.repo.list_manageable_categories()

    def create_category(self, name, description=""):
        category_name = str(name or "").strip()
        category_description = str(description or "").strip()
        if not category_name:
            raise ValueError("Category name is required")

        category_id = self._new_category_id()
        while self.repo.get_category(category_id) is not None:
            time.sleep(1)
            category_id = self._new_category_id()
        return self.repo.create_category(category_id, category_name, category_description)

    def ensure_category(self, name):
        category_name = str(name or "").strip()
        if not category_name:
            raise ValueError("Category name is required")
        category = self.repo.get_category_by_name(category_name)
        if category is None:
            return self.create_category(category_name)
        if not category["is_active"]:
            return self.repo.set_category_active(category["id"], True)
        return category

    def assign_product_category(self, product_id, category_id):
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        if category_id is not None and self.repo.get_category(category_id) is None:
            raise ValueError("Category does not exist")
        return self.repo.set_product_category(product_id, category_id)

    def update_category_name(self, category_id, name):
        category_name = str(name or "").strip()
        if not category_name:
            raise ValueError("Category name is required")
        category = self.repo.get_category(category_id)
        if category is None:
            raise ValueError("Category does not exist")
        return self.repo.update_category_name(category_id, category_name)

    def update_category_description(self, category_id, description):
        category = self.repo.get_category(category_id)
        if category is None:
            raise ValueError("Category does not exist")
        return self.repo.update_category_description(category_id, str(description or "").strip())

    def set_category_active(self, category_id, is_active):
        category = self.repo.get_category(category_id)
        if category is None:
            raise ValueError("Category does not exist")
        return self.repo.set_category_active(category_id, is_active)

    def delete_category(self, category_id):
        category = self.repo.get_category(category_id)
        if category is None:
            raise ValueError("Category does not exist")
        self.repo.delete_category(category_id)

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

    def create_product(self, name, price, description=""):
        product_name = str(name or "").strip()
        product_description = str(description or "").strip()
        price_value = migration.parse_price_to_int(price)
        if not product_name:
            raise ValueError("Product name is required")

        product_id = self._new_product_id()
        while self.repo.get_product(product_id) is not None:
            time.sleep(1)
            product_id = self._new_product_id()
        return self.repo.create_product(product_id, product_name, price_value, product_description)

    def update_product_name(self, product_id, name):
        product_name = str(name or "").strip()
        if not product_name:
            raise ValueError("Product name is required")
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        return self.repo.update_product_name(product_id, product_name)

    def update_product_price(self, product_id, price):
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        return self.repo.update_product_price(product_id, migration.parse_price_to_int(price))

    def update_product_description(self, product_id, description):
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        return self.repo.update_product_description(product_id, str(description or "").strip())

    def update_product_fulfillment_mode(self, product_id, fulfillment_mode):
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        if fulfillment_mode not in {"local_stock", "supplier_api"}:
            raise ValueError("Invalid fulfillment mode")
        return self.repo.update_product_fulfillment_mode(product_id, fulfillment_mode)

    def update_product_supplier_product_id(self, product_id, supplier_product_id):
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        supplier_product_id = str(supplier_product_id or "").strip() or None
        return self.repo.update_product_supplier_product_id(product_id, supplier_product_id)

    def update_product_supplier_provider(self, product_id, supplier_provider):
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        if supplier_provider not in {None, "sumistore", "capcut_api"}:
            raise ValueError("Invalid supplier provider")
        return self.repo.update_product_supplier_provider(product_id, supplier_provider)

    def get_resolved_product_description(self, product_id):
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        product_description = str(product["description"] or "")
        if product_description.strip():
            return product_description
        category_id = product["category_id"]
        if not category_id:
            return ""
        category = self.repo.get_category(category_id)
        if category is None:
            return ""
        return str(category["description"] or "")

    def sync_capcut_products(self, api_products):
        category = self.ensure_category("Tài khoản CapCut")
        summary = {"created": 0, "updated": 0, "hidden": 0, "errors": []}
        seen_supplier_ids = set()

        for item in api_products or []:
            if not self._contains_capcut(item.get("name")):
                continue
            try:
                supplier_product_id = str(item["id"]).strip()
                product_name = str(item["name"]).strip()
                product_price = int(item["price"])
                if not supplier_product_id or not product_name or product_price <= 0:
                    raise ValueError("Invalid CapCut product payload")
            except Exception as exc:
                summary["errors"].append(str(exc))
                continue

            seen_supplier_ids.add(supplier_product_id)
            existing = self.repo.get_product_by_supplier_mapping("capcut_api", supplier_product_id)
            if existing is None:
                product = self.create_product(product_name, product_price)
                self.update_product_fulfillment_mode(product["id"], "supplier_api")
                self.update_product_supplier_provider(product["id"], "capcut_api")
                self.update_product_supplier_product_id(product["id"], supplier_product_id)
                self.assign_product_category(product["id"], category["id"])
                summary["created"] += 1
                continue

            self.update_product_name(existing["id"], product_name)
            self.update_product_fulfillment_mode(existing["id"], "supplier_api")
            self.update_product_supplier_provider(existing["id"], "capcut_api")
            self.update_product_supplier_product_id(existing["id"], supplier_product_id)
            self.assign_product_category(existing["id"], category["id"])
            if not existing["is_active"]:
                self.reactivate_product(existing["id"])
            summary["updated"] += 1

        for product in self.repo.list_products_by_supplier_provider("capcut_api"):
            supplier_product_id = product["supplier_product_id"]
            if supplier_product_id and supplier_product_id not in seen_supplier_ids and product["is_active"]:
                self.deactivate_product(product["id"])
                summary["hidden"] += 1

        return summary

    def update_product_sales_mode(self, product_id, sales_mode):
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        if sales_mode not in {"normal", "contact_only"}:
            raise ValueError("Invalid sales mode")
        return self.repo.update_product_sales_mode(product_id, sales_mode)

    def add_product_stock(self, product_id, stock_text):
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        lines = [line.strip() for line in str(stock_text or "").splitlines() if line.strip()]
        if not lines:
            return 0
        batch_id = f"admin:{product_id}:{int(time.time())}"
        self.repo.add_stock_items(product_id, lines, batch_id=batch_id)
        return len(lines)

    def deactivate_product(self, product_id):
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        return self.repo.deactivate_product(product_id)

    def reactivate_product(self, product_id):
        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")
        return self.repo.reactivate_product(product_id)

    def get_payos_config(self):
        rows = self.repo.get_config_values("payos.")
        config = {}
        for row in rows:
            suffix = row["key"].split(".", 1)[1]
            config[suffix] = row["value"]
        return config

    def set_payos_config(self, client_id, api_key, checksum_key):
        self.repo.set_config_value("payos.client_id", str(client_id).strip())
        self.repo.set_config_value("payos.api_key", str(api_key).strip())
        self.repo.set_config_value("payos.checksum_key", str(checksum_key).strip())

    def clear_payos_config(self):
        self.repo.delete_config_prefix("payos.")

    def get_order_details(self, order_id):
        order = self.repo.get_order(str(order_id).strip())
        if order is None:
            return None

        product = self.repo.get_product(order["product_id"])
        items = self.repo.list_order_items(order["id"])
        return {
            "order": order,
            "product": product,
            "accounts": [row["delivered_content"] for row in items],
        }

    def list_orders_for_user(self, user_id):
        result = []
        for order in self.repo.list_orders_for_user(user_id):
            product = self.repo.get_product(order["product_id"])
            result.append(
                {
                    "order": order,
                    "product": product,
                }
            )
        return result

    def get_user_order_details(self, user_id, order_id):
        details = self.get_order_details(order_id)
        if details is None:
            return None
        if details["order"]["user_id"] != user_id:
            return None
        return details

    def create_pending_order(self, user_id, username, full_name, product_id, qty):
        if qty <= 0:
            raise ValueError("Quantity must be greater than zero")

        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")

        if product["fulfillment_mode"] == "supplier_api":
            return self.repo.create_order(
                order_id=self._new_order_id(),
                order_code=self._new_order_code(),
                user_id=user_id,
                username=username,
                full_name=full_name,
                product_id=product_id,
                qty=qty,
                unit_price=product["price"],
                total_amount=product["price"] * qty,
                reserved_stock_item_ids=[],
            )

        available_stock = self.repo.list_available_stock(product_id, qty)
        if len(available_stock) < qty:
            raise ValueError("Not enough stock")

        return self.repo.create_order(
            order_id=self._new_order_id(),
            order_code=self._new_order_code(),
            user_id=user_id,
            username=username,
            full_name=full_name,
            product_id=product_id,
            qty=qty,
            unit_price=product["price"],
            total_amount=product["price"] * qty,
            reserved_stock_item_ids=[row["id"] for row in available_stock],
        )

    def mark_payment_paid(self, order_id, payos_ref, amount_paid):
        order = self.repo.get_order(order_id)
        if order is None:
            raise ValueError("Order does not exist")
        if order["status"] != "pending_payment":
            raise ValueError("Order is not pending payment")

        reserved_items = self.repo.list_reserved_stock_for_order(order_id)
        if len(reserved_items) != order["qty"]:
            raise ValueError("Reserved stock mismatch")

        self.repo.complete_paid_order(order_id, payos_ref, amount_paid, reserved_items)
        return {
            "order_id": order_id,
            "accounts": [row["content"] for row in reserved_items],
        }

    def mark_supplier_payment_paid(self, order_id, payos_ref, amount_paid, delivered_accounts):
        order = self.repo.get_order(order_id)
        if order is None:
            raise ValueError("Order does not exist")
        if order["status"] != "pending_payment":
            raise ValueError("Order is not pending payment")
        if not delivered_accounts:
            raise ValueError("Delivered accounts are required")

        self.repo.complete_supplier_paid_order(
            order_id=order_id,
            payos_ref=payos_ref,
            amount_paid=amount_paid,
            product_id=order["product_id"],
            delivered_accounts=list(delivered_accounts),
        )
        return {
            "order_id": order_id,
            "accounts": list(delivered_accounts),
        }

    def cancel_pending_order(self, order_id, reason):
        order = self.repo.get_order(order_id)
        if order is None:
            raise ValueError("Order does not exist")
        if order["status"] != "pending_payment":
            raise ValueError("Only pending orders can be cancelled")

        self.repo.cancel_order_and_release_stock(order_id, reason)

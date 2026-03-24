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

    def list_active_products(self):
        return self.repo.list_active_products()

    def create_product(self, name, price):
        product_name = str(name or "").strip()
        price_value = migration.parse_price_to_int(price)
        if not product_name:
            raise ValueError("Product name is required")

        product_id = self._new_product_id()
        while self.repo.get_product(product_id) is not None:
            time.sleep(1)
            product_id = self._new_product_id()
        return self.repo.create_product(product_id, product_name, price_value)

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

    def create_pending_order(self, user_id, username, full_name, product_id, qty):
        if qty <= 0:
            raise ValueError("Quantity must be greater than zero")

        product = self.repo.get_product(product_id)
        if product is None:
            raise ValueError("Product does not exist")

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

    def cancel_pending_order(self, order_id, reason):
        order = self.repo.get_order(order_id)
        if order is None:
            raise ValueError("Order does not exist")
        if order["status"] != "pending_payment":
            raise ValueError("Only pending orders can be cancelled")

        self.repo.cancel_order_and_release_stock(order_id, reason)

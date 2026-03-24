import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from payos.types import CreatePaymentLinkRequest

import bot
import database
import repositories
import services


class DummyBot:
    def __init__(self):
        self.messages = []
        self.photos = []
        self.edits = []
        self.next_steps = []
        self.callback_answers = []

    def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id))

    def send_photo(self, chat_id, photo, **kwargs):
        self.photos.append((chat_id, photo, kwargs))

    def edit_message_text(self, text, chat_id, message_id, **kwargs):
        self.edits.append((chat_id, message_id, text, kwargs))

    def register_next_step_handler(self, message, handler, *args):
        self.next_steps.append((message, handler, args))

    def answer_callback_query(self, callback_query_id, text=None, **kwargs):
        self.callback_answers.append((callback_query_id, text, kwargs))


class FakePaymentRequests:
    def __init__(self):
        self.created_request = None

    def create(self, request):
        self.created_request = request
        return SimpleNamespace(
            checkout_url="https://example.test/checkout",
            qr_code=None,
        )


class FakePayOS:
    instances = []

    def __init__(self, client_id, api_key, checksum_key):
        self.client_id = client_id
        self.api_key = api_key
        self.checksum_key = checksum_key
        self.payment_requests = FakePaymentRequests()
        FakePayOS.instances.append(self)


class DummyThread:
    def __init__(self, target=None, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True


class DummyRepository:
    def get_product(self, product_id):
        if product_id != "prod_1":
            return None
        return {"id": "prod_1", "name": "Sample Product", "price": 20000}

    def count_stock_by_status(self, product_id):
        if product_id != "prod_1":
            return {"available": 0, "reserved": 0, "sold": 0, "disabled": 0, "total": 0}
        return {"available": 1, "reserved": 0, "sold": 0, "disabled": 0, "total": 1}

    def get_order(self, order_id):
        return {
            "id": order_id,
            "product_id": "prod_1",
            "qty": 1,
            "payos_ref": "123456789",
            "username": "@tester",
            "full_name": "Test",
            "user_id": 1,
        }


class DummyShopService:
    def __init__(self):
        self.created_orders = []
        self.payos_config = {
            "client_id": "client",
            "api_key": "api",
            "checksum_key": "checksum",
        }

    def create_pending_order(self, **kwargs):
        self.created_orders.append(kwargs)
        return {
            "id": "ORD-1",
            "order_code": 123456789,
            "product_id": kwargs["product_id"],
            "qty": kwargs["qty"],
            "unit_price": 20000,
            "total_amount": 20000,
            "status": "pending_payment",
        }

    def get_payos_config(self):
        return self.payos_config


class ProcessPurchaseTests(unittest.TestCase):
    def setUp(self):
        FakePayOS.instances.clear()
        self.user = SimpleNamespace(id=1, username="tester", first_name="Test", last_name=None)
        self.chat_id = 123
        self.product_id = "prod_1"
        self.original_db = bot.db
        self.original_bot = bot.bot
        self.original_product_repository = bot.product_repository
        self.original_shop_service = bot.shop_service

        bot.db = {"config": {"payos": {"client_id": "client", "api_key": "api", "checksum_key": "checksum"}}}
        bot.bot = DummyBot()
        bot.product_repository = DummyRepository()
        bot.shop_service = DummyShopService()

    def tearDown(self):
        bot.db = self.original_db
        bot.bot = self.original_bot
        bot.product_repository = self.original_product_repository
        bot.shop_service = self.original_shop_service

    def test_process_purchase_creates_payos_request(self):
        with patch.object(bot, "PayOS", FakePayOS), patch.object(bot.threading, "Thread", DummyThread):
            bot.process_purchase(self.user, self.chat_id, self.product_id, 1)

        self.assertEqual(len(FakePayOS.instances), 1)
        created_request = FakePayOS.instances[0].payment_requests.created_request
        self.assertIsInstance(created_request, CreatePaymentLinkRequest)
        self.assertEqual(created_request.amount, 20000)
        self.assertEqual(created_request.cancel_url, "https://t.me")
        self.assertEqual(created_request.return_url, "https://t.me")
        self.assertEqual(len(bot.shop_service.created_orders), 1)
        self.assertEqual(bot.shop_service.created_orders[0]["product_id"], self.product_id)
        self.assertEqual(len(bot.bot.messages), 1)
        self.assertIn("https://example.test/checkout", bot.bot.messages[0][2]["reply_markup"].keyboard[0][0].url)


class SQLiteAdminFlowTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "shop.db")
        database.init_db(self.db_path)
        self.repo = repositories.Repository(self.db_path)
        self.service = services.ShopService(self.db_path)

        self.original_db = bot.db
        self.original_bot = bot.bot
        self.original_product_repository = bot.product_repository
        self.original_shop_service = bot.shop_service

        bot.db = {"products": {}, "orders": {}, "config": {"payos": {}}}
        bot.bot = DummyBot()
        bot.product_repository = self.repo
        bot.shop_service = self.service

    def tearDown(self):
        bot.db = self.original_db
        bot.bot = self.original_bot
        bot.product_repository = self.original_product_repository
        bot.shop_service = self.original_shop_service
        self._tmpdir.cleanup()

    def test_show_admin_menu_reads_products_from_sqlite(self):
        self.service.create_product("SQLite Product", "10.000d")

        bot.show_admin_menu(123)

        self.assertEqual(len(bot.bot.messages), 1)
        reply_markup = bot.bot.messages[0][2]["reply_markup"]
        button_texts = [button.text for row in reply_markup.keyboard for button in row]
        self.assertTrue(any("SQLite Product" in text for text in button_texts))

    def test_show_admin_menu_includes_lookup_order_button(self):
        bot.show_admin_menu(123)

        reply_markup = bot.bot.messages[0][2]["reply_markup"]
        button_texts = [button.text for row in reply_markup.keyboard for button in row]
        self.assertIn("🔎 Tra cuu don", button_texts)

    def test_admin_process_create_prod_writes_product_to_sqlite(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="New Product | 25.000d")

        bot.admin_process_create_prod(message)

        products = list(self.service.list_active_products())
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["name"], "New Product")
        self.assertEqual(products[0]["price"], 25000)

    def test_admin_process_config_payos_writes_to_sqlite(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="client-1 | api-1 | checksum-1")

        bot.admin_process_config_payos(message)

        self.assertEqual(
            self.service.get_payos_config(),
            {
                "client_id": "client-1",
                "api_key": "api-1",
                "checksum_key": "checksum-1",
            },
        )

    def test_admin_lookup_order_callback_prompts_for_order_code(self):
        call = SimpleNamespace(
            data="admin_lookup_order",
            id="cb1",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.next_steps), 1)
        self.assertEqual(bot.bot.next_steps[0][1].__name__, "admin_process_lookup_order")
        self.assertIn("ma don", bot.bot.messages[0][1].lower())

    def test_admin_process_lookup_order_shows_delivered_accounts(self):
        product = self.service.create_product("Lookup Product", "15.000d")
        self.service.add_product_stock(product["id"], "acc-1\nacc-2")
        order = self.service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id=product["id"],
            qty=2,
        )
        self.service.mark_payment_paid(order["id"], "555666", 30000)
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text=order["id"])

        bot.admin_process_lookup_order(message)

        self.assertEqual(len(bot.bot.messages), 1)
        text = bot.bot.messages[0][1]
        self.assertIn(order["id"], text)
        self.assertIn("Lookup Product", text)
        self.assertIn("acc-1", text)
        self.assertIn("acc-2", text)
        self.assertIn("delivered", text.lower())

    def test_admin_process_lookup_order_reports_missing_order(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="ORD-NOT-FOUND")

        bot.admin_process_lookup_order(message)

        self.assertEqual(len(bot.bot.messages), 1)
        self.assertIn("khong tim thay", bot.bot.messages[0][1].lower())
        reply_markup = bot.bot.messages[0][2]["reply_markup"]
        button_texts = [button.text for row in reply_markup.keyboard for button in row]
        self.assertIn("🔙 Quay lai Admin", button_texts)


if __name__ == "__main__":
    unittest.main()

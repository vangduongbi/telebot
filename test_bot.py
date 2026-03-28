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
        self.documents = []
        self.edits = []
        self.next_steps = []
        self.callback_answers = []

    def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id))

    def reply_to(self, message, text, **kwargs):
        chat_id = message.chat.id
        self.messages.append((chat_id, text, kwargs))
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id))

    def send_photo(self, chat_id, photo, **kwargs):
        self.photos.append((chat_id, photo, kwargs))

    def send_document(self, chat_id, document, **kwargs):
        self.documents.append((chat_id, document, kwargs))

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


class FakeSupplierApiClient:
    detail_response = {
        "success": True,
        "product": {
            "id": "SP-GEF55PBV",
            "api_enabled": True,
            "price": 3000,
            "sale_price": 3000,
            "stock": 100,
        },
    }
    balance_response = {"success": True, "balance": 10000}
    buy_response = {
        "success": True,
        "raw_accounts": ["mail@example.com|pass"],
    }
    error = None

    def __init__(self, base_url, api_key, timeout=10):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout

    def get_product_detail(self, product_id):
        if self.error:
            raise self.error
        return self.detail_response

    def get_balance(self):
        if self.error:
            raise self.error
        return self.balance_response

    def buy_product(self, product_id, quantity):
        if self.error:
            raise self.error
        return self.buy_response


class FakeCapcutApiClient:
    products_response = {
        "success": True,
        "products": [
            {"id": "cc_1", "name": "CapCut Pro", "price": 30000, "stock": 10},
        ],
    }
    balance_response = {"success": True, "balance": 100000}
    buy_response = {
        "success": True,
        "order": {"accounts": ["capcut@example.com|pass"]},
    }
    error = None

    def __init__(self, base_url, api_key, timeout=10):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout

    def get_products(self):
        if self.error:
            raise self.error
        return self.products_response

    def get_balance(self):
        if self.error:
            raise self.error
        return self.balance_response

    def buy_product(self, product_id, quantity):
        if self.error:
            raise self.error
        return self.buy_response


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


class SupplierProcessPurchaseTests(unittest.TestCase):
    def setUp(self):
        FakePayOS.instances.clear()
        FakeSupplierApiClient.error = None
        FakeCapcutApiClient.error = None
        FakeSupplierApiClient.detail_response = {
            "success": True,
            "product": {
                "id": "SP-GEF55PBV",
                "api_enabled": True,
                "price": 3000,
                "sale_price": 3000,
                "stock": 100,
            },
        }
        FakeSupplierApiClient.balance_response = {"success": True, "balance": 10000}
        FakeSupplierApiClient.buy_response = {
            "success": True,
            "raw_accounts": ["mail@example.com|pass"],
        }
        FakeCapcutApiClient.products_response = {
            "success": True,
            "products": [
                {"id": "cc_1", "name": "CapCut Pro", "price": 30000, "stock": 10},
            ],
        }
        FakeCapcutApiClient.balance_response = {"success": True, "balance": 100000}
        FakeCapcutApiClient.buy_response = {
            "success": True,
            "order": {"accounts": ["capcut@example.com|pass"]},
        }

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
        self.service.set_payos_config("client", "api", "checksum")

        product = self.service.create_product("ChatGPT Plus cá nhân", "100.000đ")
        self.service.update_product_fulfillment_mode(product["id"], "supplier_api")
        self.service.update_product_supplier_product_id(product["id"], "SP-GEF55PBV")
        self.product_id = product["id"]
        self.capcut_product = self.service.create_product("CapCut Pro 1 thÃ¡ng", "60.000Ä‘")
        self.service.update_product_fulfillment_mode(self.capcut_product["id"], "supplier_api")
        self.service.update_product_supplier_provider(self.capcut_product["id"], "capcut_api")
        self.service.update_product_supplier_product_id(self.capcut_product["id"], "cc_1")
        self.user = SimpleNamespace(id=10, username="buyer", first_name="Buyer", last_name=None)

    def tearDown(self):
        bot.db = self.original_db
        bot.bot = self.original_bot
        bot.product_repository = self.original_product_repository
        bot.shop_service = self.original_shop_service
        self._tmpdir.cleanup()

    def test_process_purchase_supplier_product_checks_balance_and_creates_payment(self):
        with patch.object(bot, "PayOS", FakePayOS), patch.object(bot.threading, "Thread", DummyThread), patch.object(bot, "SupplierApiClient", FakeSupplierApiClient):
            bot.process_purchase(self.user, 123, self.product_id, 1)

        self.assertEqual(len(FakePayOS.instances), 1)
        order_rows = self.repo.list_orders_for_user(10)
        self.assertEqual(len(order_rows), 1)
        self.assertEqual(order_rows[0]["status"], "pending_payment")

    def test_process_purchase_supplier_product_blocks_when_balance_is_low(self):
        FakeSupplierApiClient.balance_response = {"success": True, "balance": 2000}

        with patch.object(bot, "PayOS", FakePayOS), patch.object(bot.threading, "Thread", DummyThread), patch.object(bot, "SupplierApiClient", FakeSupplierApiClient):
            bot.process_purchase(self.user, 123, self.product_id, 1)

        self.assertEqual(len(FakePayOS.instances), 0)
        self.assertIn("tạm thời không khả dụng", bot.bot.messages[0][1].lower())

    def test_complete_paid_order_supplier_product_buys_from_api_and_delivers(self):
        order = self.service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id=self.product_id,
            qty=1,
        )

        with patch.object(bot, "SupplierApiClient", FakeSupplierApiClient):
            bot.complete_paid_order(123, order["id"], "ORDER-1", 100000)

        order_row = self.repo.get_order(order["id"])
        items = self.repo.list_order_items(order["id"])
        self.assertEqual(order_row["status"], "delivered")
        self.assertEqual(items[0]["delivered_content"], "mail@example.com|pass")

    def test_get_runtime_product_uses_supplier_balance_divided_by_supplier_price(self):
        FakeSupplierApiClient.balance_response = {"success": True, "balance": 10000}
        FakeSupplierApiClient.detail_response = {
            "success": True,
            "product": {
                "id": "SP-GEF55PBV",
                "api_enabled": True,
                "price": 3000,
                "sale_price": 2500,
                "stock": 999,
            },
        }

        with patch.object(bot, "SupplierApiClient", FakeSupplierApiClient):
            runtime_product = bot.get_runtime_product(self.product_id)

        self.assertEqual(runtime_product["available"], 4)

    def test_get_runtime_product_returns_zero_when_supplier_unavailable(self):
        FakeSupplierApiClient.error = Exception("timeout")

        with patch.object(bot, "SupplierApiClient", FakeSupplierApiClient):
            runtime_product = bot.get_runtime_product(self.product_id)

        self.assertEqual(runtime_product["available"], 0)

    def test_get_runtime_product_uses_min_of_balance_units_and_api_stock_for_capcut(self):
        FakeCapcutApiClient.products_response = {
            "success": True,
            "products": [
                {"id": "cc_1", "name": "CapCut Pro", "price": 30000, "stock": 10},
            ],
        }
        FakeCapcutApiClient.balance_response = {"success": True, "balance": 70000}

        with patch.object(bot, "CapcutApiClient", FakeCapcutApiClient):
            runtime_product = bot.get_runtime_product(self.capcut_product["id"])

        self.assertEqual(runtime_product["available"], 2)

    def test_get_runtime_product_caps_by_api_stock_for_capcut(self):
        FakeCapcutApiClient.products_response = {
            "success": True,
            "products": [
                {"id": "cc_1", "name": "CapCut Pro", "price": 30000, "stock": 3},
            ],
        }
        FakeCapcutApiClient.balance_response = {"success": True, "balance": 300000}

        with patch.object(bot, "CapcutApiClient", FakeCapcutApiClient):
            runtime_product = bot.get_runtime_product(self.capcut_product["id"])

        self.assertEqual(runtime_product["available"], 3)

    def test_process_purchase_capcut_blocks_when_api_stock_below_qty(self):
        FakeCapcutApiClient.products_response = {
            "success": True,
            "products": [
                {"id": "cc_1", "name": "CapCut Pro", "price": 30000, "stock": 1},
            ],
        }
        FakeCapcutApiClient.balance_response = {"success": True, "balance": 300000}

        with patch.object(bot, "PayOS", FakePayOS), patch.object(bot.threading, "Thread", DummyThread), patch.object(bot, "CapcutApiClient", FakeCapcutApiClient):
            bot.process_purchase(self.user, 123, self.capcut_product["id"], 2)

        self.assertEqual(len(FakePayOS.instances), 0)
        self.assertIn("tạm thời không khả dụng", bot.bot.messages[0][1].lower())

    def test_complete_paid_order_capcut_buys_from_api_and_delivers(self):
        order = self.service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id=self.capcut_product["id"],
            qty=1,
        )

        with patch.object(bot, "CapcutApiClient", FakeCapcutApiClient):
            bot.complete_paid_order(123, order["id"], "ORDER-CC", 60000)

        order_row = self.repo.get_order(order["id"])
        items = self.repo.list_order_items(order["id"])
        self.assertEqual(order_row["status"], "delivered")
        self.assertEqual(items[0]["delivered_content"], "capcut@example.com|pass")


class ProductListEmojiTests(unittest.TestCase):
    def test_choose_product_emoji_by_name(self):
        self.assertEqual(bot.choose_product_emoji("ChatGPT Plus"), "🧠")
        self.assertEqual(bot.choose_product_emoji("Google Pro Pixel"), "🚀")
        self.assertEqual(bot.choose_product_emoji("Mail cố BH 1 tuần"), "📧")
        self.assertEqual(bot.choose_product_emoji("Admin GPT business"), "💼")
        self.assertEqual(bot.choose_product_emoji("Sản phẩm khác"), "🛍️")

    def test_format_customer_product_label_uses_matching_emoji(self):
        label = bot.format_customer_product_label(
            {
                "name": "ChatGPT Plus",
                "price_text": "100.000đ",
                "available": 5,
            }
        )

        self.assertTrue(label.startswith("🧠 "))
        self.assertIn("Còn: 5", label)


    def test_format_customer_product_label_shows_supplier_available_hint(self):
        label = bot.format_customer_product_label(
            {
                "name": "ChatGPT Plus cá nhân",
                "price_text": "100.000đ",
                "available": 2,
                "fulfillment_mode": "supplier_api",
            }
        )

        self.assertIn("Còn: 2", label)


    def test_format_customer_product_label_shows_contact_for_contact_only(self):
        label = bot.format_customer_product_label(
            {
                "name": "NÃ¢ng má»›i/gia háº¡n GPT",
                "price_text": "100.000Ä‘",
                "available": 99,
                "sales_mode": "contact_only",
            }
        )

        self.assertIn("Liên hệ", label)
        self.assertNotIn("CÃ²n:", label)


class ChatGptDeliveryFormatTests(unittest.TestCase):
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

    def test_send_delivered_order_messages_for_chatgpt_sends_txt_and_quick_copy_only(self):
        product = self.service.create_product("ChatGPT Plus cá nhân 1 tháng", "100.000Ä‘")
        account_1 = (
            "santiagoiansmith1710@hotmail.com|santiago@627553|refresh-token-1|"
            "9e5f94bc-e8a4-4e73-b8be-63364c29d753|FCREJH6VNAR3HODFLWRIPCRER3GM47OI|"
            "hanzoleged1102@@|23/03/2026 11:18:13"
        )
        account_2 = (
            "saphucthuyphuc7893@hotmail.com|sa@694823|refresh-token-2|"
            "9e5f94bc-e8a4-4e73-b8be-63364c29d753|NJ5K5RFKFT7ON4IVNACEUNI4JEBTXYAN|"
            "hanzoleged1102@@|23/03/2026 11:24:26"
        )
        self.service.add_product_stock(product["id"], f"{account_1}\n{account_2}")
        order = self.service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id=product["id"],
            qty=2,
        )
        self.service.mark_payment_paid(order["id"], "111", 200000)

        bot.send_delivered_order_messages(123, order["id"], [account_1, account_2])

        self.assertEqual(len(bot.bot.documents), 1)
        self.assertEqual(len(bot.bot.messages), 1)
        document = bot.bot.documents[0][1]
        txt_content = document.getvalue().decode("utf-8")
        self.assertIn("Email|Password mail|Refresh Token|Client ID|2FA|PASS GPT|Ngày Giờ", txt_content)
        self.assertIn(account_1, txt_content)
        self.assertIn(account_2, txt_content)

        quick_copy = bot.bot.messages[0][1]
        self.assertIn("COPY NHANH", quick_copy)
        self.assertIn("Email | PASS GPT | 2FA | Password mail", quick_copy)
        self.assertIn(
            "santiagoiansmith1710@hotmail.com | hanzoleged1102@@ | FCREJH6VNAR3HODFLWRIPCRER3GM47OI | santiago@627553",
            quick_copy,
        )
        self.assertNotIn("THANH TOÃN THÃ€NH CÃ”NG", quick_copy)


class UserHomeFlowTests(unittest.TestCase):
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

    def test_send_welcome_shows_main_menu_buttons(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123))

        bot.send_welcome(message)

        self.assertEqual(len(bot.bot.messages), 1)
        reply_markup = bot.bot.messages[0][2]["reply_markup"]
        buttons = [button for row in reply_markup.keyboard for button in row]
        labels = [button.text for button in buttons]
        self.assertIn("🛍️ Danh sách sản phẩm", labels)
        self.assertIn("🧾 Lịch sử mua hàng", labels)
        support_button = next(button for button in buttons if button.text == "💬 Liên hệ hỗ trợ")
        self.assertEqual(support_button.url, "https://t.me/libi94")

    def test_order_history_lists_only_current_user_orders(self):
        product = self.service.create_product("History Product", "20.000đ")
        self.service.add_product_stock(product["id"], "acc-1\nacc-2\nacc-3")
        own_order = self.service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id=product["id"],
            qty=1,
        )
        self.service.mark_payment_paid(own_order["id"], "111", 20000)
        other_order = self.service.create_pending_order(
            user_id=20,
            username="@other",
            full_name="Other",
            product_id=product["id"],
            qty=1,
        )
        self.service.mark_payment_paid(other_order["id"], "222", 20000)
        call = SimpleNamespace(
            data="show_order_history",
            id="history1",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=10),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        reply_markup = bot.bot.edits[0][3]["reply_markup"]
        labels = [button.text for row in reply_markup.keyboard for button in row]
        self.assertTrue(any(own_order["id"] in label for label in labels))
        self.assertFalse(any(other_order["id"] in label for label in labels))

    def test_order_history_detail_shows_accounts_for_delivered_order(self):
        product = self.service.create_product("History Product", "20.000đ")
        self.service.add_product_stock(product["id"], "acc-1\nacc-2")
        order = self.service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id=product["id"],
            qty=2,
        )
        self.service.mark_payment_paid(order["id"], "111", 40000)
        call = SimpleNamespace(
            data=f"order_detail_{order['id']}",
            id="detail1",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=10),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        text = bot.bot.edits[0][2]
        self.assertIn(order["id"], text)
        self.assertIn("History Product", text)
        self.assertIn("acc-1", text)
        self.assertIn("acc-2", text)

    def test_order_history_empty_state(self):
        call = SimpleNamespace(
            data="show_order_history",
            id="history2",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=999),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        self.assertIn("chưa có đơn hàng", bot.bot.edits[0][2].lower())


    def test_show_products_uses_support_url_for_contact_only_product(self):
        product = self.service.create_product("NÃ¢ng má»›i/gia háº¡n GPT", "100.000Ä‘")
        self.service.update_product_sales_mode(product["id"], "contact_only")
        call = SimpleNamespace(
            data="show_all_products",
            id="products1",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=10),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        markup = bot.bot.edits[0][3]["reply_markup"]
        product_button = next(
            button
            for row in markup.keyboard
            for button in row
            if button.text.endswith("Liên hệ")
        )
        self.assertEqual(product_button.url, "https://t.me/libi94")
        self.assertIsNone(product_button.callback_data)
 
    def test_quantity_screen_uses_category_description_when_product_description_is_empty(self):
        category = self.service.create_category("Google AI", "Shared category note")
        product = self.service.create_product("Google AI Pro 1 năm", "50.000đ")
        self.service.assign_product_category(product["id"], category["id"])
        self.service.add_product_stock(product["id"], "mail@example.com|pass|2fa")
        call = SimpleNamespace(
            data=f"buy_{product['id']}",
            id="products-desc-1",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=10),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        text = bot.bot.edits[0][2]
        self.assertIn("Shared category note", text)

    def test_quantity_screen_prefers_product_description_over_category_description(self):
        category = self.service.create_category("Google AI", "Shared category note")
        product = self.service.create_product("Google AI Pro 1 năm", "50.000đ")
        self.service.assign_product_category(product["id"], category["id"])
        self.service.update_product_description(product["id"], "Product-specific note")
        self.service.add_product_stock(product["id"], "mail@example.com|pass|2fa")
        call = SimpleNamespace(
            data=f"buy_{product['id']}",
            id="products-desc-2",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=10),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        text = bot.bot.edits[0][2]
        self.assertIn("Product-specific note", text)
        self.assertNotIn("Shared category note", text)

    def test_quantity_screen_omits_description_when_both_are_empty(self):
        product = self.service.create_product("Google AI Pro 1 năm", "50.000đ")
        self.service.add_product_stock(product["id"], "mail@example.com|pass|2fa")
        call = SimpleNamespace(
            data=f"buy_{product['id']}",
            id="products-desc-3",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=10),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        text = bot.bot.edits[0][2]
        self.assertNotIn("Shared category note", text)
        self.assertNotIn("Product-specific note", text)


class CategoryBotFlowTests(unittest.TestCase):
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

    def test_show_products_opens_category_menu_with_all_products_button(self):
        category = self.service.create_category("Tài khoản ChatGPT")
        product = self.service.create_product("ChatGPT Plus", "100.000đ")
        self.service.assign_product_category(product["id"], category["id"])
        call = SimpleNamespace(
            data="show_products",
            id="cat1",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=10),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        markup = bot.bot.edits[0][3]["reply_markup"]
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertIn("🗂️ Tất cả sản phẩm", labels)
        self.assertIn("📂 Tài khoản ChatGPT", labels)

    def test_show_category_displays_only_products_in_that_category(self):
        first_category = self.service.create_category("Tài khoản ChatGPT")
        second_category = self.service.create_category("Google AI")
        first_product = self.service.create_product("ChatGPT Plus", "100.000đ")
        second_product = self.service.create_product("Google Pro", "50.000đ")
        self.service.assign_product_category(first_product["id"], first_category["id"])
        self.service.assign_product_category(second_product["id"], second_category["id"])
        call = SimpleNamespace(
            data=f"show_category_{first_category['id']}",
            id="cat2",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=10),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        markup = bot.bot.edits[0][3]["reply_markup"]
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertTrue(any("ChatGPT Plus" in label for label in labels))
        self.assertFalse(any("Google Pro" in label for label in labels))

    def test_admin_process_create_category_writes_to_sqlite(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="Tài khoản ChatGPT")

        bot.admin_process_create_category(message)

        categories = bot.shop_service.list_active_categories()
        self.assertTrue(any(row["name"] == "Tài khoản ChatGPT" for row in categories))

    def test_admin_process_create_category_description_writes_to_sqlite(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="Shared category note")

        bot.admin_process_create_category_description(message, "TÃ i khoáº£n ChatGPT")

        categories = bot.shop_service.list_active_categories()
        self.assertTrue(
            any(
                row["name"] == "TÃ i khoáº£n ChatGPT"
                and row["description"] == "Shared category note"
                for row in categories
            )
        )

    def test_admin_process_create_category_description_dash_clears_description(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="-")

        bot.admin_process_create_category_description(message, "TÃ i khoáº£n ChatGPT")

        categories = bot.shop_service.list_active_categories()
        self.assertTrue(
            any(
                row["name"] == "TÃ i khoáº£n ChatGPT"
                and row["description"] == ""
                for row in categories
            )
        )

    def test_admin_assign_category_updates_product(self):
        category = self.service.create_category("Tài khoản ChatGPT")
        product = self.service.create_product("ChatGPT Plus", "100.000đ")
        call = SimpleNamespace(
            data=f"admin_setcategory_{product['id']}_{category['id']}",
            id="cat3",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(call)

        products = self.service.list_products_for_category(category["id"])
        self.assertTrue(any(row["id"] == product["id"] for row in products))


    def test_admin_category_detail_lists_products_and_add_button(self):
        category = self.service.create_category("ChatGPT")
        product = self.service.create_product("ChatGPT Plus", "100.000d")
        self.service.assign_product_category(product["id"], category["id"])
        call = SimpleNamespace(
            data=f"admin_category_{category['id']}",
            id="cat4",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        text = bot.bot.edits[0][2]
        self.assertIn("ChatGPT", text)
        self.assertIn("ChatGPT Plus", text)
        markup = bot.bot.edits[0][3]["reply_markup"]
        buttons = [button for row in markup.keyboard for button in row]
        self.assertTrue(any(button.text == "➕ Thêm sản phẩm vào category" for button in buttons))
        self.assertTrue(any(button.callback_data == f"admin_addproduct_category|{category['id']}" for button in buttons))
        self.assertTrue(any(button.callback_data == f"admin_deletecategoryproducts_{category['id']}" for button in buttons))
        self.assertTrue(any(button.text == "✏️ Sửa tên" for button in buttons))
        self.assertTrue(any(button.text == "🙈 Ẩn category" for button in buttons))
        self.assertTrue(any(button.text == "🗑️ Xóa category" for button in buttons))

    def test_show_bulk_delete_confirmation(self):
        category = self.service.create_category("ChatGPT")
        call = SimpleNamespace(
            data=f"admin_deletecategoryproducts_{category['id']}",
            id="cat-bulk-1",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        text = bot.bot.edits[0][2]
        self.assertIn("xóa cứng", text.lower())
        markup = bot.bot.edits[0][3]["reply_markup"]
        buttons = [button for row in markup.keyboard for button in row]
        self.assertTrue(
            any(button.callback_data == f"admin_confirmdeletecategoryproducts_{category['id']}" for button in buttons)
        )

    def test_confirm_bulk_delete_shows_summary_with_skipped_names(self):
        category = self.service.create_category("ChatGPT")
        clean = self.service.create_product("Clean Product", "100.000d")
        protected = self.service.create_product("Protected Product", "200.000d")
        self.service.assign_product_category(clean["id"], category["id"])
        self.service.assign_product_category(protected["id"], category["id"])
        self.repo.add_stock_items(protected["id"], ["email|pass"], "batch-1")
        call = SimpleNamespace(
            data=f"admin_confirmdeletecategoryproducts_{category['id']}",
            id="cat-bulk-2",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        text = bot.bot.edits[0][2]
        self.assertIn("Đã xóa: 1", text)
        self.assertIn("Bỏ qua: 1", text)
        self.assertIn("Protected Product", text)
        self.assertIsNone(self.repo.get_product(clean["id"]))
        self.assertIsNotNone(self.repo.get_product(protected["id"]))

    def test_admin_add_product_to_category_from_category_screen(self):
        category = self.service.create_category("ChatGPT")
        product = self.service.create_product("ChatGPT Pro", "120.000d")

        pick_list_call = SimpleNamespace(
            data=f"admin_addproduct_category|{category['id']}",
            id="cat5",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(pick_list_call)

        self.assertEqual(len(bot.bot.edits), 1)
        markup = bot.bot.edits[0][3]["reply_markup"]
        buttons = [button for row in markup.keyboard for button in row]
        self.assertTrue(any(button.text == "ChatGPT Pro" for button in buttons))
        self.assertTrue(
            any(
                button.callback_data == f"admin_pickcategoryproduct|{category['id']}|{product['id']}"
                for button in buttons
            )
        )

        assign_call = SimpleNamespace(
            data=f"admin_pickcategoryproduct|{category['id']}|{product['id']}",
            id="cat6",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(assign_call)

        products = self.service.list_products_for_category(category["id"])
        self.assertTrue(any(row["id"] == product["id"] for row in products))


    def test_admin_process_edit_category_updates_name(self):
        category = self.service.create_category("Old Category")
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="New Category")

        bot.admin_process_edit_category(message, category["id"])

        updated = self.service.list_manageable_categories()
        self.assertTrue(any(row["id"] == category["id"] and row["name"] == "New Category" for row in updated))

    def test_admin_toggle_category_hides_it_from_customer_list(self):
        category = self.service.create_category("Hidden Soon")
        hide_call = SimpleNamespace(
            data=f"admin_togglecategory_{category['id']}",
            id="cat7",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(hide_call)
        bot.bot.edits.clear()

        customer_call = SimpleNamespace(
            data="show_products",
            id="cat8",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=10),
        )

        bot.callback_query(customer_call)

        markup = bot.bot.edits[0][3]["reply_markup"]
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertFalse(any("Hidden Soon" in label for label in labels))

    def test_admin_delete_category_clears_product_assignment(self):
        category = self.service.create_category("Delete Me")
        product = self.service.create_product("GPT Plus", "100.000d")
        self.service.assign_product_category(product["id"], category["id"])

        confirm_call = SimpleNamespace(
            data=f"admin_confirmdeletecategory_{category['id']}",
            id="cat9",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(confirm_call)

        stored = self.repo.get_product(product["id"])
        self.assertIsNone(stored["category_id"])
        self.assertFalse(any(row["id"] == category["id"] for row in self.service.list_manageable_categories()))


    def test_admin_process_create_category_writes_to_sqlite(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="TÃ i khoáº£n ChatGPT")

        bot.admin_process_create_category(message)

        self.assertEqual(len(bot.bot.next_steps), 1)
        self.assertEqual(bot.bot.next_steps[0][1].__name__, "admin_process_create_category_description")

    def test_admin_category_detail_shows_description_button(self):
        category = self.service.create_category("ChatGPT")
        call = SimpleNamespace(
            data=f"admin_category_{category['id']}",
            id="cat-desc-1",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(call)

        markup = bot.bot.edits[0][3]["reply_markup"]
        buttons = [button for row in markup.keyboard for button in row]
        self.assertTrue(any(button.callback_data == f"admin_editcategorydesc_{category['id']}" for button in buttons))

    def test_admin_process_create_category_description_writes_to_sqlite(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="Shared category note")

        bot.admin_process_create_category_description(message, "TÃ i khoáº£n ChatGPT")

        categories = bot.shop_service.list_active_categories()
        self.assertTrue(
            any(
                row["name"] == "TÃ i khoáº£n ChatGPT" and row["description"] == "Shared category note"
                for row in categories
            )
        )

    def test_admin_process_create_category_description_dash_clears_description(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="-")

        bot.admin_process_create_category_description(message, "TÃ i khoáº£n ChatGPT")

        categories = bot.shop_service.list_active_categories()
        self.assertTrue(
            any(
                row["name"] == "TÃ i khoáº£n ChatGPT" and row["description"] == ""
                for row in categories
            )
        )

    def test_admin_process_edit_category_description_updates_description(self):
        category = self.service.create_category("Old Category")
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="Updated description")

        bot.admin_process_edit_category_description(message, category["id"])

        updated = self.service.list_manageable_categories()
        self.assertTrue(
            any(row["id"] == category["id"] and row["description"] == "Updated description" for row in updated)
        )

    def test_admin_process_edit_category_description_dash_clears_description(self):
        category = self.service.create_category("Old Category", "Has description")
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="-")

        bot.admin_process_edit_category_description(message, category["id"])

        updated = self.service.list_manageable_categories()
        self.assertTrue(any(row["id"] == category["id"] and row["description"] == "" for row in updated))


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

    def test_show_admin_menu_uses_stock_breakdown_with_available_primary(self):
        product = self.service.create_product("Stock Product", "10.000d")
        self.service.add_product_stock(product["id"], "acc-1\nacc-2")
        order = self.service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id=product["id"],
            qty=1,
        )
        self.service.mark_payment_paid(order["id"], "123456", 10000)

        bot.show_admin_menu(123)

        reply_markup = bot.bot.messages[0][2]["reply_markup"]
        button_texts = [button.text for row in reply_markup.keyboard for button in row]
        stock_button = next(text for text in button_texts if "Stock Product" in text)
        self.assertIn("Còn: 1", stock_button)
        self.assertIn("Đã giữ: 0", stock_button)
        self.assertIn("Đã bán: 1", stock_button)

    def test_show_admin_menu_includes_lookup_order_button(self):
        bot.show_admin_menu(123)

        reply_markup = bot.bot.messages[0][2]["reply_markup"]
        button_texts = [button.text for row in reply_markup.keyboard for button in row]
        self.assertIn("🔎 Tra cứu đơn", button_texts)

    def test_show_admin_menu_includes_sync_capcut_button(self):
        bot.show_admin_menu(123)

        reply_markup = bot.bot.messages[0][2]["reply_markup"]
        button_texts = [button.text for row in reply_markup.keyboard for button in row]
        self.assertIn("🔄 Sync CapCut", button_texts)

    def test_show_admin_menu_lists_hidden_products_with_restore_button(self):
        product = self.service.create_product("Hidden Product", "10.000d")
        self.service.deactivate_product(product["id"])

        bot.show_admin_menu(123)

        reply_markup = bot.bot.messages[0][2]["reply_markup"]
        rows = reply_markup.keyboard
        flat_texts = [button.text for row in rows for button in row]
        self.assertTrue(any("Hidden Product" in text for text in flat_texts))
        self.assertIn("👁 Hiện lại", flat_texts)

    def test_admin_restore_product_reactivates_hidden_product(self):
        product = self.service.create_product("Restore Me", "10.000d")
        self.service.deactivate_product(product["id"])
        call = SimpleNamespace(
            data=f"admin_restoreprod_{product['id']}",
            id="restore1",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(call)

        products = list(self.service.list_active_products())
        self.assertTrue(any(row["id"] == product["id"] for row in products))

    def test_admin_update_sales_mode_to_contact_only(self):
        product = self.service.create_product("Contact Product", "30.000d")
        call = SimpleNamespace(
            data=f"admin_setsalesmode|{product['id']}|contact_only",
            id="sales1",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(call)

        stored = self.repo.get_product(product["id"])
        self.assertEqual(stored["sales_mode"], "contact_only")

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
        self.assertIn("mã đơn", bot.bot.messages[0][1].lower())

    def test_admin_product_detail_shows_stock_breakdown(self):
        product = self.service.create_product("Detail Product", "10.000d")
        self.service.add_product_stock(product["id"], "acc-1\nacc-2")
        order = self.service.create_pending_order(
            user_id=10,
            username="@buyer",
            full_name="Buyer",
            product_id=product["id"],
            qty=1,
        )
        self.service.mark_payment_paid(order["id"], "123456", 10000)
        call = SimpleNamespace(
            data=f"admin_prod_{product['id']}",
            id="cb2",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(call)

        self.assertEqual(len(bot.bot.edits), 1)
        text = bot.bot.edits[0][2]
        self.assertIn("Còn: 1", text)
        self.assertIn("Đã giữ: 0", text)
        self.assertIn("Đã bán: 1", text)

    def test_admin_product_detail_shows_description_status_and_button(self):
        product = self.service.create_product("Detail Product", "10.000d")
        call = SimpleNamespace(
            data=f"admin_prod_{product['id']}",
            id="cb2desc",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        bot.callback_query(call)

        text = bot.bot.edits[0][2]
        markup = bot.bot.edits[0][3]["reply_markup"]
        buttons = [button for row in markup.keyboard for button in row]
        self.assertIn("Mô tả riêng", text)
        self.assertTrue(any(button.callback_data == f"admin_editdesc_{product['id']}" for button in buttons))

    def test_admin_process_edit_product_description_updates_sqlite(self):
        product = self.service.create_product("Detail Product", "10.000d")
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="Product note")

        bot.admin_process_edit_product_description(message, product["id"])

        stored = self.repo.get_product(product["id"])
        self.assertEqual(stored["description"], "Product note")

    def test_admin_process_edit_product_description_dash_clears_description(self):
        product = self.service.create_product("Detail Product", "10.000d")
        self.service.update_product_description(product["id"], "Product note")
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="-")

        bot.admin_process_edit_product_description(message, product["id"])

        stored = self.repo.get_product(product["id"])
        self.assertEqual(stored["description"], "")

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
        self.assertIn("delivered", text)

    def test_admin_process_lookup_order_reports_missing_order(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123), text="ORD-NOT-FOUND")

        bot.admin_process_lookup_order(message)

        self.assertEqual(len(bot.bot.messages), 1)
        self.assertIn("không tìm thấy", bot.bot.messages[0][1].lower())
        reply_markup = bot.bot.messages[0][2]["reply_markup"]
        button_texts = [button.text for row in reply_markup.keyboard for button in row]
        self.assertIn("🔙 Quay lại Admin", button_texts)


    def test_admin_sync_capcut_creates_category_and_reports_summary(self):
        FakeCapcutApiClient.products_response = {
            "success": True,
            "products": [
                {"id": "cc_1", "name": "CapCut Pro 1 thÃ¡ng", "price": 30000, "stock": 10},
                {"id": "cc_2", "name": "CapCut Pro 1 nÄƒm", "price": 120000, "stock": 5},
            ],
        }
        call = SimpleNamespace(
            data="admin_sync_capcut",
            id="sync1",
            message=SimpleNamespace(chat=SimpleNamespace(id=123), message_id=1),
            from_user=SimpleNamespace(id=1993247449),
        )

        with patch.object(bot, "CapcutApiClient", FakeCapcutApiClient):
            bot.callback_query(call)

        categories = self.service.list_active_categories()
        category = next(row for row in categories if row["name"] == "Tài khoản CapCut")
        products = self.service.list_products_for_category(category["id"])
        self.assertEqual(len(products), 2)
        self.assertEqual(len(bot.bot.messages), 1)
        self.assertIn("CapCut", bot.bot.messages[0][1])
        self.assertIn("Đã tạo: 2", bot.bot.messages[0][1])


if __name__ == "__main__":
    unittest.main()

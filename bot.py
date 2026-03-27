import io
import json
import os
import threading
import time

import qrcode
import telebot
from payos import PayOS
from payos.types import CreatePaymentLinkRequest
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

import migration
import repositories
import services
from supplier_api import SupplierApiClient, SupplierApiError


API_TOKEN = "8306268191:AAFKK33VzWyAOXe1Zg38Dk8LJ5eGAuTcVs0"
ADMIN_IDS = [1993247449]

DATA_FILE = "data.json"
DB_PATH = "shop.db"
SUPPLIER_BASE_URL = "https://sumistore.me/api"
SUPPLIER_API_KEY = "TAPI-XD2CGJRB398MTAFBDYHO"

bot = telebot.TeleBot(API_TOKEN)


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception:
                data = {}
        if "products" not in data:
            new_data = {"products": {}, "orders": {}, "config": {"payos": {}}}
            for key, value in data.items():
                if isinstance(value, list):
                    if key == "gpt":
                        new_data["products"][key] = {
                            "name": "Tài khoản GPT Plus 1 tháng",
                            "price": "100.000đ",
                            "stock": value,
                        }
                    elif key == "google":
                        new_data["products"][key] = {
                            "name": "Tài khoản Google Pro 1 năm (Pixel)",
                            "price": "200.000đ",
                            "stock": value,
                        }
                    else:
                        new_data["products"][key] = {
                            "name": f"Product {key}",
                            "price": "0đ",
                            "stock": value,
                        }
            return new_data
        if "orders" not in data:
            data["orders"] = {}
        if "config" not in data:
            data["config"] = {"payos": {}}
        return data
    return {"products": {}, "orders": {}, "config": {"payos": {}}}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


db = load_data()
migration.migrate_json_to_sqlite(db, DB_PATH)
product_repository = repositories.Repository(DB_PATH)
shop_service = services.ShopService(DB_PATH)


def normalize_text_key(text):
    return "".join(ch for ch in str(text or "").casefold() if ch.isalnum())


def bootstrap_default_supplier_mappings():
    for product in shop_service.list_active_products():
        if product["fulfillment_mode"] == "supplier_api" and product["supplier_product_id"]:
            continue
        if normalize_text_key(product["name"]) == normalize_text_key("ChatGPT Plus cá nhân"):
            shop_service.update_product_fulfillment_mode(product["id"], "supplier_api")
            shop_service.update_product_supplier_product_id(product["id"], "SP-GEF55PBV")


bootstrap_default_supplier_mappings()


def format_price(price_int):
    return f"{int(price_int):,}đ".replace(",", ".")


def get_payos_config():
    return shop_service.get_payos_config()


def get_supplier_client():
    return SupplierApiClient(SUPPLIER_BASE_URL, SUPPLIER_API_KEY)


def get_supplier_unit_price(product_detail):
    product = (product_detail or {}).get("product") or {}
    for key in ("sale_price", "special_price", "price", "base_price"):
        value = product.get(key)
        if value is not None:
            return int(value)
    raise SupplierApiError("Supplier product price is unavailable")


def extract_supplier_accounts(purchase_response):
    raw_accounts = purchase_response.get("raw_accounts")
    if isinstance(raw_accounts, list):
        accounts = [str(item).strip() for item in raw_accounts if str(item).strip()]
        if accounts:
            return accounts
    if isinstance(raw_accounts, str) and raw_accounts.strip():
        return [raw_accounts.strip()]

    accounts = []
    for row in purchase_response.get("accounts") or []:
        if isinstance(row, dict):
            if row.get("raw"):
                accounts.append(str(row["raw"]).strip())
            else:
                accounts.append(" | ".join(str(value).strip() for value in row.values()))
        elif str(row).strip():
            accounts.append(str(row).strip())
    return [account for account in accounts if account]


def get_supplier_available_units(supplier_product_id, client=None, balance_response=None):
    if not supplier_product_id:
        return 0
    try:
        client = client or get_supplier_client()
        detail = client.get_product_detail(supplier_product_id)
        unit_price = get_supplier_unit_price(detail)
        if unit_price <= 0:
            return 0
        balance_response = balance_response or client.get_balance()
        balance = int(balance_response.get("balance") or 0)
        return max(balance // unit_price, 0)
    except Exception:
        return 0


def format_unix_time(timestamp):
    if not timestamp:
        return "-"
    return time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(int(timestamp)))


def choose_product_emoji(product_name):
    name = str(product_name or "").casefold()
    if any(keyword in name for keyword in ("mail", "email")):
        return "📧"
    if any(keyword in name for keyword in ("admin", "business")):
        return "💼"
    if any(keyword in name for keyword in ("chatgpt", "gpt", "ai")):
        return "🧠"
    if any(keyword in name for keyword in ("google", "pixel", "pro")):
        return "🚀"
    return "🛍️"


def is_chatgpt_product(product_name):
    name = normalize_text_key(product_name)
    return "chatgpt" in name or "gpt" in name


def parse_chatgpt_account(account):
    parts = [part.strip() for part in str(account or "").split("|")]
    if len(parts) < 7:
        return None
    return {
        "email": parts[0],
        "password_mail": parts[1],
        "refresh_token": parts[2],
        "client_id": parts[3],
        "two_fa": parts[4],
        "pass_gpt": parts[5],
        "datetime": parts[6],
    }


def build_chatgpt_accounts_txt(accounts):
    lines = ["Email|Password mail|Refresh Token|Client ID|2FA|PASS GPT|Ngày Giờ"]
    for account in accounts:
        parsed = parse_chatgpt_account(account)
        if parsed is None:
            lines.append(str(account).strip())
            continue
        lines.append(
            "|".join(
                [
                    parsed["email"],
                    parsed["password_mail"],
                    parsed["refresh_token"],
                    parsed["client_id"],
                    parsed["two_fa"],
                    parsed["pass_gpt"],
                    parsed["datetime"],
                ]
            )
        )
    return "\n".join(lines)


def build_chatgpt_quick_copy_text(accounts):
    lines = [
        "⚡ COPY NHANH DỮ LIỆU CỘT (TELE)",
        "Bấm giữ vào khối dữ liệu cột bên dưới để sao chép nhanh trên Telegram.",
        "Khối này đang hiển thị dạng rút gọn theo cấu hình cột mặc định. Muốn xem đầy đủ tài khoản, hãy mở file đính kèm.",
        "",
        "```text",
        "Email | PASS GPT | 2FA | Password mail",
    ]
    for account in accounts:
        parsed = parse_chatgpt_account(account)
        if parsed is None:
            continue
        lines.append(
            f"{parsed['email']} | {parsed['pass_gpt']} | {parsed['two_fa']} | {parsed['password_mail']}"
        )
    lines.append("```")
    return "\n".join(lines)


def format_customer_product_label(product):
    stock_label = "Liên hệ" if product.get("sales_mode") == "contact_only" else f"Còn: {product['available']}"
    if product.get("fulfillment_mode") == "supplier_api" and product.get("sales_mode") != "contact_only":
        stock_label = f"Còn: {product['available']}"
    return (
        f"{choose_product_emoji(product['name'])} "
        f"{product['price_text']} | {product['name']} | {stock_label}"
    )


def get_main_menu_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🛍️ Danh sách sản phẩm", callback_data="show_products"))
    markup.add(InlineKeyboardButton("🧾 Lịch sử mua hàng", callback_data="show_order_history"))
    markup.add(InlineKeyboardButton("💬 Liên hệ hỗ trợ", url="https://t.me/libi94"))
    return markup


def format_order_history_label(entry):
    order = entry["order"]
    product = entry["product"]
    product_name = product["name"] if product is not None else order["product_id"]
    return (
        f"🧾 {order['id']} | {product_name} | "
        f"{order['status']} | {format_unix_time(order['created_at'])[:16]}"
    )


def get_runtime_product(product_id):
    product = product_repository.get_product(product_id)
    if product is None:
        return None
    counts = product_repository.count_stock_by_status(product_id)
    fulfillment_mode = product["fulfillment_mode"] if "fulfillment_mode" in product.keys() else "local_stock"
    supplier_product_id = product["supplier_product_id"] if "supplier_product_id" in product.keys() else None
    sales_mode = product["sales_mode"] if "sales_mode" in product.keys() else "normal"
    available = counts["available"]
    if fulfillment_mode == "supplier_api":
        available = get_supplier_available_units(supplier_product_id)
    return {
        "id": product["id"],
        "name": product["name"],
        "price": product["price"],
        "price_text": format_price(product["price"]),
        "available": available,
        "reserved": counts["reserved"],
        "sold": counts["sold"],
        "disabled": counts["disabled"],
        "total": counts["total"],
        "fulfillment_mode": fulfillment_mode,
        "supplier_product_id": supplier_product_id,
        "sales_mode": sales_mode,
        "active": bool(product["is_active"]) if "is_active" in product.keys() else True,
    }


def list_runtime_products(category_id=None):
    rows = shop_service.list_products_for_category(category_id)
    result = []
    supplier_client = None
    supplier_balance = None
    for row in rows:
        counts = product_repository.count_stock_by_status(row["id"])
        fulfillment_mode = row["fulfillment_mode"] if "fulfillment_mode" in row.keys() else "local_stock"
        supplier_product_id = row["supplier_product_id"] if "supplier_product_id" in row.keys() else None
        sales_mode = row["sales_mode"] if "sales_mode" in row.keys() else "normal"
        available = counts["available"]
        if fulfillment_mode == "supplier_api":
            if supplier_client is None:
                try:
                    supplier_client = get_supplier_client()
                    supplier_balance = supplier_client.get_balance()
                except Exception:
                    supplier_client = False
                    supplier_balance = None
            available = (
                get_supplier_available_units(
                    supplier_product_id,
                    client=supplier_client if supplier_client is not False else None,
                    balance_response=supplier_balance,
                )
                if supplier_client is not False
                else 0
            )
        result.append(
            {
                "id": row["id"],
                "name": row["name"],
                "price": row["price"],
                "price_text": format_price(row["price"]),
                "available": available,
                "reserved": counts["reserved"],
                "sold": counts["sold"],
                "disabled": counts["disabled"],
                "total": counts["total"],
                "fulfillment_mode": fulfillment_mode,
                "supplier_product_id": supplier_product_id,
                "sales_mode": sales_mode,
                "active": bool(row["is_active"]) if "is_active" in row.keys() else True,
            }
        )
    return result


def list_runtime_categories():
    return list(shop_service.list_active_categories())


def list_admin_runtime_categories():
    return list(shop_service.list_manageable_categories())


def get_runtime_category(category_id):
    return product_repository.get_category(category_id)


def check_supplier_purchase_ready(runtime_product, qty):
    if runtime_product.get("fulfillment_mode") != "supplier_api":
        return None
    if not runtime_product.get("supplier_product_id"):
        raise SupplierApiError("Supplier product is not configured")

    client = get_supplier_client()
    detail = client.get_product_detail(runtime_product["supplier_product_id"])
    product_detail = detail.get("product") or {}
    if not product_detail.get("api_enabled"):
        raise SupplierApiError("Supplier product is temporarily unavailable")
    if int(product_detail.get("stock") or 0) < qty:
        raise SupplierApiError("Supplier stock is not enough")

    balance = client.get_balance()
    required_amount = get_supplier_unit_price(detail) * qty
    current_balance = int(balance.get("balance") or 0)
    if current_balance < required_amount:
        raise SupplierApiError("Supplier balance is not enough")
    return detail


def complete_paid_order(chat_id, order_id, payos_ref, amount_paid):
    order = product_repository.get_order(order_id)
    runtime_product = get_runtime_product(order["product_id"]) if order is not None else None
    if order is None or runtime_product is None:
        return None

    if runtime_product.get("fulfillment_mode") == "supplier_api":
        try:
            client = get_supplier_client()
            purchase = client.buy_product(runtime_product["supplier_product_id"], order["qty"])
            accounts = extract_supplier_accounts(purchase)
            if not accounts:
                raise SupplierApiError("Supplier returned no accounts")
            delivered = shop_service.mark_supplier_payment_paid(order_id, payos_ref, amount_paid, accounts)
        except Exception as exc:
            shop_service.cancel_pending_order(order_id, f"supplier purchase failed: {exc}")
            bot.send_message(
                chat_id,
                "❌ Sản phẩm này tạm thời không khả dụng. Đơn hàng đã được hủy ngay sau khi kiểm tra nhà cung cấp.",
            )
            return None
    else:
        delivered = shop_service.mark_payment_paid(order_id, payos_ref, amount_paid)

    send_delivered_order_messages(chat_id, order_id, delivered["accounts"])
    send_admin_paid_notification(order_id, amount_paid, delivered["accounts"])
    return delivered


def send_delivered_order_messages(chat_id, order_id, accounts):
    order = product_repository.get_order(order_id)
    product = get_runtime_product(order["product_id"])
    product_name = product["name"] if product else order["product_id"]
    if is_chatgpt_product(product_name):
        txt_content = build_chatgpt_accounts_txt(accounts)
        document = io.BytesIO(txt_content.encode("utf-8"))
        document.name = f"accounts_{order_id}.txt"
        bot.send_document(
            chat_id,
            document=document,
            caption=(
                "📄 File accounts bạn đã mua\n"
                f"Mã đơn: {order_id}\n"
                f"Thời gian mua: {format_unix_time(order['created_at'])}\n"
                "⚠️ Vui lòng lưu lại mã đơn hàng để được hỗ trợ nhanh chóng."
            ),
        )
        bot.send_message(
            chat_id,
            build_chatgpt_quick_copy_text(accounts),
            parse_mode="Markdown",
        )
        return
    acc_text = "\n".join([f"`{acc}`" for acc in accounts])
    bot.send_message(
        chat_id,
        f"✅ **THANH TOÁN THÀNH CÔNG {order['qty']} {product_name}**\n"
        f"🔖 **Mã đơn:** `{order_id}`\n\n"
        f"🎁 Chi tiết tài khoản của bạn:\n{acc_text}\n\nCảm ơn bạn đã ủng hộ!",
        parse_mode="Markdown",
    )


def send_admin_paid_notification(order_id, amount_paid, accounts):
    order = product_repository.get_order(order_id)
    username = order["username"] or "Không có username"
    full_name = order["full_name"] or "Không có tên"
    product = get_runtime_product(order["product_id"])
    acc_text = "\n".join([f"`{acc}`" for acc in accounts])
    admin_notification = (
        f"🔔 **CÓ ĐƠN HÀNG MỚI ĐÃ THANH TOÁN!**\n"
        f"🔖 **Mã đơn:** `{order_id}`\n"
        f"💳 **PayOS Ref:** `{order['payos_ref']}` (Tiền: {format_price(amount_paid)})\n"
        f"👤 **Khách hàng:** {full_name} ({username})\n"
        f"🆔 **ID Telegram:** `{order['user_id']}`\n"
        f"🛒 **Sản phẩm:** {product['name'] if product else order['product_id']}\n"
        f"📦 **Số lượng mua:** {order['qty']}\n\n"
        f"🎁 **Tài khoản đã xuất:**\n{acc_text}"
    )
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, admin_notification, parse_mode="Markdown")
        except Exception:
            pass


@bot.message_handler(commands=["start", "menu"])
def send_welcome(message):
    bot.reply_to(
        message,
        "🧠 *Trung tâm tài khoản AI & dịch vụ số*\n"
        "⚡ Giao tự động  •  💳 Thanh toán rõ ràng  •  🛡️ Hỗ trợ nhanh\n\n"
        "Chọn một mục bên dưới để bắt đầu.",
        reply_markup=get_main_menu_markup(),
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ Bạn không có quyền truy cập lệnh này.")
        return
    show_admin_menu(message.chat.id)


def show_admin_menu(chat_id, message_id=None):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Thêm sản phẩm mới", callback_data="admin_create_prod"))
    markup.add(InlineKeyboardButton("🗂️ Quản lý category", callback_data="admin_manage_categories"))
    markup.add(InlineKeyboardButton("⚙️ Cài đặt PayOS", callback_data="admin_config_payos"))
    markup.add(InlineKeyboardButton("🔎 Tra cứu đơn", callback_data="admin_lookup_order"))

    for product in list_runtime_products():
        markup.row(
            InlineKeyboardButton(
                (
                    f"📦 {product['name']} | "
                    f"Còn: {product['available']} | "
                    f"Đã giữ: {product['reserved']} | "
                    f"Đã bán: {product['sold']}"
                ),
                callback_data=f"admin_prod_{product['id']}",
            ),
            InlineKeyboardButton("🙈", callback_data=f"admin_delprod_{product['id']}"),
        )

    hidden_products = []
    for row in shop_service.list_inactive_products():
        hidden_products.append(
            {
                "id": row["id"],
                "name": row["name"],
            }
        )
    if hidden_products:
        markup.add(InlineKeyboardButton("🙈 Sản phẩm đang ẩn", callback_data="noop"))
        for product in hidden_products:
            markup.row(
                InlineKeyboardButton(
                    f"🙈 {product['name']}",
                    callback_data=f"admin_prod_{product['id']}",
                ),
                InlineKeyboardButton("👁 Hiện lại", callback_data=f"admin_restoreprod_{product['id']}"),
            )

    text = "🔑 BẢNG ĐIỀU KHIỂN ADMIN\nChọn sản phẩm để quản lý hoặc thêm mới:"
    if message_id:
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)


def show_order_history(chat_id, message_id, user_id):
    entries = shop_service.list_orders_for_user(user_id)
    markup = InlineKeyboardMarkup()
    if not entries:
        markup.add(InlineKeyboardButton("🔙 Quay lại menu", callback_data="show_main_menu"))
        bot.edit_message_text(
            "🧾 Bạn chưa có đơn hàng nào.\nHãy bắt đầu với danh sách sản phẩm hiện có.",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup,
        )
        return

    for entry in entries[:20]:
        markup.add(
            InlineKeyboardButton(
                format_order_history_label(entry),
                callback_data=f"order_detail_{entry['order']['id']}",
            )
        )
    markup.add(InlineKeyboardButton("🔙 Quay lại menu", callback_data="show_main_menu"))
    bot.edit_message_text(
        "🧾 Lịch sử mua hàng\nChọn một đơn để xem chi tiết:",
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
    )


def show_order_detail(chat_id, message_id, user_id, order_id):
    details = shop_service.get_user_order_details(user_id, order_id)
    if details is None:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 Quay lại lịch sử", callback_data="show_order_history"))
        bot.edit_message_text(
            "❌ Không tìm thấy đơn hàng phù hợp.",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup,
        )
        return

    order = details["order"]
    product = details["product"]
    product_name = product["name"] if product is not None else order["product_id"]
    lines = [
        f"🧾 Đơn hàng: `{order['id']}`",
        f"Trạng thái: `{order['status']}`",
        f"Sản phẩm: {product_name}",
        f"Số lượng: {order['qty']}",
        f"Tổng tiền: {format_price(order['total_amount'])}",
        f"Tạo lúc: {format_unix_time(order['created_at'])}",
    ]
    if order["paid_at"]:
        lines.append(f"Thanh toán lúc: {format_unix_time(order['paid_at'])}")
    if order["delivered_at"]:
        lines.append(f"Giao lúc: {format_unix_time(order['delivered_at'])}")

    if order["status"] == "delivered" and details["accounts"]:
        lines.append("")
        lines.append("Tài khoản đã giao:")
        lines.extend([f"`{account}`" for account in details["accounts"]])

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 Quay lại lịch sử", callback_data="show_order_history"))
    bot.edit_message_text(
        "\n".join(lines),
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )


def show_customer_category_menu(chat_id, message_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🗂️ Tất cả sản phẩm", callback_data="show_all_products"))
    for category in list_runtime_categories():
        markup.add(
            InlineKeyboardButton(
                f"📂 {category['name']}",
                callback_data=f"show_category_{category['id']}",
            )
        )
    markup.add(InlineKeyboardButton("🔙 Quay lại menu", callback_data="show_main_menu"))
    bot.edit_message_text(
        "🗂️ Danh mục sản phẩm\nChọn một danh mục để xem sản phẩm cụ thể:",
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
    )


def show_customer_products(chat_id, message_id, category_id=None):
    products = list_runtime_products(category_id)
    markup = InlineKeyboardMarkup()
    if not products:
        markup.add(InlineKeyboardButton("🔙 Quay lại danh mục", callback_data="show_products"))
        bot.edit_message_text(
            "📦 Danh mục này hiện chưa có sản phẩm.",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup,
        )
        return

    for product in products:
        if product.get("sales_mode") == "contact_only":
            markup.add(
                InlineKeyboardButton(
                    format_customer_product_label(product),
                    url="https://t.me/libi94",
                )
            )
        else:
            markup.add(
                InlineKeyboardButton(
                    format_customer_product_label(product),
                    callback_data=f"buy_{product['id']}",
                )
            )
    markup.add(InlineKeyboardButton("🔙 Quay lại danh mục", callback_data="show_products"))
    bot.edit_message_text(
        "Phía dưới là danh sách sản phẩm của hệ thống.\nVui lòng chọn sản phẩm bạn muốn mua:",
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )


def show_admin_category_menu(chat_id, message_id=None):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Thêm category mới", callback_data="admin_create_category"))
    for category in list_admin_runtime_categories():
        label = f"📂 {category['name']}"
        if not category["is_active"]:
            label = f"🙈 {category['name']}"
        markup.add(
            InlineKeyboardButton(
                label,
                callback_data=f"admin_category_{category['id']}",
            )
        )
    markup.add(InlineKeyboardButton("🔙 Quay lại Admin", callback_data="admin_menu"))
    text = "🗂️ QUẢN LÝ CATEGORY\nTạo category mới hoặc quay lại menu admin."
    if message_id:
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)


def show_admin_category_detail(chat_id, message_id, category_id):
    category = get_runtime_category(category_id)
    if category is None:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 Quay lại category", callback_data="admin_manage_categories"))
        bot.edit_message_text(
            "❌ Category không tồn tại!",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup,
        )
        return

    products = list_runtime_products(category_id)
    product_lines = [f"• {product['name']}" for product in products]
    if not product_lines:
        product_lines = ["Chưa có sản phẩm nào trong category này."]

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "➕ Thêm sản phẩm vào category",
            callback_data=f"admin_addproduct_category|{category_id}",
        )
    )
    markup.add(InlineKeyboardButton("✏️ Sửa tên", callback_data=f"admin_editcategory_{category_id}"))
    toggle_label = "🙈 Ẩn category" if category["is_active"] else "👁️ Hiện category"
    markup.add(InlineKeyboardButton(toggle_label, callback_data=f"admin_togglecategory_{category_id}"))
    markup.add(InlineKeyboardButton("🗑️ Xóa category", callback_data=f"admin_deletecategory_{category_id}"))
    markup.add(InlineKeyboardButton("🔙 Quay lại category", callback_data="admin_manage_categories"))
    bot.edit_message_text(
        f"🗂️ **{category['name']}**\n\nSản phẩm hiện có:\n" + "\n".join(product_lines),
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )


def show_admin_category_product_picker(chat_id, message_id, category_id):
    category = get_runtime_category(category_id)
    if category is None:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 Quay lại category", callback_data="admin_manage_categories"))
        bot.edit_message_text(
            "❌ Category không tồn tại!",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup,
        )
        return

    products = list_runtime_products()
    markup = InlineKeyboardMarkup()
    for product in products:
        markup.add(
            InlineKeyboardButton(
                product["name"],
                callback_data=f"admin_pickcategoryproduct|{category_id}|{product['id']}",
            )
        )
    markup.add(
        InlineKeyboardButton(
            "🔙 Quay lại category",
            callback_data=f"admin_category_{category_id}",
        )
    )

    text = f"🗂️ Chọn sản phẩm để thêm vào **{category['name']}**:"
    if not products:
        text = "📦 Hiện chưa có sản phẩm nào để gán category."
    bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )


def show_category_delete_confirmation(chat_id, message_id, category_id):
    category = get_runtime_category(category_id)
    if category is None:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 Quay lại category", callback_data="admin_manage_categories"))
        bot.edit_message_text(
            "❌ Category không tồn tại!",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup,
        )
        return

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✅ Xóa", callback_data=f"admin_confirmdeletecategory_{category_id}"),
        InlineKeyboardButton("❌ Hủy", callback_data=f"admin_category_{category_id}"),
    )
    bot.edit_message_text(
        f"⚠️ Bạn có chắc muốn xóa category **{category['name']}** không?\n"
        "Mọi sản phẩm trong category này sẽ được chuyển về chưa phân loại.",
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )


def show_product_category_assignment(chat_id, message_id, product_id):
    runtime_product = get_runtime_product(product_id)
    if runtime_product is None:
        bot.edit_message_text(
            "❌ Sản phẩm không tồn tại!",
            chat_id=chat_id,
            message_id=message_id,
        )
        return

    markup = InlineKeyboardMarkup()
    for category in list_runtime_categories():
        markup.add(
            InlineKeyboardButton(
                f"📂 {category['name']}",
                callback_data=f"admin_setcategory_{product_id}_{category['id']}",
            )
        )
    markup.add(InlineKeyboardButton("🚫 Bỏ phân loại", callback_data=f"admin_clearcategory_{product_id}"))
    markup.add(InlineKeyboardButton("🔙 Quay lại sản phẩm", callback_data=f"admin_prod_{product_id}"))
    bot.edit_message_text(
        f"🗂️ Gán category cho **{runtime_product['name']}**",
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )


def show_product_supplier_config(chat_id, message_id, product_id):
    runtime_product = get_runtime_product(product_id)
    if runtime_product is None:
        bot.edit_message_text(
            "❌ Sản phẩm không tồn tại!",
            chat_id=chat_id,
            message_id=message_id,
        )
        return

    mode_label = "Kho nội bộ" if runtime_product["fulfillment_mode"] == "local_stock" else "Supplier API"
    supplier_id = runtime_product.get("supplier_product_id") or "Chưa cấu hình"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📦 Dùng kho nội bộ", callback_data=f"admin_suppliermode|{product_id}|local_stock"))
    markup.add(InlineKeyboardButton("🌐 Dùng Supplier API", callback_data=f"admin_suppliermode|{product_id}|supplier_api"))
    markup.add(InlineKeyboardButton("🔑 Đặt mã sản phẩm API", callback_data=f"admin_setsupplierid_{product_id}"))
    markup.add(InlineKeyboardButton("🔙 Quay lại sản phẩm", callback_data=f"admin_prod_{product_id}"))
    bot.edit_message_text(
        f"🌐 Cấu hình giao hàng cho **{runtime_product['name']}**\n"
        f"Chế độ hiện tại: **{mode_label}**\n"
        f"Supplier Product ID: `{supplier_id}`",
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )


def show_product_sales_mode_config(chat_id, message_id, product_id):
    runtime_product = get_runtime_product(product_id)
    if runtime_product is None:
        bot.edit_message_text(
            "❌ Sản phẩm không tồn tại!",
            chat_id=chat_id,
            message_id=message_id,
        )
        return

    mode_label = "Liên hệ" if runtime_product.get("sales_mode") == "contact_only" else "Bán bình thường"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🛒 Bán bình thường", callback_data=f"admin_setsalesmode|{product_id}|normal"))
    markup.add(InlineKeyboardButton("💬 Chỉ liên hệ", callback_data=f"admin_setsalesmode|{product_id}|contact_only"))
    markup.add(InlineKeyboardButton("🔙 Quay lại sản phẩm", callback_data=f"admin_prod_{product_id}"))
    bot.edit_message_text(
        f"💬 Chế độ bán cho **{runtime_product['name']}**\n"
        f"Chế độ hiện tại: **{mode_label}**\n\n"
        "Với chế độ `Liên hệ`, customer sẽ thấy nhãn `Liên hệ` và bấm vào sẽ mở thẳng @libi94.",
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    if call.data == "show_main_menu":
        bot.edit_message_text(
            "🧠 *Trung tâm tài khoản AI & dịch vụ số*\n"
            "⚡ Giao tự động  •  💳 Thanh toán rõ ràng  •  🛡️ Hỗ trợ nhanh\n\n"
            "Chọn một mục bên dưới để bắt đầu.",
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=get_main_menu_markup(),
            parse_mode="Markdown",
        )
        return

    if call.data == "show_products":
        show_customer_category_menu(chat_id, msg_id)
        bot.answer_callback_query(call.id, "Đã làm mới danh mục!")
        return

    if call.data == "show_all_products":
        show_customer_products(chat_id, msg_id, None)
        return

    if call.data.startswith("show_category_"):
        show_customer_products(chat_id, msg_id, call.data.split("show_category_", 1)[1])
        return

    if call.data == "show_order_history":
        show_order_history(chat_id, msg_id, call.from_user.id)
        return

    if call.data.startswith("order_detail_"):
        show_order_detail(chat_id, msg_id, call.from_user.id, call.data.split("order_detail_", 1)[1])
        return

    if call.data.startswith("buy_"):
        product_id = call.data.split("buy_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(
                call.id,
                "❌ Sản phẩm này hiện không tồn tại!",
                show_alert=True,
            )
            return
        if runtime_product.get("sales_mode") == "contact_only":
            bot.answer_callback_query(
                call.id,
                "💬 Sản phẩm này vui lòng liên hệ @libi94.",
                show_alert=True,
            )
            return
        if (
            runtime_product["fulfillment_mode"] != "supplier_api"
            and runtime_product["available"] == 0
        ):
            bot.answer_callback_query(
                call.id,
                "❌ Sản phẩm này hiện không tồn tại hoặc đã hết hàng!",
                show_alert=True,
            )
            return

        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("1", callback_data=f"qty_1_{product_id}"),
            InlineKeyboardButton("2", callback_data=f"qty_2_{product_id}"),
            InlineKeyboardButton("3", callback_data=f"qty_3_{product_id}"),
        )
        markup.row(InlineKeyboardButton("⌨️ Nhập số lượng khác", callback_data=f"qty_custom_{product_id}"))
        markup.row(InlineKeyboardButton("🔙 Quay lại", callback_data="show_products"))

        stock_line = f"📦 Tồn kho: {runtime_product['available']}"
        if runtime_product["fulfillment_mode"] == "supplier_api":
            stock_line = f"🌐 Còn: {runtime_product['available']}"

        try:
            bot.edit_message_text(
                f"🛒 Bạn đang chọn mua: **{runtime_product['name']}**\n"
                f"{stock_line}\n\n"
                "👇 Vui lòng chọn số lượng bạn muốn mua:",
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=markup,
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    if call.data.startswith("qty_"):
        parts = call.data.split("_", 2)
        action = parts[1]
        product_id = parts[2]
        if action == "custom":
            msg = bot.send_message(chat_id, "⌨️ Vui lòng nhập số lượng bạn muốn mua (nhập bằng số):")
            bot.register_next_step_handler(msg, process_custom_quantity, product_id)
        else:
            process_purchase(call.from_user, chat_id, product_id, int(action))
        return

    if call.data == "admin_menu":
        show_admin_menu(chat_id, message_id=msg_id)
        return

    if call.data == "admin_config_payos":
        msg = bot.send_message(
            chat_id,
            "⚙️ Vui lòng nhập thông tin cấu hình PayOS theo định dạng:\n"
            "`CLIENT_ID | API_KEY | CHECKSUM_KEY`\n\n"
            "Nếu muốn tắt thanh toán, gửi `off`.",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, admin_process_config_payos)
        return

    if call.data == "admin_manage_categories":
        show_admin_category_menu(chat_id, message_id=msg_id)
        return

    if call.data.startswith("admin_category_"):
        show_admin_category_detail(chat_id, msg_id, call.data.split("admin_category_", 1)[1])
        return

    if call.data == "admin_create_category":
        msg = bot.send_message(
            chat_id,
            "➕ Nhập tên category mới.\nVí dụ: `Tài khoản ChatGPT`",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, admin_process_create_category)
        return

    if call.data.startswith("admin_addproduct_category|"):
        show_admin_category_product_picker(chat_id, msg_id, call.data.split("|", 1)[1])
        return

    if call.data.startswith("admin_pickcategoryproduct|"):
        _, category_id, product_id = call.data.split("|", 2)
        shop_service.assign_product_category(product_id, category_id)
        show_admin_category_detail(chat_id, msg_id, category_id)
        return

    if call.data.startswith("admin_editcategory_"):
        category_id = call.data.split("admin_editcategory_", 1)[1]
        category = get_runtime_category(category_id)
        if category is None:
            bot.answer_callback_query(call.id, "❌ Category không tồn tại!", show_alert=True)
            return
        msg = bot.send_message(
            chat_id,
            f"✏️ Nhập tên mới cho category **{category['name']}**:",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, admin_process_edit_category, category_id)
        return

    if call.data.startswith("admin_togglecategory_"):
        category_id = call.data.split("admin_togglecategory_", 1)[1]
        category = get_runtime_category(category_id)
        if category is None:
            bot.answer_callback_query(call.id, "❌ Category không tồn tại!", show_alert=True)
            return
        shop_service.set_category_active(category_id, not bool(category["is_active"]))
        show_admin_category_detail(chat_id, msg_id, category_id)
        return

    if call.data.startswith("admin_deletecategory_"):
        show_category_delete_confirmation(chat_id, msg_id, call.data.split("admin_deletecategory_", 1)[1])
        return

    if call.data.startswith("admin_confirmdeletecategory_"):
        category_id = call.data.split("admin_confirmdeletecategory_", 1)[1]
        shop_service.delete_category(category_id)
        show_admin_category_menu(chat_id, message_id=msg_id)
        return

    if call.data == "noop":
        bot.answer_callback_query(call.id)
        return

    if call.data == "admin_create_prod":
        msg = bot.send_message(
            chat_id,
            "➕ Để thêm sản phẩm mới, gửi theo cú pháp:\n`Tên sản phẩm | Giá`\n\n"
            "Ví dụ:\n`Tài khoản Netflix 1 tháng | 60.000đ`",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, admin_process_create_prod)
        return

    if call.data == "admin_lookup_order":
        msg = bot.send_message(
            chat_id,
            "🔎 Vui lòng nhập mã đơn cần tra cứu.\nVí dụ: `ORD-79FA7F6A`",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, admin_process_lookup_order)
        return

    if call.data.startswith("admin_prod_"):
        product_id = call.data.split("admin_prod_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(call.id, "❌ Sản phẩm không tồn tại!")
            return

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📥 Nhập kho", callback_data=f"admin_addstock_{product_id}"))
        markup.add(InlineKeyboardButton("🗂️ Gán category", callback_data=f"admin_assigncategory_{product_id}"))
        markup.add(InlineKeyboardButton("💬 Chế độ bán", callback_data=f"admin_salesmodecfg_{product_id}"))
        markup.add(InlineKeyboardButton("🌐 Cấu hình API", callback_data=f"admin_suppliercfg_{product_id}"))
        markup.add(InlineKeyboardButton("✏️ Sửa tên", callback_data=f"admin_editname_{product_id}"))
        markup.add(InlineKeyboardButton("💲 Sửa giá tiền", callback_data=f"admin_editprice_{product_id}"))
        if runtime_product["active"]:
            markup.add(InlineKeyboardButton("🙈 Ẩn sản phẩm", callback_data=f"admin_delprod_{product_id}"))
        else:
            markup.add(InlineKeyboardButton("👁 Hiện lại sản phẩm", callback_data=f"admin_restoreprod_{product_id}"))
        markup.add(InlineKeyboardButton("🔙 Quay lại Admin", callback_data="admin_menu"))

        stock_lines = [
            f"📦 Còn: {runtime_product['available']}",
            f"Đã giữ: {runtime_product['reserved']}",
            f"Đã bán: {runtime_product['sold']}",
        ]
        if runtime_product["disabled"]:
            stock_lines.append(f"Đã khóa: {runtime_product['disabled']}")
        mode_label = "Kho nội bộ" if runtime_product["fulfillment_mode"] == "local_stock" else "Supplier API"
        sales_mode_label = "Liên hệ" if runtime_product.get("sales_mode") == "contact_only" else "Bán bình thường"
        stock_lines.append(f"Giao hàng: {mode_label}")
        stock_lines.append(f"Chế độ bán: {sales_mode_label}")
        if runtime_product["supplier_product_id"]:
            stock_lines.append(f"Supplier ID: {runtime_product['supplier_product_id']}")
        stock_lines.append("Trạng thái: Đang hiển thị" if runtime_product["active"] else "Trạng thái: Đang ẩn")

        try:
            bot.edit_message_text(
                f"⚙️ **Quản lý sản phẩm:** {runtime_product['name']}\n"
                f"💰 Giá: {runtime_product['price_text']}\n"
                + "\n".join(stock_lines),
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=markup,
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    if call.data.startswith("admin_assigncategory_"):
        show_product_category_assignment(chat_id, msg_id, call.data.split("admin_assigncategory_", 1)[1])
        return

    if call.data.startswith("admin_suppliercfg_"):
        show_product_supplier_config(chat_id, msg_id, call.data.split("admin_suppliercfg_", 1)[1])
        return

    if call.data.startswith("admin_salesmodecfg_"):
        show_product_sales_mode_config(chat_id, msg_id, call.data.split("admin_salesmodecfg_", 1)[1])
        return

    if call.data.startswith("admin_suppliermode|"):
        _, product_id, fulfillment_mode = call.data.split("|", 2)
        shop_service.update_product_fulfillment_mode(product_id, fulfillment_mode)
        show_product_supplier_config(chat_id, msg_id, product_id)
        return

    if call.data.startswith("admin_setsalesmode|"):
        _, product_id, sales_mode = call.data.split("|", 2)
        shop_service.update_product_sales_mode(product_id, sales_mode)
        show_product_sales_mode_config(chat_id, msg_id, product_id)
        return

    if call.data.startswith("admin_setsupplierid_"):
        product_id = call.data.split("admin_setsupplierid_", 1)[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(call.id, "❌ Sản phẩm không tồn tại!", show_alert=True)
            return
        msg = bot.send_message(
            chat_id,
            f"🔑 Nhập Supplier Product ID cho **{runtime_product['name']}**:",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, admin_process_supplier_product_id, product_id)
        return

    if call.data.startswith("admin_setcategory_"):
        payload = call.data.split("admin_setcategory_", 1)[1]
        product_part, category_suffix = payload.split("_cat_", 1)
        category_id = f"cat_{category_suffix}"
        shop_service.assign_product_category(product_part, category_id)
        show_admin_menu(chat_id, message_id=msg_id)
        return

    if call.data.startswith("admin_clearcategory_"):
        product_id = call.data.split("admin_clearcategory_", 1)[1]
        shop_service.assign_product_category(product_id, None)
        show_admin_menu(chat_id, message_id=msg_id)
        return

    if call.data.startswith("admin_addstock_"):
        product_id = call.data.split("admin_addstock_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(call.id, "❌ Sản phẩm không tồn tại!", show_alert=True)
            return
        msg = bot.send_message(
            chat_id,
            f"📥 Vui lòng dán danh sách tài khoản cho **{runtime_product['name']}**.\n"
            "Mỗi tài khoản 1 dòng, ví dụ: `email|pass`",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, process_admin_add, product_id)
        return

    if call.data.startswith("admin_editname_"):
        product_id = call.data.split("admin_editname_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(call.id, "❌ Sản phẩm không tồn tại!", show_alert=True)
            return
        msg = bot.send_message(chat_id, f"✏️ Nhập tên mới cho sản phẩm **{runtime_product['name']}**:")
        bot.register_next_step_handler(msg, admin_process_edit_name, product_id)
        return

    if call.data.startswith("admin_editprice_"):
        product_id = call.data.split("admin_editprice_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(call.id, "❌ Sản phẩm không tồn tại!", show_alert=True)
            return
        msg = bot.send_message(
            chat_id,
            f"💲 Nhập giá mới cho sản phẩm **{runtime_product['name']}** (ví dụ: `50.000đ`):",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, admin_process_edit_price, product_id)
        return

    if call.data.startswith("admin_delprod_"):
        product_id = call.data.split("admin_delprod_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(call.id, "❌ Sản phẩm không tồn tại!")
            return

        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("✅ Có, ẩn", callback_data=f"confirmdel_{product_id}"),
            InlineKeyboardButton("❌ Hủy", callback_data="admin_menu"),
        )
        try:
            bot.edit_message_text(
                f"⚠️ Bạn có chắc chắn muốn ẩn sản phẩm **{runtime_product['name']}** không?\n"
                "Hành động này sẽ ẩn sản phẩm khỏi menu bán hàng.",
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=markup,
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    if call.data.startswith("confirmdel_"):
        product_id = call.data.split("confirmdel_")[1]
        if product_repository.get_product(product_id) is not None:
            shop_service.deactivate_product(product_id)
            bot.answer_callback_query(call.id, "✅ Đã ẩn sản phẩm!", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ Sản phẩm không tồn tại.")
        show_admin_menu(chat_id, message_id=msg_id)

    if call.data.startswith("admin_restoreprod_"):
        product_id = call.data.split("admin_restoreprod_")[1]
        if product_repository.get_product(product_id) is not None:
            shop_service.reactivate_product(product_id)
            bot.answer_callback_query(call.id, "✅ Đã hiện lại sản phẩm!", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ Sản phẩm không tồn tại.")
        show_admin_menu(chat_id, message_id=msg_id)


def process_custom_quantity(message, product_id):
    try:
        qty = int(message.text.strip())
        process_purchase(message.from_user, message.chat.id, product_id, qty)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Số lượng không hợp lệ. Vui lòng thử lại lệnh /menu.")


def process_purchase(user, chat_id, product_id, qty):
    if qty <= 0:
        bot.send_message(chat_id, "❌ Số lượng mua phải lớn hơn 0.")
        return

    runtime_product = get_runtime_product(product_id)
    if runtime_product is None:
        bot.send_message(chat_id, "❌ Sản phẩm không tồn tại.")
        return

    if runtime_product.get("sales_mode") == "contact_only":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💬 Liên hệ hỗ trợ", url="https://t.me/libi94"))
        bot.send_message(
            chat_id,
            "💬 Sản phẩm này đang được xử lý theo hình thức liên hệ trực tiếp. Vui lòng bấm nút bên dưới để trao đổi với admin.",
            reply_markup=markup,
        )
        return

    if (
        runtime_product["fulfillment_mode"] != "supplier_api"
        and qty > runtime_product["available"]
    ):
        bot.send_message(
            chat_id,
            f"❌ Rất tiếc, kho không đủ. Chúng tôi chỉ còn {runtime_product['available']} tài khoản.",
        )
        return

    if runtime_product["fulfillment_mode"] == "supplier_api":
        try:
            check_supplier_purchase_ready(runtime_product, qty)
        except Exception:
            bot.send_message(
                chat_id,
                "❌ Sản phẩm này tạm thời không khả dụng. Vui lòng thử lại sau.",
            )
            return

    total_amount = runtime_product["price"] * qty
    payos_config = get_payos_config()
    if total_amount > 0 and (not payos_config or not payos_config.get("client_id")):
        bot.send_message(
            chat_id,
            "❌ Hệ thống chưa cấu hình PayOS. Quá trình mua hàng tự động không thể thực hiện.",
        )
        return

    try:
        order = shop_service.create_pending_order(
            user_id=user.id,
            username=f"@{user.username}" if user.username else None,
            full_name=f"{user.first_name} {user.last_name or ''}".strip(),
            product_id=product_id,
            qty=qty,
        )
    except ValueError as exc:
        bot.send_message(chat_id, f"❌ {exc}")
        return

    if total_amount <= 0:
        complete_paid_order(chat_id, order["id"], "TEST-FREE", 0)
        return

    payment_request = CreatePaymentLinkRequest(
        order_code=order["order_code"],
        amount=order["total_amount"],
        description=f"{order['order_code']}",
        cancel_url="https://t.me",
        return_url="https://t.me",
    )

    try:
        payos_client = PayOS(
            client_id=payos_config["client_id"],
            api_key=payos_config["api_key"],
            checksum_key=payos_config["checksum_key"],
        )
        payment_link = payos_client.payment_requests.create(payment_request)
        checkout_url = payment_link.checkout_url
        qr_code_str = getattr(payment_link, "qr_code", None)

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔗 Mở link thanh toán", url=checkout_url))

        caption_text = (
            f"📝 **Mã đơn tạm:** `{order['order_code']}`\n"
            f"💰 **Tổng tiền:** {format_price(order['total_amount'])}\n\n"
            "💳 Vui lòng quét mã QR hoặc bấm nút Mở link thanh toán để chuyển khoản.\n"
            "⏳ Hệ thống sẽ tự động giao tài khoản trong 1-2 phút sau khi thanh toán thành công."
        )

        if qr_code_str:
            qr = qrcode.QRCode(box_size=10, border=4)
            qr.add_data(qr_code_str)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            bio = io.BytesIO()
            bio.name = "qrcode.png"
            img.save(bio, "PNG")
            bio.seek(0)
            bot.send_photo(chat_id, photo=bio, caption=caption_text, parse_mode="Markdown", reply_markup=markup)
        else:
            bot.send_message(chat_id, caption_text, parse_mode="Markdown", reply_markup=markup)

        threading.Thread(
            target=poll_payment_status,
            args=(order["id"], order["order_code"], chat_id),
            daemon=True,
        ).start()
    except Exception as exc:
        shop_service.cancel_pending_order(order["id"], "payment initialization failed")
        bot.send_message(chat_id, f"❌ Lỗi tạo thanh toán từ PayOS: {exc}")


def poll_payment_status(order_id, order_code, chat_id):
    payos_config = get_payos_config()
    if not payos_config or not payos_config.get("client_id"):
        return

    try:
        payos_client = PayOS(
            client_id=payos_config["client_id"],
            api_key=payos_config["api_key"],
            checksum_key=payos_config["checksum_key"],
        )
    except Exception:
        return

    for _ in range(90):
        time.sleep(10)
        try:
            payment_info = payos_client.payment_requests.get(order_code)
            if payment_info.status == "PAID":
                complete_paid_order(chat_id, order_id, order_code, payment_info.amount)
                break
            if payment_info.status == "CANCELLED":
                shop_service.cancel_pending_order(order_id, "payment cancelled")
                bot.send_message(chat_id, f"❌ Đơn hàng `{order_code}` bị từ chối hoặc hủy thanh toán.")
                break
        except Exception:
            pass


def admin_process_config_payos(message):
    text = message.text.strip()
    if text.lower() == "off":
        shop_service.clear_payos_config()
        bot.send_message(
            message.chat.id,
            "✅ Đã tắt tính năng thanh toán PayOS.\nLưu ý: Bạn không thể tạo QR thanh toán tự động nữa.",
            parse_mode="Markdown",
        )
        return

    parts = [part.strip() for part in text.split("|")]
    if len(parts) >= 3:
        shop_service.set_payos_config(parts[0], parts[1], parts[2])
        bot.send_message(
            message.chat.id,
            "✅ Đã lưu cấu hình PayOS. Tính năng thanh toán tự động đã bật.\nDùng lệnh /admin để xem lại.",
        )
    else:
        bot.send_message(
            message.chat.id,
            "❌ Định dạng không đúng. Vui lòng nhập đúng: `CLIENT_ID | API_KEY | CHECKSUM_KEY`",
            parse_mode="Markdown",
        )


def admin_process_create_prod(message):
    if not message.text or "|" not in message.text:
        bot.send_message(message.chat.id, "❌ Định dạng không đúng. Hủy bỏ thêm sản phẩm.")
        return

    parts = message.text.split("|")
    if len(parts) >= 2:
        name = parts[0].strip()
        price = parts[1].strip()
        product = shop_service.create_product(name, price)
        bot.send_message(
            message.chat.id,
            f"✅ Đã thêm sản phẩm thành công:\nTên: {product['name']}\nGiá: {format_price(product['price'])}\n\nDùng lệnh /admin để quản lý.",
        )
    else:
        bot.send_message(message.chat.id, "❌ Vui lòng cung cấp đủ Tên | Giá.")


def admin_process_create_category(message):
    if not message.text:
        bot.send_message(message.chat.id, "❌ Tên category không hợp lệ.")
        return

    category = shop_service.create_category(message.text.strip())
    bot.send_message(
        message.chat.id,
        f"✅ Đã tạo category thành công: {category['name']}\nDùng /admin để quản lý tiếp.",
    )


def admin_process_edit_category(message, category_id):
    if not message.text:
        bot.send_message(message.chat.id, "❌ Tên category không hợp lệ.")
        return

    category = shop_service.update_category_name(category_id, message.text.strip())
    bot.send_message(
        message.chat.id,
        f"✅ Đã cập nhật category thành công: {category['name']}\nDùng /admin để quản lý tiếp.",
    )


def admin_process_supplier_product_id(message, product_id):
    supplier_product_id = str(message.text or "").strip()
    if not supplier_product_id:
        bot.send_message(message.chat.id, "❌ Supplier Product ID không hợp lệ.")
        return

    product = shop_service.update_product_supplier_product_id(product_id, supplier_product_id)
    bot.send_message(
        message.chat.id,
        f"✅ Đã cập nhật Supplier Product ID cho {product['name']}: {product['supplier_product_id']}",
    )


def admin_process_lookup_order(message):
    order_id = str(message.text or "").strip()
    details = shop_service.get_order_details(order_id)
    if details is None:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 Quay lại Admin", callback_data="admin_menu"))
        bot.send_message(
            message.chat.id,
            "❌ Không tìm thấy đơn hàng.",
            reply_markup=markup,
        )
        return

    order = details["order"]
    product = details["product"]
    product_name = product["name"] if product is not None else order["product_id"]
    lines = [
        f"🔎 Đơn hàng: `{order['id']}`",
        f"Trạng thái: `{order['status']}`",
        f"Khách hàng: {order['full_name'] or '-'} ({order['username'] or '-'})",
        f"Telegram ID: `{order['user_id']}`",
        f"Sản phẩm: {product_name}",
        f"Số lượng: {order['qty']}",
        f"Đơn giá: {format_price(order['unit_price'])}",
        f"Tổng tiền: {format_price(order['total_amount'])}",
        f"PayOS ref: `{order['payos_ref'] or '-'}`",
        f"Tạo lúc: {format_unix_time(order['created_at'])}",
    ]
    if order["paid_at"]:
        lines.append(f"Thanh toán lúc: {format_unix_time(order['paid_at'])}")
    if order["delivered_at"]:
        lines.append(f"Giao lúc: {format_unix_time(order['delivered_at'])}")

    accounts = details["accounts"]
    if order["status"] == "delivered" and accounts:
        lines.append("")
        lines.append("Tài khoản đã giao:")
        lines.extend([f"`{account}`" for account in accounts])

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 Quay lại Admin", callback_data="admin_menu"))
    bot.send_message(
        message.chat.id,
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=markup,
    )


def admin_process_edit_name(message, product_id):
    if not message.text:
        return
    shop_service.update_product_name(product_id, message.text.strip())
    bot.send_message(message.chat.id, "✅ Cập nhật tên thành công. Dùng /admin để xem lại.")


def admin_process_edit_price(message, product_id):
    if not message.text:
        return
    shop_service.update_product_price(product_id, message.text.strip())
    bot.send_message(message.chat.id, "✅ Cập nhật giá thành công. Dùng /admin để xem lại.")


def process_admin_add(message, product_id):
    if not message.text:
        bot.send_message(message.chat.id, "❌ Dữ liệu bạn gửi không hợp lệ.")
        return

    added_count = shop_service.add_product_stock(product_id, message.text)
    if added_count:
        counts = product_repository.count_stock_by_status(product_id)
        bot.send_message(
            message.chat.id,
            f"✅ Đã thêm thành công {added_count} tài khoản vào kho.\n📦 Tồn kho hiện tại: {counts['total']}",
        )
    else:
        bot.send_message(message.chat.id, "❌ Không tìm thấy thông tin tài khoản nào để thêm.")


if __name__ == "__main__":
    print("Bot đang khởi động...")
    bot.infinity_polling()

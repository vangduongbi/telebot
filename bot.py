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


API_TOKEN = "8306268191:AAFKK33VzWyAOXe1Zg38Dk8LJ5eGAuTcVs0"
ADMIN_IDS = [1993247449]

DATA_FILE = "data.json"
DB_PATH = "shop.db"

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
                            "name": "Tai khoan GPT Plus 1 thang",
                            "price": "100.000d",
                            "stock": value,
                        }
                    elif key == "google":
                        new_data["products"][key] = {
                            "name": "Tai khoan Google Pro 1 nam (Pixel)",
                            "price": "200.000d",
                            "stock": value,
                        }
                    else:
                        new_data["products"][key] = {
                            "name": f"Product {key}",
                            "price": "0d",
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


def format_price(price_int):
    return f"{int(price_int):,}d".replace(",", ".")


def get_payos_config():
    return shop_service.get_payos_config()


def format_unix_time(timestamp):
    if not timestamp:
        return "-"
    return time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(int(timestamp)))


def get_runtime_product(product_id):
    product = product_repository.get_product(product_id)
    if product is None:
        return None
    counts = product_repository.count_stock_by_status(product_id)
    return {
        "id": product["id"],
        "name": product["name"],
        "price": product["price"],
        "price_text": format_price(product["price"]),
        "available": counts["available"],
        "total": counts["total"],
    }


def list_runtime_products():
    rows = shop_service.list_active_products()
    result = []
    for row in rows:
        counts = product_repository.count_stock_by_status(row["id"])
        result.append(
            {
                "id": row["id"],
                "name": row["name"],
                "price": row["price"],
                "price_text": format_price(row["price"]),
                "available": counts["available"],
                "total": counts["total"],
            }
        )
    return result


def send_delivered_order_messages(chat_id, order_id, accounts):
    order = product_repository.get_order(order_id)
    product = get_runtime_product(order["product_id"])
    product_name = product["name"] if product else order["product_id"]
    acc_text = "\n".join([f"`{acc}`" for acc in accounts])
    bot.send_message(
        chat_id,
        f"✅ **THANH TOAN THANH CONG {order['qty']} {product_name}**\n"
        f"🔖 **Ma don:** `{order_id}`\n\n"
        f"🎁 Chi tiet tai khoan cua ban:\n{acc_text}\n\nCam on ban da ung ho!",
        parse_mode="Markdown",
    )


def send_admin_paid_notification(order_id, amount_paid, accounts):
    order = product_repository.get_order(order_id)
    username = order["username"] or "Khong co Username"
    full_name = order["full_name"] or "Khong co ten"
    product = get_runtime_product(order["product_id"])
    acc_text = "\n".join([f"`{acc}`" for acc in accounts])
    admin_notification = (
        f"🔔 **CO DON HANG MOI DA THANH TOAN!**\n"
        f"🔖 **Ma don:** `{order_id}`\n"
        f"💳 **PayOS Ref:** `{order['payos_ref']}` (Tien: {amount_paid:,}d)\n"
        f"👤 **Khach hang:** {full_name} ({username})\n"
        f"🆔 **ID Telegram:** `{order['user_id']}`\n"
        f"🛒 **San pham:** {product['name'] if product else order['product_id']}\n"
        f"📦 **So luong mua:** {order['qty']}\n\n"
        f"🎁 **Tai khoan da xuat:**\n{acc_text}"
    )
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, admin_notification, parse_mode="Markdown")
        except Exception:
            pass


@bot.message_handler(commands=["start", "menu"])
def send_welcome(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "🛍 Xem danh sach san pham",
            callback_data="show_products",
        )
    )
    bot.reply_to(
        message,
        "Xin chao! Chao mung ban den voi cua hang.\n"
        "Ho tro va lien he admin: @libi94\n"
        "Nhan nut ben duoi de xem cac san pham hien co:",
        reply_markup=markup,
    )


@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ Ban khong co quyen truy cap lenh nay.")
        return
    show_admin_menu(message.chat.id)


def show_admin_menu(chat_id, message_id=None):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Them san pham moi", callback_data="admin_create_prod"))
    markup.add(InlineKeyboardButton("⚙️ Cai dat PayOS", callback_data="admin_config_payos"))
    markup.add(InlineKeyboardButton("🔎 Tra cuu don", callback_data="admin_lookup_order"))

    for product in list_runtime_products():
        markup.row(
            InlineKeyboardButton(
                f"📦 {product['name']} ({product['total']} ton)",
                callback_data=f"admin_prod_{product['id']}",
            ),
            InlineKeyboardButton("🗑", callback_data=f"admin_delprod_{product['id']}"),
        )

    text = "🔑 BANG DIEU KHIEN ADMIN\nChon san pham de quan ly hoac them moi:"
    if message_id:
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    if call.data == "show_products":
        markup = InlineKeyboardMarkup()
        for product in list_runtime_products():
            markup.add(
                InlineKeyboardButton(
                    f"📦 {product['price_text']} | {product['name']} | Con: {product['available']}",
                    callback_data=f"buy_{product['id']}",
                )
            )
        markup.add(InlineKeyboardButton("🔄 Lam moi", callback_data="show_products"))
        try:
            bot.edit_message_text(
                "Phia duoi la danh sach san pham cua he thong.\nVui long chon san pham ban muon mua:",
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=markup,
                parse_mode="Markdown",
            )
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Da lam moi danh sach!")
        return

    if call.data.startswith("buy_"):
        product_id = call.data.split("buy_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None or runtime_product["available"] == 0:
            bot.answer_callback_query(
                call.id,
                "❌ San pham nay hien khong ton tai hoac da het hang!",
                show_alert=True,
            )
            return

        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("1", callback_data=f"qty_1_{product_id}"),
            InlineKeyboardButton("2", callback_data=f"qty_2_{product_id}"),
            InlineKeyboardButton("3", callback_data=f"qty_3_{product_id}"),
        )
        markup.row(InlineKeyboardButton("⌨️ Nhap so luong khac", callback_data=f"qty_custom_{product_id}"))
        markup.row(InlineKeyboardButton("🔙 Quay lai", callback_data="show_products"))

        try:
            bot.edit_message_text(
                f"🛒 Ban dang chon mua: **{runtime_product['name']}**\n"
                f"📦 Ton kho: {runtime_product['available']}\n\n"
                "👇 Vui long chon so luong ban muon mua:",
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
            msg = bot.send_message(chat_id, "⌨️ Vui long nhap so luong ban muon mua (nhap bang so):")
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
            "⚙️ Vui long nhap thong tin cau hinh PayOS theo dinh dang:\n"
            "`CLIENT_ID | API_KEY | CHECKSUM_KEY`\n\n"
            "Neu muon tat thanh toan, gui `off`.",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, admin_process_config_payos)
        return

    if call.data == "admin_create_prod":
        msg = bot.send_message(
            chat_id,
            "➕ De them san pham moi, gui theo cu phap:\n`Ten san pham | Gia`\n\n"
            "Vi du:\n`Tai khoan Netflix 1 thang | 60.000d`",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, admin_process_create_prod)
        return

    if call.data == "admin_lookup_order":
        msg = bot.send_message(
            chat_id,
            "🔎 Vui long nhap ma don can tra cuu.\nVi du: `ORD-79FA7F6A`",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, admin_process_lookup_order)
        return

    if call.data.startswith("admin_prod_"):
        product_id = call.data.split("admin_prod_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(call.id, "❌ San pham khong ton tai!")
            return

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📥 Nhap kho", callback_data=f"admin_addstock_{product_id}"))
        markup.add(InlineKeyboardButton("✏️ Sua ten", callback_data=f"admin_editname_{product_id}"))
        markup.add(InlineKeyboardButton("💲 Sua gia tien", callback_data=f"admin_editprice_{product_id}"))
        markup.add(InlineKeyboardButton("❌ Xoa san pham", callback_data=f"admin_delprod_{product_id}"))
        markup.add(InlineKeyboardButton("🔙 Quay lai Admin", callback_data="admin_menu"))

        try:
            bot.edit_message_text(
                f"⚙️ **Quan ly san pham:** {runtime_product['name']}\n"
                f"💰 Gia: {runtime_product['price_text']}\n"
                f"📦 Ton kho: {runtime_product['total']}",
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=markup,
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    if call.data.startswith("admin_addstock_"):
        product_id = call.data.split("admin_addstock_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(call.id, "❌ San pham khong ton tai!", show_alert=True)
            return
        msg = bot.send_message(
            chat_id,
            f"📥 Vui long dan danh sach tai khoan cho **{runtime_product['name']}**.\n"
            "Moi tai khoan 1 dong, vi du: `email|pass`",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, process_admin_add, product_id)
        return

    if call.data.startswith("admin_editname_"):
        product_id = call.data.split("admin_editname_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(call.id, "❌ San pham khong ton tai!", show_alert=True)
            return
        msg = bot.send_message(chat_id, f"✏️ Nhap ten moi cho san pham **{runtime_product['name']}**:")
        bot.register_next_step_handler(msg, admin_process_edit_name, product_id)
        return

    if call.data.startswith("admin_editprice_"):
        product_id = call.data.split("admin_editprice_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(call.id, "❌ San pham khong ton tai!", show_alert=True)
            return
        msg = bot.send_message(
            chat_id,
            f"💲 Nhap gia moi cho san pham **{runtime_product['name']}** (vi du: `50.000d`):",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, admin_process_edit_price, product_id)
        return

    if call.data.startswith("admin_delprod_"):
        product_id = call.data.split("admin_delprod_")[1]
        runtime_product = get_runtime_product(product_id)
        if runtime_product is None:
            bot.answer_callback_query(call.id, "❌ San pham khong ton tai!")
            return

        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("✅ Co, xoa", callback_data=f"confirmdel_{product_id}"),
            InlineKeyboardButton("❌ Huy", callback_data="admin_menu"),
        )
        try:
            bot.edit_message_text(
                f"⚠️ Ban co chac chan muon xoa san pham **{runtime_product['name']}** khong?\n"
                "Hanh dong nay se an san pham khoi menu ban hang.",
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
            bot.answer_callback_query(call.id, "✅ Da xoa san pham!", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ San pham da bi xoa tu truoc.")
        show_admin_menu(chat_id, message_id=msg_id)


def process_custom_quantity(message, product_id):
    try:
        qty = int(message.text.strip())
        process_purchase(message.from_user, message.chat.id, product_id, qty)
    except ValueError:
        bot.send_message(message.chat.id, "❌ So luong khong hop le. Vui long thu lai lenh /menu.")


def process_purchase(user, chat_id, product_id, qty):
    if qty <= 0:
        bot.send_message(chat_id, "❌ So luong mua phai lon hon 0.")
        return

    runtime_product = get_runtime_product(product_id)
    if runtime_product is None:
        bot.send_message(chat_id, "❌ San pham khong ton tai.")
        return

    if qty > runtime_product["available"]:
        bot.send_message(
            chat_id,
            f"❌ Rat tiec, kho khong du. Chung toi chi con {runtime_product['available']} tai khoan.",
        )
        return

    total_amount = runtime_product["price"] * qty
    payos_config = get_payos_config()
    if total_amount > 0 and (not payos_config or not payos_config.get("client_id")):
        bot.send_message(
            chat_id,
            "❌ He thong chua cau hinh PayOS. Qua trinh mua hang tu dong khong the thuc hien.",
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
        delivered = shop_service.mark_payment_paid(order["id"], "TEST-FREE", 0)
        send_delivered_order_messages(chat_id, order["id"], delivered["accounts"])
        send_admin_paid_notification(order["id"], 0, delivered["accounts"])
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
        markup.add(InlineKeyboardButton("🔗 Mo Link Thanh Toan", url=checkout_url))

        caption_text = (
            f"📝 **Ma don tam:** `{order['order_code']}`\n"
            f"💰 **Tong tien:** {order['total_amount']:,}d\n\n"
            "💳 Vui long quet ma QR hoac bam nut Mo Link Thanh Toan de chuyen khoan.\n"
            "⏳ He thong se tu dong giao tai khoan trong 1-2 phut sau khi thanh toan thanh cong."
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
        bot.send_message(chat_id, f"❌ Loi tao thanh toan tu PayOS: {exc}")


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
                delivered = shop_service.mark_payment_paid(order_id, order_code, payment_info.amount)
                send_delivered_order_messages(chat_id, order_id, delivered["accounts"])
                send_admin_paid_notification(order_id, payment_info.amount, delivered["accounts"])
                break
            if payment_info.status == "CANCELLED":
                shop_service.cancel_pending_order(order_id, "payment cancelled")
                bot.send_message(chat_id, f"❌ Don hang `{order_code}` bi tu choi/huy thanh toan.")
                break
        except Exception:
            pass


def admin_process_config_payos(message):
    text = message.text.strip()
    if text.lower() == "off":
        shop_service.clear_payos_config()
        bot.send_message(
            message.chat.id,
            "✅ Da tat tinh nang thanh toan PayOS.\nLuu y: Ban khong the tao QR thanh toan tu dong nua.",
            parse_mode="Markdown",
        )
        return

    parts = [part.strip() for part in text.split("|")]
    if len(parts) >= 3:
        shop_service.set_payos_config(parts[0], parts[1], parts[2])
        bot.send_message(
            message.chat.id,
            "✅ Da luu cau hinh PayOS. Tinh nang thanh toan tu dong da bat.\nDung lenh /admin de xem lai.",
        )
    else:
        bot.send_message(
            message.chat.id,
            "❌ Dinh dang khong dung. Vui long nhap dung: `CLIENT_ID | API_KEY | CHECKSUM_KEY`",
            parse_mode="Markdown",
        )


def admin_process_create_prod(message):
    if not message.text or "|" not in message.text:
        bot.send_message(message.chat.id, "❌ Dinh dang khong dung. Huy bo them san pham.")
        return

    parts = message.text.split("|")
    if len(parts) >= 2:
        name = parts[0].strip()
        price = parts[1].strip()
        product = shop_service.create_product(name, price)
        bot.send_message(
            message.chat.id,
            f"✅ Da them san pham thanh cong:\nTen: {product['name']}\nGia: {format_price(product['price'])}\n\nDung lenh /admin de quan ly.",
        )
    else:
        bot.send_message(message.chat.id, "❌ Vui long cung cap du Ten | Gia.")


def admin_process_lookup_order(message):
    order_id = str(message.text or "").strip()
    details = shop_service.get_order_details(order_id)
    if details is None:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 Quay lai Admin", callback_data="admin_menu"))
        bot.send_message(
            message.chat.id,
            "❌ Khong tim thay don hang.",
            reply_markup=markup,
        )
        return

    order = details["order"]
    product = details["product"]
    product_name = product["name"] if product is not None else order["product_id"]
    lines = [
        f"🔎 Don hang: `{order['id']}`",
        f"Trang thai: `{order['status']}`",
        f"Khach hang: {order['full_name'] or '-'} ({order['username'] or '-'})",
        f"Telegram ID: `{order['user_id']}`",
        f"San pham: {product_name}",
        f"So luong: {order['qty']}",
        f"Don gia: {format_price(order['unit_price'])}",
        f"Tong tien: {format_price(order['total_amount'])}",
        f"PayOS ref: `{order['payos_ref'] or '-'}`",
        f"Tao luc: {format_unix_time(order['created_at'])}",
    ]
    if order["paid_at"]:
        lines.append(f"Thanh toan luc: {format_unix_time(order['paid_at'])}")
    if order["delivered_at"]:
        lines.append(f"Giao luc: {format_unix_time(order['delivered_at'])}")

    accounts = details["accounts"]
    if order["status"] == "delivered" and accounts:
        lines.append("")
        lines.append("Tai khoan da giao:")
        lines.extend([f"`{account}`" for account in accounts])

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 Quay lai Admin", callback_data="admin_menu"))
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
    bot.send_message(message.chat.id, "✅ Cap nhat ten thanh cong. Dung /admin de xem lai.")


def admin_process_edit_price(message, product_id):
    if not message.text:
        return
    shop_service.update_product_price(product_id, message.text.strip())
    bot.send_message(message.chat.id, "✅ Cap nhat gia thanh cong. Dung /admin de xem lai.")


def process_admin_add(message, product_id):
    if not message.text:
        bot.send_message(message.chat.id, "❌ Du lieu ban gui khong hop le.")
        return

    added_count = shop_service.add_product_stock(product_id, message.text)
    if added_count:
        counts = product_repository.count_stock_by_status(product_id)
        bot.send_message(
            message.chat.id,
            f"✅ Da them thanh cong {added_count} tai khoan vao kho.\n📦 Ton kho hien tai: {counts['total']}",
        )
    else:
        bot.send_message(message.chat.id, "❌ Khong tim thay thong tin tai khoan nao de them.")


if __name__ == "__main__":
    print("Bot dang khoi dong...")
    bot.infinity_polling()

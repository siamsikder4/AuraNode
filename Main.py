import os
import json
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
import httpx
import firebase_admin
from firebase_admin import credentials, firestore

app = FastAPI()

# Firebase ইনিশিয়ালাইজেশন
if not firebase_admin._apps:
    firebase_json_env = os.getenv("FIREBASE_KEY_JSON")
    if firebase_json_env:
        cred = credentials.Certificate(json.loads(firebase_json_env))
    elif os.path.exists("firebase_key.json"):
        cred = credentials.Certificate("firebase_key.json")
    else:
        raise FileNotFoundError("Firebase credentials not found!")
    firebase_admin.initialize_app(cred)

db = firestore.client()

CURRENT_TOKEN = None
RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL", "https://your-service.onrender.com")

user_carts = {}

PRODUCTS_CATALOG = {
    "proxy_9_50mb": {"name": "9 PROXY 50 MB", "cat": "Proxy", "price": 6},
    "proxy_9_100mb": {"name": "9 PROXY 100 MB", "cat": "Proxy", "price": 12},
    "proxy_9_200mb": {"name": "9 PROXY 200 MB", "cat": "Proxy", "price": 23},
    "proxy_rapid_100mb": {"name": "Rapid PROXY 100 MB", "cat": "Proxy", "price": 18},
    "vpn_1m": {"name": "WireGuard VPN 1 Month", "cat": "VPN", "price": 60},
    "mail_temp": {"name": "Temp Mail Premium", "cat": "Mail", "price": 10}
}

async def sync_telegram_webhook(token: str):
    global CURRENT_TOKEN
    CURRENT_TOKEN = token
    webhook_url = f"{RENDER_APP_URL.rstrip('/')}/webhook/telegram"
    async with httpx.AsyncClient() as client:
        await client.get(f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}")
    print(f"[*] Telegram Webhook Synced: {token[:10]}...")

def listen_to_token_changes():
    def on_snapshot(doc_snapshot, changes, read_time):
        for doc in doc_snapshot:
            data = doc.to_dict()
            new_token = data.get("token")
            if new_token and new_token != CURRENT_TOKEN:
                asyncio.run(sync_telegram_webhook(new_token))

    doc_ref = db.collection("bot_config").document("main")
    doc_ref.on_snapshot(on_snapshot)

@app.on_event("startup")
async def startup_event():
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, listen_to_token_changes)

async def send_tg_api(method: str, payload: dict):
    if not CURRENT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{CURRENT_TOKEN}/{method}"
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)

# ড্যাশবোর্ডের সেভ করা ড্র্যাগ-অ্যান্ড-ড্রপ পজিশন ও সাইজ হুবহু কিবোর্ডে রূপান্তর
def get_dynamic_keyboard():
    ui_doc = db.collection("bot_ui").document("settings").get()
    ui = ui_doc.to_dict() if ui_doc.exists else {}
    buttons = ui.get("buttons", [])

    if not buttons:
        # ফলব্যাক ডিফল্ট বাটন
        return {
            "keyboard": [
                [{"text": "🟢 Buy Product"}],
                [{"text": "👤 My Profile"}, {"text": "💳 Deposit"}],
                [{"text": "🛡️ Get Code"}, {"text": "🎧 Support"}]
            ],
            "resize_keyboard": True
        }, ui

    keyboard_grid = []
    temp_row = []

    # ড্যাশবোর্ডে যেভাবে বাটন সাজানো হয়েছে ঠিক সেই অর্ডারে রো/কলাম তৈরি
    for btn in buttons:
        dot = btn.get("dot", "🟢")
        lbl = btn.get("label", "Button")
        btn_text = f"{dot} {lbl}".strip()
        width = btn.get("width", "half")

        if width == "full":
            if temp_row:
                keyboard_grid.append(temp_row)
                temp_row = []
            keyboard_grid.append([{"text": btn_text}])
        else:
            temp_row.append({"text": btn_text})
            if len(temp_row) == 2:
                keyboard_grid.append(temp_row)
                temp_row = []

    if temp_row:
        keyboard_grid.append(temp_row)

    return {"keyboard": keyboard_grid, "resize_keyboard": True}, ui

def get_user_profile(user_id: int, user_info: dict):
    u_ref = db.collection("users").document(str(user_id))
    doc = u_ref.get()
    if not doc.exists:
        init_data = {
            "user_id": user_id,
            "name": user_info.get("first_name", ""),
            "username": user_info.get("username", "None"),
            "balance": 20.0,
            "referrals": 0,
            "created_at": datetime.utcnow()
        }
        u_ref.set(init_data)
        return init_data
    return doc.to_dict()

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    if not CURRENT_TOKEN:
        return {"status": "no_token"}

    update = await request.json()

    if "message" in update:
        msg = update["message"]
        chat_id = msg.get("chat", {}).get("id")
        user = msg.get("from", {})
        text = msg.get("text", "")
        profile = get_user_profile(user.get("id"), user)
        kb, ui_settings = get_dynamic_keyboard()

        # ড্যাশবোর্ডের বাটন আইডি মেলানো (টেক্সট যাই হোক আইডি ধরে অ্যাকশন রান করবে)
        matched_btn_id = None
        for b in ui_settings.get("buttons", []):
            dot = b.get("dot", "🟢")
            lbl = b.get("label", "")
            full_label = f"{dot} {lbl}".strip()
            if text == full_label or text == lbl:
                matched_btn_id = b.get("id")
                break

        if text == "/start":
            shop_title = ui_settings.get("shop_name", "AuraNode Store")
            welcome_header = ui_settings.get("welcome_text", "স্বাগতম আমাদের স্টোরে!")
            emoji_id = ui_settings.get("custom_emoji_id")

            # প্রিমিয়াম কাস্টম ইমোজি ট্যাগ
            if emoji_id:
                brand_display = f'<tg-emoji emoji_id="{emoji_id}">⚡</tg-emoji> <b>{shop_title}</b>'
            else:
                brand_display = f'⚡ <b>{shop_title}</b>'

            welcome_msg = (
                f"👋 <b>Welcome, {user.get('first_name', 'Customer')}!</b>\n\n"
                f"{brand_display}\n{welcome_header}\n\n"
                f"<b>TOP Your Stats:</b>\n"
                f"👥 Total Referrals: <b>{profile.get('referrals', 0)}</b>\n"
                f"💳 Balance: <b>{profile.get('balance', 0.0):.2f} BDT</b>"
            )
            await send_tg_api("sendMessage", {
                "chat_id": chat_id,
                "text": welcome_msg,
                "parse_mode": "HTML",
                "reply_markup": kb
            })

        # বাটন অ্যাকশন হ্যান্ডলার (আইডি বা টেক্সট উভয়ই সাপোর্ট করবে)
        elif matched_btn_id == "buy" or "Buy" in text or text == "/buy":
            cat_keyboard = {
                "inline_keyboard": [
                    [{"text": "🛡️ VPN", "callback_data": "cat_vpn"}, {"text": "🌐 Proxy", "callback_data": "cat_proxy"}],
                    [{"text": "✉️ Mail", "callback_data": "cat_mail"}],
                    [{"text": "❌ Cancel", "callback_data": "action_cancel"}]
                ]
            }
            await send_tg_api("sendMessage", {
                "chat_id": chat_id,
                "text": "🛒 <b>Buy Products</b>\n\nSelect a category:",
                "parse_mode": "HTML",
                "reply_markup": cat_keyboard
            })

        elif matched_btn_id == "profile" or "Profile" in text:
            prof_text = (
                f"👤 <b>User Profile</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{user.get('id')}</code>\n"
                f"📛 <b>Name:</b> {user.get('first_name')}\n"
                f"💵 <b>Balance:</b> <b>{profile.get('balance', 0.0):.2f} BDT</b>\n"
                f"👥 <b>Referrals:</b> {profile.get('referrals', 0)}"
            )
            await send_tg_api("sendMessage", {"chat_id": chat_id, "text": prof_text, "parse_mode": "HTML"})

        elif matched_btn_id == "deposit" or "Deposit" in text:
            dep_text = "💳 <b>Deposit System</b>\n\nSend bKash/Nagad: <code>017XXXXXXXX</code>\nএরপর অ্যাডমিনকে ট্রানজেকশন আইডি পাঠান।"
            await send_tg_api("sendMessage", {"chat_id": chat_id, "text": dep_text, "parse_mode": "HTML"})

        elif matched_btn_id == "support" or "Support" in text:
            await send_tg_api("sendMessage", {"chat_id": chat_id, "text": "🎧 <b>Support:</b> @siamsikder", "parse_mode": "HTML"})

        elif matched_btn_id == "code" or "Code" in text or text == "/stock":
            stock_doc = db.collection("inventory").document("stock").get()
            s_data = stock_doc.to_dict() if stock_doc.exists else {}
            vpn_cnt = len(s_data.get("vpn", []))
            proxy_cnt = len(s_data.get("proxy", []))
            stock_msg = (
                "📊 <b>লাইভ ইনভেন্টরি স্টক</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"🛡️ VPN: <code>{vpn_cnt}</code> টি\n"
                f"🌐 Proxy: <code>{proxy_cnt}</code> টি"
            )
            await send_tg_api("sendMessage", {"chat_id": chat_id, "text": stock_msg, "parse_mode": "HTML"})

    elif "callback_query" in update:
        cq = update["callback_query"]
        cb_id = cq.get("id")
        chat_id = cq.get("message", {}).get("chat", {}).get("id")
        msg_id = cq.get("message", {}).get("message_id")
        user = cq.get("from", {})
        data = cq.get("data")
        user_id = user.get("id")

        await send_tg_api("answerCallbackQuery", {"callback_query_id": cb_id})

        if data == "cat_proxy":
            proxy_keyboard = {
                "inline_keyboard": [
                    [{"text": "📍 9 PROXY 50 MB ❯ 6 BDT", "callback_data": "prod_proxy_9_50mb"}],
                    [{"text": "📍 9 PROXY 100 MB ❯ 12 BDT", "callback_data": "prod_proxy_9_100mb"}],
                    [{"text": "📍 9 PROXY 200 MB ❯ 23 BDT", "callback_data": "prod_proxy_9_200mb"}],
                    [{"text": "🔙 Back", "callback_data": "back_to_cats"}, {"text": "❌ Cancel", "callback_data": "action_cancel"}]
                ]
            }
            await send_tg_api("editMessageText", {
                "chat_id": chat_id,
                "message_id": msg_id,
                "text": "🛒 <b>Category: PROXY</b>\n\nSelect a product:",
                "parse_mode": "HTML",
                "reply_markup": proxy_keyboard
            })

        elif data == "cat_vpn":
            vpn_keyboard = {
                "inline_keyboard": [
                    [{"text": "🛡️ WireGuard VPN 1 Month ❯ 60 BDT", "callback_data": "prod_vpn_1m"}],
                    [{"text": "🔙 Back", "callback_data": "back_to_cats"}, {"text": "❌ Cancel", "callback_data": "action_cancel"}]
                ]
            }
            await send_tg_api("editMessageText", {
                "chat_id": chat_id,
                "message_id": msg_id,
                "text": "🛒 <b>Category: VPN</b>\n\nSelect a product:",
                "parse_mode": "HTML",
                "reply_markup": vpn_keyboard
            })

        elif data == "back_to_cats":
            cat_keyboard = {
                "inline_keyboard": [
                    [{"text": "🛡️ VPN", "callback_data": "cat_vpn"}, {"text": "🌐 Proxy", "callback_data": "cat_proxy"}],
                    [{"text": "✉️ Mail", "callback_data": "cat_mail"}],
                    [{"text": "❌ Cancel", "callback_data": "action_cancel"}]
                ]
            }
            await send_tg_api("editMessageText", {
                "chat_id": chat_id,
                "message_id": msg_id,
                "text": "🛒 <b>Buy Products</b>\n\nSelect a category:",
                "parse_mode": "HTML",
                "reply_markup": cat_keyboard
            })

        elif data == "action_cancel":
            await send_tg_api("editMessageText", {
                "chat_id": chat_id,
                "message_id": msg_id,
                "text": "❌ <b>Cancelled.</b>",
                "parse_mode": "HTML"
            })

        elif data.startswith("prod_"):
            p_key = data.replace("prod_", "")
            user_carts[user_id] = {"item": p_key, "qty": 1}
            await render_summary_page(chat_id, msg_id, user_id)

        elif data == "qty_minus":
            if user_id in user_carts and user_carts[user_id]["qty"] > 1:
                user_carts[user_id]["qty"] -= 1
                await render_summary_page(chat_id, msg_id, user_id)

        elif data == "qty_plus":
            if user_id in user_carts:
                user_carts[user_id]["qty"] += 1
                await render_summary_page(chat_id, msg_id, user_id)

        elif data == "confirm_order":
            if user_id not in user_carts:
                return
            cart = user_carts[user_id]
            prod = PRODUCTS_CATALOG.get(cart["item"])
            total_price = prod["price"] * cart["qty"]

            u_ref = db.collection("users").document(str(user_id))
            user_doc = u_ref.get().to_dict()
            current_bal = user_doc.get("balance", 0.0)

            if current_bal < total_price:
                await send_tg_api("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ <b>Insufficient Balance!</b>\nপ্রয়োজন: {total_price:.2f} BDT\nব্যালেন্স: {current_bal:.2f} BDT",
                    "parse_mode": "HTML"
                })
                return

            stock_ref = db.collection("inventory").document("stock")
            stock_doc = stock_ref.get()
            stock_data = stock_doc.to_dict() if stock_doc.exists else {"proxy": [], "vpn": []}
            cat_field = prod["cat"].lower()
            available_stock = stock_data.get(cat_field, [])

            if len(available_stock) < cart["qty"]:
                await send_tg_api("sendMessage", {"chat_id": chat_id, "text": "❌ <b>Out of Stock!</b> পর্যাপ্ত স্টক খালি নেই।", "parse_mode": "HTML"})
                return

            new_bal = current_bal - total_price
            u_ref.update({"balance": new_bal})

            delivered_items = []
            for _ in range(cart["qty"]):
                delivered_items.append(available_stock.pop(0))
            stock_ref.update({cat_field: available_stock})

            for item in delivered_items:
                parts = item.split(":")
                host = parts[0] if len(parts) > 0 else "niceproxy.io"
                port = parts[1] if len(parts) > 1 else "17521"
                uname = parts[2] if len(parts) > 2 else "user_default"
                pwd = parts[3] if len(parts) > 3 else "pass_default"

                invoice = (
                    "🎉 <b>Purchase successful, Now enjoy!</b> ✅\n\n"
                    f"📍 <b>Product:</b> {prod['name']}\n"
                    f"💵 <b>Remaining Balance:</b> {new_bal:.2f} BDT\n\n"
                    "📥 <b>Your Details:</b>\n\n"
                    f"Host/IP ❯ <code>{host}</code>\n"
                    f"Port ❯ <code>{port}</code>\n"
                    f"Username ❯ <code>{uname}</code>\n"
                    f"Password ❯ <code>{pwd}</code>\n\n"
                    "💥 <i>Thank you for shopping with us!</i>"
                )
                await send_tg_api("sendMessage", {"chat_id": chat_id, "text": invoice, "parse_mode": "HTML"})

            del user_carts[user_id]

    return {"status": "ok"}

async def render_summary_page(chat_id: int, msg_id: int, user_id: int):
    cart = user_carts.get(user_id)
    if not cart:
        return
    prod = PRODUCTS_CATALOG.get(cart["item"])
    qty = cart["qty"]
    total = prod["price"] * qty

    summary_text = (
        "🧾 <b>PURCHASE SUMMARY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 <b>Category:</b> {prod['cat']}\n"
        f"📍 <b>Package:</b> {prod['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>Quantity:</b> {qty}\n"
        f"💵 <b>Rate:</b> {prod['price']:.2f} BDT\n"
        f"🛒 <b>Total Price:</b> <b>{total:.2f} BDT</b>"
    )

    summary_keyboard = {
        "inline_keyboard": [
            [{"text": "➖", "callback_data": "qty_minus"}, {"text": f"{qty}", "callback_data": "noop"}, {"text": "➕", "callback_data": "qty_plus"}],
            [{"text": "🔙 Back", "callback_data": "cat_proxy"}, {"text": "❌ Cancel", "callback_data": "action_cancel"}],
            [{"text": "✅ Confirm", "callback_data": "confirm_order"}]
        ]
    }

    await send_tg_api("editMessageText", {
        "chat_id": chat_id,
        "message_id": msg_id,
        "text": summary_text,
        "parse_mode": "HTML",
        "reply_markup": summary_keyboard
    })

@app.get("/")
def home():
    return {"status": "live", "engine": "AuraNode Store Dynamic Engine"}
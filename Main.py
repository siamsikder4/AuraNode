import os
import json
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
import httpx
import firebase_admin
from firebase_admin import credentials, firestore

app = FastAPI()

# Firebase ইনিশিয়ালাইজেশন (এনভায়রনমেন্ট ভেরিয়েবল বা ফাইল থেকে)
if not firebase_admin._apps:
    firebase_json_env = os.getenv("FIREBASE_KEY_JSON")
    
    if firebase_json_env:
        # Render Environment Variable থেকে সরাসরি লোড
        key_dict = json.loads(firebase_json_env)
        cred = credentials.Certificate(key_dict)
    elif os.path.exists("firebase_key.json"):
        # যদি রিপোজিটরিতে ফাইল থাকে
        cred = credentials.Certificate("firebase_key.json")
    else:
        raise FileNotFoundError("Firebase credentials not found! Set FIREBASE_KEY_JSON in Render environment.")
        
    firebase_admin.initialize_app(cred)

db = firestore.client()

CURRENT_TOKEN = None
RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL", "https://your-service.onrender.com")

async def sync_telegram_webhook(token: str):
    global CURRENT_TOKEN
    CURRENT_TOKEN = token
    webhook_url = f"{RENDER_APP_URL.rstrip('/')}/webhook/telegram"
    async with httpx.AsyncClient() as client:
        await client.get(f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}")
    print(f"[*] Telegram Webhook Active: {token[:10]}...")

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

def save_order(user_info: dict, product_name: str, delivered_data: str):
    order = {
        "telegram_id": user_info.get("id"),
        "first_name": user_info.get("first_name", ""),
        "username": user_info.get("username", "None"),
        "product": product_name,
        "delivered_credential": delivered_data,
        "timestamp": datetime.utcnow()
    }
    db.collection("orders").add(order)

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

        if text == "/start":
            welcome_text = (
                f"👋 *স্বাগতম, {user.get('first_name', 'User')}!*\n\n"
                "⚡ *AuraNode Digital Store* - এ আপনাকে স্বাগতম।\n"
                "এখানে প্রিমিয়াম VPN এবং Residential Proxy পেয়ে যাবেন ইনস্ট্যান্ট ডেলিভারিতে।\n\n"
                "👇 *নিচের অপশন থেকে সিলেক্ট করুন:*"
            )

            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "🛡️ Buy VPN (WireGuard)", "callback_data": "buy_vpn"},
                        {"text": "🌐 Buy Proxy (Elite)", "callback_data": "buy_proxy"}
                    ],
                    [
                        {"text": "📦 স্টক চেক করুন", "callback_data": "check_stock"},
                        {"text": "💬 সাপোর্ট", "url": "https://t.me/siamsikder"}
                    ]
                ]
            }

            await send_tg_api("sendMessage", {
                "chat_id": chat_id,
                "text": welcome_text,
                "parse_mode": "Markdown",
                "reply_markup": keyboard
            })

    elif "callback_query" in update:
        cq = update["callback_query"]
        cb_id = cq.get("id")
        chat_id = cq.get("message", {}).get("chat", {}).get("id")
        user = cq.get("from", {})
        data = cq.get("data")

        await send_tg_api("answerCallbackQuery", {"callback_query_id": cb_id})

        stock_ref = db.collection("inventory").document("stock")
        stock_doc = stock_ref.get()
        stock_data = stock_doc.to_dict() if stock_doc.exists else {"vpn": [], "proxy": []}

        if data == "check_stock":
            vpn_cnt = len(stock_data.get("vpn", []))
            proxy_cnt = len(stock_data.get("proxy", []))
            stock_msg = (
                "📊 *লাইভ ইনভেন্টরি স্টক স্ট্যাটাস*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"🛡️ *প্রিমিয়াম VPN:* `{vpn_cnt}` টি এভেইলেবল\n"
                f"🌐 *রেসিডেনশিয়াল Proxy:* `{proxy_cnt}` টি এভেইলেবল\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
            await send_tg_api("sendMessage", {
                "chat_id": chat_id,
                "text": stock_msg,
                "parse_mode": "Markdown"
            })

        elif data == "buy_vpn":
            vpn_list = stock_data.get("vpn", [])
            if vpn_list:
                item = vpn_list.pop(0)
                stock_ref.update({"vpn": vpn_list})
                save_order(user, "VPN", item)

                delivery_text = (
                    "🎉 *অর্ডার সফল হয়েছে!*\n\n"
                    "🛡️ *আপনার VPN কনফিগারেশন কী:*\n"
                    f"`{item}`\n\n"
                    "ধন্যবাদ আমাদের সাথে থাকার জন্য!"
                )
            else:
                delivery_text = "❌ দুঃখিত! বর্তমানে সব VPN স্টক শেষ হয়ে গেছে।"

            await send_tg_api("sendMessage", {
                "chat_id": chat_id,
                "text": delivery_text,
                "parse_mode": "Markdown"
            })

        elif data == "buy_proxy":
            proxy_list = stock_data.get("proxy", [])
            if proxy_list:
                item = proxy_list.pop(0)
                stock_ref.update({"proxy": proxy_list})
                save_order(user, "Proxy", item)

                delivery_text = (
                    "🎉 *অর্ডার সফল হয়েছে!*\n\n"
                    "🌐 *আপনার প্রক্সি ক্রেডেনশিয়াল (IP:Port:User:Pass):*\n"
                    f"`{item}`"
                )
            else:
                delivery_text = "❌ দুঃখিত! বর্তমানে সব প্রক্সি স্টক শেষ হয়ে গেছে।"

            await send_tg_api("sendMessage", {
                "chat_id": chat_id,
                "text": delivery_text,
                "parse_mode": "Markdown"
            })

    return {"status": "ok"}

@app.get("/")
def home():
    return {"status": "running", "service": "AuraNode Engine"}
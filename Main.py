import os
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
import httpx
import firebase_admin
from firebase_admin import credentials, firestore

app = FastAPI()

# Firebase ইনিশিয়ালাইজেশন
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase_key.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

CURRENT_TOKEN = None
RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL", "https://your-service.onrender.com")

async def sync_telegram_webhook(token: str):
    global CURRENT_TOKEN
    CURRENT_TOKEN = token
    webhook_url = f"{RENDER_APP_URL}/webhook/telegram"
    async with httpx.AsyncClient() as client:
        await client.get(f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}")
    print(f"[*] Webhook Connected for token: {token[:10]}...")

# Firebase থেকে ড্যাশবোর্ডে দেওয়া টোকেন রিয়েলটাইম লোড
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

# কাস্টমার ডাটা Firebase-এ সেভ করার ফাংশন
def save_customer_order(user_info: dict, product_name: str, item_delivered: str):
    order_data = {
        "telegram_id": user_info.get("id"),
        "first_name": user_info.get("first_name", ""),
        "username": user_info.get("username", "None"),
        "product": product_name,
        "delivered_credential": item_delivered,
        "timestamp": datetime.utcnow()
    }
    # Firebase-এর 'orders' কালেকশনে অটোমেটিক নতুন ডকুমেন্ট তৈরি হবে
    db.collection("orders").add(order_data)

    # কাস্টমারের প্রোফাইল 'customers' লিস্টেও আপডেট থাকবে
    customer_ref = db.collection("customers").document(str(user_info.get("id")))
    customer_ref.set({
        "telegram_id": user_info.get("id"),
        "name": user_info.get("first_name", ""),
        "username": user_info.get("username", "None"),
        "last_active": datetime.utcnow()
    }, merge=True)

# টেলিগ্রাম মেসেজ হ্যান্ডলার
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    if not CURRENT_TOKEN:
        return {"status": "no_token"}

    update = await request.json()
    message = update.get("message", {})
    user = message.get("from", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if not chat_id or not text:
        return {"status": "ignored"}

    stock_ref = db.collection("inventory").document("stock")
    stock_doc = stock_ref.get()
    stock_data = stock_doc.to_dict() if stock_doc.exists else {"vpn": [], "proxy": []}

    reply_text = ""

    # ১. কাস্টমার /start দিলে প্রোফাইল ডাটাবেসে যাবে
    if text == "/start":
        db.collection("customers").document(str(user.get("id"))).set({
            "telegram_id": user.get("id"),
            "name": user.get("first_name", ""),
            "username": user.get("username", "None"),
            "joined_at": datetime.utcnow()
        }, merge=True)
        reply_text = f"স্বাগতম {user.get('first_name', '')}!\n\n/buy_vpn - VPN কিনুন\n/buy_proxy - Proxy কিনুন\n/stock - বর্তমান স্টক দেখুন"

    elif text == "/stock":
        vpn_c = len(stock_data.get("vpn", []))
        proxy_c = len(stock_data.get("proxy", []))
        reply_text = f"📦 বর্তমান স্টক অবস্থা:\n🛡️ VPN: {vpn_c} টি\n🌐 Proxy: {proxy_c} টি"

    # ২. কাস্টমার VPN নিলে ডাটা সেভ ও ডেলিভারি
    elif text == "/buy_vpn":
        vpn_list = stock_data.get("vpn", [])
        if vpn_list:
            item = vpn_list.pop(0)
            stock_ref.update({"vpn": vpn_list})
            # Firebase-এ অর্ডারের লগ এবং কাস্টমার ডিটেইলস সেভ
            save_customer_order(user, "VPN", item)
            reply_text = f"✅ আপনার VPN কনফিগ কী:\n`{item}`\n\nধন্যবাদ!"
        else:
            reply_text = "❌ দুঃখিত! বর্তমানে VPN স্টক শেষ হয়ে গেছে।"

    # ৩. কাস্টমার Proxy নিলে ডাটা সেভ ও ডেলিভারি
    elif text == "/buy_proxy":
        proxy_list = stock_data.get("proxy", [])
        if proxy_list:
            item = proxy_list.pop(0)
            stock_ref.update({"proxy": proxy_list})
            # Firebase-এ অর্ডারের লগ এবং কাস্টমার ডিটেইলস সেভ
            save_customer_order(user, "Proxy", item)
            reply_text = f"✅ আপনার Proxy Credentials:\n`{item}`\n\nধন্যবাদ!"
        else:
            reply_text = "❌ দুঃখিত! বর্তমানে Proxy স্টক শেষ হয়ে গেছে।"

    if reply_text:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{CURRENT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": reply_text, "parse_mode": "Markdown"}
            )

    return {"status": "ok"}
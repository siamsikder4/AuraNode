from fastapi import APIRouter, Request
import httpx
from config import bot_state, products_db

router = APIRouter(prefix="/webhook", tags=["Webhook"])

async def send_tg_message(chat_id: int, text: str):
    token = bot_state.get("token")
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)

@router.post("/telegram")
async def telegram_webhook_handler(request: Request):
    data = await request.json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if not chat_id or not text:
        return {"status": "ignored"}

    if text == "/start":
        msg = (
            "👋 *আমাদের শপে স্বাগতম!*\n\n"
            "প্রয়োজনীয় কমান্ডসমূহ:\n"
            "🔹 `/buy_vpn` - VPN কিনুন\n"
            "🔹 `/buy_proxy` - Proxy কিনুন\n"
            "🔹 `/stock` - স্টক চেক করুন"
        )
        await send_tg_message(chat_id, msg)

    elif text == "/stock":
        msg = (
            f"📦 *বর্তমান স্টক:*\n"
            f"🛡️ VPN: {len(products_db['vpn'])} টি\n"
            f"🌐 Proxy: {len(products_db['proxy'])} টি"
        )
        await send_tg_message(chat_id, msg)

    elif text == "/buy_vpn":
        if products_db["vpn"]:
            key = products_db["vpn"].pop(0)
            msg = f"✅ *VPN ডেলিভারি:*\n`{key}`"
        else:
            msg = "❌ দুঃখিত, বর্তমানে কোনো VPN স্টক নেই।"
        await send_tg_message(chat_id, msg)

    elif text == "/buy_proxy":
        if products_db["proxy"]:
            proxy = products_db["proxy"].pop(0)
            msg = f"✅ *Proxy ডেলিভারি:*\n`{proxy}`"
        else:
            msg = "❌ দুঃখিত, বর্তমানে কোনো Proxy স্টক নেই।"
        await send_tg_message(chat_id, msg)

    return {"status": "ok"}
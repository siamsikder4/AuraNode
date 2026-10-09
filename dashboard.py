from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
from config import bot_state

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

class BotConnectRequest(BaseModel):
    token: str
    server_url: str

@router.get("/status")
async def get_bot_status():
    return {
        "connected": bot_state["is_connected"],
        "has_token": bool(bot_state["token"])
    }

@router.post("/connect-bot")
async def connect_bot(data: BotConnectRequest):
    token = data.token.strip()
    server_url = data.server_url.strip().rstrip("/")
    webhook_url = f"{server_url}/webhook/telegram"

    async with httpx.AsyncClient() as client:
        tg_res = await client.get(
            f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}"
        )
        res_data = tg_res.json()

        if not res_data.get("ok"):
            raise HTTPException(
                status_code=400, 
                detail=f"Telegram Error: {res_data.get('description')}"
            )

    bot_state["token"] = token
    bot_state["is_connected"] = True
    return {"message": "টেলিগ্রাম বট সফলভাবে যুক্ত হয়েছে!"}
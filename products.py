from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from config import products_db

router = APIRouter(prefix="/api/products", tags=["Products"])

class AddStockRequest(BaseModel):
    category: str
    items: List[str]

@router.get("/stock")
async def get_all_stock():
    return {
        "vpn_available": len(products_db["vpn"]),
        "proxy_available": len(products_db["proxy"])
    }

@router.post("/add-stock")
async def add_stock(data: AddStockRequest):
    cat = data.category.lower()
    if cat in products_db:
        products_db[cat].extend(data.items)
        return {
            "message": f"{len(data.items)}টি {cat.upper()} সফলভাবে স্টকে যুক্ত হয়েছে!",
            "total_count": len(products_db[cat])
        }
    return {"error": "ক্যাটাগরি ভুল! শুধুমাত্র 'vpn' অথবা 'proxy' দিন।"}
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboard import router as dashboard_router
from products import router as products_router
from bot_webhook import router as webhook_router

app = FastAPI(title="Store Bot Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router)
app.include_router(products_router)
app.include_router(webhook_router)

@app.get("/")
def home():
    return {"status": "online", "message": "সার্ভার চালু আছে!"}

if __name__ == "__main__":
    uvicorn.run("Main:app", host="0.0.0.0", port=8000, reload=True)
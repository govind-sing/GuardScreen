from fastapi import FastAPI
from sqlalchemy import text
from app.core.db import engine
from app.core.redis_client import redis_client
from app.api.v1.gateway import router as gateway_router

app = FastAPI(title="GuardScreen Gateway")
app.include_router(gateway_router)

@app.get("/health")
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await redis_client.ping()
    return {"status": "ok"}
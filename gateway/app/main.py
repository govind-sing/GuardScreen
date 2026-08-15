from fastapi import FastAPI
from sqlalchemy import text
from app.core.db import engine
from app.core.redis_client import redis_client

app = FastAPI(title="GuardScreen Gateway")

@app.get("/health")
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await redis_client.ping()
    return {"status": "ok"}
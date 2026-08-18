from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from arq.connections import RedisSettings, create_pool

from app.config import settings
from app.core.db import engine
from app.core.redis_client import redis_client
from app.api.v1.gateway import router as gateway_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.arq_redis_url))
    yield
    await app.state.arq_pool.close()


app = FastAPI(title="GuardScreen Gateway", lifespan=lifespan)
app.include_router(gateway_router)


@app.get("/health")
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await redis_client.ping()
    return {"status": "ok"}
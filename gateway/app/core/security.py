import hashlib
from fastapi import Header, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.request_log import Agent


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def get_current_agent(
    x_api_key: str = Header(...),
    session: AsyncSession = Depends(get_db),
) -> Agent:
    key_hash = hash_api_key(x_api_key)
    result = await session.execute(
        select(Agent).where(Agent.api_key_hash == key_hash, Agent.is_active == True)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    return agent
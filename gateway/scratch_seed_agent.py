"""
One-off script to seed a test Agent for local development.
Prints the raw API key ONCE — save it, it's not recoverable
(only the hash is stored, same as a real password).
"""
import asyncio
import secrets

from app.core.db import SessionLocal
from app.core.security import hash_api_key
from app.models.request_log import Agent


async def main():
    raw_key = secrets.token_urlsafe(32)

    async with SessionLocal() as session:
        agent = Agent(
            name="local-test-agent",
            api_key_hash=hash_api_key(raw_key),
            role="agent",
            is_active=True,
        )
        session.add(agent)
        await session.commit()
        print(f"Created agent: {agent.id}")

    print(f"Raw API key (save this, won't be shown again): {raw_key}")


if __name__ == "__main__":
    asyncio.run(main())
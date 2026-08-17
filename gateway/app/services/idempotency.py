import uuid

from app.config import settings
from app.core.redis_client import redis_client
from app.core.exceptions import GuardScreenError


class IdempotencyError(GuardScreenError):
    """Raised when the idempotency check itself fails (Redis unreachable, etc.)."""


async def check_and_reserve(idempotency_key: str, candidate_id: uuid.UUID) -> uuid.UUID | None:
    """
    Attempts to atomically reserve this idempotency_key for candidate_id.

    Returns None if the key was not previously used (this request should
    proceed as new — the key is now reserved for candidate_id).

    Returns the EXISTING candidate_id if the key was already used by a
    prior request (this request is a duplicate — caller should return
    the prior result instead of doing any new work).
    """
    try:
        was_set = await redis_client.set(
            name=f"idempotency:{idempotency_key}",
            value=str(candidate_id),
            nx=True,
            ex=settings.idempotency_ttl_seconds,
        )
    except Exception as e:
        raise IdempotencyError(f"Redis idempotency check failed: {e}") from e

    if was_set:
        return None

    existing_value = await redis_client.get(f"idempotency:{idempotency_key}")
    if existing_value is None:
        raise IdempotencyError("Idempotency key existed but expired before it could be read")

    return uuid.UUID(existing_value)
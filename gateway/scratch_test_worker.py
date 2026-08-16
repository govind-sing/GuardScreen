"""
Throwaway script to manually verify the worker end-to-end:
creates the FK chain (agent -> request_log -> candidate), uploads
a real file to MinIO, then enqueues an arq job and lets the worker
process it. Not part of the app — delete once confirmed working.

Usage:
    python scratch_test_worker.py /path/to/your/resume.pdf

Run this, then separately run the worker in another terminal:
    arq app.worker.WorkerSettings
"""
import asyncio
import sys
import uuid
from pathlib import Path

from arq.connections import RedisSettings, create_pool

from app.config import settings
from app.core.db import SessionLocal
from app.models.request_log import Agent, RequestLog
from app.models.candidate import Candidate
from app.services.storage import upload_file


async def main():
    if len(sys.argv) != 2:
        print("Usage: python scratch_test_worker.py <path-to-file>")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"File not found: {file_path}")
        sys.exit(1)

    file_bytes = file_path.read_bytes()
    file_type = file_path.suffix.lstrip(".").lower()

    async with SessionLocal() as session:
        # 1. throwaway agent (FK requires one)
        agent = Agent(name=f"scratch-test-agent-{uuid.uuid4()}", api_key_hash="unused", role="test")
        session.add(agent)
        await session.flush()  # get agent.id without committing yet

        # 2. request_log row, status="pending" — written before any real work, per decision #6
        request_log = RequestLog(agent_id=agent.id, status="pending")
        session.add(request_log)
        await session.flush()

        # 3. upload the real file to MinIO
        candidate_id = uuid.uuid4()
        storage_key = upload_file(str(candidate_id), file_path.name, file_bytes)
        print(f"Uploaded. storage_key = {storage_key}")

        # 4. candidate row, status="queued" — exactly what the real route will do
        candidate = Candidate(
            id=candidate_id,
            request_id=request_log.id,
            original_filename=file_path.name,
            file_type=file_type,
            storage_bucket=settings.minio_bucket,
            storage_key=storage_key,
            status="queued",
        )
        session.add(candidate)
        await session.commit()

        print(f"Created candidate row: {candidate_id}")

    # 5. enqueue the arq job
    redis_pool = await create_pool(RedisSettings.from_dsn(settings.arq_redis_url))
    await redis_pool.enqueue_job("process_candidate", str(candidate_id))
    print(f"Enqueued job for candidate {candidate_id}")
    print("Now check the worker's logs, and query the candidates row to see it update.")


if __name__ == "__main__":
    asyncio.run(main())
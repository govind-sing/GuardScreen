"""
Throwaway script to manually verify the worker end-to-end:
creates the FK chain (agent -> request_log -> candidate), uploads
a real file to MinIO, enqueues an arq job, then polls the candidates
row until the worker reaches a terminal status and prints the result.
Not part of the app — delete once confirmed working.

Usage:
    python scratch_test_worker.py /path/to/your/resume.pdf

Run the worker separately first (or it must already be running):
    docker-compose up -d worker
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

JD_TEXT = """
We are hiring a Backend Engineer with strong experience in Python, FastAPI,
PostgreSQL, and AWS. Experience with Docker and CI/CD pipelines is a plus.
"""

TERMINAL_STATUSES = {"done", "rejected_not_resume", "failed"}
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 60


async def wait_for_result(candidate_id: uuid.UUID) -> Candidate:
    elapsed = 0
    while elapsed < POLL_TIMEOUT_SECONDS:
        async with SessionLocal() as session:
            candidate = await session.get(Candidate, candidate_id)
            if candidate.status in TERMINAL_STATUSES:
                return candidate
            print(f"  ...status={candidate.status}, waiting")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
    raise TimeoutError(f"Candidate {candidate_id} did not reach a terminal status within {POLL_TIMEOUT_SECONDS}s")


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
        agent = Agent(name=f"scratch-test-agent-{uuid.uuid4()}", api_key_hash="unused", role="test")
        session.add(agent)
        await session.flush()

        request_log = RequestLog(agent_id=agent.id, status="pending")
        session.add(request_log)
        await session.flush()

        candidate_id = uuid.uuid4()
        storage_key = upload_file(str(candidate_id), file_path.name, file_bytes)
        print(f"Uploaded. storage_key = {storage_key}")

        candidate = Candidate(
            id=candidate_id,
            request_id=request_log.id,
            original_filename=file_path.name,
            file_type=file_type,
            storage_bucket=settings.minio_bucket,
            storage_key=storage_key,
            jd_text=JD_TEXT,
            status="queued",
        )
        session.add(candidate)
        await session.commit()

        print(f"Created candidate row: {candidate_id}")

    redis_pool = await create_pool(RedisSettings.from_dsn(settings.arq_redis_url))
    await redis_pool.enqueue_job("process_candidate", str(candidate_id))
    print(f"Enqueued job for candidate {candidate_id}")

    print("Waiting for worker to finish...")
    try:
        result = await wait_for_result(candidate_id)
    except TimeoutError as e:
        print(f"❌ {e}")
        sys.exit(1)

    print("-" * 60)
    if result.status == "done":
        print(f"✅ SUCCESS — status: done")
        print(f"   is_resume: {result.is_resume}")
        print(f"   jd_valid: {result.jd_valid}")
        print(f"   score: {result.score}")
        print(f"   reasoning: {result.score_reasoning}")
    elif result.status == "rejected_not_resume":
        print(f"⚠️  REJECTED — status: rejected_not_resume")
        print(f"   is_resume: {result.is_resume}")
        print(f"   jd_valid: {result.jd_valid}")
        print(f"   reasoning: {result.score_reasoning}")
    else:
        print(f"❌ FAILED — status: {result.status}")
        print(f"   error_detail: {result.error_detail}")
        print(f"Done")


if __name__ == "__main__":
    asyncio.run(main())
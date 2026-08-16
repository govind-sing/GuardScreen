import asyncio
import uuid

from arq.connections import RedisSettings
from sqlalchemy import select

from app.config import settings
from app.core.db import SessionLocal
from app.core.exceptions import GuardScreenError
from app.models.candidate import Candidate
from app.services import storage, parsing

MIN_WORDS_BEFORE_OCR_FALLBACK = 20  # placeholder threshold — revisit once we build OCR


async def process_candidate(ctx, candidate_id: str) -> None:
    """
    Single arq task covering the pipeline through parsing:
    download from MinIO -> extract text -> (OCR fallback, not yet built)
    -> save extracted_text, set status="scoring".

    Scoring itself is added here once services/screening.py exists —
    not a separate arq job, just the next step in this same function.
    """
    async with SessionLocal() as session:
        candidate = await session.get(Candidate, uuid.UUID(candidate_id))
        if candidate is None:
            # Shouldn't happen — the row is written before the job is enqueued.
            # Nothing to update if it doesn't exist; just log and stop.
            print(f"[worker] candidate {candidate_id} not found, skipping")
            return

        candidate.status = "parsing"
        await session.commit()

        try:
            file_bytes = await asyncio.to_thread(storage.download_file, candidate.storage_key)
            text = await asyncio.to_thread(parsing.extract_text, file_bytes, candidate.file_type)

            if len(text.split()) < MIN_WORDS_BEFORE_OCR_FALLBACK:
                # OCR fallback goes here once built — for now, treat as a failure
                # so it's visible rather than silently scored on near-empty text.
                candidate.status = "failed"
                candidate.error_detail = "Extracted text too short — likely a scanned PDF, OCR not yet implemented"
                await session.commit()
                return

            candidate.extracted_text = text
            candidate.status = "scoring"
            await session.commit()

            # TODO: call services/screening.py here once it exists —
            # sets is_resume, score, score_reasoning, final status="done"

        except GuardScreenError as e:
            candidate.status = "failed"
            candidate.error_detail = str(e)
            await session.commit()


class WorkerSettings:
    functions = [process_candidate]
    redis_settings = RedisSettings.from_dsn(settings.arq_redis_url)
    job_timeout = 120
    max_tries = 1  # no retries for now, per decision
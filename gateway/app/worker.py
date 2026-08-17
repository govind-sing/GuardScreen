import asyncio
import uuid

from arq.connections import RedisSettings
from sqlalchemy import select

from app.config import settings
from app.core.db import SessionLocal
from app.core.exceptions import GuardScreenError
from app.models.candidate import Candidate
from app.services import storage, parsing, screening

MIN_WORDS_BEFORE_OCR_FALLBACK = 20  # placeholder threshold — revisit once we build OCR


async def process_candidate(ctx, candidate_id: str) -> None:
    """
    Full Phase 1 pipeline: download -> extract -> (OCR fallback, not yet
    built) -> score -> save. Naive baseline — no retries, no guardrails.
    """
    async with SessionLocal() as session:
        candidate = await session.get(Candidate, uuid.UUID(candidate_id))
        if candidate is None:
            print(f"[worker] candidate {candidate_id} not found, skipping")
            return

        candidate.status = "parsing"
        await session.commit()

        try:
            file_bytes = await asyncio.to_thread(storage.download_file, candidate.storage_key)
            text = await asyncio.to_thread(parsing.extract_text, file_bytes, candidate.file_type)

            if len(text.split()) < MIN_WORDS_BEFORE_OCR_FALLBACK:
                candidate.status = "failed"
                candidate.error_detail = "Extracted text too short — likely a scanned PDF, OCR not yet implemented"
                await session.commit()
                return

            candidate.extracted_text = text
            candidate.status = "scoring"
            await session.commit()

            result = await asyncio.to_thread(screening.score_resume, text, candidate.jd_text)

            candidate.is_resume = result["is_resume"]
            candidate.jd_valid = result["jd_valid"]
            candidate.score = result["score"]
            candidate.score_reasoning = result["reasoning"]

            if not result["is_resume"] or not result["jd_valid"]:
                candidate.status = "rejected_not_resume"
            else:
                candidate.status = "done"

            await session.commit()

        except GuardScreenError as e:
            candidate.status = "failed"
            candidate.error_detail = str(e)
            await session.commit()


class WorkerSettings:
    functions = [process_candidate]
    redis_settings = RedisSettings.from_dsn(settings.arq_redis_url)
    job_timeout = 120
    max_tries = 1
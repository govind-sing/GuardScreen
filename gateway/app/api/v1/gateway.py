import uuid
import time

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from arq.connections import RedisSettings, create_pool

from app.config import settings
from app.core.db import get_db
from app.core.security import get_current_agent
from app.models.request_log import Agent, RequestLog
from app.models.candidate import Candidate
from app.schemas.gateway import ScreenResponse, ScreenStatusResponse
from app.services.storage import upload_file, StorageError
from app.services.idempotency import check_and_reserve
from app.services.audit import RequestTimer, mark_success, mark_error

router = APIRouter(prefix="/v1", tags=["screening"])

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf", "docx"}


@router.post("/screen", response_model=ScreenResponse, status_code=202)
async def screen_resume(
    request: Request,
    resume: UploadFile = File(...),
    jd_text: str = Form(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    agent: Agent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_db),
):
    timer = RequestTimer()
    candidate_id = uuid.uuid4()

    if idempotency_key:
        existing_candidate_id = await check_and_reserve(idempotency_key, candidate_id)
        if existing_candidate_id is not None:
            existing = await session.get(Candidate, existing_candidate_id)
            if existing is not None:
                return ScreenResponse(candidate_id=existing.id, status=existing.status)

    file_type = resume.filename.rsplit(".", 1)[-1].lower() if "." in resume.filename else ""
    if file_type not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {file_type!r}. Only PDF and DOCX allowed.")

    if not jd_text or not jd_text.strip():
        raise HTTPException(status_code=400, detail="jd_text is required")

    file_bytes = await resume.read()
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 5MB limit")

    request_log = RequestLog(agent_id=agent.id, status="pending", idempotency_key=idempotency_key)
    session.add(request_log)
    await session.flush()

    try:
        storage_key = upload_file(str(candidate_id), resume.filename, file_bytes)
    except StorageError as e:
        mark_error(request_log, timer, str(e))
        await session.commit()
        raise HTTPException(status_code=502, detail=f"Storage upload failed: {e}")

    candidate = Candidate(
        id=candidate_id,
        request_id=request_log.id,
        original_filename=resume.filename,
        file_type=file_type,
        storage_bucket=settings.minio_bucket,
        storage_key=storage_key,
        jd_text=jd_text,
        status="queued",
    )
    session.add(candidate)
    request_log.candidate_id = candidate_id

    try:
        await request.app.state.arq_pool.enqueue_job("process_candidate", str(candidate_id))
    except Exception as e:
        mark_error(request_log, timer, f"Enqueue failed: {e}")
        await session.commit()
        raise HTTPException(status_code=502, detail="Failed to enqueue processing job")

    mark_success(request_log, timer)
    await session.commit()

    return ScreenResponse(candidate_id=candidate_id, status="queued")



@router.get("/screen/{candidate_id}", response_model=ScreenStatusResponse)
async def get_screen_status(
    candidate_id: uuid.UUID,
    agent: Agent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_db),
):
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    return ScreenStatusResponse(
        candidate_id=candidate.id,
        status=candidate.status,
        is_resume=candidate.is_resume,
        jd_valid=candidate.jd_valid,
        score=candidate.score,
        score_reasoning=candidate.score_reasoning,
        error_detail=candidate.error_detail,
    )
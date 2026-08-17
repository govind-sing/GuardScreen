import uuid
from typing import Optional
from pydantic import BaseModel


class ScreenResponse(BaseModel):
    candidate_id: uuid.UUID
    status: str


class ScreenStatusResponse(BaseModel):
    candidate_id: uuid.UUID
    status: str
    is_resume: Optional[bool] = None
    jd_valid: Optional[bool] = None
    score: Optional[float] = None
    score_reasoning: Optional[str] = None
    error_detail: Optional[str] = None
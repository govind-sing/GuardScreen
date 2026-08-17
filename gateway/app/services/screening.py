import json

from groq import Groq

from app.config import settings
from app.core.exceptions import GuardScreenError


class ScoringError(GuardScreenError):
    """Raised when the LLM call fails or returns unparseable output."""


SYSTEM_PROMPT = """You are a resume screening assistant. You will be given
a job description and a candidate's resume text. Do three things:

1. Determine whether the resume text is actually a resume/CV at all.
2. Determine whether the job description text is actually a genuine job
   description (not random/gibberish/unrelated text).
3. If both are valid, score how well the resume fits the job description,
   0-100, and explain your reasoning briefly.

Respond with ONLY a JSON object in this exact shape, no other text:
{"is_resume": true/false, "jd_valid": true/false, "score": <int 0-100>, "reasoning": "<brief explanation>"}

If is_resume is false or jd_valid is false, set score to 0 and use
reasoning to explain which one failed and why.
"""

_client = Groq(api_key=settings.groq_api_key)


def score_resume(resume_text: str, jd_text: str) -> dict:
    """
    Single naive LLM call: judges is_resume + jd_valid + produces score
    and reasoning in one pass. No retries, no output validation beyond
    JSON parsing — deliberately naive, Phase 1 baseline.

    Returns: {"is_resume": bool, "jd_valid": bool, "score": float, "reasoning": str}
    Raises: ScoringError on API failure or unparseable output.
    """
    user_prompt = f"JOB DESCRIPTION:\n{jd_text}\n\nRESUME TEXT:\n{resume_text}"

    try:
        response = _client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
    except Exception as e:
        raise ScoringError(f"Groq API call failed: {e}") from e

    raw_content = response.choices[0].message.content

    try:
        parsed = json.loads(raw_content)
    except (json.JSONDecodeError, TypeError) as e:
        raise ScoringError(f"Could not parse LLM response as JSON: {e}. Raw: {raw_content!r}") from e

    required_fields = {"is_resume", "jd_valid", "score", "reasoning"}
    if not required_fields.issubset(parsed.keys()):
        raise ScoringError(f"LLM response missing expected fields: {parsed!r}")

    return {
        "is_resume": bool(parsed["is_resume"]),
        "jd_valid": bool(parsed["jd_valid"]),
        "score": float(parsed["score"]),
        "reasoning": str(parsed["reasoning"]),
    }
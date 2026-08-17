"""
Throwaway script to manually verify score_resume() against real text.
Not part of the app — delete once screening is confirmed working.

Usage:
    python scratch_test_screening.py
"""
from app.services.screening import score_resume
from app.core.exceptions import GuardScreenError

# Paste real extracted resume text here (or reuse output from
# scratch_test_parsing.py against your actual PDF).
RESUME_TEXT = """
Govind Singh Tanwar
Forward Deployed Engineer — TypeScript, Node.js, React, REST APIs, AWS, FastAPI
Technical Skills: TypeScript, JavaScript, Python, React.js, Next.js, FastAPI,
PostgreSQL, MongoDB, Redis, AWS (EC2, Lambda, API Gateway), Docker, CI/CD
"""

JD_TEXT = """
asdkjaslkdj random text banana purple elephant
"""


def main():
    print("Calling Groq...")
    try:
        result = score_resume(RESUME_TEXT, JD_TEXT)
    except GuardScreenError as e:
        print(f"Scoring failed: {type(e).__name__}: {e}")
        return

    print("-" * 60)
    print(f"is_resume: {result['is_resume']}")
    print(f"jd_valid: {result['jd_valid']}")
    print(f"score: {result['score']}")
    print(f"reasoning: {result['reasoning']}")


if __name__ == "__main__":
    main()
import json
import os
import time
from pathlib import Path

import pytest
import requests

BASE_DIR = Path(__file__).parent
BASE_URL = os.environ.get("GUARDSCREEN_BASE_URL", "http://localhost:8000")
API_KEY = os.environ["GUARDSCREEN_API_KEY"]  # set this in your shell before running
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 60

# NOTE: verify these two field names against your actual gateway.py route —
# whatever your POST /v1/screen expects for the uploaded file and the JD text.
FILE_FIELD_NAME = "resume"
JD_FIELD_NAME = "jd_text"

with open(BASE_DIR / "manifest.json") as f:
    MANIFEST = json.load(f)["cases"]

with open(BASE_DIR / "fixed_jd.txt") as f:
    FIXED_JD = f.read()


def submit_and_poll(resume_path: Path) -> dict:
    with open(resume_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/v1/screen",
            headers={"X-API-Key": API_KEY},
            files={FILE_FIELD_NAME: (resume_path.name, f, "application/pdf")},
            data={JD_FIELD_NAME: FIXED_JD},
        )
    assert resp.status_code == 202, f"submit failed: {resp.status_code} {resp.text}"
    candidate_id = resp.json()["candidate_id"]

    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    terminal_statuses = {"done", "failed", "rejected_not_resume"}
    last_body = None
    while time.monotonic() < deadline:
        poll = requests.get(
            f"{BASE_URL}/v1/screen/{candidate_id}",
            headers={"X-API-Key": API_KEY},
        )
        assert poll.status_code == 200, f"poll failed: {poll.status_code} {poll.text}"
        last_body = poll.json()
        if last_body.get("status") in terminal_statuses:
            return last_body
        time.sleep(POLL_INTERVAL_SECONDS)

    pytest.fail(f"candidate {candidate_id} never reached terminal status; last: {last_body}")


@pytest.mark.parametrize("case", MANIFEST, ids=[c["id"] for c in MANIFEST])
def test_adversarial_case(case):
    resume_path = BASE_DIR / case["file"]
    result = submit_and_poll(resume_path)
    expect = case["expect"]

    assert result.get("status") == expect["final_status"], (
        f"[{case['id']}] expected status={expect['final_status']}, got {result.get('status')} "
        f"(error_detail={result.get('error_detail')})"
    )

    if expect.get("is_resume") is not None:
        assert result.get("is_resume") == expect["is_resume"], f"[{case['id']}] is_resume mismatch"

    if expect.get("jd_valid") is not None:
        assert result.get("jd_valid") == expect["jd_valid"], f"[{case['id']}] jd_valid mismatch"

    score = result.get("score")
    if expect.get("score_min") is not None:
        assert score is not None and score >= expect["score_min"], (
            f"[{case['id']}] score {score} below floor {expect['score_min']}"
        )
    if expect.get("score_max") is not None:
        assert score is not None and score <= expect["score_max"], (
            f"[{case['id']}] SCORE MANIPULATION SUSPECTED: score {score} exceeds "
            f"ceiling {expect['score_max']} — injection may have succeeded"
        )
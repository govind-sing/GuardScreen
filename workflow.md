# GuardScreen — Project Workflow & Decision Log

## What This Project Is

GuardScreen is an AI Gateway with evaluation-gated guardrails, demonstrated
on a resume-screening multi-agent system. It exists to prove — not just
claim — that an LLM-based agent can resist prompt injection (specifically
indirect injection: malicious instructions hidden inside untrusted content
like an uploaded resume, not typed directly by a user).

The resume screener is the *tenant* of the system. The AI Gateway,
guardrails, and eval harness are the actual subject of the project.

## Goal

Not to finish a demo. To become a production-grade AI engineer who can:
- Explain every infrastructure decision and its trade-offs in an interview
- Reason about a system that has to handle real traffic, not just work once
- Prove reliability with evals, not vibes
- Understand the failure modes of RAG/agent/gateway systems, not just the
  happy path

## High-Level Architecture

- **AI Gateway** — single choke point for all LLM and MCP tool calls.
  Handles auth, rate limiting, idempotency, audit logging, and (later)
  guardrail enforcement, so this logic exists in exactly one place instead
  of being duplicated inside every agent.
- **Agents (LangGraph)** — Parser (raw resume in, structured fields out,
  no scoring authority), Scorer (only sees structured fields, never raw
  text), Reviewer (flags low-confidence/suspicious cases for a human).
  Least-privilege by design — this is the main injection defense, not
  just filters.
- **MCP server** — agents call tools (`extract_resume_fields`,
  `flag_for_review`, `notify_reviewer`) through a self-written MCP server,
  not inline functions. Gateway guards MCP tool calls the same way it
  guards LLM calls, because tool invocation is a separate trust boundary
  from prompt input.
- **Eval harness** — adversarial resume dataset + regression gate. Any
  prompt/model/agent/tool change must pass threshold before "shipping."
- **Postgres** — durable system of record: agent registry, audit log,
  candidate data (kept in separate tables — see decision log).
- **Redis** — fast, ephemeral: idempotency keys, rate-limit counters.

## Phases

- Phase 0 — Skeleton & contracts ✅ **done**
- Phase 1 — Baseline resume screener (naive, unguarded) — deliberately vulnerable control group. ✅ **done**
- Phase 2 — Adversarial eval dataset (defines "success" before any defense is built)
- Phase 3 — Input guardrails at the gateway (PII scrubbing, injection classifier)
- Phase 4 — Multi-agent decomposition + MCP tool layer
- Phase 5 — Output guardrails + policy enforcement (groundedness, leak detection)
- Phase 6 — Pre-deploy eval gate + CI
- Phase 7 — Observability + gateway hardening
- Phase 8 — Deploy + writeup

## Phase 0 — What We Built and Why

### Three independent services from day one (Docker Compose)
`gateway`, `postgres`, `redis` as separate containers on purpose — even
though one process could technically do all of this today. Forces
thinking in real network boundaries (service-to-service calls, not
function calls) from the start, since that's how this will actually
behave once there are multiple real agent services.

### Postgres as system of record, Redis as fast/ephemeral cache
General principle: Redis = fast, ephemeral, short-TTL, high-frequency
check-and-set data. Postgres = durable, queryable, source-of-truth,
audit-grade data.
- Idempotency keys → Redis, with a TTL (see below)
- Agent identity/permissions → source of truth in Postgres, hot-path
  checks cached in Redis with short TTL (planned, not yet implemented)
- Audit log (`request_log`) → Postgres, synchronous write per request
  (no Redis buffering yet — that's a Phase 7 optimization we're
  deliberately not doing early, to avoid solving a scale problem we
  don't have yet)

### Idempotency key TTL (60 min, tunable)
Two opposing forces set the TTL: keys can't live forever (Redis is
in-memory — unbounded keys is a slow memory leak), but the TTL must
outlast the longest realistic retry window of the calling agent,
otherwise a legitimate retry can be mistaken for a new request. 60 min
is a safe starting point; real TTL should be tuned in Phase 7 once we
have real retry-latency data instead of guessing.

### `request_log` does NOT store raw resume text
Audit logs and personal/sensitive data are kept in separate tables
even though they relate to the same event, because they have different
access patterns, different sensitivity, and different retention/
compliance rules (e.g. a candidate's data may need to be deletable on
request, while the fact that a request happened may still need to be
retained for audit). Same principle as separation of concerns, applied
to data modeling instead of code. `request_log` stores a `candidate_id`
reference; raw resume data lives in its own table with tighter access
control (created in Phase 1).

### `status` defaults to `'pending'`, row written BEFORE the LLM call
Models the real lifecycle of a request: write intent first, then update
to `success` / `error` / `blocked` once the outcome is known. A row
stuck at `pending` past a reasonable window is itself a signal — it
tells you precisely where and roughly when something failed (crash,
hung call, network partition), instead of leaving zero trace. Same
principle behind the outbox/saga patterns.

### Idempotency enforced in Redis (SETNX), not a Postgres UNIQUE constraint
A DB unique constraint only catches a duplicate *after* you've already
done the expensive work (e.g. called the LLM) — too late. Redis SETNX
with a TTL checks *before* any expensive work happens. The Postgres
index on `idempotency_key` exists for querying/debugging only, not
enforcement.

### `api/` vs `services/` separation
Routes only parse request → call a service function → format response.
All real logic (idempotency check, audit write, later: guardrail calls)
lives in `services/`, decoupled from HTTP/FastAPI, so it can be called
directly by tests or the eval harness without spinning up a server.

### `schemas/` vs `models/` kept separate even though they look identical today
`models/` = database shape. `schemas/` = API contract. They diverge
fast — e.g. `api_key_hash` belongs in the DB model but should never be
serialized into an API response. Conflating the two is a classic bug
that turns into a security issue later.

### API versioned from day one (`/v1/...`)
Costs nothing now; retrofitting versioning after clients depend on
unversioned routes is genuinely painful later.

### SQLAlchemy models as source of truth + Alembic for schema changes
`Base.metadata.create_all()` was rejected — it can only create tables
that don't exist, with no concept of altering or migrating existing
ones, and no history of what changed when. Alembic diffs models against
the live DB and generates versioned, reviewable SQL migration files.
Rule: **autogenerate is a first draft, not ground truth** — always read
the generated file before applying it (autogenerate can't tell a rename
from a drop+create, and can silently delete data; new NOT NULL columns
on populated tables need a default/backfill, not a blind constraint).

### Rule: only edit/regenerate a migration if it has never been applied anywhere
Once a migration has run against any real database (yours, a
teammate's, staging), editing it retroactively causes environments to
disagree about migration history. Confirmed empirically during Phase 0
debugging: `alembic_version` existing with zero rows + no real tables
present meant nothing had actually been applied yet, so hand-editing
the migration (to add missing indexes) was safe.

### Foreign keys do not automatically get an index in Postgres
`ForeignKey("agents.id")` only creates the constraint, not an index.
Without one, joins/filters on `agent_id` full-table-scan at real volume.
Had to explicitly add `index=True` to the SQLAlchemy column and
`op.create_index()` in the migration.

### Two separate connection-string contexts, not one shared `.env`
A hostname that resolves inside the Docker Compose network (`postgres`,
`redis`) does not resolve on the host machine, and vice versa (`localhost`).
Rule adopted: `docker-compose.yml`'s `environment:` block is the single
source of truth for the container's runtime config (since a real env var
always wins over `.env` file values in Pydantic's `BaseSettings` anyway).
`gateway/.env` is host-only, used only when running tools like Alembic
directly from the Mac, and always points at `localhost`.

### Dockerfile: `COPY requirements.txt` before `COPY . .`
Docker layer caching — splitting these means `pip install` only re-runs
when dependencies actually change, not on every code edit. Meaningful
time savings once iterating daily in later phases.

### Async DB driver requires explicit `+psycopg` in the connection string
A bare `postgresql://` URL makes SQLAlchemy default to `psycopg2` (sync,
never installed), causing a `ModuleNotFoundError` at runtime. Must be
`postgresql+psycopg://` to use the installed async v3 driver.

## Status
Phase 0 complete: three services running via Docker Compose, schema
applied via a reviewed Alembic migration, `/health` endpoint confirms
FastAPI ↔ Postgres ↔ Redis connectivity across the real container
network boundary.


# Phase 1 — Baseline Resume Screener (Naive, Unguarded)

## What We Built

A full async pipeline: client uploads a resume (PDF/docx) + pastes a job
description → gateway validates, stores, and enqueues → a separate worker
process downloads, extracts text, calls an LLM to score fit, and writes
the result → client polls for the outcome. No guardrails anywhere in this
path — this is the deliberately naive control group Phase 2's eval suite
will measure improvements against.

## `Base` (DeclarativeBase) relocated to `app/core/db.py`

Originally lived inline in `models/request_log.py`. When `models/candidate.py`
was added, Alembic's `env.py` only imported `Base` from `request_log.py` —
so `Candidate` never got registered onto `Base.metadata` (a class only
attaches to metadata when its module is actually imported/executed), and
`alembic revision --autogenerate` silently produced empty migrations with
no error. Fixed by moving `Base` to the neutral, infra-appropriate
`core/db.py`, and centralizing all model imports in `app/models/__init__.py`
so any future model only needs one line added there — `env.py` now imports
`Base` from `core/db.py` plus does `import app.models` purely for its
metadata-registration side effect, and never needs touching again per new
model.

## File upload chosen over pasted-text ingestion

More realistic (real screening systems take files, not JSON blobs), and
more relevant to the actual threat model — indirect prompt injection via
hidden text is far easier to demonstrate inside a PDF/docx (invisible text,
tiny fonts, text boxes) than inside plain pasted text. Directly serves
Phase 2's adversarial dataset.

## Raw file bytes stored, not just extracted text

Enables re-parsing later with a better library (e.g. `pypdf` → `pdfplumber`)
without needing the client to re-upload. Same reasoning as keeping durable
source data around rather than only derived data.

## MinIO for object storage, accessed via `boto3` (not the `minio` SDK)

MinIO is S3-API-compatible. Using `boto3` — AWS's own SDK — means the exact
same code works against real AWS S3 in Phase 8 with only an endpoint URL
and credential change. Using MinIO's own SDK would have required a rewrite
later, defeating the reason MinIO was chosen as a local stand-in in the
first place. Bucket key shape: `{candidate_id}/{original_filename}`, single
bucket, no per-environment separation yet (deferred to Phase 8).
`ensure_bucket_exists()` self-heals (creates the bucket on first use if
missing) rather than requiring a manual setup step.

## `arq` chosen over Celery + RabbitMQ

Celery's default task execution model is synchronous — task functions are
plain `def`, not `async def`. This codebase's DB access (async SQLAlchemy)
and LLM calls are async-native throughout; using Celery would mean either
wrapping every async call in `asyncio.run()` inside sync task functions, or
maintaining a parallel sync version of shared service code. `arq` is
async-native by design — task functions are `async def` and directly reuse
the same session/client code the gateway already uses. Important nuance:
this friction is isolated to the worker's *task execution model* —
RabbitMQ vs. Redis as the broker has zero bearing on it; enqueueing a job
is always a fast, non-blocking network call regardless of broker.

## Worker runs as a separate Docker container, same codebase — not a separate repo

Scaling is decided by container/service separation (`docker-compose up
--scale worker=N`), not by folder structure. A separate codebase for the
worker would only add cost (duplicated models, duplicated config, a
code-sharing problem to solve) with zero scaling benefit, since containers
already scale independently regardless of whether source lives in one
folder or two. Standard real-world pattern: one image, one Dockerfile,
`CMD` overridden per deployment target (`uvicorn` for gateway, `arq` for
worker).

## Async job architecture chosen deliberately, to learn it

Sync-blocking processing was the simpler option; async queue-based
processing was chosen specifically as a deliberate complexity trade for
depth, matching the project's explicit goal of learning real distributed-
systems patterns, not shipping the fastest demo.

## Gateway and worker never talk to each other directly

They communicate only through shared state: the `candidates` row in
Postgres (source of truth for job status) and the Redis queue (the
handoff mechanism). This is what makes independent horizontal scaling
possible — neither process needs to know how many instances of the other
exist.

## `extract_text()` is synchronous; caller offloads via `asyncio.to_thread()`

`pypdf`/`python-docx` are CPU-bound, blocking libraries with nothing to
`await` internally — wrapping the function itself in `async def` would be
misleading. Instead, the function stays plain `def`, and every caller
(the worker task) wraps calls in `asyncio.to_thread()` so arq's event loop
stays free to work on other concurrent jobs. The same pattern is applied
to `storage.download_file()` and `screening.score_resume()` inside
`worker.py`, since both are also synchronous, blocking network calls.

## `extract_text()` raises exceptions, doesn't return error tuples

Matches the existing project philosophy that errors are operational
signal, not something to swallow. Custom exceptions
(`UnsupportedFileTypeError`, `ExtractionFailedError`, and later
`StorageError`, `ScoringError`, `IdempotencyError`) are centralized under
one shared `GuardScreenError` base class in `app/core/exceptions.py`, so
callers can catch broadly (`except GuardScreenError`) or narrowly
(`except ExtractionFailedError`), and Phase 2's eval harness has one
consistent exception vocabulary to categorize failures against across the
whole pipeline.

## `extract_text()` makes no judgment about "is this enough text"

Kept single-purpose: pure extraction only. The decision of whether a
result is too short (likely a scanned PDF with no text layer) lives one
level up, in `worker.py` (`MIN_WORDS_BEFORE_OCR_FALLBACK = 20`). No OCR
fallback was built this phase — a scanned PDF is detected and the
candidate is marked `status="failed"` with a clear `error_detail`, rather
than silently producing a meaningless score. Deliberately deferred, not
an oversight; documented as a known limitation.

## `python-docx` and `pypdf` have known extraction limitations

`python-docx` only reads `doc.paragraphs` — it will not pick up text
inside tables, headers/footers, or text boxes, meaning table-based resume
layouts (e.g. skills grids) will have incomplete extraction. `pypdf` was
also observed to introduce minor artifacts (stray spaces, mid-word line
breaks) on some real PDFs during testing. Both are known, accepted
Phase 1 limitations — `pdfplumber` was identified as a fallback option if
either becomes a real problem for Phase 2's eval data, but not adopted now.

## `candidates` table added, with `request_log.candidate_id`'s deferred FK

`candidates` stores: raw file location (`storage_bucket`/`storage_key`,
not raw bytes in Postgres), `original_filename`, `file_type`,
`extracted_text`, the client-submitted `jd_text`, LLM judgments
(`is_resume`, `jd_valid`), the naive score (`score`, `score_reasoning`),
and a pipeline `status`. Adding this table also let us finally add the FK
constraint on `request_log.candidate_id` that Phase 0 deliberately left
nullable/unconstrained, since the referenced table didn't exist yet — both
changes landed in one migration, since they're logically one change.

## `jd_text` is required (NOT NULL), not optional

A null JD would let the system silently produce a meaningless score.
Rejected at the route level (400) if missing/blank instead. This decision
required wiping existing test data and adding the column as `NOT NULL`
directly, rather than the safer nullable-then-backfill pattern — acceptable
here because the data was disposable local test data, not anything real.

## `jd_valid` added as its own boolean column, alongside `is_resume`

Caught during testing: nothing was checking whether the client-submitted
JD text was itself genuine, only whether the uploaded file was a real
resume. Rather than a separate heuristic pre-filter, the LLM judges JD
validity in the *same* combined call as resume validity and scoring —
consistent with the "naive baseline, no pre-filtering heuristics"
approach, and avoids a second API call. Verified directly: a real resume
against a garbage JD correctly returns `is_resume=True, jd_valid=False,
score=0`, and a garbage document against a real JD correctly returns
`is_resume=False, jd_valid=True, score=0` — the two failure modes are
distinguishable via the booleans even though `status` collapses both into
the same `"rejected_not_resume"` value.

## `score` is a plain Float, `score_reasoning` is plain Text — not structured

No JSON breakdown (e.g. `{strengths, gaps}`). Consequence accepted
explicitly: Phase 2's eval harness will be able to judge whether the naive
score was too high or too low, but not easily judge *why*, unless a raw
LLM-response log is added later as a cheap follow-up.

## Groq chosen as the LLM provider; one combined call, plain JSON output

A single call returns `{is_resume, jd_valid, score, reasoning}` as JSON,
parsed with plain `json.loads()` — no structured-output/tool-calling
enforcement. Deliberately naive: brittleness on malformed JSON is honest
signal for Phase 2's evals to measure, not something to guardrail away
this early. `ScoringError` is raised on parse failure or missing expected
fields, no silent defaults. Note this single-call design is explicitly
*not* how Phase 4's real Parser/Scorer agent split will work — the Scorer
there will only ever see the Parser's structured output, never raw resume
text, as the core injection defense. The scoring model changed mid-phase
(`llama-3.3-70b-versatile` → `openai/gpt-oss-120b`, both Groq-hosted, same
client interface) due to hitting free-tier rate limits during testing —
worth remembering if comparing future eval numbers against "the Phase 1
baseline," since the model itself isn't held constant across this phase's
own development.

## Auth: seeded single test agent, `X-API-Key` header, SHA-256 hash

Real per-request auth was a hard requirement (routes need a valid
`agent_id` to write `request_log` rows), but full production-grade auth
(bcrypt/argon2 hashing, key rotation, multiple real agents) was explicitly
deferred. One agent is seeded via a throwaway script that prints its raw
API key exactly once (only the hash is stored). `GET
/v1/screen/{candidate_id}` requires a valid key but does not enforce that
the requesting agent owns that candidate — any authenticated agent can
poll any candidate_id. Both gaps are accepted, documented Phase 1
limitations, not oversights.

## `request_log.status` tracks only the gateway request outcome

Explicitly scoped to mean "did we successfully validate, upload, and
enqueue this request" (`pending` → `success`/`error`) — not the async
pipeline's eventual outcome, which is `candidates.status`'s job. Avoids
either blocking the HTTP response on the worker finishing (defeating the
whole point of async processing) or coupling the worker back to
gateway-owned audit data.

## Idempotency: optional client-supplied `Idempotency-Key` header, Redis SETNX

Implements Phase 0's original decision to enforce idempotency in Redis
before any expensive work happens. `redis_client.set(..., nx=True, ex=TTL)`
is Redis's atomic check-and-set — avoids a race condition a separate
check-then-set would have under concurrent requests. On a duplicate key,
the route returns the *existing* candidate's live status rather than
re-doing any work; verified directly by sending two identical requests
with the same key and confirming both returned the same `candidate_id`,
with the second reflecting real-time state (`"done"`) rather than
retriggering processing. `request_log.idempotency_key` is still populated
on every request regardless, purely for querying/debugging — same as
Phase 0's original note that this column was never meant to be the
enforcement mechanism itself. `candidate_id` is generated up front, before
knowing whether the request is a duplicate, since the reservation call
needs some ID to reserve against; a discarded UUID on the duplicate path
is an accepted minor inefficiency.

## `services/audit.py` is deliberately thin, does not commit

`mark_success()`/`mark_error()` only mutate the in-memory `RequestLog`
object; the route retains full control of its own session/commit
lifecycle. A `RequestTimer` (wrapping `time.monotonic()`) is instantiated
at the top of the route handler to compute `latency_ms` at whichever
terminal point the request reaches.

## Shared arq pool via FastAPI lifespan, not per-request `create_pool()`

Originally, `create_pool()` was called fresh on every `POST /v1/screen`
request, opening a new Redis connection pool each time — flagged early as
a known inefficiency and deliberately left unfixed until the rest of the
route was proven correct, per an incremental build preference. Fixed at
the end of Phase 1: the pool is created once at app startup via FastAPI's
`lifespan` context manager, stored on `app.state.arq_pool`, reused by
every request, and closed cleanly on shutdown.

## Postgres/Redis/MinIO connection limits — understood, deliberately untuned

A detailed question about concurrent load from both gateway and worker
processes surfaced real distinctions worth recording: Postgres has a hard
`max_connections` ceiling with no graceful queuing past it — connections
are *rejected*, not queued, once exceeded; any queuing that does happen is
client-side, inside SQLAlchemy's own connection pool (defaults:
`pool_size`≈5, `max_overflow`≈10, `pool_timeout`≈30s), not inside Postgres
itself. MinIO has no equivalent hard connection ceiling — it degrades in
latency under load instead — but the `boto3` client has its own
client-side pool (default 10 connections) that queues independently.
Explicitly concluded this is not a Phase 1 problem at current
single-developer, local scale, and deferred to Phase 7/8 as a documented,
understood gap rather than an unknown one.

## Recurring gotcha: host vs. container DNS, now hit three times

Same root cause as Phase 0's original Postgres issue, recurring for every
new external service added this phase (MinIO, then arq's Redis DB): a
hostname that resolves inside the Docker network (`minio`, `redis`) means
nothing on the host Mac, which only knows `localhost`. Every new external
dependency needs its connection config added to *both* `.env` files —
root `.env` (container-facing) and `gateway/.env` (host-only, for
scratch scripts and Alembic run directly from the Mac) — or host-side
scripts fail with DNS resolution errors. Worth checking for on any future
new service, not just repeating the fix reactively each time.

## `docker-compose up` can silently run a stale image after a failed build

Discovered when a mistyped dependency pin (`groq==0.1.6`, a nonexistent
version — transposition of the intended `1.6.0`) caused a build failure,
but `docker-compose up -d` still reported the container as "Started,"
because it silently fell back to whatever image had been built
previously. The failed build wasn't obvious from `up`'s own output —
worth explicitly checking build success (not just container "Started"
status) whenever `requirements.txt` changes.

## Status

Phase 1 complete: full async pipeline verified end-to-end through real
testing at every layer — parsing, storage, screening, worker (both
success and rejection paths), the `POST`/`GET` routes, idempotency, and
audit logging. Deliberately naive throughout (no OCR, no retries,
SHA-256 not bcrypt, no GET ownership enforcement, non-streamed size cap,
no structured LLM output) — this is the intended unguarded control group
Phase 2's adversarial eval suite will measure improvements against.
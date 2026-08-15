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
- Phase 1 — Baseline resume screener (naive, unguarded) — deliberately vulnerable control group
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
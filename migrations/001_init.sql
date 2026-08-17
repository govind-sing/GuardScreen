CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT,
    name TEXT NOT NULL UNIQUE,
    api_key_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'agent',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE request_log (
    id UUID PRIMARY KEY DEFAULT,
    agent_id UUID NOT NULL REFERENCES agents(id),
    idempotency_key TEXT,
    candidate_id UUID,              -- FK target added once Phase 1 creates `candidates`
    model_used TEXT,
    latency_ms INTEGER,
    token_count INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | success | error | blocked
    error_detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_request_log_agent_id ON request_log(agent_id);
CREATE INDEX idx_request_log_idempotency_key ON request_log(idempotency_key);



-- candidates table (reference only — Alembic migration is authoritative)
CREATE TABLE candidates (
    id UUID PRIMARY KEY,  -- generated app-side (uuid.uuid4()), not DB-side
    request_id UUID NOT NULL REFERENCES request_log(id),
    original_filename VARCHAR NOT NULL,
    file_type VARCHAR NOT NULL,
    storage_bucket VARCHAR NOT NULL,
    storage_key VARCHAR NOT NULL,
    extracted_text TEXT,
    jd_text TEXT NOT NULL,
    is_resume BOOLEAN,
    jd_valid BOOLEAN,
    score FLOAT,
    score_reasoning TEXT,
    status VARCHAR NOT NULL DEFAULT 'queued',
    error_detail VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX ix_candidates_request_id ON candidates (request_id);

ALTER TABLE request_log
    ADD CONSTRAINT fk_request_log_candidate_id
    FOREIGN KEY (candidate_id) REFERENCES candidates(id);
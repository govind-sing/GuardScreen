CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    api_key_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'agent',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE request_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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
CREATE SCHEMA datapilot_meta AUTHORIZATION analytics_owner;
REVOKE ALL ON SCHEMA datapilot_meta FROM PUBLIC;

CREATE TABLE datapilot_meta.analysis_runs (
    run_id uuid PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'rejected')),
    question text NOT NULL CHECK (char_length(question) BETWEEN 3 AND 4000),
    session_id text CHECK (session_id IS NULL OR char_length(session_id) <= 200),
    model_name text NOT NULL CHECK (char_length(model_name) BETWEEN 1 AND 255),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    duration_ms double precision CHECK (duration_ms IS NULL OR duration_ms >= 0),
    result jsonb,
    error jsonb,
    CONSTRAINT analysis_runs_terminal_payload_check CHECK (
        (status = 'running' AND completed_at IS NULL AND result IS NULL AND error IS NULL)
        OR
        (status = 'succeeded' AND completed_at IS NOT NULL AND result IS NOT NULL AND error IS NULL)
        OR
        (status IN ('failed', 'rejected') AND completed_at IS NOT NULL
            AND result IS NULL AND error IS NOT NULL)
    )
);

CREATE INDEX analysis_runs_started_at_idx
    ON datapilot_meta.analysis_runs (started_at DESC);
CREATE INDEX analysis_runs_session_started_idx
    ON datapilot_meta.analysis_runs (session_id, started_at DESC)
    WHERE session_id IS NOT NULL;

CREATE ROLE datapilot_metadata LOGIN PASSWORD 'local-metadata-only';
GRANT CONNECT ON DATABASE analytics TO datapilot_metadata;
GRANT USAGE ON SCHEMA datapilot_meta TO datapilot_metadata;
GRANT SELECT, INSERT, UPDATE ON datapilot_meta.analysis_runs TO datapilot_metadata;
ALTER ROLE datapilot_metadata SET search_path = datapilot_meta, public;
ALTER ROLE datapilot_metadata SET statement_timeout = '5s';

COMMENT ON SCHEMA datapilot_meta IS
    'DataPilot operational metadata. This schema is not exposed to the analytics read-only role.';
COMMENT ON TABLE datapilot_meta.analysis_runs IS
    'Synchronous analysis run state, result envelopes, and safe failure audit records.';

-- 001_initial.sql
-- Normalized schema for demo-creation-agent
-- Compatible with both SQLite and PostgreSQL (Supabase)

-- Track applied migrations
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Persistent Data -------------------------------------------------------

-- The meeting transcript that triggered a demo
CREATE TABLE IF NOT EXISTS transcripts (
    id                  TEXT PRIMARY KEY,
    content             TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'web',
    meeting_link        TEXT,
    additional_context  TEXT,
    company             TEXT,
    contact_name        TEXT,
    contact_email       TEXT,
    industry            TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- The persistent demo artifact (replaces solutions registry)
CREATE TABLE IF NOT EXISTS demos (
    id              TEXT PRIMARY KEY,
    transcript_id   TEXT REFERENCES transcripts(id),
    source          TEXT NOT NULL DEFAULT 'web',
    demo_type       TEXT,
    use_case        TEXT,
    name            TEXT,
    description     TEXT,
    keywords        TEXT,
    stack           TEXT,
    skills_used     TEXT,
    is_reusable     INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Deploy attempts (one demo can have multiple retries)
CREATE TABLE IF NOT EXISTS deployments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    demo_id             TEXT NOT NULL REFERENCES demos(id),
    github_repo         TEXT,
    railway_project_id  TEXT,
    railway_service_id  TEXT,
    railway_env_id      TEXT,
    deploy_url          TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    error               TEXT,
    health_check_passed INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Extensible key-value pairs for future integrations (CRM, calendar, etc.)
CREATE TABLE IF NOT EXISTS demo_metadata (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    demo_id     TEXT NOT NULL REFERENCES demos(id),
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'system',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(demo_id, key)
);

-- Session Data (Debug/Ephemeral) ----------------------------------------

-- Pipeline execution state
CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT PRIMARY KEY,
    demo_id             TEXT NOT NULL REFERENCES demos(id),
    status              TEXT NOT NULL DEFAULT 'idle',
    current_stage       INTEGER NOT NULL DEFAULT 0,
    mode                TEXT NOT NULL DEFAULT 'auto',
    error               TEXT,
    stage_1_understand  TEXT,
    stage_2_design      TEXT,
    stage_3_demo        TEXT,
    stage_4_guide       TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Pipeline execution logs
CREATE TABLE IF NOT EXISTS session_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    timestamp   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    level       TEXT NOT NULL DEFAULT 'info',
    stage       INTEGER,
    message     TEXT NOT NULL
);

-- Slack pipeline state (ephemeral, for pause/resume between stages)
CREATE TABLE IF NOT EXISTS slack_state (
    channel_id  TEXT PRIMARY KEY,
    state       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_demos_transcript ON demos(transcript_id);
CREATE INDEX IF NOT EXISTS idx_demos_reusable ON demos(is_reusable, is_active);
CREATE INDEX IF NOT EXISTS idx_deployments_demo ON deployments(demo_id);
CREATE INDEX IF NOT EXISTS idx_sessions_demo ON sessions(demo_id);
CREATE INDEX IF NOT EXISTS idx_session_logs_session ON session_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_demo_metadata_demo ON demo_metadata(demo_id);

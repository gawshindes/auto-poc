-- 003_session_transcript.sql
-- Simplify data model: 7 tables → 4 tables.
-- Absorb transcripts into sessions, deployments into demos, drop demo_metadata.

PRAGMA foreign_keys=OFF;

-- Step 1: Add new columns to demos (while old tables still exist for backfill)
ALTER TABLE demos ADD COLUMN session_id TEXT;
ALTER TABLE demos ADD COLUMN company TEXT;
ALTER TABLE demos ADD COLUMN deploy_url TEXT;
ALTER TABLE demos ADD COLUMN github_repo TEXT;
ALTER TABLE demos ADD COLUMN health_check_passed INTEGER NOT NULL DEFAULT 0;

-- Step 2: Backfill demos from deployments + sessions
UPDATE demos SET
    deploy_url = (SELECT d.deploy_url FROM deployments d WHERE d.demo_id = demos.id ORDER BY d.id DESC LIMIT 1),
    github_repo = (SELECT d.github_repo FROM deployments d WHERE d.demo_id = demos.id ORDER BY d.id DESC LIMIT 1),
    health_check_passed = COALESCE((SELECT d.health_check_passed FROM deployments d WHERE d.demo_id = demos.id ORDER BY d.id DESC LIMIT 1), 0),
    session_id = (SELECT s.id FROM sessions s WHERE s.demo_id = demos.id LIMIT 1),
    company = (SELECT t.company FROM transcripts t WHERE t.id = demos.transcript_id LIMIT 1);

-- Step 3: Recreate sessions with transcript data, WITHOUT demo_id
CREATE TABLE sessions_new (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'web',
    transcript TEXT,
    meeting_link TEXT,
    additional_context TEXT,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'idle',
    current_stage INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'auto',
    error TEXT,
    stage_1_understand TEXT,
    stage_2_design TEXT,
    stage_3_demo TEXT,
    stage_4_guide TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT INTO sessions_new (id, source, transcript, meeting_link, additional_context, email,
    status, current_stage, mode, error,
    stage_1_understand, stage_2_design, stage_3_demo, stage_4_guide,
    created_at, updated_at)
SELECT s.id,
    COALESCE(t.source, 'web'),
    t.content,
    t.meeting_link,
    t.additional_context,
    NULL,
    s.status, s.current_stage, s.mode, s.error,
    s.stage_1_understand, s.stage_2_design, s.stage_3_demo, s.stage_4_guide,
    s.created_at, s.updated_at
FROM sessions s
LEFT JOIN demos d ON s.demo_id = d.id
LEFT JOIN transcripts t ON d.transcript_id = t.id;

DROP TABLE sessions;
ALTER TABLE sessions_new RENAME TO sessions;

-- Step 4: Drop obsolete tables and columns
DROP TABLE IF EXISTS demo_metadata;
DROP TABLE IF EXISTS deployments;
DROP TABLE IF EXISTS transcripts;
DROP TABLE IF EXISTS slack_state;

PRAGMA foreign_keys=ON;

CREATE INDEX IF NOT EXISTS idx_demos_session ON demos(session_id);

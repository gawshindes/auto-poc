-- 003_session_transcript_pg.sql
-- Simplify data model: 7 tables → 4 tables.
-- Absorb transcripts into sessions, deployments into demos, drop demo_metadata.

-- Add new columns to sessions
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'web';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS transcript TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS meeting_link TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS additional_context TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS email TEXT;

-- Add new columns to demos
ALTER TABLE demos ADD COLUMN IF NOT EXISTS session_id TEXT REFERENCES sessions(id);
ALTER TABLE demos ADD COLUMN IF NOT EXISTS company TEXT;
ALTER TABLE demos ADD COLUMN IF NOT EXISTS deploy_url TEXT;
ALTER TABLE demos ADD COLUMN IF NOT EXISTS github_repo TEXT;
ALTER TABLE demos ADD COLUMN IF NOT EXISTS health_check_passed INTEGER NOT NULL DEFAULT 0;

-- Backfill sessions from transcripts
UPDATE sessions SET
    source = COALESCE(t.source, 'web'),
    transcript = t.content,
    meeting_link = t.meeting_link,
    additional_context = t.additional_context
FROM demos d
JOIN transcripts t ON d.transcript_id = t.id
WHERE sessions.demo_id = d.id AND sessions.transcript IS NULL;

-- Backfill demos from deployments + sessions
UPDATE demos SET
    deploy_url = dep.deploy_url,
    github_repo = dep.github_repo,
    health_check_passed = COALESCE(dep.health_check_passed, 0)
FROM (SELECT DISTINCT ON (demo_id) * FROM deployments ORDER BY demo_id, id DESC) dep
WHERE dep.demo_id = demos.id AND demos.deploy_url IS NULL;

UPDATE demos SET session_id = s.id
FROM sessions s WHERE s.demo_id = demos.id AND demos.session_id IS NULL;

UPDATE demos SET company = t.company
FROM transcripts t WHERE t.id = demos.transcript_id AND demos.company IS NULL;

-- Drop old columns and tables
ALTER TABLE sessions DROP COLUMN IF EXISTS demo_id;
ALTER TABLE demos DROP COLUMN IF EXISTS transcript_id;
DROP TABLE IF EXISTS demo_metadata;
DROP TABLE IF EXISTS deployments;
DROP TABLE IF EXISTS transcripts;
DROP TABLE IF EXISTS slack_state;

DROP INDEX IF EXISTS idx_sessions_demo;
DROP INDEX IF EXISTS idx_deployments_demo;
DROP INDEX IF EXISTS idx_demos_transcript;
DROP INDEX IF EXISTS idx_demo_metadata_demo;

CREATE INDEX IF NOT EXISTS idx_demos_session ON demos(session_id);

INSERT INTO schema_migrations (version, name)
VALUES (3, '003_session_transcript_pg.sql') ON CONFLICT DO NOTHING;

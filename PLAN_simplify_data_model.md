# Simplify Data Model: 7 tables → 4 tables

## Context

The current schema has unnecessary indirection. Transcripts, deployments, and demo_metadata are always accessed through sessions or demos — never independently. This change collapses them:

- **Transcript** → absorbed into session (it's the pipeline input, "stage 0")
- **Deployments** → absorbed into demo (deploy_url, github_repo, health_check are demo properties)
- **Demo metadata** → dropped (only stored `notification_email`, which is already on `session.email`; `get_metadata` is never called)
- **FK flip**: `demos.session_id` replaces `sessions.demo_id`

### Final schema (4 tables + 3 support tables)

```
sessions    — pipeline execution + transcript input
demos       — deployed artifacts (only created on successful deploy)
session_logs — pipeline logs per session
team_members, slack_state — unchanged
```

**Dropped tables**: `transcripts`, `deployments`, `demo_metadata`

---

## Final table definitions

### `sessions` (absorbs transcript data)
```sql
id                  TEXT PRIMARY KEY
source              TEXT NOT NULL DEFAULT 'web'     -- from transcripts.source
transcript          TEXT                            -- from transcripts.content (the raw text)
meeting_link        TEXT                            -- from transcripts
additional_context  TEXT                            -- from transcripts
email               TEXT                            -- was in demo_metadata as notification_email
status              TEXT NOT NULL DEFAULT 'idle'
current_stage       INTEGER NOT NULL DEFAULT 0
mode                TEXT NOT NULL DEFAULT 'auto'
error               TEXT
stage_1_understand  TEXT                            -- JSON: includes extracted company/contact/industry
stage_2_design      TEXT                            -- JSON
stage_3_demo        TEXT                            -- generated code
stage_4_guide       TEXT                            -- guide text
created_at          TEXT
updated_at          TEXT
```

Customer info (company, contact_name, contact_email, industry) lives inside `stage_1_understand` JSON — no need for separate columns since it's extracted during Stage 1.

### `demos` (absorbs deployment data)
```sql
id                      TEXT PRIMARY KEY
session_id              TEXT REFERENCES sessions(id)  -- nullable for manual demos
source                  TEXT NOT NULL DEFAULT 'web'
demo_type               TEXT
use_case                TEXT
name                    TEXT
description             TEXT
keywords                TEXT                          -- JSON array
stack                   TEXT
skills_used             TEXT                          -- JSON array
deploy_url              TEXT                          -- from deployments
github_repo             TEXT                          -- from deployments
health_check_passed     INTEGER NOT NULL DEFAULT 0    -- from deployments
is_reusable             INTEGER NOT NULL DEFAULT 0
is_active               INTEGER NOT NULL DEFAULT 1
created_at              TEXT
updated_at              TEXT
```

### `session_logs`, `team_members`, `slack_state` — unchanged

---

## Files to modify

| File | Change |
|------|--------|
| `storage/migrations/003_session_transcript.sql` | Rewrite: restructure sessions, add columns to demos, drop 3 tables |
| `storage/migrations/003_session_transcript_pg.sql` | Same for Postgres |
| `storage/__init__.py` | Remove transcript methods, deployment methods, metadata methods; add `get_demo_by_session_id` |
| `storage/sqlite_backend.py` | Rewrite session/demo methods, remove transcript/deployment/metadata methods |
| `storage/supabase_backend.py` | Same |
| `web/app.py` | Inline transcript into session, save deploy info on demo, remove all deployment/metadata calls |
| `scripts/migrate_to_supabase.py` | Update for new schema |

**No frontend changes** — API response shapes stay identical.

---

## Migration SQL

### SQLite (`003_session_transcript.sql`)

```sql
PRAGMA foreign_keys=OFF;

-- Step 1: Add new columns to demos (while old tables still exist for backfill)
ALTER TABLE demos ADD COLUMN session_id TEXT;
ALTER TABLE demos ADD COLUMN deploy_url TEXT;
ALTER TABLE demos ADD COLUMN github_repo TEXT;
ALTER TABLE demos ADD COLUMN health_check_passed INTEGER NOT NULL DEFAULT 0;

-- Step 2: Backfill demos from deployments + sessions
UPDATE demos SET
    deploy_url = (SELECT d.deploy_url FROM deployments d WHERE d.demo_id = demos.id ORDER BY d.id DESC LIMIT 1),
    github_repo = (SELECT d.github_repo FROM deployments d WHERE d.demo_id = demos.id ORDER BY d.id DESC LIMIT 1),
    health_check_passed = COALESCE((SELECT d.health_check_passed FROM deployments d WHERE d.demo_id = demos.id ORDER BY d.id DESC LIMIT 1), 0),
    session_id = (SELECT s.id FROM sessions s WHERE s.demo_id = demos.id LIMIT 1);

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

-- Step 4: Drop obsolete tables
DROP TABLE IF EXISTS demo_metadata;
DROP TABLE IF EXISTS deployments;
DROP TABLE IF EXISTS transcripts;

PRAGMA foreign_keys=ON;

CREATE INDEX IF NOT EXISTS idx_demos_session ON demos(session_id);
```

### Postgres (`003_session_transcript_pg.sql`)

```sql
-- Add new columns to sessions
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'web';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS transcript TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS meeting_link TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS additional_context TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS email TEXT;

-- Add new columns to demos
ALTER TABLE demos ADD COLUMN IF NOT EXISTS session_id TEXT REFERENCES sessions(id);
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

-- Drop old columns and tables
ALTER TABLE sessions DROP COLUMN IF EXISTS demo_id;
ALTER TABLE demos DROP COLUMN IF EXISTS transcript_id;
DROP TABLE IF EXISTS demo_metadata;
DROP TABLE IF EXISTS deployments;
DROP TABLE IF EXISTS transcripts;

DROP INDEX IF EXISTS idx_sessions_demo;
DROP INDEX IF EXISTS idx_deployments_demo;
DROP INDEX IF EXISTS idx_demos_transcript;
DROP INDEX IF EXISTS idx_demo_metadata_demo;

CREATE INDEX IF NOT EXISTS idx_demos_session ON demos(session_id);

INSERT INTO schema_migrations (version, name)
VALUES (3, '003_session_transcript_pg.sql') ON CONFLICT DO NOTHING;
```

---

## `storage/__init__.py` changes

### Remove these abstract methods:
- `save_transcript()`, `get_transcript()`
- `save_deployment()`, `get_latest_deployment()`
- `save_metadata()`, `get_metadata()`

### Add:
```python
@abstractmethod
def get_demo_by_session_id(self, session_id: str) -> dict | None:
    """Return the demo created by a given session, or None."""
```

---

## Backend method changes (both SQLite + Supabase)

### `save_session()` — new columns
Include: `source`, `transcript`, `meeting_link`, `additional_context`, `email`
Remove: `demo_id`

### `get_session()` — no change (SELECT * picks up new columns)

### `list_sessions()` — simplified JOIN
```sql
SELECT s.id, s.source, s.status, s.current_stage, s.mode,
       s.created_at, s.updated_at,
       d.id AS demo_id, d.name AS demo_name,
       d.deploy_url, d.health_check_passed
FROM sessions s
LEFT JOIN demos d ON d.session_id = s.id
ORDER BY s.updated_at DESC
```
Customer `company` comes from `stage_1_understand` JSON (already on session), not from a separate transcript table. For the list view, we can extract it in Python after the query, or just skip it in the list (the demo name is more useful).

### `save_demo()` — new columns
Include: `session_id`, `deploy_url`, `github_repo`, `health_check_passed`
Remove: `transcript_id`

### `list_demos()` — remove deployment JOIN
Deploy fields now on demos directly. Remove the `LEFT JOIN deployments` subquery.
For `company` in list view: JOIN demos → sessions, then extract from `stage_1_understand` JSON. Or: store company on demo directly (simpler — add during demo creation from understand output).

**Decision**: Add `company` as a denormalized field on `demos` table (populated from `stage_1_understand.customer.company` when demo is created). This avoids needing to parse JSON in SQL queries.

→ Add `company TEXT` column to demos table in migration.

### `get_solutions()` — simplify
Remove deployment subquery. `deploy_url` and `health_check_passed` are on demos directly.

### New: `get_demo_by_session_id(session_id)`
```sql
SELECT * FROM demos WHERE session_id = ? LIMIT 1
```

### Remove entirely:
- `save_transcript()`, `get_transcript()`
- `save_deployment()`, `get_latest_deployment()`
- `save_metadata()`, `get_metadata()`

---

## `web/app.py` changes

### `_new_session()` — absorb transcript
```python
def _new_session(transcript_text, mode="auto", email="", additional_context="", source="web"):
    sess_id = _gen_id("sess")
    session = {
        "id": sess_id,
        "source": source,
        "transcript": transcript_text,
        "additional_context": additional_context or None,
        "email": email or None,
        "mode": mode,
        "status": "idle",
        "current_stage": 0,
    }
    _backend.save_session(session)
    return session
```
No transcript record. Returns just the session.

### `/upload` endpoint
`session = _new_session(transcript_text)` — single return value.

### `/run/{session_id}` endpoint
```python
session = _load_session(session_id)
# Transcript content is on the session directly
# No demo lookup — build in-memory
demo = {"id": _gen_id("demo"), "source": session.get("source", "web")}
```

### `_run_pipeline_thread()` — key changes

**Stage 1**: `run_understand(session["transcript"])` instead of `transcript["content"]`

**After Stage 1** (customer enrichment): Currently saves customer info back to transcript. Remove that — customer info lives in `stage_1_understand` JSON on the session.

**Stage 2** (additional context): Read from `session.get("additional_context")` instead of `transcript.get("additional_context")`.

**After deploy success**:
```python
demo["session_id"] = session["id"]
demo["deploy_url"] = live_url
demo["github_repo"] = deploy_result.github_repo
demo["health_check_passed"] = deploy_result.verified
demo["company"] = customer.get("company")  # denormalized for list queries
_backend.save_demo(demo)
```
No `save_deployment()`, no `session["demo_id"]`, no session re-save.

**After deploy failure**: Nothing extra — error is on the session.

**Email**: Read from `session.get("email")`. No `save_metadata` or `get_metadata`.

### `/stream/{session_id}`
Replace `get_latest_deployment(session["demo_id"])` with `_backend.get_demo_by_session_id(session_id)`.

### `/redeploy/{session_id}`
Find demo: `_backend.get_demo_by_session_id(session_id)`.
On success: update demo's `deploy_url`, `github_repo`, `health_check_passed` via `save_demo()`.
On failure: no demo update (was never saved or stays unchanged).

### `GET /session/{session_id}`
Replace `get_latest_deployment` with `get_demo_by_session_id`. Deploy fields come from demo directly.

### `GET /api/demos/{demo_id}`
- Deploy fields already on demo (no `get_latest_deployment` call)
- Transcript fields: load session via `demo["session_id"]`, extract from session
- Session embedding: direct lookup via `_backend.get_session(demo["session_id"])`

### `POST /api/solutions` (manual add)
Include `deploy_url`, `github_repo`, `health_check_passed` directly in demo dict.

### Function signature change
`_run_pipeline_thread(session, demo)` — remove `transcript` parameter (it's on the session).

---

## Updated `demos` table (with `company`)

```sql
demos (
    id, session_id, source, company,
    demo_type, use_case, name, description, keywords, stack, skills_used,
    deploy_url, github_repo, health_check_passed,
    is_reusable, is_active, created_at, updated_at
)
```

Note: `transcript_id` column removed from demos (no more transcripts table).

---

## Verification

1. Delete `data.db`, start app → 4 core tables created (sessions, demos, session_logs + team/slack)
2. Upload transcript → session created with transcript text inline
3. Run pipeline → Stage 1 extracts customer info into `stage_1_understand`
4. Successful deploy → demo created with `deploy_url`, `github_repo`, `session_id`
5. Failed deploy → no demo, error on session
6. Demo Library → shows deployed demos with URLs and status badges
7. Demo detail → transcript content from session, deploy info from demo
8. Redeploy → updates demo's deploy fields
9. Manual add solution → creates demo directly with deploy_url

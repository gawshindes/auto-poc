-- 002_team_pg.sql
-- Move team members from team.json into the database (PostgreSQL)

CREATE TABLE IF NOT EXISTS team_members (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
);

-- ============================================================================
-- 001_init_auth_schema.sql — bootstrap the FastAPI-Users schema on PostgreSQL
--
-- Creates (all idempotent, safe to re-run):
--   * login role    drone_api        (password aligned on every run)
--   * database      drone_navigation (owner: drone_api)
--   * tables        "user", oauth_account, user_settings   (+ indexes)
--
-- The table DDL is generated from server/app/models.py
-- (sqlalchemy CreateTable/CreateIndex with the postgresql dialect), so it is
-- guaranteed to match what the FastAPI app expects. Re-generate after any
-- model change:
--   cd server && python -m migrations.generate_ddl   (see app/models.py header)
--
-- Usage — local Ubuntu desktop (cluster 14/main) or ECS (cluster 16/main):
--   sudo -u postgres psql -v ON_ERROR_STOP=1 \
--        -v app_password='<strong-secret>' -f 001_init_auth_schema.sql
--
-- Notes:
--   * "user" is a reserved word in PostgreSQL — keep it double-quoted.
--   * user_settings.settings gets a '{}'::jsonb default added by hand
--     (the SQLAlchemy model uses an app-side default=dict instead).
--   * user_settings.updated_at is maintained by the app (server_default now(),
--     refreshed on every UPDATE via SQLAlchemy onupdate=func.now()).
-- ============================================================================

-- ─── 1. Login role (idempotent; password aligned on every run) ──────────────
-- psql does NOT substitute :variables inside DO $$ ... $$ dollar-quoting,
-- so role bootstrap uses SELECT ... \gexec instead.
SELECT 'CREATE ROLE drone_api LOGIN PASSWORD ' || quote_literal(:'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'drone_api')\gexec
SELECT 'ALTER ROLE drone_api WITH LOGIN PASSWORD ' || quote_literal(:'app_password')\gexec

-- ─── 2. Database (idempotent) ───────────────────────────────────────────────
SELECT 'CREATE DATABASE drone_navigation OWNER drone_api'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'drone_navigation')\gexec

\connect drone_navigation

-- ─── 3. Tables (DDL generated from server/app/models.py) ────────────────────
CREATE TABLE IF NOT EXISTS "user" (
    display_name VARCHAR(100),
    id UUID NOT NULL,
    email VARCHAR(320) NOT NULL,
    hashed_password VARCHAR(1024) NOT NULL,
    is_active BOOLEAN NOT NULL,
    is_superuser BOOLEAN NOT NULL,
    is_verified BOOLEAN NOT NULL,
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_user_email ON "user" (email);

CREATE TABLE IF NOT EXISTS oauth_account (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    oauth_name VARCHAR(100) NOT NULL,
    access_token VARCHAR(1024) NOT NULL,
    expires_at INTEGER,
    refresh_token VARCHAR(1024),
    account_id VARCHAR(320) NOT NULL,
    account_email VARCHAR(320) NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES "user" (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_oauth_account_account_id ON oauth_account (account_id);
CREATE INDEX IF NOT EXISTS ix_oauth_account_oauth_name ON oauth_account (oauth_name);

-- Option A: one settings document per user (single-row JSONB).
-- FK + ON DELETE CASCADE mirrors oauth_account: deleting a user wipes prefs.
CREATE TABLE IF NOT EXISTS user_settings (
    user_id UUID NOT NULL,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (user_id),
    FOREIGN KEY (user_id) REFERENCES "user" (id) ON DELETE CASCADE
);

-- ─── 4. Privileges for the app role ─────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO drone_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO drone_api;

-- ─── 5. Verification output ─────────────────────────────────────────────────
SELECT schemaname, tablename, tableowner
FROM pg_tables
WHERE tablename IN ('user', 'oauth_account', 'user_settings')
ORDER BY tablename;

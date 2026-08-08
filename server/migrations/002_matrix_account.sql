-- ============================================================================
-- 002_matrix_account.sql — add the hidden-Synapse-account mapping table
--
-- Creates (idempotent, safe to re-run):
--   * table  matrix_account  (user_id PK FK->user CASCADE, mxid unique-index)
--
-- DDL generated from server/app/models.py (see migrations/generate_ddl.py).
-- Run AFTER 001_init_auth_schema.sql (needs the "user" table + drone_api role).
--
-- Usage — local (cluster on 5433) or ECS (5432):
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d drone_navigation \
--        -f 002_matrix_account.sql
--   # local user-owned cluster instead:
--   psql -h 127.0.0.1 -p 5433 -U robot -d drone_navigation \
--        -v ON_ERROR_STOP=1 -f 002_matrix_account.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS matrix_account (
        user_id UUID NOT NULL,
        mxid VARCHAR(255) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (user_id),
        FOREIGN KEY(user_id) REFERENCES "user" (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_matrix_account_mxid ON matrix_account (mxid);

-- Same privileges as the auth tables (role created by 001).
GRANT SELECT, INSERT, UPDATE, DELETE ON matrix_account TO drone_api;

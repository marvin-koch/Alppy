-- Runs once, automatically, the first time the `postgres` container's data
-- volume is initialised (see docker-compose.yml: mounted read-only into
-- /docker-entrypoint-initdb.d/). It prepares the extension the app's tables
-- depend on and the ROLES they are read through; alembic
-- (apps/api/alembic) owns every table.
--
-- pgvector backs SourceChunk.embedding (vector(1024) — see
-- alppy.core.config.Settings.embedding_dim and ADR 0001). The initial
-- migration (apps/api/alembic/versions/0001_initial.py) also runs
-- `CREATE EXTENSION IF NOT EXISTS vector` itself, so this file is not the
-- only place it happens — but a schema created straight from `psql` (a
-- restore, a manual `createdb`, a second database in the same cluster)
-- should not have to know that.
CREATE EXTENSION IF NOT EXISTS vector;

-- --------------------------------------------------------------------------
-- Two roles, because tenant isolation stopped being only application-level
-- (D84). Row-level security is enforced against `app_role`; it is not
-- enforced against whoever owns the tables, so the two MUST be different
-- roles or the policies are decoration.
--
--   POSTGRES_USER (default `alppy`)  owns the schema. Alembic and the
--       cross-school CLI (seed, backfill-events, purge-prompt-logs) connect
--       as this one. It carries BYPASSRLS *explicitly*: every policy is
--       written FORCE, which applies to the owner too, and a migration that
--       cannot see the rows it is rewriting is a migration that silently
--       rewrites nothing.
--
--   alppy_app                        the API and the worker. No DDL, no
--       BYPASSRLS, and every read it makes is filtered by
--       `app.current_school_id` (apps/api/alppy/db/tenancy.py). With that GUC
--       unset it sees NOTHING, which is the intended default.
--
-- The password here is a development default, like every other credential in
-- this repo's compose file. A real deployment creates `alppy_app` by hand with
-- its own password; `Settings._refuse_unsafe_deployment` refuses to boot a
-- staging or production API whose DSN names the owning role, so forgetting
-- this step fails loudly at startup rather than quietly at the first query.
-- --------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alppy_app') THEN
        CREATE ROLE alppy_app LOGIN PASSWORD 'alppy_app';
    END IF;
END
$$;

ALTER ROLE alppy_app NOBYPASSRLS NOCREATEDB NOCREATEROLE NOSUPERUSER;

-- Bounds on a runaway query, set on the ROLE rather than in the DSN: a
-- connection string is edited by whoever is debugging a timeout, and the
-- bound that protects the database is the one they cannot drop by accident.
-- The worker legitimately runs longer than the API (a scan pipeline, an
-- embedding write) and raises its own ceiling per connection — see
-- ALPPY_DB_STATEMENT_TIMEOUT_MS.
ALTER ROLE alppy_app SET statement_timeout = '15s';
ALTER ROLE alppy_app SET idle_in_transaction_session_timeout = '30s';

-- The owner gets no statement_timeout: a migration rewriting a large table is
-- meant to take as long as it takes.
ALTER ROLE CURRENT_USER BYPASSRLS;

-- GRANT ... ON DATABASE takes a literal name, so the current one is
-- interpolated rather than spelled.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO alppy_app', current_database());
END
$$;
GRANT USAGE ON SCHEMA public TO alppy_app;

-- DML only. Notably absent: CREATE, TRUNCATE, REFERENCES — and any grant at
-- all on future *routines* beyond the one the worker needs (granted by the
-- migration that defines it).
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO alppy_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO alppy_app;

-- The tables alembic has already created, if this file is being replayed onto
-- a populated database rather than an empty one.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO alppy_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO alppy_app;

-- Runs once, on first container start (docker-entrypoint-initdb.d), connected to the dev database
-- as the migrator superuser. For a non-Docker PostgreSQL install, run scripts/init_local_db.ps1,
-- which executes the same statements with psql.
--
-- Roles are cluster-wide. Table-level GRANTs live in sql/grants.sql and are applied by the
-- Alembic migration after the tables exist (they must be re-applied per database).

\set app_pw      `echo "$LEA_APP_PASSWORD"`
\set analytics_pw `echo "$LEA_ANALYTICS_PASSWORD"`
\set evaluation_pw `echo "$LEA_EVALUATION_PASSWORD"`

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lea_app') THEN
        CREATE ROLE lea_app LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lea_analytics_ro') THEN
        CREATE ROLE lea_analytics_ro LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lea_evaluation') THEN
        CREATE ROLE lea_evaluation LOGIN;
    END IF;
END
$$;

ALTER ROLE lea_app          PASSWORD :'app_pw';
ALTER ROLE lea_analytics_ro PASSWORD :'analytics_pw';
ALTER ROLE lea_evaluation   PASSWORD :'evaluation_pw';

-- Nobody but the migrator may create objects in public.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

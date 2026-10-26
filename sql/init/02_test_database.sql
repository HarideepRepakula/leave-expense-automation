-- Runs once, on first container start. Creates the isolated test database (spec section 23)
-- and enables btree_gist there so the test-only EXCLUDE constraint (amendment A3) can be added.

\set test_db `echo "$LEA_TEST_DB"`

SELECT 'CREATE DATABASE ' || quote_ident(:'test_db') || ' OWNER lea_migrator'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'test_db')
\gexec

\connect :test_db

CREATE EXTENSION IF NOT EXISTS btree_gist;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

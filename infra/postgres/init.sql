-- NexusFlow PostgreSQL initialization script
-- Runs once when the container is first created.
-- DO NOT use this for schema changes — use Alembic migrations.

-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- Create application role with limited privileges
-- (Docker compose creates the nexusflow superuser — this adds a read-only role for monitoring)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'nexusflow_readonly') THEN
        CREATE ROLE nexusflow_readonly LOGIN PASSWORD 'readonly_dev';
        GRANT CONNECT ON DATABASE nexusflow TO nexusflow_readonly;
    END IF;
END
$$;

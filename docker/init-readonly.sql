-- Runs once when the Postgres volume is first created.
-- The app executes model-generated SQL as this role, so even a query that slipped past the
-- SQL guard could not modify data.
CREATE ROLE app_readonly LOGIN PASSWORD 'readonly';
GRANT CONNECT ON DATABASE shop TO app_readonly;
GRANT USAGE ON SCHEMA public TO app_readonly;
-- Tables are created later by `python -m app.seed` (as role "app"); grant on those automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE app IN SCHEMA public GRANT SELECT ON TABLES TO app_readonly;
ALTER ROLE app_readonly SET statement_timeout = '10s';

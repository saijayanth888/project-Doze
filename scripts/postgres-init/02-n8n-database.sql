-- Dedicated database for n8n (same owner as POSTGRES_USER).
-- n8n connects with DB_POSTGRESDB_USER / DB_POSTGRESDB_PASSWORD matching
-- the modelforge superuser — avoids a second DB password.

SELECT format(
    'CREATE DATABASE %I OWNER %I',
    'n8n',
    current_user
)
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n')
\gexec

\c n8n

GRANT ALL ON SCHEMA public TO CURRENT_USER;
ALTER SCHEMA public OWNER TO CURRENT_USER;

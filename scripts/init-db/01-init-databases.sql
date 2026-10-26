-- =========================================================================
-- KeelStream PostgreSQL Multi-Database Initialization
-- =========================================================================
-- Automatically executed upon container first boot via /docker-entrypoint-initdb.d

-- Create logical databases for subsystems if they do not exist
SELECT 'CREATE DATABASE db_keycloak'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'db_keycloak')\gexec

SELECT 'CREATE DATABASE db_frappe'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'db_frappe')\gexec

SELECT 'CREATE DATABASE db_n8n'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'db_n8n')\gexec

-- Grant full privileges to main application user
GRANT ALL PRIVILEGES ON DATABASE db_keycloak TO keelstream;
GRANT ALL PRIVILEGES ON DATABASE db_frappe TO keelstream;
GRANT ALL PRIVILEGES ON DATABASE db_n8n TO keelstream;

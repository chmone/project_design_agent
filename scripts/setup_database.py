# scripts/setup_database.py
"""
Database setup script for Design Research Agent v1.2
Creates all required tables and indexes for Phase 1.1
"""

import asyncio
import os
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg
from shared.logging import logger, setup_logging

async def create_database_if_not_exists(admin_url: str, database_name: str):
    """Create database if it doesn't exist"""
    try:
        # Connect to postgres database to create our database
        admin_conn = await asyncpg.connect(admin_url)
        
        # Check if database exists
        db_exists = await admin_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", database_name
        )
        
        if not db_exists:
            await admin_conn.execute(f'CREATE DATABASE "{database_name}"')
            logger.info(f"Created database: {database_name}")
        else:
            logger.info(f"Database already exists: {database_name}")
        
        await admin_conn.close()
        
    except Exception as e:
        logger.error(f"Failed to create database: {e}")
        raise

async def setup_tables(database_url: str):
    """Create all required tables and indexes"""
    
    conn = await asyncpg.connect(database_url)
    
    try:
        logger.info("Creating database tables...")
        
        # Task queue table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS task_queue (
                task_id VARCHAR(36) PRIMARY KEY,
                status VARCHAR(20) NOT NULL,
                project_data JSONB NOT NULL,
                agent_outputs JSONB DEFAULT '{}',
                quality_scores JSONB DEFAULT '{}',
                token_usage JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                error_message TEXT
            )
        """)
        logger.info("✓ Created task_queue table")

        # Approval requests table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS approval_requests (
                id SERIAL PRIMARY KEY,
                task_id VARCHAR(36) REFERENCES task_queue(task_id) ON DELETE CASCADE,
                phase VARCHAR(50) NOT NULL,
                agent_output JSONB NOT NULL,
                recommendation TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP,
                reviewer_feedback TEXT,
                expires_at TIMESTAMP NOT NULL,
                quality_score FLOAT
            )
        """)
        logger.info("✓ Created approval_requests table")

        # Circuit breaker state table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS circuit_breaker_state (
                agent_name VARCHAR(100) PRIMARY KEY,
                state VARCHAR(20) NOT NULL,
                failure_count INTEGER DEFAULT 0,
                last_failure_time TIMESTAMP,
                success_count INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created circuit_breaker_state table")

        # Token budget tracking table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS token_budgets (
                task_id VARCHAR(36) PRIMARY KEY REFERENCES task_queue(task_id) ON DELETE CASCADE,
                total_budget INTEGER NOT NULL,
                consumed_tokens INTEGER DEFAULT 0,
                phase_allocations JSONB DEFAULT '{}',
                usage_by_phase JSONB DEFAULT '{}',
                budget_exceeded BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created token_budgets table")

        # Quality approvals analytics table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS quality_approvals (
                id SERIAL PRIMARY KEY,
                task_id VARCHAR(36) REFERENCES task_queue(task_id) ON DELETE CASCADE,
                phase VARCHAR(50) NOT NULL,
                quality_data JSONB NOT NULL,
                approval_type VARCHAR(20) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✓ Created quality_approvals table")

        # Create indexes for performance
        logger.info("Creating database indexes...")
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_status ON task_queue(status)
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_created ON task_queue(created_at)
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_expires ON task_queue(expires_at) 
            WHERE expires_at IS NOT NULL
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_approval_task ON approval_requests(task_id)
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_approval_status_expires ON approval_requests(status, expires_at)
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_budget_task ON token_budgets(task_id)
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_quality_approvals_task ON quality_approvals(task_id)
        """)
        
        logger.info("✓ Created all indexes")
        
        # Add some constraints for data integrity
        logger.info("Adding data constraints...")
        
        await conn.execute("""
            ALTER TABLE task_queue 
            ADD CONSTRAINT IF NOT EXISTS chk_task_status 
            CHECK (status IN ('pending', 'running', 'awaiting_approval', 'approved', 'completed', 'failed', 'expired'))
        """)
        
        await conn.execute("""
            ALTER TABLE approval_requests 
            ADD CONSTRAINT IF NOT EXISTS chk_approval_status 
            CHECK (status IN ('pending', 'approved', 'rejected', 'expired'))
        """)
        
        await conn.execute("""
            ALTER TABLE circuit_breaker_state 
            ADD CONSTRAINT IF NOT EXISTS chk_circuit_state 
            CHECK (state IN ('closed', 'open', 'half_open'))
        """)
        
        await conn.execute("""
            ALTER TABLE token_budgets 
            ADD CONSTRAINT IF NOT EXISTS chk_positive_budget 
            CHECK (total_budget > 0 AND consumed_tokens >= 0)
        """)
        
        logger.info("✓ Added data constraints")
        
        # Create a function to update timestamps automatically
        await conn.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql'
        """)
        
        # Add triggers for automatic timestamp updates
        await conn.execute("""
            DROP TRIGGER IF EXISTS update_task_queue_updated_at ON task_queue;
            CREATE TRIGGER update_task_queue_updated_at
                BEFORE UPDATE ON task_queue
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column()
        """)
        
        await conn.execute("""
            DROP TRIGGER IF EXISTS update_token_budgets_updated_at ON token_budgets;
            CREATE TRIGGER update_token_budgets_updated_at
                BEFORE UPDATE ON token_budgets
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column()
        """)
        
        logger.info("✓ Created automatic timestamp triggers")
        
        logger.info("Database setup completed successfully!")
        
    except Exception as e:
        logger.error(f"Failed to setup tables: {e}")
        raise
    finally:
        await conn.close()

async def verify_setup(database_url: str):
    """Verify the database setup is working correctly"""
    
    conn = await asyncpg.connect(database_url)
    
    try:
        logger.info("Verifying database setup...")
        
        # Check all tables exist
        tables = await conn.fetch("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """)
        
        expected_tables = {
            'approval_requests',
            'circuit_breaker_state', 
            'quality_approvals',
            'task_queue',
            'token_budgets'
        }
        
        found_tables = {row['table_name'] for row in tables}
        
        if not expected_tables.issubset(found_tables):
            missing = expected_tables - found_tables
            raise Exception(f"Missing tables: {missing}")
        
        logger.info(f"✓ All {len(expected_tables)} tables found")
        
        # Check indexes exist
        indexes = await conn.fetch("""
            SELECT indexname FROM pg_indexes 
            WHERE schemaname = 'public' 
            AND indexname LIKE 'idx_%'
        """)
        
        if len(indexes) < 6:  # We created 7 indexes
            logger.warning(f"Expected at least 6 indexes, found {len(indexes)}")
        else:
            logger.info(f"✓ Found {len(indexes)} indexes")
        
        # Test basic functionality
        test_task_id = 'test-setup-verification'
        
        # Insert test record
        await conn.execute("""
            INSERT INTO task_queue (task_id, status, project_data) 
            VALUES ($1, 'pending', '{"test": true}')
            ON CONFLICT (task_id) DO NOTHING
        """, test_task_id)
        
        # Query test record
        test_record = await conn.fetchrow("""
            SELECT * FROM task_queue WHERE task_id = $1
        """, test_task_id)
        
        if not test_record:
            raise Exception("Failed to insert/query test record")
        
        # Clean up test record
        await conn.execute("""
            DELETE FROM task_queue WHERE task_id = $1
        """, test_task_id)
        
        logger.info("✓ Basic database operations working")
        logger.info("Database verification completed successfully!")
        
    except Exception as e:
        logger.error(f"Database verification failed: {e}")
        raise
    finally:
        await conn.close()

async def main():
    """Main setup function"""
    
    # Setup logging
    setup_logging(level="INFO", json_logs=False)
    
    logger.info("Starting Design Research Agent v1.2 database setup")
    
    # Get database configuration from environment
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        # Default local development setup
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432") 
        user = os.getenv("DB_USER", "postgres")
        password = os.getenv("DB_PASSWORD", "postgres")
        database = os.getenv("DB_NAME", "design_agent")
        
        database_url = f"postgresql://{user}:{password}@{host}:{port}/{database}"
        admin_url = f"postgresql://{user}:{password}@{host}:{port}/postgres"
        
        logger.info(f"Using database: {host}:{port}/{database}")
        
        # Create database if it doesn't exist
        try:
            await create_database_if_not_exists(admin_url, database)
        except Exception as e:
            logger.warning(f"Could not create database (may already exist): {e}")
    
    try:
        # Setup tables and indexes
        await setup_tables(database_url)
        
        # Verify setup
        await verify_setup(database_url)
        
        logger.info("🎉 Database setup completed successfully!")
        logger.info("You can now start the Design Research Agent application")
        
    except Exception as e:
        logger.error(f"Database setup failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
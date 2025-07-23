# infrastructure/storage/persistent_task_queue.py
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import asyncpg
from domain.models.task_state import TaskStatus, ApprovalStatus, TaskStateSnapshot, ApprovalRequest, TokenBudgetState
from domain.models.agent_context import AgentOutput
from shared.logging import logger

class PersistentTaskQueue:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.connection_pool: Optional[asyncpg.Pool] = None

    async def initialize(self):
        """Initialize database connection pool and create tables"""
        self.connection_pool = await asyncpg.create_pool(
            self.database_url,
            min_size=5,
            max_size=20,
            command_timeout=60
        )
        await self._create_tables()
        await self._create_indexes()

    async def _create_tables(self):
        """Create all required database tables"""
        async with self.connection_pool.acquire() as conn:
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

            # Approval requests table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_requests (
                    id SERIAL PRIMARY KEY,
                    task_id VARCHAR(36) REFERENCES task_queue(task_id),
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

            # Token budget tracking table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS token_budgets (
                    task_id VARCHAR(36) PRIMARY KEY REFERENCES task_queue(task_id),
                    total_budget INTEGER NOT NULL,
                    consumed_tokens INTEGER DEFAULT 0,
                    phase_allocations JSONB DEFAULT '{}',
                    usage_by_phase JSONB DEFAULT '{}',
                    budget_exceeded BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Quality approvals analytics table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS quality_approvals (
                    id SERIAL PRIMARY KEY,
                    task_id VARCHAR(36) REFERENCES task_queue(task_id),
                    phase VARCHAR(50) NOT NULL,
                    quality_data JSONB NOT NULL,
                    approval_type VARCHAR(20) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    async def _create_indexes(self):
        """Create database indexes for performance"""
        async with self.connection_pool.acquire() as conn:
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_task_status ON task_queue(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_task_created ON task_queue(created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_task ON approval_requests(task_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_token_budget_task ON token_budgets(task_id)")

    async def enqueue_task(self, task_id: str, project_data: Dict[str, Any], 
                         expires_hours: int = 48) -> None:
        """Add new task to the queue"""
        expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
        
        async with self.connection_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO task_queue (task_id, status, project_data, expires_at)
                VALUES ($1, $2, $3, $4)
            """, task_id, TaskStatus.PENDING.value, json.dumps(project_data), expires_at)
            
        logger.info("Task enqueued", task_id=task_id, expires_at=expires_at.isoformat())

    async def update_task_status(self, task_id: str, status: TaskStatus, 
                               agent_output: Optional[AgentOutput] = None,
                               error_message: Optional[str] = None) -> None:
        """Update task status with optional agent output"""
        async with self.connection_pool.acquire() as conn:
            if agent_output:
                await conn.execute("""
                    UPDATE task_queue 
                    SET status = $2, 
                        agent_outputs = agent_outputs || $3,
                        token_usage = token_usage || $4,
                        quality_scores = quality_scores || $5,
                        updated_at = CURRENT_TIMESTAMP,
                        error_message = $6
                    WHERE task_id = $1
                """, task_id, status.value, 
                    json.dumps({f"{status.value}_output": agent_output.data}),
                    json.dumps({f"{status.value}_tokens": agent_output.tokens_used}),
                    json.dumps({f"{status.value}_quality": agent_output.confidence_score}),
                    error_message)
            else:
                await conn.execute("""
                    UPDATE task_queue 
                    SET status = $2, updated_at = CURRENT_TIMESTAMP, error_message = $3
                    WHERE task_id = $1
                """, task_id, status.value, error_message)
                
        logger.info("Task status updated", task_id=task_id, status=status.value, error=error_message)

    async def create_approval_request(self, task_id: str, phase: str, 
                                    agent_output: AgentOutput, recommendation: str,
                                    expires_hours: int = 24) -> int:
        """Create human approval request"""
        expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
        
        async with self.connection_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO approval_requests 
                (task_id, phase, agent_output, recommendation, expires_at, quality_score)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, task_id, phase, json.dumps(agent_output.data), recommendation, 
                expires_at, agent_output.confidence_score)
            
            approval_id = row['id']
            logger.info("Approval request created", 
                       task_id=task_id, 
                       phase=phase, 
                       approval_id=approval_id,
                       expires_at=expires_at.isoformat())
            return approval_id

    async def get_task(self, task_id: str) -> Optional[TaskStateSnapshot]:
        """Get complete task state"""
        async with self.connection_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM task_queue WHERE task_id = $1
            """, task_id)
            
            if row:
                return TaskStateSnapshot(
                    task_id=row["task_id"],
                    status=TaskStatus(row["status"]),
                    project_data=json.loads(row["project_data"]),
                    agent_outputs=json.loads(row["agent_outputs"]),
                    quality_scores=json.loads(row["quality_scores"]),
                    token_usage=json.loads(row["token_usage"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    expires_at=row["expires_at"],
                    error_message=row["error_message"]
                )
            return None

    async def get_pending_approvals(self, task_id: str) -> List[ApprovalRequest]:
        """Get all pending approval requests for a task"""
        async with self.connection_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM approval_requests 
                WHERE task_id = $1 AND status = 'pending' AND expires_at > CURRENT_TIMESTAMP
                ORDER BY submitted_at
            """, task_id)
            
            return [
                ApprovalRequest(
                    approval_id=row['id'],
                    task_id=row['task_id'],
                    phase=row['phase'],
                    agent_output=json.loads(row['agent_output']),
                    recommendation=row['recommendation'],
                    status=ApprovalStatus(row['status']),
                    submitted_at=row['submitted_at'],
                    expires_at=row['expires_at'],
                    reviewed_at=row['reviewed_at'],
                    reviewer_feedback=row['reviewer_feedback'],
                    quality_score=row['quality_score']
                )
                for row in rows
            ]

    async def update_approval_status(self, approval_id: int, status: ApprovalStatus,
                                   feedback: Optional[str] = None) -> bool:
        """Update approval request status"""
        async with self.connection_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE approval_requests 
                SET status = $2, reviewed_at = CURRENT_TIMESTAMP, reviewer_feedback = $3
                WHERE id = $1 AND status = 'pending'
            """, approval_id, status.value, feedback)
            
            updated = int(result.split()[-1]) > 0
            if updated:
                logger.info("Approval status updated", 
                           approval_id=approval_id, 
                           status=status.value, 
                           feedback=feedback)
            return updated

    async def cleanup_expired_tasks(self) -> int:
        """Clean up expired tasks and approvals"""
        async with self.connection_pool.acquire() as conn:
            # Update expired tasks
            task_result = await conn.execute("""
                UPDATE task_queue SET status = 'expired' 
                WHERE status IN ('pending', 'awaiting_approval') 
                AND expires_at < CURRENT_TIMESTAMP
            """)
            
            # Update expired approvals
            approval_result = await conn.execute("""
                UPDATE approval_requests SET status = 'expired'
                WHERE status = 'pending' AND expires_at < CURRENT_TIMESTAMP
            """)
            
            expired_tasks = int(task_result.split()[-1])
            expired_approvals = int(approval_result.split()[-1])
            
            if expired_tasks > 0 or expired_approvals > 0:
                logger.info("Expired items cleaned up", 
                           expired_tasks=expired_tasks, 
                           expired_approvals=expired_approvals)
            
            return expired_tasks

    async def get_task_list(self, status: Optional[TaskStatus] = None, 
                           limit: int = 100) -> List[TaskStateSnapshot]:
        """Get list of tasks with optional status filter"""
        async with self.connection_pool.acquire() as conn:
            if status:
                rows = await conn.fetch("""
                    SELECT * FROM task_queue 
                    WHERE status = $1 
                    ORDER BY created_at DESC 
                    LIMIT $2
                """, status.value, limit)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM task_queue 
                    ORDER BY created_at DESC 
                    LIMIT $1
                """, limit)
            
            return [
                TaskStateSnapshot(
                    task_id=row["task_id"],
                    status=TaskStatus(row["status"]),
                    project_data=json.loads(row["project_data"]),
                    agent_outputs=json.loads(row["agent_outputs"]),
                    quality_scores=json.loads(row["quality_scores"]),
                    token_usage=json.loads(row["token_usage"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    expires_at=row["expires_at"],
                    error_message=row["error_message"]
                )
                for row in rows
            ]

    async def close(self):
        """Close database connection pool"""
        if self.connection_pool:
            await self.connection_pool.close()
            logger.info("Database connection pool closed")
# infrastructure/resilience/circuit_breaker.py
from enum import Enum
from datetime import datetime, timedelta
from typing import Callable, Any, Optional, Dict
import asyncio
from dataclasses import dataclass
import asyncpg
import json
from shared.logging import logger

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: timedelta = timedelta(minutes=2)
    success_threshold: int = 3
    timeout_seconds: float = 30.0

class CircuitBreakerRegistry:
    """Global registry for all circuit breakers with persistence"""
    
    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool
        self.breakers: Dict[str, 'CircuitBreaker'] = {}

    async def get_breaker(self, agent_name: str, config: CircuitBreakerConfig) -> 'CircuitBreaker':
        if agent_name not in self.breakers:
            breaker = CircuitBreaker(agent_name, config, self.db_pool)
            await breaker.initialize()
            self.breakers[agent_name] = breaker
        return self.breakers[agent_name]

    async def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        status = {}
        for name, breaker in self.breakers.items():
            status[name] = await breaker.get_status()
        return status

class CircuitBreaker:
    def __init__(self, agent_name: str, config: CircuitBreakerConfig, db_pool: asyncpg.Pool):
        self.agent_name = agent_name
        self.config = config
        self.db_pool = db_pool
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.success_count = 0

    async def initialize(self):
        """Load state from database"""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT state, failure_count, last_failure_time, success_count
                    FROM circuit_breaker_state 
                    WHERE agent_name = $1
                """, self.agent_name)
                
                if row:
                    self.state = CircuitState(row['state'])
                    self.failure_count = row['failure_count']
                    self.last_failure_time = row['last_failure_time']
                    self.success_count = row['success_count']
        except Exception as e:
            logger.warning(f"Failed to load circuit breaker state for {self.agent_name}: {e}")

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        if self.state == CircuitState.OPEN:
            if await self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                await self._persist_state()
            else:
                raise CircuitOpenError(f"Circuit breaker for {self.agent_name} is OPEN")

        try:
            result = await asyncio.wait_for(
                func(*args, **kwargs), 
                timeout=self.config.timeout_seconds
            )
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise e

    async def _should_attempt_reset(self) -> bool:
        if not self.last_failure_time:
            return False
        return datetime.utcnow() - self.last_failure_time > self.config.recovery_timeout

    async def _on_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                await self._persist_state()
        elif self.state == CircuitState.CLOSED and self.failure_count > 0:
            self.failure_count = 0
            await self._persist_state()

    async def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            
        await self._persist_state()

    async def _persist_state(self):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO circuit_breaker_state 
                    (agent_name, state, failure_count, last_failure_time, success_count, updated_at)
                    VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                    ON CONFLICT (agent_name) DO UPDATE SET
                    state = $2, failure_count = $3, last_failure_time = $4, 
                    success_count = $5, updated_at = CURRENT_TIMESTAMP
                """, self.agent_name, self.state.value, self.failure_count, 
                    self.last_failure_time, self.success_count)
        except Exception as e:
            logger.error(f"Failed to persist circuit breaker state for {self.agent_name}: {e}")

    async def get_status(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "success_count": self.success_count
        }

    async def force_open(self):
        """Manually open circuit breaker for testing or emergency"""
        self.state = CircuitState.OPEN
        self.last_failure_time = datetime.utcnow()
        await self._persist_state()

    async def force_close(self):
        """Manually close circuit breaker for testing or recovery"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        await self._persist_state()

class CircuitOpenError(Exception):
    pass
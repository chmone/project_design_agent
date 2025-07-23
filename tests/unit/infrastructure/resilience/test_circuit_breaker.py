# tests/unit/infrastructure/resilience/test_circuit_breaker.py
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from infrastructure.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitBreakerConfig,
    CircuitState,
    CircuitOpenError
)

@pytest.fixture
def mock_db_pool():
    """Mock database pool for testing"""
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.acquire.return_value.__aexit__.return_value = None
    
    # Mock fetchrow to return None (no existing state)
    conn.fetchrow.return_value = None
    conn.execute.return_value = None
    
    return pool

@pytest.fixture
def circuit_config():
    """Default circuit breaker configuration for testing"""
    return CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=timedelta(seconds=5),
        success_threshold=2,
        timeout_seconds=1.0
    )

class TestCircuitBreaker:
    """Test circuit breaker functionality"""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_initialization(self, mock_db_pool, circuit_config):
        """Test circuit breaker initialization"""
        breaker = CircuitBreaker("test_agent", circuit_config, mock_db_pool)
        
        await breaker.initialize()
        
        assert breaker.agent_name == "test_agent"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0

    @pytest.mark.asyncio
    async def test_successful_call(self, mock_db_pool, circuit_config):
        """Test successful function call through circuit breaker"""
        breaker = CircuitBreaker("test_agent", circuit_config, mock_db_pool)
        await breaker.initialize()
        
        async def success_func():
            return "success"
        
        result = await breaker.call(success_func)
        
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_failure_tracking(self, mock_db_pool, circuit_config):
        """Test failure tracking and circuit opening"""
        breaker = CircuitBreaker("test_agent", circuit_config, mock_db_pool)
        await breaker.initialize()
        
        async def failing_func():
            raise Exception("Test failure")
        
        # Should accumulate failures without opening initially
        for i in range(circuit_config.failure_threshold - 1):
            with pytest.raises(Exception):
                await breaker.call(failing_func)
            assert breaker.state == CircuitState.CLOSED
            assert breaker.failure_count == i + 1
        
        # Final failure should open the circuit
        with pytest.raises(Exception):
            await breaker.call(failing_func)
        
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == circuit_config.failure_threshold

    @pytest.mark.asyncio
    async def test_circuit_open_behavior(self, mock_db_pool, circuit_config):
        """Test behavior when circuit is open"""
        breaker = CircuitBreaker("test_agent", circuit_config, mock_db_pool)
        await breaker.initialize()
        
        # Force circuit open
        breaker.state = CircuitState.OPEN
        breaker.last_failure_time = datetime.utcnow()
        
        async def any_func():
            return "should not execute"
        
        # Calls should be rejected immediately
        with pytest.raises(CircuitOpenError):
            await breaker.call(any_func)

    @pytest.mark.asyncio
    async def test_circuit_recovery(self, mock_db_pool, circuit_config):
        """Test circuit recovery from open to half-open to closed"""
        breaker = CircuitBreaker("test_agent", circuit_config, mock_db_pool)
        await breaker.initialize()
        
        # Force circuit open with old failure time
        breaker.state = CircuitState.OPEN
        breaker.last_failure_time = datetime.utcnow() - circuit_config.recovery_timeout - timedelta(seconds=1)
        
        async def success_func():
            return "success"
        
        # Should transition to half-open and succeed
        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.success_count == 1
        
        # Additional successes should close the circuit
        for i in range(circuit_config.success_threshold - 1):
            await breaker.call(success_func)
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_timeout_handling(self, mock_db_pool):
        """Test function timeout handling"""
        config = CircuitBreakerConfig(timeout_seconds=0.1)  # Very short timeout
        breaker = CircuitBreaker("test_agent", config, mock_db_pool)
        await breaker.initialize()
        
        async def slow_func():
            await asyncio.sleep(0.2)  # Longer than timeout
            return "should timeout"
        
        with pytest.raises(asyncio.TimeoutError):
            await breaker.call(slow_func)
        
        assert breaker.failure_count == 1

    @pytest.mark.asyncio
    async def test_half_open_failure(self, mock_db_pool, circuit_config):
        """Test failure in half-open state"""
        breaker = CircuitBreaker("test_agent", circuit_config, mock_db_pool)
        await breaker.initialize()
        
        # Set to half-open state
        breaker.state = CircuitState.HALF_OPEN
        breaker.success_count = 1
        
        async def failing_func():
            raise Exception("Half-open failure")
        
        with pytest.raises(Exception):
            await breaker.call(failing_func)
        
        # Should transition back to open
        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_status_reporting(self, mock_db_pool, circuit_config):
        """Test circuit breaker status reporting"""
        breaker = CircuitBreaker("test_agent", circuit_config, mock_db_pool)
        await breaker.initialize()
        
        status = await breaker.get_status()
        
        assert status["state"] == CircuitState.CLOSED.value
        assert status["failure_count"] == 0
        assert status["success_count"] == 0
        assert status["last_failure_time"] is None

    @pytest.mark.asyncio
    async def test_manual_circuit_control(self, mock_db_pool, circuit_config):
        """Test manual circuit breaker control"""
        breaker = CircuitBreaker("test_agent", circuit_config, mock_db_pool)
        await breaker.initialize()
        
        # Test force open
        await breaker.force_open()
        assert breaker.state == CircuitState.OPEN
        assert breaker.last_failure_time is not None
        
        # Test force close
        await breaker.force_close()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0

class TestCircuitBreakerRegistry:
    """Test circuit breaker registry functionality"""
    
    @pytest.mark.asyncio
    async def test_registry_breaker_creation(self, mock_db_pool, circuit_config):
        """Test circuit breaker creation through registry"""
        registry = CircuitBreakerRegistry(mock_db_pool)
        
        breaker1 = await registry.get_breaker("agent1", circuit_config)
        breaker2 = await registry.get_breaker("agent2", circuit_config)
        
        assert breaker1.agent_name == "agent1"
        assert breaker2.agent_name == "agent2"
        assert breaker1 is not breaker2

    @pytest.mark.asyncio
    async def test_registry_breaker_reuse(self, mock_db_pool, circuit_config):
        """Test that registry reuses existing breakers"""
        registry = CircuitBreakerRegistry(mock_db_pool)
        
        breaker1 = await registry.get_breaker("agent1", circuit_config)
        breaker2 = await registry.get_breaker("agent1", circuit_config)
        
        assert breaker1 is breaker2

    @pytest.mark.asyncio
    async def test_registry_status_collection(self, mock_db_pool, circuit_config):
        """Test collecting status from all registered breakers"""
        registry = CircuitBreakerRegistry(mock_db_pool)
        
        await registry.get_breaker("agent1", circuit_config)
        await registry.get_breaker("agent2", circuit_config)
        
        all_status = await registry.get_all_status()
        
        assert "agent1" in all_status
        assert "agent2" in all_status
        assert all_status["agent1"]["state"] == CircuitState.CLOSED.value
        assert all_status["agent2"]["state"] == CircuitState.CLOSED.value

class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker with realistic scenarios"""
    
    @pytest.mark.asyncio
    async def test_realistic_failure_recovery_cycle(self, mock_db_pool):
        """Test a realistic failure and recovery cycle"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=timedelta(milliseconds=100),
            success_threshold=2,
            timeout_seconds=0.1
        )
        
        breaker = CircuitBreaker("integration_test", config, mock_db_pool)
        await breaker.initialize()
        
        call_count = 0
        
        async def unreliable_func():
            nonlocal call_count
            call_count += 1
            
            # Fail first 2 calls, then succeed
            if call_count <= 2:
                raise Exception(f"Failure {call_count}")
            return f"Success {call_count}"
        
        # First two calls should fail and open circuit
        with pytest.raises(Exception):
            await breaker.call(unreliable_func)
        
        with pytest.raises(Exception):
            await breaker.call(unreliable_func)
        
        assert breaker.state == CircuitState.OPEN
        
        # Immediate calls should be rejected
        with pytest.raises(CircuitOpenError):
            await breaker.call(unreliable_func)
        
        # Wait for recovery timeout
        await asyncio.sleep(0.2)
        
        # Should transition to half-open and succeed
        result = await breaker.call(unreliable_func)
        assert result == "Success 3"
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Another success should close the circuit
        result = await breaker.call(unreliable_func)
        assert result == "Success 4"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_concurrent_calls(self, mock_db_pool, circuit_config):
        """Test circuit breaker with concurrent calls"""
        breaker = CircuitBreaker("concurrent_test", circuit_config, mock_db_pool)
        await breaker.initialize()
        
        call_results = []
        
        async def concurrent_func(call_id):
            await asyncio.sleep(0.01)  # Small delay
            return f"Result {call_id}"
        
        # Execute multiple concurrent calls
        tasks = [breaker.call(concurrent_func, i) for i in range(5)]
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 5
        assert all("Result" in result for result in results)
        assert breaker.state == CircuitState.CLOSED
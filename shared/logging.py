# shared/logging.py
import structlog
import logging
import sys
from typing import Any, Dict, Optional

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

# Get logger instance
logger = structlog.get_logger()

# Configure standard library logging
logging.basicConfig(
    format="%(message)s",
    stream=sys.stdout,
    level=logging.INFO,
)

def setup_logging(level: str = "INFO", json_logs: bool = True):
    """Setup logging configuration"""
    log_level = getattr(logging, level.upper())
    logging.getLogger().setLevel(log_level)
    
    if not json_logs:
        # Use human-readable format for development
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.dev.ConsoleRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

def log_agent_execution(
    agent_name: str,
    task_id: str,
    execution_time_ms: int,
    tokens_used: int,
    success: bool,
    confidence_score: Optional[float] = None,
    error_message: Optional[str] = None
):
    """Log agent execution metrics"""
    extra_data = {
        "agent_name": agent_name,
        "task_id": task_id,
        "execution_time_ms": execution_time_ms,
        "tokens_used": tokens_used,
        "success": success
    }
    
    if confidence_score is not None:
        extra_data["confidence_score"] = confidence_score
    
    if error_message:
        extra_data["error_message"] = error_message
        logger.error("Agent execution failed", **extra_data)
    else:
        logger.info("Agent execution completed", **extra_data)

def log_circuit_breaker_event(
    agent_name: str,
    event_type: str,
    state: str,
    failure_count: int,
    additional_context: Optional[Dict[str, Any]] = None
):
    """Log circuit breaker state changes"""
    extra_data = {
        "agent_name": agent_name,
        "event_type": event_type,
        "circuit_state": state,
        "failure_count": failure_count
    }
    
    if additional_context:
        extra_data.update(additional_context)
    
    logger.info("Circuit breaker event", **extra_data)

def log_approval_request(
    task_id: str,
    phase: str,
    quality_score: float,
    human_review_required: bool,
    approval_id: Optional[int] = None
):
    """Log human approval requests"""
    logger.info("Approval request", 
               task_id=task_id,
               phase=phase,
               quality_score=quality_score,
               human_review_required=human_review_required,
               approval_id=approval_id)

def log_token_usage(
    task_id: str,
    phase: str,
    tokens_consumed: int,
    remaining_budget: int,
    budget_exceeded: bool
):
    """Log token usage tracking"""
    logger.info("Token usage", 
               task_id=task_id,
               phase=phase,
               tokens_consumed=tokens_consumed,
               remaining_budget=remaining_budget,
               budget_exceeded=budget_exceeded)
# domain/models/task_state.py
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"

class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"

@dataclass(frozen=True)
class TaskStateSnapshot:
    """Immutable snapshot of task state at a point in time"""
    task_id: str
    status: TaskStatus
    project_data: Dict[str, Any]
    agent_outputs: Dict[str, Any]
    quality_scores: Dict[str, float]
    token_usage: Dict[str, int]
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    error_message: Optional[str] = None

@dataclass(frozen=True)
class ApprovalRequest:
    """Immutable approval request for human oversight"""
    approval_id: int
    task_id: str
    phase: str
    agent_output: Dict[str, Any]
    recommendation: str
    status: ApprovalStatus
    submitted_at: datetime
    expires_at: datetime
    reviewed_at: Optional[datetime] = None
    reviewer_feedback: Optional[str] = None
    quality_score: Optional[float] = None

@dataclass(frozen=True)
class TokenBudgetState:
    """Immutable token budget state"""
    task_id: str
    total_budget: int
    consumed_tokens: int
    remaining_tokens: int
    phase_allocations: Dict[str, int]
    usage_by_phase: Dict[str, int]
    budget_exceeded: bool
    last_updated: datetime
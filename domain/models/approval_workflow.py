# domain/models/approval_workflow.py
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

class InterventionTrigger(Enum):
    QUALITY_FAILURE = "quality_failure"
    AGENT_ERROR = "agent_error"
    TOKEN_EXCEEDED = "token_exceeded"
    USER_REQUEST = "user_request"
    CONSISTENCY_FAILURE = "consistency_failure"
    NONE = "none"

@dataclass(frozen=True)
class QualityAssessment:
    """Immutable quality assessment result"""
    overall_score: float
    component_scores: Dict[str, float]
    human_review_required: bool
    issues: List[str]
    recommendations: List[str]
    confidence_level: float
    assessment_timestamp: datetime

@dataclass(frozen=True)
class InterventionContext:
    """Immutable context for human intervention"""
    task_id: str
    trigger: InterventionTrigger
    phase: str
    agent_output: Optional[Dict[str, Any]]
    quality_assessment: Optional[QualityAssessment]
    error_details: Optional[str]
    suggested_action: str
    intervention_timestamp: datetime

# Pydantic models for API request/response
class ApprovalRequestModel(BaseModel):
    task_id: str = Field(..., description="Unique task identifier")
    phase: str = Field(..., description="Agent phase requiring approval")
    agent_output: Dict[str, Any] = Field(..., description="Agent output data")
    recommendation: str = Field(..., description="System recommendation for human reviewer")
    quality_score: float = Field(..., ge=0.0, le=1.0, description="Automated quality assessment")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Agent confidence level")

class ApprovalResponseModel(BaseModel):
    approved: bool = Field(..., description="Human approval decision")
    feedback: Optional[str] = Field(None, description="Human feedback on the output")
    modifications: Optional[Dict[str, Any]] = Field(None, description="Suggested modifications")
    quality_override: Optional[float] = Field(None, ge=0.0, le=1.0, description="Human quality assessment")

class ApprovalStatusModel(BaseModel):
    approval_id: int
    task_id: str
    phase: str
    status: str
    submitted_at: datetime
    expires_at: datetime
    reviewed_at: Optional[datetime] = None
    reviewer_feedback: Optional[str] = None
# domain/models/agent_context.py
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

class AnalysisDepth(str, Enum):
    QUICK = "quick"
    STANDARD = "standard"
    COMPREHENSIVE = "comprehensive"

@dataclass(frozen=True)
class AgentInput:
    """Immutable input for stateless agent transformations"""
    project_description: str
    analysis_depth: AnalysisDepth
    token_budget: int
    context_data: Dict[str, Any]
    timestamp: datetime
    task_id: str

@dataclass(frozen=True)
class AgentOutput:
    """Immutable output from stateless agent transformations"""
    success: bool
    data: Dict[str, Any]
    confidence_score: float
    tokens_used: int
    execution_time_ms: int
    error_message: Optional[str] = None
    recommendations: Optional[List[str]] = None

@dataclass(frozen=True)
class ResearchContext:
    """Immutable research findings context"""
    market_analysis: Dict[str, Any]
    technology_landscape: Dict[str, Any]
    best_practices: List[str]
    source_confidence: float
    research_timestamp: datetime
    source_urls: List[str]

@dataclass(frozen=True)
class RequirementsContext:
    """Immutable requirements analysis context"""
    functional_requirements: List[Dict[str, Any]]
    non_functional_requirements: List[Dict[str, Any]]
    user_personas: List[Dict[str, Any]]
    business_constraints: List[Dict[str, Any]]
    quality_score: float
    analysis_timestamp: datetime
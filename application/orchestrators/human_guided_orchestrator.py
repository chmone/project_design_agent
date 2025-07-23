# application/orchestrators/human_guided_orchestrator.py
from typing import Dict, Any, Optional, List
from datetime import datetime
import asyncio
from enum import Enum

from domain.models.task_state import TaskStatus
from domain.models.agent_context import AgentInput, AnalysisDepth
from domain.models.approval_workflow import InterventionTrigger, InterventionContext
from infrastructure.storage.persistent_task_queue import PersistentTaskQueue
from application.services.token_budget_manager import TokenBudgetManager
from infrastructure.agents.stateless_research_agent import StatelessResearchAgent
from shared.logging import logger

class OrchestrationPhase(Enum):
    INITIALIZATION = "initialization"
    RESEARCH = "research"
    ANALYSIS = "analysis"  # Phase 1.2 will add this
    COMPLETE = "complete"
    FAILED = "failed"

class HumanGuidedOrchestrator:
    """Orchestrator with mandatory human approval gates for Phase 1"""
    
    def __init__(self, 
                 task_queue: PersistentTaskQueue,
                 token_manager: TokenBudgetManager,
                 research_agent: StatelessResearchAgent):
        self.task_queue = task_queue
        self.token_manager = token_manager
        self.research_agent = research_agent
        
        # Human approval is required after each phase in Phase 1
        self.approval_required_phases = ["research", "analysis"]

    async def execute_analysis(self, task_id: str, project_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Phase 1.1 analysis with mandatory human oversight"""
        
        logger.info("Starting human-guided analysis", task_id=task_id)
        
        try:
            # Initialize token budget
            analysis_depth = AnalysisDepth(project_data.get("analysis_depth", "standard"))
            custom_budget = project_data.get("token_budget")
            
            await self.token_manager.initialize_budget(
                task_id=task_id,
                analysis_depth=analysis_depth,
                custom_budget=custom_budget
            )
            
            # Update task status to running
            await self.task_queue.update_task_status(task_id, TaskStatus.RUNNING)
            
            # Execute research phase
            research_result = await self._execute_research_phase(task_id, project_data)
            
            if not research_result["success"]:
                await self._handle_phase_failure(task_id, "research", research_result["error"])
                return {
                    "status": "failed",
                    "failed_phase": "research",
                    "error": research_result["error"],
                    "human_intervention": False
                }
            
            # MANDATORY: Request human approval for research results
            approval_required = await self._request_human_approval(
                task_id=task_id,
                phase="research",
                agent_output=research_result["output"],
                recommendation="Research phase completed. Please review findings and approve to continue to analysis phase."
            )
            
            if approval_required:
                return {
                    "status": "awaiting_approval",
                    "current_phase": "research",
                    "partial_results": {"research": research_result["output"]},
                    "human_intervention": True,
                    "next_action": "human_approval_required",
                    "approval_message": "Research phase requires human validation before proceeding"
                }
            
            # This path should not be reached in Phase 1.1 (always requires approval)
            logger.warning("Unexpected automatic approval in Phase 1.1", task_id=task_id)
            
            return {
                "status": "unexpected_state",
                "message": "Phase 1.1 should always require human approval",
                "partial_results": {"research": research_result["output"]}
            }
            
        except Exception as e:
            logger.error("Orchestration failed", task_id=task_id, error=str(e))
            await self.task_queue.update_task_status(
                task_id, 
                TaskStatus.FAILED, 
                error_message=f"Orchestration error: {str(e)}"
            )
            
            return {
                "status": "failed",
                "error": str(e),
                "human_intervention": False
            }

    async def continue_after_approval(self, task_id: str, 
                                    modifications: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Continue orchestration after human approval"""
        
        logger.info("Continuing after human approval", task_id=task_id)
        
        try:
            # Get current task state
            task = await self.task_queue.get_task(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            
            # For Phase 1.1, we only have research phase
            # In Phase 1.2, we'll add analysis phase here
            
            # Mark task as completed for Phase 1.1
            await self.task_queue.update_task_status(task_id, TaskStatus.COMPLETED)
            
            logger.info("Phase 1.1 analysis completed", task_id=task_id)
            
            return {
                "status": "completed",
                "phases_completed": ["research"],
                "final_results": task.agent_outputs,
                "human_interventions": 1,  # Research approval
                "token_usage": await self._get_final_token_usage(task_id)
            }
            
        except Exception as e:
            logger.error("Failed to continue after approval", task_id=task_id, error=str(e))
            await self.task_queue.update_task_status(
                task_id, 
                TaskStatus.FAILED, 
                error_message=f"Post-approval error: {str(e)}"
            )
            
            return {
                "status": "failed",
                "error": str(e)
            }

    async def _execute_research_phase(self, task_id: str, project_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute research phase with token management"""
        
        logger.info("Executing research phase", task_id=task_id)
        
        try:
            # Get token allocation for research phase
            research_budget = await self.token_manager.get_phase_allocation(task_id, "research")
            
            if research_budget < 500:  # Minimum viable budget
                return {
                    "success": False,
                    "error": f"Insufficient research budget: {research_budget} tokens",
                    "phase": "research"
                }
            
            # Create agent input
            agent_input = AgentInput(
                project_description=project_data["description"],
                analysis_depth=AnalysisDepth(project_data.get("analysis_depth", "standard")),
                token_budget=research_budget,
                context_data=project_data,
                timestamp=datetime.utcnow(),
                task_id=task_id
            )
            
            # Execute research agent
            research_output = await self.research_agent.transform(agent_input)
            
            if not research_output.success:
                return {
                    "success": False,
                    "error": research_output.error_message,
                    "phase": "research",
                    "tokens_attempted": research_output.tokens_used
                }
            
            # Consume tokens from budget
            tokens_consumed = await self.token_manager.consume_tokens(
                task_id, "research", research_output.tokens_used
            )
            
            if not tokens_consumed:
                return {
                    "success": False,
                    "error": f"Token budget exceeded: attempted {research_output.tokens_used} tokens",
                    "phase": "research"
                }
            
            # Update task with research results
            await self.task_queue.update_task_status(
                task_id, 
                TaskStatus.RUNNING, 
                agent_output=research_output
            )
            
            logger.info("Research phase completed successfully", 
                       task_id=task_id,
                       tokens_used=research_output.tokens_used,
                       confidence=research_output.confidence_score)
            
            return {
                "success": True,
                "output": research_output,
                "phase": "research",
                "tokens_used": research_output.tokens_used,
                "confidence": research_output.confidence_score
            }
            
        except Exception as e:
            logger.error("Research phase failed", task_id=task_id, error=str(e))
            return {
                "success": False,
                "error": str(e),
                "phase": "research"
            }

    async def _request_human_approval(self, task_id: str, phase: str, 
                                    agent_output: Any, recommendation: str) -> bool:
        """Request human approval - always returns True in Phase 1.1"""
        
        # Create approval request
        approval_id = await self.task_queue.create_approval_request(
            task_id=task_id,
            phase=phase,
            agent_output=agent_output,
            recommendation=recommendation
        )
        
        # Update task status to awaiting approval
        await self.task_queue.update_task_status(task_id, TaskStatus.AWAITING_APPROVAL)
        
        logger.info("Human approval requested", 
                   task_id=task_id, 
                   phase=phase, 
                   approval_id=approval_id)
        
        # Phase 1.1 always requires human approval
        return True

    async def _handle_phase_failure(self, task_id: str, phase: str, error: str):
        """Handle failure in a specific phase"""
        
        await self.task_queue.update_task_status(
            task_id, 
            TaskStatus.FAILED, 
            error_message=f"Phase '{phase}' failed: {error}"
        )
        
        logger.error("Phase failed", task_id=task_id, phase=phase, error=error)

    async def _get_final_token_usage(self, task_id: str) -> Dict[str, Any]:
        """Get final token usage summary"""
        
        budget_status = await self.token_manager.get_budget_status(task_id)
        if not budget_status:
            return {"error": "No budget information available"}
        
        return {
            "total_budget": budget_status.total_budget,
            "consumed_tokens": budget_status.consumed_tokens,
            "remaining_tokens": budget_status.remaining_tokens,
            "usage_by_phase": budget_status.usage_by_phase,
            "budget_exceeded": budget_status.budget_exceeded,
            "efficiency_score": await self._calculate_efficiency_score(budget_status)
        }

    async def _calculate_efficiency_score(self, budget_state) -> float:
        """Calculate token usage efficiency score"""
        if budget_state.total_budget == 0:
            return 0.0
        
        utilization = budget_state.consumed_tokens / budget_state.total_budget
        
        # Ideal utilization is around 80-90%
        if 0.8 <= utilization <= 0.9:
            return 1.0
        elif utilization < 0.8:
            return utilization / 0.8  # Penalize under-utilization
        else:
            return max(0.1, 1.0 - (utilization - 0.9) * 2)  # Penalize over-utilization

    async def get_orchestration_status(self, task_id: str) -> Dict[str, Any]:
        """Get current orchestration status"""
        
        task = await self.task_queue.get_task(task_id)
        if not task:
            return {"error": "Task not found"}
        
        pending_approvals = await self.task_queue.get_pending_approvals(task_id)
        budget_status = await self.token_manager.get_budget_status(task_id)
        
        return {
            "task_id": task_id,
            "status": task.status.value,
            "current_phase": self._determine_current_phase(task, pending_approvals),
            "pending_approvals": len(pending_approvals),
            "completed_phases": list(task.agent_outputs.keys()),
            "token_usage": {
                "consumed": budget_status.consumed_tokens if budget_status else 0,
                "remaining": budget_status.remaining_tokens if budget_status else 0,
                "budget_exceeded": budget_status.budget_exceeded if budget_status else False
            },
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "error_message": task.error_message
        }

    def _determine_current_phase(self, task, pending_approvals) -> str:
        """Determine current orchestration phase"""
        
        if task.status == TaskStatus.PENDING:
            return "initialization"
        elif task.status == TaskStatus.RUNNING:
            if "research_output" in task.agent_outputs:
                return "research_complete"
            else:
                return "research"
        elif task.status == TaskStatus.AWAITING_APPROVAL:
            if pending_approvals:
                return f"awaiting_approval_{pending_approvals[0].phase}"
            else:
                return "awaiting_approval"
        elif task.status == TaskStatus.COMPLETED:
            return "complete"
        elif task.status == TaskStatus.FAILED:
            return "failed"
        else:
            return task.status.value

    async def cleanup_task(self, task_id: str) -> bool:
        """Clean up task resources (for testing or maintenance)"""
        
        try:
            # This could include cleanup of temporary files, cache entries, etc.
            logger.info("Cleaning up task resources", task_id=task_id)
            
            # For now, just log the cleanup
            return True
            
        except Exception as e:
            logger.error("Failed to cleanup task", task_id=task_id, error=str(e))
            return False
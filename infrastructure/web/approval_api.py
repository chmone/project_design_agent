# infrastructure/web/approval_api.py
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from infrastructure.storage.persistent_task_queue import PersistentTaskQueue
from domain.models.task_state import TaskStatus, ApprovalStatus
from domain.models.approval_workflow import (
    ApprovalRequestModel, 
    ApprovalResponseModel, 
    ApprovalStatusModel,
    InterventionContext,
    InterventionTrigger
)
from domain.models.agent_context import AgentOutput
from shared.logging import logger, log_approval_request

router = APIRouter(prefix="/approval", tags=["human-approval"])

# Dependency injection functions
async def get_task_queue() -> PersistentTaskQueue:
    # This will be properly injected in the main application
    # For now, returning a placeholder
    pass

async def get_orchestrator():
    # This will be properly injected in the main application
    pass

class TaskStatusResponse(BaseModel):
    task_id: str
    current_status: str
    pending_approvals: int
    approval_history: List[Dict[str, Any]] = []
    next_action: str
    intervention_context: Optional[Dict[str, Any]] = None

@router.post("/request", response_model=ApprovalStatusModel)
async def request_approval(
    request: ApprovalRequestModel,
    task_queue: PersistentTaskQueue = Depends(get_task_queue)
):
    """Request human approval for agent output"""
    
    try:
        # Create AgentOutput from request data
        agent_output = AgentOutput(
            success=True,
            data=request.agent_output,
            confidence_score=request.confidence_score,
            tokens_used=0,  # Will be updated by orchestrator
            execution_time_ms=0
        )
        
        # Create approval request with 24-hour expiration
        approval_id = await task_queue.create_approval_request(
            task_id=request.task_id,
            phase=request.phase,
            agent_output=agent_output,
            recommendation=request.recommendation,
            expires_hours=24
        )
        
        # Update task status to awaiting approval
        await task_queue.update_task_status(
            request.task_id, 
            TaskStatus.AWAITING_APPROVAL
        )
        
        # Log approval request
        log_approval_request(
            task_id=request.task_id,
            phase=request.phase,
            quality_score=request.quality_score,
            human_review_required=True,
            approval_id=approval_id
        )
        
        return ApprovalStatusModel(
            approval_id=approval_id,
            task_id=request.task_id,
            phase=request.phase,
            status="pending",
            submitted_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=24)
        )
        
    except Exception as e:
        logger.error("Failed to create approval request", 
                    task_id=request.task_id, 
                    phase=request.phase, 
                    error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create approval request: {str(e)}")

@router.get("/pending/{task_id}", response_model=List[ApprovalStatusModel])
async def get_pending_approvals(
    task_id: str,
    task_queue: PersistentTaskQueue = Depends(get_task_queue)
):
    """Get all pending approvals for a task"""
    
    try:
        approval_requests = await task_queue.get_pending_approvals(task_id)
        
        return [
            ApprovalStatusModel(
                approval_id=approval.approval_id,
                task_id=approval.task_id,
                phase=approval.phase,
                status=approval.status.value,
                submitted_at=approval.submitted_at,
                expires_at=approval.expires_at,
                reviewed_at=approval.reviewed_at,
                reviewer_feedback=approval.reviewer_feedback
            )
            for approval in approval_requests
        ]
        
    except Exception as e:
        logger.error("Failed to get pending approvals", task_id=task_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get pending approvals: {str(e)}")

@router.post("/respond/{approval_id}", response_model=ApprovalStatusModel)
async def respond_to_approval(
    approval_id: int,
    response: ApprovalResponseModel,
    background_tasks: BackgroundTasks,
    task_queue: PersistentTaskQueue = Depends(get_task_queue),
    orchestrator = Depends(get_orchestrator)
):
    """Human response to approval request"""
    
    try:
        # Update approval status
        approval_updated = await task_queue.update_approval_status(
            approval_id=approval_id,
            status=ApprovalStatus.APPROVED if response.approved else ApprovalStatus.REJECTED,
            feedback=response.feedback
        )
        
        if not approval_updated:
            raise HTTPException(status_code=404, detail="Approval not found or already processed")
        
        # Get approval details for response
        async with task_queue.connection_pool.acquire() as conn:
            approval = await conn.fetchrow("""
                SELECT * FROM approval_requests WHERE id = $1
            """, approval_id)
            
            if not approval:
                raise HTTPException(status_code=404, detail="Approval not found")
        
        # Resume task execution if approved
        if response.approved:
            # Update task status
            await task_queue.update_task_status(
                approval['task_id'], 
                TaskStatus.APPROVED
            )
            
            # Continue orchestration in background (if orchestrator available)
            if orchestrator:
                background_tasks.add_task(
                    orchestrator.continue_after_approval,
                    approval['task_id'],
                    response.modifications
                )
        else:
            # Handle rejection - could implement retry logic or escalation
            await task_queue.update_task_status(
                approval['task_id'], 
                TaskStatus.FAILED,
                error_message=f"Human rejected approval for phase {approval['phase']}: {response.feedback}"
            )
        
        logger.info("Approval response processed", 
                   approval_id=approval_id,
                   approved=response.approved,
                   task_id=approval['task_id'],
                   phase=approval['phase'])
        
        return ApprovalStatusModel(
            approval_id=approval['id'],
            task_id=approval['task_id'],
            phase=approval['phase'],
            status=approval['status'],
            submitted_at=approval['submitted_at'],
            expires_at=approval['expires_at'],
            reviewed_at=datetime.utcnow(),
            reviewer_feedback=response.feedback
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process approval response", 
                    approval_id=approval_id, 
                    error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process approval response: {str(e)}")

@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_approval_status(
    task_id: str,
    task_queue: PersistentTaskQueue = Depends(get_task_queue)
):
    """Get comprehensive approval status for a task"""
    
    try:
        # Get task state
        task = await task_queue.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Get pending approvals
        pending_approvals = await task_queue.get_pending_approvals(task_id)
        
        # Determine next action
        next_action = "continue_execution"
        if pending_approvals:
            next_action = "await_human_review"
        elif task.status == TaskStatus.FAILED:
            next_action = "review_failure"
        elif task.status == TaskStatus.EXPIRED:
            next_action = "handle_expiration"
        
        # Get approval history (simplified for now)
        approval_history = []
        async with task_queue.connection_pool.acquire() as conn:
            history_rows = await conn.fetch("""
                SELECT phase, status, reviewed_at, reviewer_feedback 
                FROM approval_requests 
                WHERE task_id = $1 AND status != 'pending'
                ORDER BY reviewed_at DESC
                LIMIT 10
            """, task_id)
            
            approval_history = [
                {
                    "phase": row['phase'],
                    "status": row['status'],
                    "reviewed_at": row['reviewed_at'].isoformat() if row['reviewed_at'] else None,
                    "feedback": row['reviewer_feedback']
                }
                for row in history_rows
            ]
        
        # Create intervention context if needed
        intervention_context = None
        if task.status == TaskStatus.AWAITING_APPROVAL and pending_approvals:
            latest_approval = pending_approvals[0]  # Most recent
            intervention_context = {
                "trigger": InterventionTrigger.QUALITY_FAILURE.value,  # Default assumption
                "phase": latest_approval.phase,
                "quality_score": latest_approval.quality_score,
                "recommendation": latest_approval.recommendation,
                "expires_at": latest_approval.expires_at.isoformat()
            }
        
        return TaskStatusResponse(
            task_id=task_id,
            current_status=task.status.value,
            pending_approvals=len(pending_approvals),
            approval_history=approval_history,
            next_action=next_action,
            intervention_context=intervention_context
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get approval status", task_id=task_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get approval status: {str(e)}")

@router.delete("/expire/{approval_id}")
async def expire_approval(
    approval_id: int,
    task_queue: PersistentTaskQueue = Depends(get_task_queue)
):
    """Manually expire an approval request (admin function)"""
    
    try:
        approval_updated = await task_queue.update_approval_status(
            approval_id=approval_id,
            status=ApprovalStatus.EXPIRED,
            feedback="Manually expired by administrator"
        )
        
        if not approval_updated:
            raise HTTPException(status_code=404, detail="Approval not found or already processed")
        
        logger.info("Approval manually expired", approval_id=approval_id)
        
        return {"message": "Approval expired successfully", "approval_id": approval_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to expire approval", approval_id=approval_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to expire approval: {str(e)}")

@router.get("/health")
async def approval_system_health(
    task_queue: PersistentTaskQueue = Depends(get_task_queue)
):
    """Health check for approval system"""
    
    try:
        # Check database connectivity
        async with task_queue.connection_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        # Get system statistics
        async with task_queue.connection_pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) FILTER (WHERE status = 'pending') as pending_approvals,
                    COUNT(*) FILTER (WHERE status = 'approved') as approved_count,
                    COUNT(*) FILTER (WHERE status = 'rejected') as rejected_count,
                    COUNT(*) FILTER (WHERE expires_at < CURRENT_TIMESTAMP AND status = 'pending') as expired_pending
                FROM approval_requests
                WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
            """)
        
        return {
            "status": "healthy",
            "database_connection": "ok",
            "last_24h_stats": {
                "pending_approvals": stats['pending_approvals'],
                "approved_count": stats['approved_count'],
                "rejected_count": stats['rejected_count'],
                "expired_pending": stats['expired_pending']
            }
        }
        
    except Exception as e:
        logger.error("Approval system health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e)
        }
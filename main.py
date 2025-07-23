# main.py
import os
import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
import asyncpg
from datetime import datetime

# Internal imports
from infrastructure.storage.persistent_task_queue import PersistentTaskQueue
from application.services.token_budget_manager import TokenBudgetManager
from infrastructure.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitBreakerConfig
from infrastructure.agents.stateless_research_agent import StatelessResearchAgent
from application.orchestrators.human_guided_orchestrator import HumanGuidedOrchestrator
from infrastructure.web.approval_api import router as approval_router
from domain.models.agent_context import AnalysisDepth
from shared.logging import logger, setup_logging

# Global application state
app_state = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    
    # Startup
    logger.info("Starting Design Research Agent v1.2")
    
    # Setup logging
    setup_logging(
        level=os.getenv("LOG_LEVEL", "INFO"),
        json_logs=os.getenv("JSON_LOGS", "true").lower() == "true"
    )
    
    # Database setup
    database_url = os.getenv("DATABASE_URL", "postgresql://localhost:5432/design_agent")
    
    try:
        # Initialize database connection pool
        db_pool = await asyncpg.create_pool(database_url, min_size=5, max_size=20)
        app_state["db_pool"] = db_pool
        
        # Initialize task queue
        task_queue = PersistentTaskQueue(database_url)
        await task_queue.initialize()
        app_state["task_queue"] = task_queue
        
        # Initialize token budget manager
        token_manager = TokenBudgetManager(db_pool)
        app_state["token_manager"] = token_manager
        
        # Initialize circuit breaker registry
        circuit_breaker_registry = CircuitBreakerRegistry(db_pool)
        app_state["circuit_breaker_registry"] = circuit_breaker_registry
        
        # Initialize agents with circuit breakers
        research_circuit_breaker = await circuit_breaker_registry.get_breaker(
            "research_agent", 
            CircuitBreakerConfig(failure_threshold=3, timeout_seconds=30.0)
        )
        
        research_agent = StatelessResearchAgent(research_circuit_breaker)
        app_state["research_agent"] = research_agent
        
        # Initialize orchestrator
        orchestrator = HumanGuidedOrchestrator(task_queue, token_manager, research_agent)
        app_state["orchestrator"] = orchestrator
        
        logger.info("Application initialized successfully")
        
        # Start background cleanup task
        asyncio.create_task(cleanup_expired_tasks())
        
    except Exception as e:
        logger.error("Failed to initialize application", error=str(e))
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Design Research Agent")
    
    if "task_queue" in app_state:
        await app_state["task_queue"].close()
    
    if "db_pool" in app_state:
        await app_state["db_pool"].close()

# Create FastAPI app
app = FastAPI(
    title="Design Research Agent v1.2",
    description="Stateless multi-agent system for project research and analysis with human oversight",
    version="1.2.0",
    lifespan=lifespan
)

# Request/Response models
class AnalyzeRequest(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=10, max_length=5000)
    analysis_depth: AnalysisDepth = Field(default=AnalysisDepth.STANDARD)
    token_budget: Optional[int] = Field(default=None, ge=5000, le=100000)

class AnalyzeResponse(BaseModel):
    task_id: str
    status: str
    estimated_completion: str
    approval_required: bool
    approval_url: Optional[str] = None
    message: str

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: Dict[str, Any]
    results: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    human_intervention_required: bool
    next_action: str

# Dependency injection
async def get_task_queue() -> PersistentTaskQueue:
    return app_state["task_queue"]

async def get_token_manager() -> TokenBudgetManager:
    return app_state["token_manager"]

async def get_orchestrator() -> HumanGuidedOrchestrator:
    return app_state["orchestrator"]

async def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    return app_state["circuit_breaker_registry"]

# Note: APIRouter doesn't support dependency_overrides
# Dependencies are resolved through the main app when router is included

# Main API endpoints
@app.post("/analyze", response_model=AnalyzeResponse)
async def start_analysis(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    orchestrator: HumanGuidedOrchestrator = Depends(get_orchestrator),
    task_queue: PersistentTaskQueue = Depends(get_task_queue)
):
    """Start a new project analysis with human oversight"""
    
    try:
        # Generate unique task ID
        task_id = str(uuid.uuid4())
        
        # Prepare project data
        project_data = {
            "project_name": request.project_name,
            "description": request.description,
            "analysis_depth": request.analysis_depth.value,
            "token_budget": request.token_budget,
            "created_at": datetime.utcnow().isoformat()
        }
        
        # Enqueue task
        await task_queue.enqueue_task(task_id, project_data)
        
        # Start orchestration in background
        background_tasks.add_task(
            execute_analysis_background,
            task_id,
            project_data,
            orchestrator
        )
        
        logger.info("Analysis started", 
                   task_id=task_id,
                   project_name=request.project_name,
                   analysis_depth=request.analysis_depth.value)
        
        return AnalyzeResponse(
            task_id=task_id,
            status="started",
            estimated_completion=(datetime.utcnow()).isoformat(),
            approval_required=True,  # Phase 1.1 always requires approval
            approval_url=f"/approval/pending/{task_id}",
            message="Analysis started. Human approval will be required after research phase."
        )
        
    except Exception as e:
        logger.error("Failed to start analysis", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to start analysis: {str(e)}")

@app.get("/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    orchestrator: HumanGuidedOrchestrator = Depends(get_orchestrator)
):
    """Get current status of an analysis task"""
    
    try:
        status = await orchestrator.get_orchestration_status(task_id)
        
        if "error" in status:
            raise HTTPException(status_code=404, detail=status["error"])
        
        # Determine if human intervention is needed
        human_intervention_required = (
            status["status"] == "awaiting_approval" or
            status["pending_approvals"] > 0
        )
        
        # Determine next action
        next_action = "wait"
        if human_intervention_required:
            next_action = "human_approval_required"
        elif status["status"] == "completed":
            next_action = "download_results"
        elif status["status"] == "failed":
            next_action = "review_error"
        elif status["status"] == "running":
            next_action = "wait_for_completion"
        
        return TaskStatusResponse(
            task_id=task_id,
            status=status["status"],
            progress={
                "current_phase": status["current_phase"],
                "completed_phases": status["completed_phases"],
                "token_usage": status["token_usage"],
                "pending_approvals": status["pending_approvals"]
            },
            results=None,  # Results available after completion
            error_message=status.get("error_message"),
            human_intervention_required=human_intervention_required,
            next_action=next_action
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get task status", task_id=task_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {str(e)}")

@app.get("/tasks/{task_id}/results")
async def get_task_results(
    task_id: str,
    task_queue: PersistentTaskQueue = Depends(get_task_queue)
):
    """Get final results of a completed analysis"""
    
    try:
        task = await task_queue.get_task(task_id)
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        if task.status.value != "completed":
            raise HTTPException(
                status_code=400, 
                detail=f"Task not completed. Current status: {task.status.value}"
            )
        
        return {
            "task_id": task_id,
            "status": "completed",
            "project_data": task.project_data,
            "agent_outputs": task.agent_outputs,
            "quality_scores": task.quality_scores,
            "token_usage": task.token_usage,
            "created_at": task.created_at.isoformat(),
            "completed_at": task.updated_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get task results", task_id=task_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get task results: {str(e)}")

@app.get("/health")
async def health_check(
    circuit_breaker_registry: CircuitBreakerRegistry = Depends(get_circuit_breaker_registry)
):
    """System health check"""
    
    try:
        # Check database connectivity
        async with app_state["db_pool"].acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        # Get circuit breaker status
        circuit_status = await circuit_breaker_registry.get_all_status()
        
        # Check for any open circuit breakers
        open_circuits = [name for name, status in circuit_status.items() 
                        if status["state"] == "open"]
        
        health_status = "healthy" if not open_circuits else "degraded"
        
        return {
            "status": health_status,
            "database": "connected",
            "circuit_breakers": circuit_status,
            "open_circuits": open_circuits,
            "version": "1.2.0",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "service": "Design Research Agent v1.2",
        "description": "Stateless multi-agent system with human oversight",
        "phase": "1.1 - Stateless Foundation & Human Oversight",
        "features": [
            "Stateless agent architecture",
            "Circuit breaker fault tolerance",
            "Persistent task queue with PostgreSQL",
            "Human approval workflow",
            "Token budget management",
            "Error recovery framework"
        ],
        "endpoints": {
            "start_analysis": "POST /analyze",
            "task_status": "GET /tasks/{task_id}/status",
            "task_results": "GET /tasks/{task_id}/results",
            "approval_workflow": "/approval/*",
            "health_check": "GET /health"
        }
    }

# Include approval router
app.include_router(approval_router)

# Background tasks
async def execute_analysis_background(
    task_id: str, 
    project_data: Dict[str, Any],
    orchestrator: HumanGuidedOrchestrator
):
    """Execute analysis in background"""
    try:
        result = await orchestrator.execute_analysis(task_id, project_data)
        logger.info("Background analysis completed", 
                   task_id=task_id, 
                   status=result.get("status"))
    except Exception as e:
        logger.error("Background analysis failed", task_id=task_id, error=str(e))

async def cleanup_expired_tasks():
    """Background task to clean up expired tasks"""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            
            if "task_queue" in app_state:
                expired_count = await app_state["task_queue"].cleanup_expired_tasks()
                if expired_count > 0:
                    logger.info("Cleaned up expired tasks", count=expired_count)
                    
        except Exception as e:
            logger.error("Failed to cleanup expired tasks", error=str(e))

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=os.getenv("RELOAD", "false").lower() == "true"
    )
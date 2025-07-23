# application/services/token_budget_manager.py
from typing import Dict, Any, Optional
from datetime import datetime
import asyncpg
import json
from dataclasses import asdict
from domain.models.task_state import TokenBudgetState
from domain.models.agent_context import AnalysisDepth
from shared.logging import logger, log_token_usage

class TokenBudgetManager:
    """Manage token budgets with automatic cutoffs and allocation strategies"""
    
    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool
        
        # Default budget allocations by analysis depth
        self.budget_templates = {
            AnalysisDepth.QUICK: {
                "total": 10000,
                "allocations": {
                    "research": 3000,
                    "analysis": 2500,
                    "questions": 2000,
                    "architecture": 2000,
                    "reserve": 500
                }
            },
            AnalysisDepth.STANDARD: {
                "total": 25000,
                "allocations": {
                    "research": 8000,
                    "analysis": 6000,
                    "questions": 4000,
                    "architecture": 5000,
                    "documentation": 1500,
                    "reserve": 500
                }
            },
            AnalysisDepth.COMPREHENSIVE: {
                "total": 50000,
                "allocations": {
                    "research": 15000,
                    "analysis": 12000,
                    "questions": 8000,
                    "architecture": 10000,
                    "documentation": 4000,
                    "validation": 1000
                }
            }
        }

    async def initialize_budget(self, task_id: str, analysis_depth: AnalysisDepth,
                              custom_budget: Optional[int] = None) -> TokenBudgetState:
        """Initialize token budget for a task"""
        
        template = self.budget_templates[analysis_depth]
        total_budget = custom_budget or template["total"]
        
        # Scale allocations if custom budget provided
        if custom_budget:
            scale_factor = custom_budget / template["total"]
            phase_allocations = {
                phase: int(allocation * scale_factor)
                for phase, allocation in template["allocations"].items()
            }
        else:
            phase_allocations = template["allocations"].copy()
        
        budget_state = TokenBudgetState(
            task_id=task_id,
            total_budget=total_budget,
            consumed_tokens=0,
            remaining_tokens=total_budget,
            phase_allocations=phase_allocations,
            usage_by_phase={},
            budget_exceeded=False,
            last_updated=datetime.utcnow()
        )
        
        # Store in database
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO token_budgets 
                (task_id, total_budget, consumed_tokens, phase_allocations, usage_by_phase, budget_exceeded)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, task_id, total_budget, 0, 
                json.dumps(phase_allocations), 
                json.dumps({}), 
                False)
        
        logger.info("Token budget initialized", 
                   task_id=task_id,
                   total_budget=total_budget,
                   analysis_depth=analysis_depth.value)
        
        return budget_state

    async def get_budget_status(self, task_id: str) -> Optional[TokenBudgetState]:
        """Get current budget status for a task"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM token_budgets WHERE task_id = $1
            """, task_id)
            
            if row:
                return TokenBudgetState(
                    task_id=row['task_id'],
                    total_budget=row['total_budget'],
                    consumed_tokens=row['consumed_tokens'],
                    remaining_tokens=row['total_budget'] - row['consumed_tokens'],
                    phase_allocations=json.loads(row['phase_allocations']),
                    usage_by_phase=json.loads(row['usage_by_phase']),
                    budget_exceeded=row['budget_exceeded'],
                    last_updated=row['updated_at']
                )
            return None

    async def get_phase_allocation(self, task_id: str, phase: str) -> int:
        """Get token allocation for a specific phase"""
        budget_status = await self.get_budget_status(task_id)
        if not budget_status:
            raise ValueError(f"No budget found for task {task_id}")
        
        phase_allocation = budget_status.phase_allocations.get(phase, 0)
        phase_used = budget_status.usage_by_phase.get(phase, 0)
        remaining_phase_budget = phase_allocation - phase_used
        
        # Also consider overall remaining budget
        remaining_overall = budget_status.remaining_tokens
        
        return min(remaining_phase_budget, remaining_overall)

    async def consume_tokens(self, task_id: str, phase: str, tokens_used: int) -> bool:
        """Consume tokens for a phase, returns False if budget exceeded"""
        async with self.db_pool.acquire() as conn:
            # Get current state
            row = await conn.fetchrow("""
                SELECT * FROM token_budgets WHERE task_id = $1
            """, task_id)
            
            if not row:
                raise ValueError(f"No budget found for task {task_id}")
            
            current_consumed = row['consumed_tokens']
            total_budget = row['total_budget']
            usage_by_phase = json.loads(row['usage_by_phase'])
            phase_allocations = json.loads(row['phase_allocations'])
            
            # Check if consumption would exceed budget
            new_consumed = current_consumed + tokens_used
            budget_exceeded = new_consumed > total_budget
            
            # Check phase-specific budget
            phase_used = usage_by_phase.get(phase, 0)
            phase_allocation = phase_allocations.get(phase, 0)
            new_phase_used = phase_used + tokens_used
            phase_exceeded = new_phase_used > phase_allocation
            
            if budget_exceeded:
                # Mark budget as exceeded but don't update consumption
                await conn.execute("""
                    UPDATE token_budgets 
                    SET budget_exceeded = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE task_id = $1
                """, task_id)
                
                log_token_usage(task_id, phase, tokens_used, 
                              total_budget - current_consumed, True)
                
                logger.warning("Token budget exceeded", 
                             task_id=task_id,
                             phase=phase,
                             attempted_consumption=tokens_used,
                             current_consumed=current_consumed,
                             total_budget=total_budget)
                return False
            
            # Update consumption
            usage_by_phase[phase] = new_phase_used
            
            await conn.execute("""
                UPDATE token_budgets 
                SET consumed_tokens = $2, 
                    usage_by_phase = $3, 
                    budget_exceeded = $4,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = $1
            """, task_id, new_consumed, json.dumps(usage_by_phase), phase_exceeded)
            
            remaining_tokens = total_budget - new_consumed
            
            log_token_usage(task_id, phase, tokens_used, remaining_tokens, False)
            
            logger.info("Tokens consumed", 
                       task_id=task_id,
                       phase=phase,
                       tokens_used=tokens_used,
                       total_consumed=new_consumed,
                       remaining_tokens=remaining_tokens,
                       phase_exceeded=phase_exceeded)
            
            return True

    async def allocate_emergency_budget(self, task_id: str, additional_tokens: int,
                                      justification: str) -> bool:
        """Allocate additional emergency budget"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM token_budgets WHERE task_id = $1
            """, task_id)
            
            if not row:
                raise ValueError(f"No budget found for task {task_id}")
            
            new_total = row['total_budget'] + additional_tokens
            
            await conn.execute("""
                UPDATE token_budgets 
                SET total_budget = $2, 
                    budget_exceeded = FALSE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = $1
            """, task_id, new_total)
            
            logger.info("Emergency budget allocated", 
                       task_id=task_id,
                       additional_tokens=additional_tokens,
                       new_total=new_total,
                       justification=justification)
            
            return True

    async def get_budget_recommendations(self, task_id: str) -> Dict[str, Any]:
        """Get budget optimization recommendations"""
        budget_status = await self.get_budget_status(task_id)
        if not budget_status:
            return {}
        
        recommendations = []
        
        # Check for phase imbalances
        total_allocated = sum(budget_status.phase_allocations.values())
        if total_allocated != budget_status.total_budget:
            recommendations.append({
                "type": "allocation_mismatch",
                "message": f"Phase allocations ({total_allocated}) don't match total budget ({budget_status.total_budget})",
                "severity": "warning"
            })
        
        # Check for high consumption phases
        for phase, used in budget_status.usage_by_phase.items():
            allocated = budget_status.phase_allocations.get(phase, 0)
            if allocated > 0:
                usage_ratio = used / allocated
                if usage_ratio > 0.9:
                    recommendations.append({
                        "type": "high_phase_usage",
                        "phase": phase,
                        "usage_ratio": usage_ratio,
                        "message": f"Phase '{phase}' using {usage_ratio:.1%} of allocation",
                        "severity": "warning" if usage_ratio < 1.0 else "critical"
                    })
        
        # Overall budget health
        consumption_ratio = budget_status.consumed_tokens / budget_status.total_budget
        if consumption_ratio > 0.8:
            recommendations.append({
                "type": "high_overall_usage",
                "consumption_ratio": consumption_ratio,
                "message": f"Overall budget {consumption_ratio:.1%} consumed",
                "severity": "warning" if consumption_ratio < 0.95 else "critical"
            })
        
        return {
            "task_id": task_id,
            "budget_health": "good" if consumption_ratio < 0.7 else "warning" if consumption_ratio < 0.9 else "critical",
            "recommendations": recommendations,
            "efficiency_score": self._calculate_efficiency_score(budget_status),
            "projected_overage": max(0, budget_status.consumed_tokens - budget_status.total_budget)
        }

    def _calculate_efficiency_score(self, budget_state: TokenBudgetState) -> float:
        """Calculate budget efficiency score (0.0 to 1.0)"""
        if budget_state.total_budget == 0:
            return 0.0
        
        # Base efficiency on consumption rate and phase balance
        consumption_efficiency = 1.0 - (budget_state.consumed_tokens / budget_state.total_budget)
        
        # Phase balance efficiency
        if budget_state.usage_by_phase:
            phase_variances = []
            for phase, used in budget_state.usage_by_phase.items():
                allocated = budget_state.phase_allocations.get(phase, 1)
                variance = abs(used / allocated - 0.5) if allocated > 0 else 0
                phase_variances.append(variance)
            
            phase_efficiency = 1.0 - (sum(phase_variances) / len(phase_variances))
        else:
            phase_efficiency = 1.0
        
        # Weighted combination
        return (consumption_efficiency * 0.7) + (phase_efficiency * 0.3)

    async def reset_budget(self, task_id: str) -> bool:
        """Reset budget consumption (for testing or restart scenarios)"""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE token_budgets 
                SET consumed_tokens = 0, 
                    usage_by_phase = '{}', 
                    budget_exceeded = FALSE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = $1
            """, task_id)
            
            updated = int(result.split()[-1]) > 0
            if updated:
                logger.info("Budget reset", task_id=task_id)
            return updated
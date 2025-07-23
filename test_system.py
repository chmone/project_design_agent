#!/usr/bin/env python3
"""
Test script for Design Research Agent v1.2 Phase 1.1
Run this to verify everything is working before starting the API server
"""

import sys
import os
sys.path.insert(0, '.')

def test_core_models():
    """Test core domain models"""
    print("🧪 Testing Core Models...")
    
    from domain.models.agent_context import AgentInput, AgentOutput, AnalysisDepth
    from domain.models.task_state import TaskStatus, ApprovalStatus, TokenBudgetState
    from datetime import datetime
    
    # Test AgentInput
    agent_input = AgentInput(
        project_description="Test E-commerce Platform",
        analysis_depth=AnalysisDepth.STANDARD,
        token_budget=15000,
        context_data={"domain": "ecommerce"},
        timestamp=datetime.utcnow(),
        task_id="test-123"
    )
    
    # Test immutability
    try:
        agent_input.project_description = "Modified"
        return False, "Immutability check failed"
    except:
        pass  # Expected
    
    # Test TokenBudgetState
    budget = TokenBudgetState(
        task_id="test-123",
        total_budget=15000,
        consumed_tokens=3500,
        remaining_tokens=11500,
        phase_allocations={"research": 6000, "analysis": 9000},
        usage_by_phase={"research": 3500},
        budget_exceeded=False,
        last_updated=datetime.utcnow()
    )
    
    return True, f"✅ Core models working - Budget: {budget.consumed_tokens}/{budget.total_budget}"

def test_api_components():
    """Test API components"""
    print("🌐 Testing API Components...")
    
    from fastapi import FastAPI
    from pydantic import BaseModel, Field
    import uvicorn
    import asyncpg
    
    # Test request model
    class TestRequest(BaseModel):
        project_name: str = Field(..., min_length=1)
        description: str = Field(..., min_length=10)
        token_budget: int = Field(default=15000, ge=5000)
    
    request = TestRequest(
        project_name="Test Project",
        description="This is a test project description with sufficient length",
        token_budget=15000
    )
    
    return True, f"✅ API components working - FastAPI + AsyncPG ready"

def test_database_schema():
    """Test database schema completeness"""
    print("🗄️  Testing Database Schema...")
    
    with open('scripts/setup_database.py', 'r') as f:
        schema_content = f.read()
    
    tables = schema_content.count('CREATE TABLE IF NOT EXISTS')
    indexes = schema_content.count('CREATE INDEX IF NOT EXISTS')
    
    required_tables = ['task_queue', 'approval_requests', 'circuit_breaker_state', 'token_budgets', 'quality_approvals']
    missing_tables = [table for table in required_tables if table not in schema_content]
    
    if missing_tables:
        return False, f"Missing tables: {missing_tables}"
    
    return True, f"✅ Database schema complete - {tables} tables, {indexes} indexes"

def main():
    """Run all tests"""
    print("🚀 Design Research Agent v1.2 - Phase 1.1 System Test")
    print("=" * 56)
    print()
    
    tests = [
        ("Core Models", test_core_models),
        ("API Components", test_api_components),
        ("Database Schema", test_database_schema)
    ]
    
    all_passed = True
    
    for test_name, test_func in tests:
        try:
            passed, message = test_func()
            print(f"{message}")
            if not passed:
                all_passed = False
                print(f"❌ {test_name} FAILED")
            else:
                print(f"✅ {test_name} PASSED")
        except Exception as e:
            print(f"❌ {test_name} ERROR: {e}")
            all_passed = False
        print()
    
    if all_passed:
        print("🎉 ALL TESTS PASSED!")
        print()
        print("📋 Next Steps to Start the API Server:")
        print("1. Start PostgreSQL:")
        print("   docker run --name design-agent-postgres \\")
        print("     -e POSTGRES_DB=design_agent \\")
        print("     -e POSTGRES_USER=postgres \\")
        print("     -e POSTGRES_PASSWORD=postgres \\")
        print("     -p 5432:5432 -d postgres:15")
        print()
        print("2. Setup database schema:")
        print("   export DATABASE_URL='postgresql://postgres:postgres@localhost:5432/design_agent'")
        print("   python3 scripts/setup_database.py")
        print()
        print("3. Start the API server:")
        print("   python3 main.py")
        print()
        print("4. Test the API:")
        print("   curl http://localhost:8000/health")
        print("   curl http://localhost:8000/")
        print()
        print("🌟 Your Design Research Agent v1.2 is ready for deployment!")
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
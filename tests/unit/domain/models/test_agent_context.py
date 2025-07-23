# tests/unit/domain/models/test_agent_context.py
import pytest
from datetime import datetime
from dataclasses import FrozenInstanceError

from domain.models.agent_context import (
    AgentInput, 
    AgentOutput, 
    ResearchContext, 
    RequirementsContext,
    AnalysisDepth
)

class TestAgentContext:
    """Test immutable context models"""
    
    def test_agent_input_immutability(self):
        """Test that AgentInput is truly immutable"""
        agent_input = AgentInput(
            project_description="Test project",
            analysis_depth=AnalysisDepth.STANDARD,
            token_budget=10000,
            context_data={"key": "value"},
            timestamp=datetime.utcnow(),
            task_id="test-task-123"
        )
        
        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(FrozenInstanceError):
            agent_input.project_description = "Modified"
        
        with pytest.raises(FrozenInstanceError):
            agent_input.token_budget = 20000

    def test_agent_output_immutability(self):
        """Test that AgentOutput is truly immutable"""
        agent_output = AgentOutput(
            success=True,
            data={"result": "test"},
            confidence_score=0.85,
            tokens_used=1500,
            execution_time_ms=2000,
            error_message=None,
            recommendations=["Test recommendation"]
        )
        
        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(FrozenInstanceError):
            agent_output.success = False
        
        with pytest.raises(FrozenInstanceError):
            agent_output.confidence_score = 0.9

    def test_research_context_immutability(self):
        """Test that ResearchContext is truly immutable"""
        research_context = ResearchContext(
            market_analysis={"market_size": "large"},
            technology_landscape={"recommended_tech": "Python"},
            best_practices=["Use HTTPS", "Validate inputs"],
            source_confidence=0.8,
            research_timestamp=datetime.utcnow(),
            source_urls=["https://example.com"]
        )
        
        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(FrozenInstanceError):
            research_context.source_confidence = 0.9

    def test_requirements_context_immutability(self):
        """Test that RequirementsContext is truly immutable"""
        requirements_context = RequirementsContext(
            functional_requirements=[{"req": "User login"}],
            non_functional_requirements=[{"req": "Performance"}],
            user_personas=[{"name": "Admin"}],
            business_constraints=[{"constraint": "Budget"}],
            quality_score=0.7,
            analysis_timestamp=datetime.utcnow()
        )
        
        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(FrozenInstanceError):
            requirements_context.quality_score = 0.8

    def test_context_data_mutation_protection(self):
        """Test that mutable data within contexts is protected"""
        context_data = {"mutable": "value"}
        
        agent_input = AgentInput(
            project_description="Test",
            analysis_depth=AnalysisDepth.QUICK,
            token_budget=5000,
            context_data=context_data,
            timestamp=datetime.utcnow(),
            task_id="test-task"
        )
        
        # Modifying original dict shouldn't affect the frozen context
        context_data["mutable"] = "changed"
        
        # The context should still have the original value
        assert agent_input.context_data["mutable"] == "value"

    def test_analysis_depth_enum(self):
        """Test AnalysisDepth enum values"""
        assert AnalysisDepth.QUICK.value == "quick"
        assert AnalysisDepth.STANDARD.value == "standard"
        assert AnalysisDepth.COMPREHENSIVE.value == "comprehensive"
        
        # Test enum comparison
        assert AnalysisDepth.STANDARD == AnalysisDepth.STANDARD
        assert AnalysisDepth.QUICK != AnalysisDepth.COMPREHENSIVE

    def test_agent_output_optional_fields(self):
        """Test AgentOutput with optional fields"""
        # Without optional fields
        output1 = AgentOutput(
            success=True,
            data={},
            confidence_score=0.5,
            tokens_used=100,
            execution_time_ms=500
        )
        
        assert output1.error_message is None
        assert output1.recommendations is None
        
        # With optional fields
        output2 = AgentOutput(
            success=False,
            data={},
            confidence_score=0.0,
            tokens_used=50,
            execution_time_ms=100,
            error_message="Test error",
            recommendations=["Fix this", "Try that"]
        )
        
        assert output2.error_message == "Test error"
        assert len(output2.recommendations) == 2

    def test_context_serialization_compatibility(self):
        """Test that contexts can be converted to dict for serialization"""
        agent_input = AgentInput(
            project_description="Test project",
            analysis_depth=AnalysisDepth.STANDARD,
            token_budget=10000,
            context_data={"key": "value"},
            timestamp=datetime.utcnow(),
            task_id="test-task-123"
        )
        
        # Should be able to convert to dict
        input_dict = agent_input.__dict__
        assert "project_description" in input_dict
        assert "analysis_depth" in input_dict
        assert input_dict["project_description"] == "Test project"

    def test_nested_context_immutability(self):
        """Test immutability of nested data structures"""
        research_context = ResearchContext(
            market_analysis={"trends": ["AI", "Cloud"]},
            technology_landscape={"languages": ["Python", "JavaScript"]},
            best_practices=["Security first", "Test everything"],
            source_confidence=0.85,
            research_timestamp=datetime.utcnow(),
            source_urls=["https://research1.com", "https://research2.com"]
        )
        
        # The context itself should be immutable
        with pytest.raises(FrozenInstanceError):
            research_context.source_confidence = 0.9
        
        # But the nested data should still be accessible
        assert "AI" in research_context.market_analysis["trends"]
        assert "Python" in research_context.technology_landscape["languages"]
        assert len(research_context.best_practices) == 2
        assert len(research_context.source_urls) == 2
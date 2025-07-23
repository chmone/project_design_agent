# infrastructure/agents/stateless_research_agent.py
from typing import Dict, Any
import asyncio
from datetime import datetime
from domain.models.agent_context import AgentInput, AgentOutput, ResearchContext
from infrastructure.resilience.circuit_breaker import CircuitBreaker
from shared.logging import logger, log_agent_execution

class StatelessResearchAgent:
    """Pure function research agent with web search capabilities"""
    
    def __init__(self, circuit_breaker: CircuitBreaker, web_tool=None):
        self.circuit_breaker = circuit_breaker
        self.web_tool = web_tool or MockWebResearchTool()

    async def transform(self, input_data: AgentInput) -> AgentOutput:
        """Pure transformation: project description → research findings"""
        start_time = datetime.utcnow()
        
        try:
            return await self.circuit_breaker.call(self._execute_research, input_data)
        except Exception as e:
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            log_agent_execution(
                agent_name="research_agent",
                task_id=input_data.task_id,
                execution_time_ms=execution_time,
                tokens_used=0,
                success=False,
                error_message=str(e)
            )
            
            return AgentOutput(
                success=False,
                data={},
                confidence_score=0.0,
                tokens_used=0,
                execution_time_ms=execution_time,
                error_message=str(e)
            )

    async def _execute_research(self, input_data: AgentInput) -> AgentOutput:
        start_time = datetime.utcnow()
        total_tokens = 0
        
        # Allocate token budget
        market_budget = int(input_data.token_budget * 0.4)  # 40% for market analysis
        tech_budget = int(input_data.token_budget * 0.4)    # 40% for tech landscape
        reserve_budget = input_data.token_budget - market_budget - tech_budget  # 20% reserve

        # Market analysis
        market_data = await self.web_tool.search_market_analysis(
            query=input_data.project_description,
            max_tokens=market_budget,
            analysis_depth=input_data.analysis_depth
        )
        total_tokens += market_data.tokens_used

        # Technology landscape analysis
        remaining_budget = tech_budget + reserve_budget - (total_tokens - market_data.tokens_used)
        tech_data = await self.web_tool.search_technology_landscape(
            query=input_data.project_description,
            max_tokens=max(remaining_budget, 1000),  # Minimum 1K tokens
            analysis_depth=input_data.analysis_depth
        )
        total_tokens += tech_data.tokens_used

        # Best practices research
        best_practices = market_data.best_practices + tech_data.best_practices
        
        # Calculate confidence based on data quality
        confidence = min(
            market_data.confidence * 0.5 + tech_data.confidence * 0.5,
            0.95  # Cap at 95% confidence
        )

        research_context = ResearchContext(
            market_analysis=market_data.findings,
            technology_landscape=tech_data.findings,
            best_practices=best_practices,
            source_confidence=confidence,
            research_timestamp=input_data.timestamp,
            source_urls=market_data.source_urls + tech_data.source_urls
        )

        execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        # Log successful execution
        log_agent_execution(
            agent_name="research_agent",
            task_id=input_data.task_id,
            execution_time_ms=execution_time,
            tokens_used=total_tokens,
            success=True,
            confidence_score=confidence
        )

        return AgentOutput(
            success=True,
            data=research_context.__dict__,
            confidence_score=confidence,
            tokens_used=total_tokens,
            execution_time_ms=execution_time,
            recommendations=[
                f"Review {len(market_data.source_urls)} market analysis sources",
                f"Validate {len(tech_data.source_urls)} technology recommendations",
                f"Consider budget allocation: used {total_tokens}/{input_data.token_budget} tokens"
            ]
        )


class MockWebResearchTool:
    """Mock web research tool for testing and development"""
    
    async def search_market_analysis(self, query: str, max_tokens: int, analysis_depth) -> 'MockSearchResult':
        # Simulate network delay
        await asyncio.sleep(0.1)
        
        # Mock market analysis based on project description keywords
        market_findings = self._generate_mock_market_data(query)
        
        tokens_used = min(max_tokens, 2000)  # Simulate token consumption
        
        return MockSearchResult(
            findings=market_findings,
            confidence=0.8,
            tokens_used=tokens_used,
            source_urls=[
                "https://example.com/market-report-1",
                "https://example.com/industry-analysis-2"
            ],
            best_practices=[
                "Follow industry security standards",
                "Implement scalable architecture patterns",
                "Use established payment processing solutions"
            ]
        )
    
    async def search_technology_landscape(self, query: str, max_tokens: int, analysis_depth) -> 'MockSearchResult':
        # Simulate network delay
        await asyncio.sleep(0.1)
        
        # Mock technology analysis
        tech_findings = self._generate_mock_tech_data(query)
        
        tokens_used = min(max_tokens, 1800)  # Simulate token consumption
        
        return MockSearchResult(
            findings=tech_findings,
            confidence=0.75,
            tokens_used=tokens_used,
            source_urls=[
                "https://example.com/tech-stack-guide",
                "https://example.com/architecture-patterns"
            ],
            best_practices=[
                "Use microservices for scalability",
                "Implement proper monitoring and logging",
                "Follow REST API design principles"
            ]
        )
    
    def _generate_mock_market_data(self, query: str) -> Dict[str, Any]:
        """Generate mock market analysis data"""
        
        # Simple keyword-based mock data generation
        if "ecommerce" in query.lower() or "store" in query.lower():
            return {
                "market_size": "$4.9 trillion global e-commerce market",
                "growth_rate": "14.7% CAGR",
                "key_trends": [
                    "Mobile commerce dominance",
                    "AI-powered personalization",
                    "Social commerce integration"
                ],
                "competitive_landscape": {
                    "major_players": ["Amazon", "Shopify", "WooCommerce"],
                    "market_share_leaders": "Amazon (38%), followed by specialized platforms"
                },
                "customer_expectations": [
                    "Fast loading times (<3 seconds)",
                    "Mobile-optimized experience",
                    "Secure payment processing",
                    "Easy returns and refunds"
                ]
            }
        else:
            return {
                "market_overview": "General software market analysis",
                "key_trends": [
                    "Cloud-first architecture", 
                    "API-driven development",
                    "User experience focus"
                ],
                "growth_indicators": "Positive growth in digital transformation",
                "customer_needs": [
                    "Reliable performance",
                    "Intuitive user interface",
                    "Data security and privacy"
                ]
            }
    
    def _generate_mock_tech_data(self, query: str) -> Dict[str, Any]:
        """Generate mock technology landscape data"""
        
        return {
            "recommended_stack": {
                "frontend": ["React", "Vue.js", "Next.js"],
                "backend": ["Node.js", "Python FastAPI", "Java Spring"],
                "database": ["PostgreSQL", "MongoDB", "Redis"],
                "cloud": ["AWS", "Google Cloud", "Azure"],
                "monitoring": ["DataDog", "New Relic", "Prometheus"]
            },
            "architecture_patterns": [
                "Microservices with API Gateway",
                "Event-driven architecture",
                "CQRS for complex domains"
            ],
            "security_considerations": [
                "OAuth 2.0 / JWT authentication",
                "HTTPS everywhere",
                "Input validation and sanitization",
                "Regular security audits"
            ],
            "scalability_factors": [
                "Horizontal scaling capabilities",
                "Database read replicas",
                "CDN for static assets",
                "Caching strategies"
            ]
        }


class MockSearchResult:
    """Mock search result for web research"""
    
    def __init__(self, findings: Dict[str, Any], confidence: float, 
                 tokens_used: int, source_urls: list, best_practices: list):
        self.findings = findings
        self.confidence = confidence
        self.tokens_used = tokens_used
        self.source_urls = source_urls
        self.best_practices = best_practices
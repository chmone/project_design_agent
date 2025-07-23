"""
Design Research Agent v1.2 - Stateless Architecture with Human Oversight

A CrewAI-based multi-agent system that transforms user ideas into comprehensive 
project artifacts through intelligent questioning, research, and analysis.

Features:
- Stateless agent architecture with immutable context models
- Circuit breaker pattern for fault tolerance
- Human oversight gates with quality validation
- Persistent task queue with PostgreSQL backend
- Token budget management with automatic cutoffs
"""

__version__ = "1.2.0"
__author__ = "Design Agent Team"
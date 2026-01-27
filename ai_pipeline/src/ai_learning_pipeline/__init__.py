"""
AI Learning Pipeline - Self-Learning System for IncidentFox.

This package implements the scheduled learning pipeline that:
1. Ingests knowledge from configured sources (Confluence, GitHub, etc.)
2. Processes pending knowledge teachings from agents
3. Runs maintenance tasks (decay, rebalancing, gap detection)
4. Generates improvement proposals for human review
"""

__version__ = "1.0.0"

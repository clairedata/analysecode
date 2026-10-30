"""
Couche Application de l'architecture hexagonale.

Contient les cas d'usage et les orchestrateurs (le Harness Engine).
Elle coordonne les flux entre le domaine, les ports d'outils et le port LLM.
"""

from analyscode.application.engine import DEFAULT_SYSTEM_PROMPT, AgentEngine

__all__ = ["AgentEngine", "DEFAULT_SYSTEM_PROMPT"]

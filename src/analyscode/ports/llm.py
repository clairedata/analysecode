"""
Port abstrait pour les Modèles de Langage (ports/llm.py).

Ce fichier définit la frontière hexagonale (Port secondaire) pour la communication avec les LLMs.
Il impose le contrat que tout adaptateur d'IA (OpenAI, Ollama, Claude, MockLLM) doit respecter.
"""

from abc import ABC, abstractmethod
from typing import Any

from analyscode.domain.models import ChatMessage, LLMResponse


class LLMError(Exception):
    """Exception de base déclenchée en cas d'erreur de communication avec un fournisseur LLM."""
    pass


class LLMPort(ABC):
    """
    Interface abstraite (Port secondaire) pour l'interrogation d'un Modèle de Langage.
    
    Le moteur d'orchestration de l'agent ne connaît QUE cette classe.
    Il ne sait jamais s'il dialogue avec un serveur OpenAI distant,
    un modèle Ollama local, ou un Mock de test en mémoire.
    """

    @abstractmethod
    def generate_response(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """
        Envoie l'historique des messages et la liste des outils disponibles au modèle.
        
        Args:
            messages: Liste ordonnée des messages de la conversation (system, user, assistant, tool).
            tools: Liste optionnelle des définitions d'outils au format JSON Schema
                   (générée par ToolRegistryPort.get_openai_tools()).
                   
        Returns:
            LLMResponse: La décision prise par le modèle (texte final ou liste de ToolCall).
            
        Raises:
            LLMError: En cas d'échec réseau, de quota épuisé ou de réponse invalide.
        """
        pass

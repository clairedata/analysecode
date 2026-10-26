"""
Modèles de données du Domaine (domain/models.py).

Définit la grammaire universelle et les structures de données neutres de l'agent :
- Rôles de conversation (Role).
- Appels d'outils formulés par le modèle (ToolCall).
- Messages de conversation (ChatMessage).
- Réponse d'un LLM lors d'un tour (LLMResponse).
- Compte rendu final d'analyse (AgentResponse).

Ces modèles sont 100% indépendants de tout fournisseur d'IA ou bibliothèque externe.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    """
    Rôle d'un émetteur de message dans la conversation avec l'agent.
    Hérite de 'str' pour faciliter la sérialisation JSON directe.
    """
    SYSTEM = "system"        # Directives de cadrage, règles de sécurité et format attendu
    USER = "user"            # L'instruction ou la question posée par le développeur
    ASSISTANT = "assistant"  # La réponse du LLM (texte ou demande d'appels d'outils)
    TOOL = "tool"            # Le résultat renvoyé par un outil après son exécution


@dataclass(frozen=True)
class ToolCall:
    """
    Représente la demande formelle du LLM d'exécuter un outil précis.
    
    Attributes:
        id: Identifiant unique attribué par le modèle (ex: 'call_12345').
            Indispensable pour associer ensuite le résultat de l'outil au bon appel.
        tool_name: Le nom de l'outil à invoquer (ex: 'read_file', 'run_pytest').
        arguments: Dictionnaire des paramètres décodés depuis le JSON du LLM.
    """
    id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    """
    Représente un message unitaire dans l'historique de conversation de l'agent.
    
    Attributes:
        role: Le rôle de l'émetteur (SYSTEM, USER, ASSISTANT, ou TOOL).
        content: Le contenu textuel du message (ex: prompt, explication, résultat d'outil).
        tool_calls: Liste d'outils demandés par le LLM (uniquement quand role == ASSISTANT).
        tool_call_id: Référence à l'appel d'outil concerné (uniquement quand role == TOOL).
    """
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None

    @classmethod
    def system(cls, content: str) -> "ChatMessage":
        """Fabrique un message système de cadrage."""
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> "ChatMessage":
        """Fabrique un message utilisateur."""
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(cls, content: str | None = None, tool_calls: list[ToolCall] | None = None) -> "ChatMessage":
        """Fabrique une réponse de l'assistant avec du texte et/ou des appels d'outils."""
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls or [])

    @classmethod
    def tool_result(cls, tool_call_id: str, content: str) -> "ChatMessage":
        """Fabrique un message contenant l'observation (résultat) renvoyée par un outil."""
        return cls(role=Role.TOOL, content=content, tool_call_id=tool_call_id)


@dataclass(frozen=True)
class LLMResponse:
    """
    Structure normalisée retournée par n'importe quel adaptateur LLM (OpenAI, Claude, Mock).
    
    Attributes:
        content: Texte explicatif ou réponse finale du LLM (None si le modèle n'a émis que des tool_calls).
        tool_calls: Liste des outils demandés par le modèle pour ce tour.
    """
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        """Retourne True si le modèle a demandé l'exécution d'au moins un outil."""
        return len(self.tool_calls) > 0


@dataclass(frozen=True)
class AgentResponse:
    """
    Compte rendu final retourné par le moteur de l'agent (Harness Engine) au développeur.
    
    Attributes:
        content: Le rapport complet d'analyse (Faits observés, Hypothèses, Propositions de correction).
        turns_count: Le nombre de tours de boucle ReAct effectués pour arriver au résultat.
        success: True si l'agent a complété son travail normalement, False si limite atteinte ou incident.
        error: Message explicatif en cas d'interruption anormale.
    """
    content: str
    turns_count: int
    success: bool
    error: str | None = None

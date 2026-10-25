"""
Contrats d'interface (Ports secondaires) pour les outils de l'agent.
Définit les abstractions nécessaires pour que le cœur de l'agent
puisse interagir avec n'importe quel ensemble d'outils sans dépendance concrète.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ToolResult:
    """
    Représente le résultat immuable de l'exécution d'un outil.
    
    Attributes:
        success: True si l'outil a fonctionné normalement, False en cas d'erreur ou d'échec.
        output: Le texte renvoyé par l'outil (contenu de fichier, sortie console, etc.).
        error: Message d'erreur éventuel en cas d'échec d'exécution ou violation de sécurité.
    """
    success: bool
    output: str
    error: str | None = None

    def to_content(self) -> str:
        """Formate le résultat pour être injecté comme contenu de message 'tool' dans la conversation."""
        if not self.success and self.error:
            return f"ERREUR: {self.error}\nSortie partielle:\n{self.output}".strip()
        return self.output


@dataclass
class ToolDefinition:
    """
    Métadonnées décrivant un outil, compatibles avec le standard OpenAI Function Calling.
    """
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_openai_schema(self) -> dict[str, Any]:
        """Convertit la définition en schéma attendu par l'API OpenAI dans le champ 'tools'."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class Tool(ABC):
    """
    Classe de base abstraite (Port) que tout outil doit implémenter.
    """

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """Retourne les métadonnées et le schéma de l'outil pour le LLM."""
        pass

    @abstractmethod
    def execute(self, arguments: Mapping[str, Any]) -> ToolResult:
        """
        Exécute l'outil avec les arguments fournis par le modèle.
        
        Args:
            arguments: Dictionnaire des paramètres décodés depuis le JSON du LLM.
            
        Returns:
            ToolResult: Résultat standardisé de l'exécution.
        """
        pass


class ToolRegistryPort(ABC):
    """
    Interface du registre d'outils.
    Permet à l'agent de découvrir et d'invoquer les outils disponibles.
    """

    @abstractmethod
    def register(self, tool: Tool) -> None:
        """Enregistre un nouvel outil dans le registre."""
        pass

    @abstractmethod
    def get(self, tool_name: str) -> Tool | None:
        """Récupère un outil par son nom."""
        pass

    @abstractmethod
    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Génère la liste de tous les outils au format JSON Schema attendu par OpenAI."""
        pass

    @abstractmethod
    def execute(self, tool_name: str, arguments: Mapping[str, Any]) -> ToolResult:
        """Exécute l'outil désigné de façon sécurisée."""
        pass

"""
Registre d'outils par défaut (registry.py).

Implémente ToolRegistryPort pour rassembler, documenter pour OpenAI
et invoquer tous les outils disponibles pour l'agent.
"""

from pathlib import Path
from typing import Any, Mapping

from analyscode.adapters.tools.fs import ListDirTool, ReadFileTool, SearchCodeTool
from analyscode.adapters.tools.pytest_runner import PytestRunnerTool
from analyscode.domain.security import SafeCommandValidator, SafePathValidator
from analyscode.ports.tools import Tool, ToolRegistryPort, ToolResult


class DefaultToolRegistry(ToolRegistryPort):
    """
    Registre d'outils concret qui stocke les instances de Tool,
    génère les schémas pour le LLM et exécute les appels demandés.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Enregistre un outil dans le dictionnaire interne."""
        name = tool.definition.name
        if name in self._tools:
            raise ValueError(f"Un outil nommé '{name}' est déjà enregistré.")
        self._tools[name] = tool

    def get(self, tool_name: str) -> Tool | None:
        """Récupère un outil par son nom."""
        return self._tools.get(tool_name)

    def list_tools(self) -> list[Tool]:
        """Retourne la liste de tous les outils enregistrés."""
        return list(self._tools.values())

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Génère la liste complète des définitions au format JSON Schema attendu par OpenAI."""
        return [tool.definition.to_openai_schema() for tool in self._tools.values()]

    def execute(self, tool_name: str, arguments: Mapping[str, Any]) -> ToolResult:
        """
        Recherche l'outil demandé et l'exécute avec les arguments fournis.
        Garantit qu'aucun crash Python inopiné ne casse le moteur de l'agent.
        """
        tool = self.get(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Outil inconnu '{tool_name}'. Outils disponibles : {list(self._tools.keys())}",
            )

        try:
            return tool.execute(arguments)
        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Erreur inattendue lors de l'exécution de l'outil '{tool_name}' : {exc}",
            )


def create_default_registry(project_root: str | Path) -> DefaultToolRegistry:
    """
    Fonction usine (Factory) qui initialise la sécurité et enregistre tous les outils du MVP.
    
    Args:
        project_root: Racine du projet Python à analyser.
        
    Returns:
        DefaultToolRegistry: Registre configuré et prêt à l'emploi.
    """
    path_validator = SafePathValidator(project_root)
    cmd_validator = SafeCommandValidator(path_validator)
    root_resolved = path_validator.root_path

    registry = DefaultToolRegistry()
    registry.register(ListDirTool(path_validator))
    registry.register(ReadFileTool(path_validator))
    registry.register(SearchCodeTool(path_validator))
    registry.register(PytestRunnerTool(cmd_validator, project_root=root_resolved))

    return registry

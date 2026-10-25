"""
Adaptateur d'exécution de tests (pytest_runner.py).

Permet à l'agent d'exécuter pytest de manière totalement contrôlée :
- Pas de shell système (shell=False).
- Validation stricte des arguments via SafeCommandValidator.
- Timeout strict pour couper court à d'éventuelles boucles infinies dans le code testé.
- Confinement dans le répertoire de travail du projet analysé (cwd=project_root).
"""

from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

from analyscode.domain.security import SafeCommandValidator, SecurityError
from analyscode.ports.tools import Tool, ToolDefinition, ToolResult


class PytestRunnerTool(Tool):
    """
    Outil permettant à l'agent d'exécuter pytest sur le projet cible.
    """

    # Durée maximale en secondes allouée à une exécution de tests
    DEFAULT_TIMEOUT_SECONDS = 30

    def __init__(
        self,
        cmd_validator: SafeCommandValidator,
        project_root: Path,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._cmd_validator = cmd_validator
        self._project_root = project_root
        self._timeout_seconds = timeout_seconds

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="run_pytest",
            description=(
                "Exécute pytest sur le projet cible pour vérifier l'état des tests. "
                "Permet de cibler un fichier de test spécifique ou de filtrer par nom."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "test_path": {
                        "type": "string",
                        "description": "Chemin relatif du fichier ou dossier de test à exécuter (ex: 'tests/test_auth.py').",
                    },
                    "filter_expr": {
                        "type": "string",
                        "description": "Filtre d'expression pour -k (ex: 'test_login and not slow').",
                    },
                    "extra_args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Options supplémentaires pytest autorisées (ex: ['-v', '--tb=short']).",
                    },
                },
                "required": [],
            },
        )

    def execute(self, arguments: Mapping[str, Any]) -> ToolResult:
        raw_args: list[str] = []

        test_path = arguments.get("test_path")
        if test_path:
            raw_args.append(str(test_path).strip())

        filter_expr = arguments.get("filter_expr")
        if filter_expr:
            raw_args.extend(["-k", str(filter_expr).strip()])

        extra_args = arguments.get("extra_args")
        if extra_args and isinstance(extra_args, list):
            for arg in extra_args:
                raw_args.append(str(arg).strip())

        try:
            # 1. Validation de sécurité obligatoire
            safe_args = self._cmd_validator.validate_pytest_args(raw_args)

            # 2. Construction de la commande finale
            # On utilise l'exécutable Python courant avec -m pytest
            command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider"] + safe_args

            # 3. Exécution avec timeout et sans shell
            process = subprocess.run(
                command,
                cwd=str(self._project_root),
                capture_output=True,
                text=True,
                shell=False,
                timeout=self._timeout_seconds,
            )

            # Combinaison propre de stdout et stderr
            output_parts: list[str] = []
            if process.stdout:
                output_parts.append(process.stdout.strip())
            if process.stderr:
                output_parts.append("[STDERR]\n" + process.stderr.strip())

            full_output = "\n\n".join(output_parts) if output_parts else "[Aucune sortie produite]"

            # Pytest returncode : 0 = Tous les tests passent, 1 = Échecs de tests, >1 = Erreurs d'exécution/syntaxe
            is_success = (process.returncode == 0)

            return ToolResult(
                success=is_success,
                output=full_output,
                error=None if is_success else f"pytest s'est terminé avec le code retour {process.returncode}."
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Délai d'exécution dépassé ({self._timeout_seconds} secondes). Les tests sont trop lents ou bloquants."
            )
        except SecurityError as sec_err:
            return ToolResult(
                success=False,
                output="",
                error=f"Violation de sécurité : {sec_err}"
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Erreur lors du lancement de pytest : {exc}"
            )

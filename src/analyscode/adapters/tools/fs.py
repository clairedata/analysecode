"""
Adaptateurs d'outils pour le système de fichiers (fs.py).

Fournit les outils concrets :
- ListDirTool : exploration arborescente du projet cible.
- ReadFileTool : lecture paginée avec numéros de lignes (protège la fenêtre de contexte).
- SearchCodeTool : recherche textuelle ou par regex dans le code source.

Tous ces outils utilisent obligatoirement SafePathValidator pour garantir
l'impossibilité physique de sortir du projet cible.
"""

from pathlib import Path
import re
from typing import Any, Mapping

from analyscode.domain.security import SafePathValidator, SecurityError
from analyscode.ports.tools import Tool, ToolDefinition, ToolResult


# Dossiers et extensions systématiquement ignorés pour économiser les tokens
DEFAULT_EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".idea", ".vscode", "build", "dist", ".egg-info"
}
DEFAULT_TEXT_EXTENSIONS = {
    ".py", ".toml", ".json", ".md", ".txt", ".yaml", ".yml",
    ".ini", ".cfg", ".sql", ".html", ".css", ".js", ".sh"
}


class ListDirTool(Tool):
    """Outil permettant à l'agent d'explorer l'arborescence des fichiers du projet."""

    def __init__(self, path_validator: SafePathValidator) -> None:
        self._path_validator = path_validator

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_dir",
            description=(
                "Liste les fichiers et sous-dossiers d'un répertoire dans le projet. "
                "Exclut automatiquement les dossiers parasites (.git, .venv, __pycache__)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "relative_path": {
                        "type": "string",
                        "description": "Chemin relatif du dossier à inspecter (défaut : racine du projet '.').",
                        "default": ".",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Profondeur maximale d'exploration (défaut : 2).",
                        "default": 2,
                    },
                },
                "required": [],
            },
        )

    def execute(self, arguments: Mapping[str, Any]) -> ToolResult:
        rel_path = arguments.get("relative_path", ".")
        max_depth = int(arguments.get("max_depth", 2))

        try:
            target_dir = self._path_validator.validate_path(rel_path)
            if not target_dir.exists():
                return ToolResult(success=False, output="", error=f"Le dossier '{rel_path}' n'existe pas.")
            if not target_dir.is_dir():
                return ToolResult(success=False, output="", error=f"'{rel_path}' n'est pas un dossier.")

            lines: list[str] = []
            root_path = self._path_validator.root_path

            def _explore(current: Path, current_depth: int) -> None:
                if current_depth > max_depth:
                    return

                try:
                    entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                except PermissionError as err:
                    lines.append(f"  [Accès refusé]: {err}")
                    return

                for entry in entries:
                    if entry.name in DEFAULT_EXCLUDED_DIRS:
                        continue

                    rel_entry = entry.relative_to(root_path)
                    indent = "  " * current_depth

                    if entry.is_dir():
                        lines.append(f"{indent}[DIR]  {rel_entry.as_posix()}/")
                        _explore(entry, current_depth + 1)
                    else:
                        size_kb = max(1, entry.stat().st_size // 1024)
                        lines.append(f"{indent}[FILE] {rel_entry.as_posix()} ({size_kb} KB)")

            _explore(target_dir, current_depth=0)

            if not lines:
                return ToolResult(success=True, output=f"Le dossier '{rel_path}' est vide ou ne contient que des éléments exclus.")

            return ToolResult(success=True, output="\n".join(lines))

        except SecurityError as sec_err:
            return ToolResult(success=False, output="", error=str(sec_err))
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Erreur inattendue lors du listage : {exc}")


class ReadFileTool(Tool):
    """
    Outil de lecture paginée de fichier texte.
    
    Affiche les lignes avec préfixe 'L<numero>: ' pour que le LLM
    puisse facilement citer les numéros de lignes cibles dans ses correctifs.
    """

    # Plafond strict pour éviter de faire déborder le contexte du LLM
    HARD_MAX_LINES = 300

    def __init__(self, path_validator: SafePathValidator) -> None:
        self._path_validator = path_validator

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description=(
                "Lit le contenu d'un fichier texte avec numérotation des lignes (ex: L12: ...). "
                "Permet de lire tout le fichier ou une plage ciblée (start_line, end_line)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Chemin relatif du fichier à lire (ex: 'src/module.py').",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Numéro de ligne de début (1-indexé, optionnel).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Numéro de ligne de fin (inclus, optionnel).",
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(self, arguments: Mapping[str, Any]) -> ToolResult:
        file_path_str = arguments.get("file_path")
        if not file_path_str:
            return ToolResult(success=False, output="", error="Le paramètre 'file_path' est obligatoire.")

        start_line = arguments.get("start_line")
        end_line = arguments.get("end_line")

        try:
            target_file = self._path_validator.validate_path(file_path_str)
            if not target_file.exists():
                return ToolResult(success=False, output="", error=f"Le fichier '{file_path_str}' n'existe pas.")
            if not target_file.is_file():
                return ToolResult(success=False, output="", error=f"'{file_path_str}' n'est pas un fichier régulier.")

            # Lecture avec gestion sécurisée des encodages
            try:
                content = target_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = target_file.read_text(encoding="utf-8", errors="replace")

            all_lines = content.splitlines()
            total_lines = len(all_lines)

            # Détermination de la plage de lecture
            s_idx = max(1, int(start_line)) if start_line is not None else 1
            e_idx = min(total_lines, int(end_line)) if end_line is not None else total_lines

            if s_idx > total_lines:
                return ToolResult(
                    success=True,
                    output=f"[Fichier {file_path_str} : start_line {s_idx} dépasse le nombre total de lignes ({total_lines})]"
                )

            # Tranche sélectionnée
            selected_lines = all_lines[s_idx - 1 : e_idx]

            # Vérification du plafond pour ne pas saturer le contexte
            if len(selected_lines) > self.HARD_MAX_LINES:
                selected_lines = selected_lines[: self.HARD_MAX_LINES]
                truncated_note = f"\n... [Tronqué : {self.HARD_MAX_LINES} lignes affichées sur {len(all_lines)}. Utilisez start_line/end_line pour lire la suite]"
            else:
                truncated_note = ""

            # Formatage avec préfixe de ligne
            numbered_lines = [
                f"L{s_idx + i}: {line}"
                for i, line in enumerate(selected_lines)
            ]

            output = f"--- {file_path_str} (Total: {total_lines} lignes) ---\n" + "\n".join(numbered_lines) + truncated_note
            return ToolResult(success=True, output=output)

        except SecurityError as sec_err:
            return ToolResult(success=False, output="", error=str(sec_err))
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Erreur de lecture : {exc}")


class SearchCodeTool(Tool):
    """
    Outil de recherche textuelle ou par expression régulière dans les fichiers source.
    Permet à l'agent de trouver où une fonction, une classe ou une variable est définie/utilisée.
    """

    MAX_MATCHES = 30

    def __init__(self, path_validator: SafePathValidator) -> None:
        self._path_validator = path_validator

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_code",
            description=(
                "Recherche un terme, nom de fonction, ou motif regex dans les fichiers source du projet. "
                "Retourne le fichier, le numéro de ligne et l'extrait trouvé."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Le texte ou regex à rechercher.",
                    },
                    "relative_path": {
                        "type": "string",
                        "description": "Sous-dossier dans lequel limiter la recherche (optionnel, défaut : '.').",
                        "default": ".",
                    },
                },
                "required": ["query"],
            },
        )

    def execute(self, arguments: Mapping[str, Any]) -> ToolResult:
        query = arguments.get("query")
        if not query:
            return ToolResult(success=False, output="", error="Le paramètre 'query' est obligatoire.")

        rel_path = arguments.get("relative_path", ".")

        try:
            target_dir = self._path_validator.validate_path(rel_path)
            if not target_dir.exists():
                return ToolResult(success=False, output="", error=f"Le chemin '{rel_path}' n'existe pas.")

            try:
                regex = re.compile(query, re.IGNORECASE)
            except re.error as reg_err:
                return ToolResult(success=False, output="", error=f"Expression régulière invalide : {reg_err}")

            root_path = self._path_validator.root_path
            matches: list[str] = []

            # Recherche récursive dans les fichiers textes autorisés
            for file_path in target_dir.rglob("*"):
                # Ignorer les dossiers ou les fichiers binaires/exclus
                if any(part in DEFAULT_EXCLUDED_DIRS for part in file_path.parts):
                    continue
                if not file_path.is_file() or file_path.suffix.lower() not in DEFAULT_TEXT_EXTENSIONS:
                    continue

                try:
                    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
                except Exception:
                    continue

                rel_file = file_path.relative_to(root_path).as_posix()

                for line_idx, line in enumerate(lines, start=1):
                    if regex.search(line):
                        matches.append(f"{rel_file}:L{line_idx}: {line.strip()[:150]}")
                        if len(matches) >= self.MAX_MATCHES:
                            break

                if len(matches) >= self.MAX_MATCHES:
                    break

            if not matches:
                return ToolResult(success=True, output=f"Aucune occurrence trouvée pour : '{query}'")

            header = f"Trouvé {len(matches)} occurrence(s) pour '{query}'"
            if len(matches) >= self.MAX_MATCHES:
                header += f" (limité à {self.MAX_MATCHES} résultats) :"
            else:
                header += " :"

            return ToolResult(success=True, output=header + "\n" + "\n".join(matches))

        except SecurityError as sec_err:
            return ToolResult(success=False, output="", error=str(sec_err))
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Erreur lors de la recherche : {exc}")

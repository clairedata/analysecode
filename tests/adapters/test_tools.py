"""
Tests unitaires des adaptateurs d'outils (fs, pytest_runner, registry).

Vérifie le fonctionnement de chaque outil sur un projet Python factice
et s'assure que la sécurité et la robustesse sont préservées en toutes circonstances.
"""

from pathlib import Path
import pytest

from analyscode.adapters.tools.fs import ListDirTool, ReadFileTool, SearchCodeTool
from analyscode.adapters.tools.pytest_runner import PytestRunnerTool
from analyscode.adapters.tools.registry import create_default_registry, DefaultToolRegistry
from analyscode.domain.security import SafeCommandValidator, SafePathValidator


@pytest.fixture
def mock_target_project(tmp_path: Path) -> Path:
    """
    RÔLE :
    Crée un projet Python factice complet et isolé dans un dossier temporaire pour servir de cobaye.
    Ce projet contient un bug intentionnel (division par zéro dans `divide(10, 0)`).

    QUAND CETTE FIXTURE EST-ELLE APPELÉE ?
    Exécutée automatiquement par pytest avant chaque fonction de test qui la déclare en paramètre,
    garantissant que chaque test s'exécute dans un environnement propre et sans effet de bord.
    """
    proj = tmp_path / "sample_app"
    proj.mkdir()

    # Dossier src contenant le code source
    src = proj / "src"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "math_utils.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n\n"
        "def divide(a, b):\n"
        "    # Intentionnellement sans vérification pour tester les bugs\n"
        "    return a / b\n",
        encoding="utf-8",
    )

    # Dossier tests contenant les tests du projet cible
    tests = proj / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_math.py").write_text(
        "from src.math_utils import add, divide\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n\n"
        "def test_divide_fail():\n"
        "    assert divide(10, 0) == 0  # Doit lever ZeroDivisionError\n",
        encoding="utf-8",
    )

    # Dossier parasite (.git) devant obligatoirement être ignoré par l'agent
    git_dir = proj / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

    return proj


# ==============================================================================
# Tests pour ListDirTool
# ==============================================================================

def test_list_dir_success_and_ignore_git(mock_target_project: Path) -> None:
    """
    RÔLE :
    Vérifie que l'outil `list_dir` liste fidèlement les dossiers utiles (`src`, `tests`)
    tout en filtrant automatiquement les dossiers parasites (`.git`, `.venv`, etc.).

    DANS QUEL CAS L'AGENT APPELLE CET OUTIL ?
    Au tout début d'une mission d'analyse ou d'onboarding, lorsque l'agent a besoin
    de cartographier la structure globale du projet sans saturer sa mémoire de fichiers inutiles.
    """
    path_val = SafePathValidator(mock_target_project)
    tool = ListDirTool(path_val)

    result = tool.execute({"relative_path": "."})
    assert result.success is True
    # Doit contenir les dossiers sources et tests
    assert "src" in result.output
    assert "tests" in result.output
    # Doit impérativement exclure .git
    assert ".git" not in result.output


def test_list_dir_block_outside_traversal(mock_target_project: Path) -> None:
    """
    RÔLE :
    Vérifie que `list_dir` bloque immédiatement toute tentative de naviguer hors de la racine
    du projet via des chemins relatifs suspects (ex: `../`).

    DANS QUEL CAS CE SCÉNARIO SE PRODUIT ?
    Si le LLM hallucine ou tente d'explorer le système d'exploitation hôte en dehors du projet
    assigné. L'outil doit intercepter l'erreur sans faire crasher l'agent.
    """
    path_val = SafePathValidator(mock_target_project)
    tool = ListDirTool(path_val)

    result = tool.execute({"relative_path": "../"})
    assert result.success is False
    assert "Accès refusé" in (result.error or "")


# ==============================================================================
# Tests pour ReadFileTool
# ==============================================================================

def test_read_file_full_and_numbered(mock_target_project: Path) -> None:
    """
    RÔLE :
    Vérifie que `read_file` lit le contenu d'un fichier et préfixe chaque ligne
    avec son numéro sous la forme `L<numero>: ` (ex: `L1: def add...`).

    DANS QUEL CAS L'AGENT APPELLE CET OUTIL ?
    Quand l'agent a repéré un fichier suspect ou un fichier de test et doit lire son implémentation
    pour pouvoir citer avec exactitude les lignes cibles dans sa proposition de correction.
    """
    path_val = SafePathValidator(mock_target_project)
    tool = ReadFileTool(path_val)

    result = tool.execute({"file_path": "src/math_utils.py"})
    assert result.success is True
    assert "L1: def add(a, b):" in result.output
    assert "L5: def divide(a, b):" in result.output


def test_read_file_pagination(mock_target_project: Path) -> None:
    """
    RÔLE :
    Vérifie le mécanisme de pagination de `read_file` via les paramètres `start_line` et `end_line`.

    DANS QUEL CAS L'AGENT APPELLE CET OUTIL ?
    Quand un fichier est volumineux (ex: 500 lignes) et que l'agent ne souhaite inspecter
    qu'une fonction précise (ex: lignes 40 à 60) pour économiser des tokens et rester rapide.
    """
    path_val = SafePathValidator(mock_target_project)
    tool = ReadFileTool(path_val)

    # Lire uniquement les lignes 4 à 6
    result = tool.execute({"file_path": "src/math_utils.py", "start_line": 4, "end_line": 6})
    assert result.success is True
    assert "L4: " in result.output
    assert "L5: def divide(a, b):" in result.output
    assert "L6: " in result.output
    # La ligne 1 ne doit pas être présente dans le résultat
    assert "L1: " not in result.output


def test_read_file_not_found(mock_target_project: Path) -> None:
    """
    RÔLE :
    Vérifie la robustesse de `read_file` lorsqu'on lui demande un fichier qui n'existe pas.

    DANS QUEL CAS CE SCÉNARIO SE PRODUIT ?
    Si le LLM se trompe dans le nom d'un module ou suppose l'existence d'un fichier.
    L'outil doit renvoyer une erreur explicite dans `result.error` sans interrompre le programme Python,
    ce qui permet à l'agent de comprendre son erreur et de réajuster sa recherche au tour suivant.
    """
    path_val = SafePathValidator(mock_target_project)
    tool = ReadFileTool(path_val)

    result = tool.execute({"file_path": "src/inexistant.py"})
    assert result.success is False
    assert "n'existe pas" in (result.error or "")


# ==============================================================================
# Tests pour SearchCodeTool
# ==============================================================================

def test_search_code_finds_symbol(mock_target_project: Path) -> None:
    """
    RÔLE :
    Vérifie que `search_code` retrouve une définition de fonction ou une variable
    et retourne son fichier et son numéro de ligne exact.

    DANS QUEL CAS L'AGENT APPELLE CET OUTIL ?
    Quand l'agent cherche où une fonction mentionnée dans une erreur de test est déclarée,
    ou quand l'utilisateur demande : « Où est implémentée la logique de calcul de prix ? ».
    Cela lui évite de devoir lire tous les fichiers un par un.
    """
    path_val = SafePathValidator(mock_target_project)
    tool = SearchCodeTool(path_val)

    result = tool.execute({"query": "def divide"})
    assert result.success is True
    assert "math_utils.py" in result.output
    assert "L5:" in result.output


def test_search_code_no_match(mock_target_project: Path) -> None:
    """
    RÔLE :
    Vérifie que `search_code` réagit calmement quand aucun résultat ne correspond à la requête.

    DANS QUEL CAS CE SCÉNARIO SE PRODUIT ?
    Quand l'agent cherche un symbole ou un mot-clé qui n'existe pas dans le projet.
    L'outil renvoie un message informatif propre (« Aucune occurrence ») au lieu d'un crash.
    """
    path_val = SafePathValidator(mock_target_project)
    tool = SearchCodeTool(path_val)

    result = tool.execute({"query": "non_existent_symbol_12345"})
    assert result.success is True
    assert "Aucune occurrence" in result.output


# ==============================================================================
# Tests pour PytestRunnerTool
# ==============================================================================

def test_pytest_runner_detects_test_failure(mock_target_project: Path) -> None:
    """
    RÔLE :
    Vérifie que `run_pytest` exécute réellement pytest sur le projet cible, détecte un échec
    de test (code de retour non nul) et capture fidèlement la trace de l'erreur (ZeroDivisionError).

    DANS QUEL CAS L'AGENT APPELLE CET OUTIL ?
    Quand l'utilisateur demande : « Lance les tests et dis-moi pourquoi ça échoue ».
    L'agent s'appuie sur la sortie réelle de cette commande pour établir ses Faits observés
    sans jamais inventer ou halluciner de résultats.
    """
    path_val = SafePathValidator(mock_target_project)
    cmd_val = SafeCommandValidator(path_val)
    runner = PytestRunnerTool(cmd_val, project_root=mock_target_project)

    # Lance tous les tests du projet factice (test_divide_fail doit échouer)
    result = runner.execute({})
    assert result.success is False  # Code retour != 0
    assert "FAILED" in result.output or "ZeroDivisionError" in result.output


def test_pytest_runner_targeted_test_pass(mock_target_project: Path) -> None:
    """
    RÔLE :
    Vérifie que `run_pytest` supporte le filtrage d'un test spécifique (ex: `-k test_add`)
    et remonte un statut de succès (`success=True`) lorsque ce test passe.

    DANS QUEL CAS L'AGENT APPELLE CET OUTIL ?
    Quand l'agent souhaite vérifier si un test particulier réussit isolément,
    ou pour valider une hypothèse sur une seule fonction sans relancer tous les tests du projet.
    """
    path_val = SafePathValidator(mock_target_project)
    cmd_val = SafeCommandValidator(path_val)
    runner = PytestRunnerTool(cmd_val, project_root=mock_target_project)

    # Filtrer uniquement sur le test qui réussit (test_add)
    result = runner.execute({"filter_expr": "test_add"})
    assert result.success is True
    assert "1 passed" in result.output


# ==============================================================================
# Tests pour DefaultToolRegistry
# ==============================================================================

def test_tool_registry_openai_schemas_and_dispatch(mock_target_project: Path) -> None:
    """
    RÔLE :
    Vérifie que le registre d'outils (`DefaultToolRegistry`) :
    1. Enregistre bien les 4 outils du MVP (`list_dir`, `read_file`, `search_code`, `run_pytest`).
    2. Génère correctement les spécifications JSON Schema attendues par l'API OpenAI.
    3. Route et exécute correctement les outils demandés.
    4. Répond proprement avec un message d'erreur si un outil inconnu est demandé.

    DANS QUEL CAS CE COMPOSANT INTERVIENT ?
    C'est la tour de contrôle utilisée par le moteur du harness (`engine.py`) à chaque tour
    de conversation avec le LLM.
    """
    registry = create_default_registry(mock_target_project)

    # 1. Vérifie que les 4 outils sont bien enregistrés
    tools = registry.list_tools()
    tool_names = {t.definition.name for t in tools}
    assert tool_names == {"list_dir", "read_file", "search_code", "run_pytest"}

    # 2. Vérifie la génération du schéma OpenAI
    schemas = registry.get_openai_tools()
    assert len(schemas) == 4
    for schema in schemas:
        assert schema["type"] == "function"
        assert "name" in schema["function"]
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]

    # 3. Test de dispatch d'exécution
    res = registry.execute("read_file", {"file_path": "src/math_utils.py", "start_line": 1, "end_line": 2})
    assert res.success is True

    # 4. Outil inconnu
    res_unknown = registry.execute("unregistered_tool", {})
    assert res_unknown.success is False
    assert "Outil inconnu" in (res_unknown.error or "")

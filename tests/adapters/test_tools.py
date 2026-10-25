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
    """Crée une structure de projet Python complète et factice."""
    proj = tmp_path / "sample_app"
    proj.mkdir()

    # Dossier src
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

    # Dossier tests
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

    # Dossier parasite à ignorer
    git_dir = proj / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

    return proj


# ==============================================================================
# Tests pour ListDirTool
# ==============================================================================

def test_list_dir_success_and_ignore_git(mock_target_project: Path) -> None:
    path_val = SafePathValidator(mock_target_project)
    tool = ListDirTool(path_val)

    result = tool.execute({"relative_path": "."})
    assert result.success is True
    # Doit contenir src et tests
    assert "src" in result.output
    assert "tests" in result.output
    # Doit impérativement exclure .git
    assert ".git" not in result.output


def test_list_dir_block_outside_traversal(mock_target_project: Path) -> None:
    path_val = SafePathValidator(mock_target_project)
    tool = ListDirTool(path_val)

    result = tool.execute({"relative_path": "../"})
    assert result.success is False
    assert "Accès refusé" in (result.error or "")


# ==============================================================================
# Tests pour ReadFileTool
# ==============================================================================

def test_read_file_full_and_numbered(mock_target_project: Path) -> None:
    path_val = SafePathValidator(mock_target_project)
    tool = ReadFileTool(path_val)

    result = tool.execute({"file_path": "src/math_utils.py"})
    assert result.success is True
    assert "L1: def add(a, b):" in result.output
    assert "L5: def divide(a, b):" in result.output


def test_read_file_pagination(mock_target_project: Path) -> None:
    path_val = SafePathValidator(mock_target_project)
    tool = ReadFileTool(path_val)

    # Lire uniquement les lignes 4 à 6
    result = tool.execute({"file_path": "src/math_utils.py", "start_line": 4, "end_line": 6})
    assert result.success is True
    assert "L4: " in result.output
    assert "L5: def divide(a, b):" in result.output
    assert "L6: " in result.output
    # La ligne 1 ne doit pas être dans le résultat
    assert "L1: " not in result.output


def test_read_file_not_found(mock_target_project: Path) -> None:
    path_val = SafePathValidator(mock_target_project)
    tool = ReadFileTool(path_val)

    result = tool.execute({"file_path": "src/inexistant.py"})
    assert result.success is False
    assert "n'existe pas" in (result.error or "")


# ==============================================================================
# Tests pour SearchCodeTool
# ==============================================================================

def test_search_code_finds_symbol(mock_target_project: Path) -> None:
    path_val = SafePathValidator(mock_target_project)
    tool = SearchCodeTool(path_val)

    result = tool.execute({"query": "def divide"})
    assert result.success is True
    assert "math_utils.py" in result.output
    assert "L5:" in result.output


def test_search_code_no_match(mock_target_project: Path) -> None:
    path_val = SafePathValidator(mock_target_project)
    tool = SearchCodeTool(path_val)

    result = tool.execute({"query": "non_existent_symbol_12345"})
    assert result.success is True
    assert "Aucune occurrence" in result.output


# ==============================================================================
# Tests pour PytestRunnerTool
# ==============================================================================

def test_pytest_runner_detects_test_failure(mock_target_project: Path) -> None:
    path_val = SafePathValidator(mock_target_project)
    cmd_val = SafeCommandValidator(path_val)
    runner = PytestRunnerTool(cmd_val, project_root=mock_target_project)

    # Lance tous les tests du projet factice (test_divide_fail doit échouer)
    result = runner.execute({})
    assert result.success is False  # Code retour != 0
    assert "FAILED" in result.output or "ZeroDivisionError" in result.output


def test_pytest_runner_targeted_test_pass(mock_target_project: Path) -> None:
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

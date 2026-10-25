"""
Tests unitaires pour le module de sécurité (SafePathValidator et SafeCommandValidator).

Ces tests vérifient de manière exhaustive que les barrières de sécurité
fonctionnent parfaitement pour les cas normaux, les cas limites et les tentatives d'attaques.
"""

from pathlib import Path
import pytest

from analyscode.domain.security import (
    SafePathValidator,
    SafeCommandValidator,
    PathTraversalError,
    CommandInjectionError,
)


# ==============================================================================
# Fixtures pour les tests
# ==============================================================================

@pytest.fixture
def dummy_project(tmp_path: Path) -> Path:
    """Crée une arborescence de projet cible fictive dans un dossier temporaire."""
    project_dir = tmp_path / "target_project"
    project_dir.mkdir()

    # Création de sous-dossiers et fichiers factices
    src_dir = project_dir / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('app')", encoding="utf-8")

    tests_dir = project_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text("def test_dummy(): pass", encoding="utf-8")

    return project_dir


@pytest.fixture
def path_validator(dummy_project: Path) -> SafePathValidator:
    """Fournit une instance de SafePathValidator configurée sur le projet factice."""
    return SafePathValidator(dummy_project)


@pytest.fixture
def cmd_validator(path_validator: SafePathValidator) -> SafeCommandValidator:
    """Fournit une instance de SafeCommandValidator."""
    return SafeCommandValidator(path_validator)


# ==============================================================================
# Tests pour SafePathValidator (Confinement de chemin)
# ==============================================================================

class TestSafePathValidator:
    def test_init_raises_error_when_root_does_not_exist(self, tmp_path: Path) -> None:
        """Vérifie qu'une racine inexistante lève immédiatement une exception FileNotFoundError."""
        non_existent = tmp_path / "does_not_exist"
        with pytest.raises(FileNotFoundError):
            SafePathValidator(non_existent)

    def test_allow_valid_relative_paths(
        self, path_validator: SafePathValidator, dummy_project: Path
    ) -> None:
        """Vérifie que les chemins relatifs valides internes au projet sont autorisés et résolus."""
        # Fichier à la racine
        assert path_validator.validate_path(".") == dummy_project
        # Sous-dossier
        assert path_validator.validate_path("src") == dummy_project / "src"
        # Fichier dans un sous-dossier
        assert path_validator.validate_path("src/app.py") == dummy_project / "src" / "app.py"
        # Avec syntaxe Windows ou POSIX
        assert path_validator.validate_path("tests/test_app.py") == dummy_project / "tests" / "test_app.py"

    def test_allow_valid_absolute_paths_within_root(
        self, path_validator: SafePathValidator, dummy_project: Path
    ) -> None:
        """Vérifie qu'un chemin absolu est autorisé SI et seulement S'IL est à l'intérieur de la racine."""
        target_abs = dummy_project / "src" / "app.py"
        assert path_validator.validate_path(target_abs) == target_abs

    def test_block_parent_directory_traversal(self, path_validator: SafePathValidator) -> None:
        """Vérifie que toute tentative de remonter avec '../' est immédiatement bloquée."""
        with pytest.raises(PathTraversalError):
            path_validator.validate_path("../secret.txt")

        with pytest.raises(PathTraversalError):
            path_validator.validate_path("src/../../hors_projet.py")

    def test_block_absolute_path_outside_root(
        self, path_validator: SafePathValidator, tmp_path: Path
    ) -> None:
        """Vérifie qu'un chemin absolu pointant vers un autre dossier est bloqué."""
        other_dir = tmp_path / "autre_dossier"
        other_dir.mkdir()
        forbidden_file = other_dir / "secret.env"
        forbidden_file.write_text("API_KEY=123", encoding="utf-8")

        with pytest.raises(PathTraversalError):
            path_validator.validate_path(forbidden_file)

    def test_is_safe_helper(self, path_validator: SafePathValidator) -> None:
        """Vérifie que la méthode is_safe renvoie un booléen sans lever d'exception."""
        assert path_validator.is_safe("src/app.py") is True
        assert path_validator.is_safe("../../etc/passwd") is False


# ==============================================================================
# Tests pour SafeCommandValidator (Sécurité des commandes pytest)
# ==============================================================================

class TestSafeCommandValidator:
    def test_allow_safe_flags(self, cmd_validator: SafeCommandValidator) -> None:
        """Vérifie que les options légitimes de pytest sont acceptées."""
        raw_args = ["-v", "-q", "-x", "--tb=short"]
        validated = cmd_validator.validate_pytest_args(raw_args)
        assert validated == raw_args

    def test_allow_safe_filter_expression(self, cmd_validator: SafeCommandValidator) -> None:
        """Vérifie qu'un filtre avec -k est validé correctement."""
        raw_args = ["-k", "test_app and not test_slow"]
        validated = cmd_validator.validate_pytest_args(raw_args)
        assert validated == ["-k", "test_app and not test_slow"]

    def test_allow_valid_test_file_target(self, cmd_validator: SafeCommandValidator) -> None:
        """Vérifie qu'un chemin vers un fichier de test interne est autorisé."""
        raw_args = ["tests/test_app.py", "-v"]
        validated = cmd_validator.validate_pytest_args(raw_args)
        assert validated == [str(Path("tests/test_app.py")), "-v"]

    def test_block_shell_injection_characters(self, cmd_validator: SafeCommandValidator) -> None:
        """Vérifie que les métacaractères d'injection shell provoquent une erreur."""
        forbidden_samples = [
            ["tests/test_app.py; rm -rf /"],
            ["-k", "test_app && echo pwned"],
            ["-v | cat"],
            ["`whoami`"],
            ["$(id)"],
            ["> output.txt"],
        ]
        for sample in forbidden_samples:
            with pytest.raises(CommandInjectionError):
                cmd_validator.validate_pytest_args(sample)

    def test_block_disallowed_pytest_flags(self, cmd_validator: SafeCommandValidator) -> None:
        """Vérifie que les drapeaux non autorisés ou dangereux sont rejetés."""
        with pytest.raises(CommandInjectionError):
            cmd_validator.validate_pytest_args(["--import-mode=importlib"])

        with pytest.raises(CommandInjectionError):
            cmd_validator.validate_pytest_args(["-o", "addopts=--capture=no"])

    def test_block_test_target_path_traversal(self, cmd_validator: SafeCommandValidator) -> None:
        """Vérifie que spécifier un fichier de test en dehors de la racine échoue."""
        with pytest.raises(PathTraversalError):
            cmd_validator.validate_pytest_args(["../../other_project/tests/test_hack.py"])

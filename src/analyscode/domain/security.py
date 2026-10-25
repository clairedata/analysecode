"""
Module de sécurité (Domaine de l'architecture hexagonale).

Ce module constitue le « Security Guard » (garde-fous) de l'agent.
Règle d'or de sécurité des agents IA :
On ne fait JAMAIS confiance au modèle de langage pour s'auto-censurer.
La sécurité doit être vérifiée au niveau du code Python, de manière déterministe.
"""

from pathlib import Path
import re
from typing import Sequence


class SecurityError(Exception):
    """Exception de base pour toutes les violations de sécurité détectées."""
    pass


class PathTraversalError(SecurityError):
    """Déclenchée lorsqu'un chemin tente de sortir du répertoire racine autorisé."""
    pass


class CommandInjectionError(SecurityError):
    """Déclenchée lorsqu'une commande contient des caractères ou des options interdites."""
    pass


class SafePathValidator:
    """
    Assure le confinement (« jail » ou « chroot » logique) des accès aux fichiers.
    
    Tout chemin demandé par le LLM (ex: '../../etc/passwd' ou 'C:\\Windows')
    est résolu de manière canonique (en suivant les liens et en éliminant les '..').
    S'il ne se situe pas strictement sous la racine du projet analysé,
    l'accès est immédiatement bloqué.
    """

    def __init__(self, root_dir: str | Path) -> None:
        """
        Initialise le validateur avec la racine autorisée du projet cible.
        
        Args:
            root_dir: Chemin vers le répertoire racine du projet à analyser.
        """
        # .resolve() calcule le chemin absolu réel en éliminant les liens symboliques et les '..'
        self._root_path = Path(root_dir).resolve()

        if not self._root_path.exists():
            raise FileNotFoundError(f"Le répertoire racine spécifié n'existe pas : {self._root_path}")
        
        if not self._root_path.is_dir():
            raise NotADirectoryError(f"Le chemin racine n'est pas un dossier : {self._root_path}")

    @property
    def root_path(self) -> Path:
        """Retourne le chemin canonique de la racine surveillée."""
        return self._root_path

    def validate_path(self, target_path: str | Path) -> Path:
        """
        Valide et résout un chemin cible.
        
        Args:
            target_path: Chemin relatif ou absolu demandé.
            
        Returns:
            Path: Le chemin canonique résolu et garanti sécurisé.
            
        Raises:
            PathTraversalError: Si le chemin résolu sort de la racine autorisée.
        """
        target = Path(target_path)

        # Si le chemin est relatif, on le résout par rapport à la racine autorisée
        if not target.is_absolute():
            resolved = (self._root_path / target).resolve()
        else:
            resolved = target.resolve()

        # Vérification stricte : le chemin résolu doit être un enfant de root_path
        try:
            # is_relative_to() vérifie la filiation stricte dans la hiérarchie de fichiers
            if not resolved.is_relative_to(self._root_path):
                raise PathTraversalError(
                    f"Accès refusé : Le chemin '{target_path}' pointe hors de la racine autorisée '{self._root_path}'."
                )
        except ValueError:
            # Cas où les chemins sont sur des disques différents (ex: C: vs D: sous Windows)
            raise PathTraversalError(
                f"Accès refusé : Le chemin '{target_path}' est sur un lecteur différent de la racine '{self._root_path}'."
            )

        return resolved

    def is_safe(self, target_path: str | Path) -> bool:
        """Retourne True si le chemin est sécurisé, False sinon (sans lever d'exception)."""
        try:
            self.validate_path(target_path)
            return True
        except (SecurityError, Exception):
            return False


class SafeCommandValidator:
    """
    Sécurise l'exécution des tests pytest.
    
    Garantit que :
    1. Aucun métacaractère shell ne peut provoquer d'injection de commande.
    2. Seuls des arguments pytest pré-approuvés ou des chemins de test sûrs sont acceptés.
    """

    # Caractères dangereux typiques des injections de shell (ex: cmd1 ; cmd2 ou cmd1 && cmd2)
    FORBIDDEN_SHELL_CHARS = {";", "&", "|", "`", "$", "(", ")", "<", ">", "\n", "\r"}

    # Liste blanche des options pytest autorisées pour l'agent
    ALLOWED_PYTEST_FLAGS = {
        "-k",           # Filtrer par nom d'expression
        "-m",           # Filtrer par marqueur
        "-v",           # Mode verbeux
        "-q",           # Mode silencieux
        "-s",           # Ne pas capturer stdout
        "-x",           # S'arrêter au premier échec
        "--tb=short",   # Traceback court
        "--tb=line",    # Traceback sur une ligne
        "--tb=no",      # Pas de traceback
        "--maxfail=1",  # S'arrêter après 1 échec
    }

    # Motif regex pour les arguments de filtres acceptables (ex: -k "test_addition")
    SAFE_FILTER_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\s\.]+$")

    def __init__(self, path_validator: SafePathValidator) -> None:
        """
        Initialise le validateur de commande en l'associant au validateur de chemin.
        
        Args:
            path_validator: Le validateur de chemins pour sécuriser les fichiers cibles de test.
        """
        self._path_validator = path_validator

    def validate_pytest_args(self, raw_args: Sequence[str]) -> list[str]:
        """
        Valide et assainit la liste des arguments fournis pour exécuter pytest.
        
        Args:
            raw_args: Liste des arguments (ex: ['-k', 'test_auth', 'tests/test_auth.py']).
            
        Returns:
            list[str]: Liste des arguments vérifiés et sécurisés.
            
        Raises:
            CommandInjectionError: Si un caractère interdit ou un argument non autorisé est détecté.
        """
        validated_args: list[str] = []
        skip_next = False

        for i, arg in enumerate(raw_args):
            if skip_next:
                skip_next = False
                continue

            # 1. Vérifier l'absence absolue de métacaractères d'injection shell
            for char in self.FORBIDDEN_SHELL_CHARS:
                if char in arg:
                    raise CommandInjectionError(
                        f"Caractère shell interdit '{char}' détecté dans l'argument : {arg}"
                    )

            # 2. Cas des options simples autorisées (ex: -v, -q, -x, --tb=short)
            if arg in self.ALLOWED_PYTEST_FLAGS:
                validated_args.append(arg)

                # Si l'option prend une valeur suivante (ex: -k "mon_test" ou -m "unit")
                if arg in {"-k", "-m"} and i + 1 < len(raw_args):
                    next_val = raw_args[i + 1]
                    # Vérifier également la valeur suivante
                    for char in self.FORBIDDEN_SHELL_CHARS:
                        if char in next_val:
                            raise CommandInjectionError(
                                f"Caractère shell interdit dans la valeur du filtre : {next_val}"
                            )
                    if not self.SAFE_FILTER_PATTERN.match(next_val):
                        raise CommandInjectionError(
                            f"Format de filtre non sécurisé pour '{arg}' : {next_val}"
                        )
                    validated_args.append(next_val)
                    skip_next = True
                continue

            # 3. Cas des options avec '=' (ex: --tb=short)
            if arg.startswith("-") and arg not in self.ALLOWED_PYTEST_FLAGS:
                raise CommandInjectionError(
                    f"Option pytest non autorisée pour l'agent : '{arg}'"
                )

            # 4. Cas où l'argument est un chemin de fichier ou dossier de test (ex: 'tests/test_calc.py')
            safe_target_path = self._path_validator.validate_path(arg)
            # On conserve le chemin relatif par rapport à la racine pour la ligne de commande
            relative_target = safe_target_path.relative_to(self._path_validator.root_path)
            validated_args.append(str(relative_target))

        return validated_args

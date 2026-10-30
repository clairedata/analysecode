"""
Tests unitaires pour le moteur du Harness (AgentEngine).

Ces tests vérifient le bon fonctionnement de la boucle ReAct de manière 100% déterministe
sans aucun appel réseau et sans consommer de tokens, grâce à un MockLLM.
"""

from pathlib import Path
from typing import Any
import pytest

from analyscode.adapters.tools.registry import create_default_registry
from analyscode.application.engine import AgentEngine
from analyscode.domain.models import ChatMessage, LLMResponse, Role, ToolCall
from analyscode.ports.llm import LLMError, LLMPort
from analyscode.ports.tools import ToolRegistryPort


# ==============================================================================
# LE MOCK LLM : L'Adaptateur de test pour simuler une IA (Pattern "Test Spy")
# ==============================================================================

class MockLLM(LLMPort):
    """
    RÔLE DU MOCK DANS L'ARCHITECTURE HEXAGONALE :
    Puisque `AgentEngine` ne dépend que de l'interface abstraite `LLMPort`,
    cette classe agit comme un véritable adaptateur LLM sans dépendance externe.
    
    Elle simule fidèlement les réponses d'un LLM tout en jouant le rôle d'ESPION ("Spy") :
    elle enregistre chaque message reçu pour permettre aux tests de vérifier
    exactement ce que le moteur a transmis à l'IA à chaque tour.
    """

    def __init__(self, planned_responses: list[LLMResponse | Exception]) -> None:
        """
        Initialise le Mock avec la séquence des réponses prévues.
        
        Args:
            planned_responses: Liste ordonnée [Réponse_Tour_1, Réponse_Tour_2, ...].
        """
        # EXPLICATION DE `reversed` :
        # En Python, retirer le dernier élément d'une liste avec `.pop()` est une opération
        # instantanée en O(1), alors que retirer le premier élément avec `.pop(0)` est lent en O(n).
        # En inversant la liste au départ avec reversed(), le Tour 1 se retrouve à la fin.
        # Ainsi, au premier appel, .pop() retirera bien Réponse_Tour_1 !
        self._responses = list(reversed(planned_responses))

        # EXPLICATION DE LA DOUBLE LISTE `list[list[ChatMessage]]` :
        # - Lors d'UN appel, le moteur envoie une liste de messages : list[ChatMessage].
        # - Comme le moteur effectue PLUSIEURS appels (un par tour de boucle ReAct),
        #   calls_history stocke la liste de chaque appel :
        #   calls_history[0] = messages envoyés lors de l'Appel 1 (Tour 1)
        #   calls_history[1] = messages envoyés lors de l'Appel 2 (Tour 2)
        # D'où une "liste de listes" de messages : list[list[ChatMessage]].
        self.calls_history: list[list[ChatMessage]] = []

        # Même logique : enregistre la liste des outils fournis à chaque appel (Tour 1, Tour 2...)
        self.tools_provided_history: list[list[dict[str, Any]] | None] = []

    def generate_response(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """
        Simule un tour de réponse du LLM et enregistre ce qui a été reçu.
        """
        # EXPLICATION DE `list(messages)` :
        # En Python, les listes sont mutables et transmises par référence.
        # Si on faisait `self.calls_history.append(messages)`, toute modification ultérieure
        # de l'historique par le moteur modifierait rétroactivement notre enregistrement !
        # `list(messages)` crée un "snapshot" (une copie figée) de l'état exact des messages
        # à la seconde précise où l'appel a eu lieu.
        self.calls_history.append(list(messages))
        self.tools_provided_history.append(tools)

        # Vérification qu'il reste bien une réponse pré-programmée pour ce tour
        if not self._responses:
            raise RuntimeError("Le MockLLM a épuisé toutes ses réponses prévues !")

        # On extrait la réponse prévue pour ce tour
        next_action = self._responses.pop()

        # Si l'action prévue est une Exception (ex: simulation d'une coupure réseau ou erreur API)
        if isinstance(next_action, Exception):
            raise next_action

        return next_action


# ==============================================================================
# FIXTURES PYTEST
# ==============================================================================

@pytest.fixture
def dummy_project(tmp_path: Path) -> Path:
    """
    RÔLE : Crée un mini-projet Python réel dans un dossier temporaire isolé.
    Permet de tester que les outils de l'agent lisent de vrais fichiers sur le disque.
    """
    proj = tmp_path / "target_app"
    proj.mkdir()

    src = proj / "src"
    src.mkdir()
    (src / "calculator.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n",
        encoding="utf-8",
    )
    return proj


@pytest.fixture
def real_registry(dummy_project: Path) -> ToolRegistryPort:
    """
    RÔLE : Fournit un vrai registre d'outils sécurisé pointant sur le projet factice.
    Démontre que le moteur communique avec le vrai ToolRegistryPort.
    """
    return create_default_registry(dummy_project)


# ==============================================================================
# TESTS DES SCÉNARIOS DE LA BOUCLE DU MOTEUR (ReAct)
# ==============================================================================

def test_engine_direct_response_without_tools(real_registry: ToolRegistryPort) -> None:
    """
    SCÉNARIO TESTÉ : Réponse directe en 1 tour sans appel d'outil.
    
    RÔLE DU TEST :
    Vérifie que lorsque le LLM n'a pas besoin d'outils et produit directement du texte,
    la boucle ReAct s'arrête immédiatement au 1er tour et retourne le résultat.
    """
    expected_text = (
        "### 1. Faits observés\nProjet standard.\n"
        "### 2. Diagnostic & Hypothèses\nAucun problème détecté.\n"
        "### 3. Proposition de correction\nAucune correction nécessaire."
    )
    mock_llm = MockLLM([
        LLMResponse(content=expected_text, tool_calls=[])
    ])

    engine = AgentEngine(llm=mock_llm, tool_registry=real_registry, max_turns=10)

    # Exécution de l'instruction utilisateur
    response = engine.run("Quelle est la structure générale du projet ?")

    # 1. Vérification du statut de succès et du compteur de tours
    assert response.success is True
    assert response.turns_count == 1
    assert response.content == expected_text
    assert response.error is None

    # 2. Vérification de l'historique complet (System, User, Assistant)
    history = engine.history
    assert len(history) == 3
    assert history[0].role == Role.SYSTEM
    assert history[1].role == Role.USER
    assert history[2].role == Role.ASSISTANT
    assert history[2].content == expected_text


def test_engine_full_react_cycle_with_tool_call(
    dummy_project: Path, real_registry: ToolRegistryPort
) -> None:
    """
    SCÉNARIO TESTÉ : Le cycle ReAct complet en 2 tours.
    - Tour 1 : Le LLM décide d'invoquer l'outil `read_file` sur 'src/calculator.py'.
    - Le Moteur exécute réellement l'outil sur le disque et capture son observation.
    - Tour 2 : Le LLM reçoit l'observation et formule sa conclusion finale.

    RÔLE DU TEST :
    Prouver que l'orchestration ReAct (Raisonnement -> Action -> Observation -> Synthèse)
    fonctionne parfaitement et préserve l'ordre chronologique des messages.
    """
    # Tour 1 : L'assistant formule sa volonté d'appeler read_file
    turn_1_response = LLMResponse(
        content="Je vais d'abord examiner le fichier calculator.py.",
        tool_calls=[
            ToolCall(
                id="call_read_1",
                tool_name="read_file",
                arguments={"file_path": "src/calculator.py"},
            )
        ],
    )
    # Tour 2 : L'assistant a pris connaissance du fichier et donne sa réponse finale
    turn_2_response = LLMResponse(
        content="### 1. Faits observés\nLa fonction add(a, b) fait a + b.\n"
                "### 2. Diagnostic & Hypothèses\nLe code est valide.\n"
                "### 3. Proposition de correction\nAucune modification requise.",
        tool_calls=[],
    )

    mock_llm = MockLLM([turn_1_response, turn_2_response])
    engine = AgentEngine(llm=mock_llm, tool_registry=real_registry, max_turns=10)

    # Lancement de l'analyse
    response = engine.run("Analyse le fichier calculator.py")

    # 1. Vérification du résultat global
    assert response.success is True
    assert response.turns_count == 2
    assert "La fonction add(a, b)" in response.content

    # 2. Vérification de la chronologie exacte des 5 messages dans l'historique
    history = engine.history
    assert len(history) == 5

    # Message 1 : Consignes système
    assert history[0].role == Role.SYSTEM
    # Message 2 : Demande utilisateur
    assert history[1].role == Role.USER
    # Message 3 : Décision Tour 1 (Assistant avec ToolCall)
    assert history[2].role == Role.ASSISTANT
    assert len(history[2].tool_calls) == 1
    assert history[2].tool_calls[0].tool_name == "read_file"
    # Message 4 : Observation réelle renvoyée par l'outil read_file
    assert history[3].role == Role.TOOL
    assert history[3].tool_call_id == "call_read_1"
    assert "L1: def add(a, b):" in (history[3].content or "")
    # Message 5 : Réponse finale Tour 2 (Assistant texte)
    assert history[4].role == Role.ASSISTANT
    assert history[4].content == turn_2_response.content


def test_engine_stops_at_max_turns_when_looping(real_registry: ToolRegistryPort) -> None:
    """
    SCÉNARIO TESTÉ : Boucle infinie d'outils.
    
    RÔLE DU TEST :
    Vérifie que si un LLM demande sans cesse des outils sans jamais s'arrêter,
    le garde-fou `max_turns` stoppe net l'exécution à la limite fixée (ici 3 tours)
    sans faire planter l'application.
    """
    infinite_tool_response = LLMResponse(
        content="Je continue à chercher...",
        tool_calls=[
            ToolCall(id="loop_call", tool_name="list_dir", arguments={"relative_path": "."})
        ],
    )

    mock_llm = MockLLM([infinite_tool_response] * 10)
    engine = AgentEngine(llm=mock_llm, tool_registry=real_registry, max_turns=3)

    response = engine.run("Boucle infinie test")

    assert response.success is False
    assert response.turns_count == 3
    assert "Limite de sécurité atteinte (3 tours)" in (response.error or "")
    assert "interrompue" in response.content


def test_engine_gracefully_handles_llm_error(real_registry: ToolRegistryPort) -> None:
    """
    SCÉNARIO TESTÉ : Défaillance réseau ou indisponibilité du fournisseur LLM.
    
    RÔLE DU TEST :
    Vérifie que si une exception `LLMError` est levée pendant l'appel,
    le moteur l'intercepte proprement et retourne un `AgentResponse` avec success=False.
    """
    mock_llm = MockLLM([
        LLMError("Échec de connexion réseau au serveur d'API.")
    ])

    engine = AgentEngine(llm=mock_llm, tool_registry=real_registry, max_turns=5)

    response = engine.run("Analyse sous panne réseau")

    assert response.success is False
    assert response.turns_count == 1
    assert "Erreur lors de la communication avec le LLM" in (response.error or "")
    assert "Échec de connexion réseau" in (response.error or "")

"""
Moteur d'orchestration de l'agent (application/engine.py).

Ce module est le « Cerveau » (Harness Engine) de l'agent IA.
Il implémente la boucle autonome ReAct (Reasoning -> Action -> Observation) :
1. RAISONNEMENT : Le LLM analyse la situation et décide quoi faire.
2. ACTION : Si le LLM demande un outil, le moteur l'exécute de façon sécurisée.
3. OBSERVATION : Le résultat de l'outil est réinjecté dans l'historique de conversation.
4. RÉPÉTITION : Le cycle recommence jusqu'à l'obtention d'une réponse finale
                ou jusqu'à l'atteinte du nombre maximal de tours autorisé (max_turns).
"""

from typing import Sequence

from analyscode.domain.models import AgentResponse, ChatMessage, LLMResponse, Role, ToolCall
from analyscode.ports.llm import LLMError, LLMPort
from analyscode.ports.tools import ToolRegistryPort


# Prompt système par défaut qui cadre le comportement et le format de restitution
DEFAULT_SYSTEM_PROMPT = """Tu es un agent d'assistance au développement logiciel expert en Python.
Ton objectif est d'analyser le projet cible, d'expliquer son code, d'identifier des bugs potentiels et de proposer des corrections.

RÈGLES D'ACTION :
1. Tu as accès à des outils pour explorer le projet (list_dir, read_file, search_code, run_pytest).
2. Pour chaque problème, appuie-toi sur des FAITS RÉELS observés via tes outils. Ne suppose jamais le contenu d'un fichier sans l'avoir lu.
3. Si un test échoue, lis la trace d'erreur exacte produite par pytest, puis lis le code source correspondant.
4. Tu es en MODE LECTURE SEULE : tu ne peux pas modifier directement les fichiers sur le disque.

FORMAT DE RESTITUTION OBLIGATOIRE :
Lorsque tu formules ta réponse finale, structure-la impérativement selon ces 3 sections :

### 1. Faits observés
- Détaille ce que les outils ont réellement renvoyé (ex: traces de pytest, contenu de fonctions lues).

### 2. Diagnostic & Hypothèses
- Explique la cause racine du dysfonctionnement ou la logique du code analysé.

### 3. Proposition de correction
- Indique le fichier cible et les numéros de lignes précis (ex: `L12-L18`).
- Fournis le bloc de code corrigé sous la forme :
```python
# Lignes cibles : L12-L18
<ton code corrigé ici>
```
"""


class AgentEngine:
    """
    Chef d'orchestre de l'agent.
    
    Reçoit ses dépendances par injection (LLMPort et ToolRegistryPort),
    maintient l'état de la conversation et pilote les itérations.
    """

    def __init__(
        self,
        llm: LLMPort,
        tool_registry: ToolRegistryPort,
        max_turns: int = 10,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        """
        Initialise le moteur du Harness.
        
        Args:
            llm: N'importe quel adaptateur respectant LLMPort (OpenAI, Ollama, Mock).
            tool_registry: Le registre des outils disponibles et sécurisés.
            max_turns: Garde-fou opérationnel limitant le nombre de tours de boucle.
            system_prompt: Consignes de cadrage transmises au modèle.
        """
        self._llm = llm
        self._tools = tool_registry
        self._max_turns = max_turns
        self._system_prompt = system_prompt
        self._history: list[ChatMessage] = []

    @property
    def history(self) -> list[ChatMessage]:
        """Retourne une copie de l'historique complet des messages de la session."""
        return list(self._history)

    def run(self, user_instruction: str) -> AgentResponse:
        """
        Déclenche l'analyse autonome en réponse à une instruction de l'utilisateur.
        
        Args:
            user_instruction: La demande de l'utilisateur (ex: "Pourquoi mes tests échouent ?").
            
        Returns:
            AgentResponse: Le compte rendu final produit par l'agent.
        """
        # 1. INITIALISATION DU CONTEXTE DE DÉPART
        # On prépare l'historique avec les règles (System) et la demande (User)
        self._history = [
            ChatMessage.system(self._system_prompt),
            ChatMessage.user(user_instruction),
        ]

        # Récupération de la liste des schémas JSON de tous les outils autorisés
        tools_schema = self._tools.get_openai_tools()

        # 2. LA BOUCLE REACT (Reasoning -> Action -> Observation)
        for current_turn in range(1, self._max_turns + 1):
            try:
                # ÉTAPE A : RAISONNEMENT (Appel au LLM)
                # On soumet l'historique complet et la boîte à outils au modèle
                llm_response: LLMResponse = self._llm.generate_response(
                    messages=self._history,
                    tools=tools_schema,
                )
            except LLMError as err:
                # En cas de panne réseau ou d'erreur API, on interrompt proprement sans crasher
                return AgentResponse(
                    content="",
                    turns_count=current_turn,
                    success=False,
                    error=f"Erreur lors de la communication avec le LLM : {err}",
                )

            # ÉTAPE B : ANALYSE DE LA DÉCISION DU MODÈLE
            if not llm_response.has_tool_calls:
                # CAS 1 : Le LLM a produit du texte sans demander d'outil.
                # Cela signifie qu'il a terminé son enquête et donne sa réponse finale !
                final_content = llm_response.content or "[Aucune réponse textuelle fournie]"
                
                # On archive la réponse de l'assistant dans l'historique
                self._history.append(ChatMessage.assistant(content=final_content))

                return AgentResponse(
                    content=final_content,
                    turns_count=current_turn,
                    success=True,
                )

            # CAS 2 : Le LLM a demandé d'exécuter un ou plusieurs outils.
            # On enregistre d'abord l'intention de l'assistant dans l'historique
            self._history.append(
                ChatMessage.assistant(
                    content=llm_response.content,
                    tool_calls=llm_response.tool_calls,
                )
            )

            # ÉTAPE C : ACTION & OBSERVATION (Exécution des outils)
            for tool_call in llm_response.tool_calls:
                # 1. Action : on exécute l'outil via notre registre sécurisé
                tool_result = self._tools.execute(
                    tool_name=tool_call.tool_name,
                    arguments=tool_call.arguments,
                )

                # 2. Observation : on extrait le résultat brut (ou le message d'erreur)
                observation_content = tool_result.to_content()

                # 3. Mémorisation : on réinjecte le résultat dans la conversation (rôle 'tool')
                # pour que le LLM puisse le lire au tour suivant
                self._history.append(
                    ChatMessage.tool_result(
                        tool_call_id=tool_call.id,
                        content=observation_content,
                    )
                )

            # La boucle continue au tour suivant (le modèle va réévaluer la situation
            # avec les nouvelles observations en mémoire)

        # 3. GARDE-FOU ATTEINT : Si on sort de la boucle sans réponse finale
        return AgentResponse(
            content="L'analyse a été interrompue : le nombre maximal de tours d'analyse a été atteint.",
            turns_count=self._max_turns,
            success=False,
            error=f"Limite de sécurité atteinte ({self._max_turns} tours). L'agent n'a pas pu converger.",
        )

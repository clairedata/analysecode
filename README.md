# AnalysCode — Agent IA d'Analyse et d'Audit de Code Python

**AnalysCode** est un agent d'assistance au développement logiciel spécialisé dans l'écosystème Python. Il analyse des bases de code existantes, explique leur architecture, exécute les tests unitaires et propose des correctifs ciblés sans jamais modifier directement les fichiers (mode lecture seule sécurisé).

Ce projet a également une **vocation pédagogique** forte : construire un **Harness d'Agent IA « from scratch »** (sans framework tiers lourd type LangChain ou CrewAI) selon les principes de l'**Architecture Hexagonale (Ports & Adaptateurs)**, afin de comprendre chaque rouage de la prise de décision autonome d'un LLM.

---

## 🏛️ Architecture Hexagonale du Projet

L'architecture sépare strictement le cœur métier (le domaine et les règles de sécurité) des détails techniques d'infrastructure (les outils, l'accès au disque, l'API OpenAI, la CLI).

```
                            ┌───────────────────────────────────────────────┐
                            │              ADAPTATEURS PRIMAIRES            │
                            │             (Entrée / Utilisateur)            │
                            │                    [ CLI ]                    │
                            └───────────────────────┬───────────────────────┘
                                                    │
                                        ┌───────────▼───────────┐
                                        │     Port d'Entrée     │
                                        │     (AgentService)    │
                            ┌───────────┴───────────────────────┴───────────┐
                            │                CŒUR DU DOMAINE                │
                            │                                               │
                            │  - Boucle ReAct (Harness Engine)              │
                            │  - Invariants de Sécurité (SafePath, SafeCmd) │
                            │  - Gestion du contexte & Garde-fous           │
                            │                                               │
                            └───┬───────────────────────────────┬───────────┘
                                │ Port LLM                      │ Port Tools
                    ┌───────────▼───────────┐       ┌───────────▼───────────┐
                    │     ADAPTATEUR LLM    │       │   ADAPTATEUR OUTILS   │
                    │       [ OpenAI ]      │       │  [ Filesystem local ] │
                    │ (ou Ollama / Claude)  │       │  [ Pytest Runner ]    │
                    └───────────────────────┘       └───────────────────────┘
                                                    ADAPTATEURS SECONDAIRES
```

---

## 🗺️ Feuille de Route Détaillée (Étape par Étape)

### ✅ Étape 1 : Domaine Métier & Sécurité d'abord *(Terminée)*
L'agent manipule des fichiers et des commandes : la sécurité ne doit jamais reposer sur le simple prompt du LLM, mais être **garantie au niveau du code Python**.
- **`SafePathValidator`** : Confinement strict du système de fichiers (*virtual jail*). Tout chemin relatif ou absolu (`../`, liens symboliques, chemins système) est résolu canoniquement (`Path.resolve()`) et validé (`is_relative_to(project_root)`).
- **`SafeCommandValidator`** : Prévention des injections shell. Filtrage strict des métacaractères dangereux (`;`, `&&`, `|`, `` ` ``, `$()`, etc.), vérification des options pytest (`-k`, `-v`, `--tb=short`) et interdiction formelle de `shell=True`.
- **Validation** : 12 tests unitaires exhaustifs dans `tests/domain/test_security.py`.

---

### ✅ Étape 2 : Ports et Adaptateurs d'Outils *(Terminée)*
Découplage de la boîte à outils mise à la disposition de l'agent.
- **Le Port (`ports/tools.py`)** :
  - `ToolDefinition` : Génère le schéma JSON conforme au standard *OpenAI Function Calling*.
  - `ToolResult` : Encapsule le résultat d'un outil (`success`, `output`, `error`) de manière immuable.
  - `Tool` & `ToolRegistryPort` : Interfaces abstraites.
- **Les Adaptateurs d'Outils (`adapters/tools/`)** :
  - `ListDirTool` : Exploration arborescente avec exclusion des dossiers parasites (`.git`, `__pycache__`, `.venv`).
  - `ReadFileTool` : Lecture paginée avec numérotation explicite (`L1: ...`, `L5: ...`) et plafond de protection pour préserver la fenêtre de contexte du modèle.
  - `SearchCodeTool` : Recherche textuelle ou par expression régulière dans les fichiers sources.
  - `PytestRunnerTool` : Exécution supervisée de `pytest` via `subprocess.run(shell=False)` avec capture brute de `stdout`/`stderr` et timeout strict de 30 secondes.
  - `DefaultToolRegistry` : Registre centralisé assurant le routage sécurisé des appels d'outils.
- **Validation** : Suite de tests unitaires documentée dans `tests/adapters/test_tools.py`.

---

### 🔄 Étape 3 : Le Moteur du Harness & Intégration LLM *(Prochaine étape)*
C'est le cerveau de l'agent. Cette étape orchestre la réflexion et l'action autonome du modèle de langage.

#### 1. Le Port LLM (`ports/llm.py`)
- Définit l'interface abstraite permettant d'envoyer des messages et de recevoir des décisions du modèle (texte ou demandes de `tool_calls`), sans dépendance forte à un fournisseur spécifique.

#### 2. L'Adaptateur OpenAI (`adapters/llm/openai_client.py`)
- Implémente le client officiel OpenAI.
- Gère la transmission des schémas d'outils et la réception des objets `tool_calls`.
- Convertit les réponses brutes de l'API en modèles de données du domaine.

#### 3. Le Moteur ReAct (`engine.py`)
- **La boucle ReAct (Raisonnement $\rightarrow$ Action $\rightarrow$ Observation)** :
  1. L'utilisateur pose une question ou demande un audit sur le projet.
  2. Le moteur injecte le **Prompt Système** et l'historique de conversation.
  3. Le LLM analyse la situation et décide soit de répondre directement, soit d'invoquer un outil (ex: `run_pytest` ou `read_file`).
  4. Le moteur intercepte la demande, exécute l'outil via le registre sécurisé et injecte le résultat réel (**le Fait observé**) dans la conversation.
  5. Le LLM réévalue l'état enrichi et poursuit jusqu'à la résolution.
- **Garde-fous opérationnels** :
  - `max_turns` : Limite stricte du nombre de tours (ex: 10 itérations max) pour empêcher les boucles infinies et maîtriser les coûts d'API.
  - Gestion des erreurs de parsing JSON : si le LLM produit des arguments invalides, un message d'erreur lui est renvoyé pour auto-correction.
- **Directives de Restitution (Prompt Système)** :
  Contraint le modèle à structurer ses réponses selon 3 piliers :
  - **Faits observés** (sorties réelles des tests ou du code lu).
  - **Hypothèses / Diagnostic** (analyse causale).
  - **Propositions de correction** (bloc markdown ciblé avec fichier et plages de lignes `L10-L15`, sans modification automatique).

#### 4. Tests avec Mock LLM (`tests/test_engine.py`)
- Validation complète de la boucle ReAct à l'aide d'un faux adaptateur LLM sans consommer de vrais tokens OpenAI.

---

### ⏳ Étape 4 : Interface Ligne de Commande (CLI) *(À venir)*
- Point d'entrée utilisateur en ligne de commande :
  ```powershell
  python -m analyscode --target ./mon_projet "Pourquoi les tests échouent ?"
  ```
- Affichage clair et convivial dans la console des étapes de réflexion, des outils invoqués et du rapport d'audit final.

---

### ⏳ Étape 5 : Validation Grandeur Nature E2E *(À venir)*
- Test de bout en bout sur un projet Python réel contenant un bug.
- Vérification que l'agent identifie l'erreur via `pytest`, lit le fichier source et formule le bon correctif sans modifier les fichiers.

---

## 🚀 Commandes Utiles

- **Installer l'environnement de développement** :
  ```powershell
  uv add pytest openai
  ```
- **Lancer tous les tests unitaires (Sécurité + Outils)** :
  ```powershell
  uv run pytest
  ```
- **Lancer uniquement les tests de sécurité** :
  ```powershell
  uv run pytest tests/domain/test_security.py
  ```

  ## ajotuer pour test commande git existe sur le pdf progit

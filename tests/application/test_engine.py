"""
Tests unitaires pour le moteur du Harness (AgentEngine).

Ce fichier testera la boucle ReAct de manière déterministe grâce à un MockLLM :
- Vérifie que l'agent s'arrête dès qu'une réponse finale textuelle est reçue.
- Vérifie que les tool_calls demandés sont bien transmis au registre et réinjectés.
- Vérifie que l'agent s'arrête proprement s'il atteint le nombre maximal de tours (max_turns).
"""

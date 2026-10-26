"""
Adaptateur concret pour l'API OpenAI (adapters/llm/openai_client.py).

Ce fichier implémentera l'interface `LLMPort` avec le SDK officiel OpenAI.
Il gérera :
- La configuration du client OpenAI (clé API, modèle).
- La conversion des messages neutres au format attendu par OpenAI.
- L'appel réseau à l'API de Chat Completions avec support natif des `tool_calls`.
- La désérialisation de la réponse du modèle en structures de données du domaine.
"""

"""
Moteur d'orchestration de l'agent (application/engine.py).

Ce fichier contiendra la classe concrète `AgentEngine` qui implémente :
- La boucle ReAct autonome (Raisonnement -> Action -> Observation).
- Le maintien de l'historique de conversation (contexte).
- L'injection du prompt système (directives de sécurité et format des réponses).
- Le garde-fou limitant le nombre maximum de tours (max_turns).
"""

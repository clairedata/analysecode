# AGENTS.md — Règles de développement

## 1. Principes généraux

- Comprendre le besoin avant toute implémentation.
- Respecter le périmètre validé du projet.
- Privilégier la simplicité, la lisibilité et la maintenabilité.
- Éviter les dépendances, abstractions et fonctionnalités inutiles.
- Ne pas inventer de résultats, de tests ou de comportements.
- Signaler clairement les hypothèses, les risques et les limites.

## 2. Méthode de travail

- Examiner les fichiers et la documentation existants avant de proposer des changements.
- Si le besoin est ambigu, poser des questions avant de décider.
- Pour chaque phase, présenter l'objectif, le plan et les critères d'acceptation.
- Travailler par petites étapes indépendantes et vérifiables.
- Attendre ma validation avant de passer à la phase suivante lorsqu'elle est explicitement requise.
- Ne pas créer ou modifier de fichiers pendant une phase d'analyse seule.

## 3. Architecture et code

- Respecter la séparation des responsabilités.
- Utiliser des noms explicites et des fonctions à responsabilité claire.
- Réutiliser le code existant lorsqu'il convient.
- Éviter la duplication et les abstractions prématurées.
- Justifier les nouvelles dépendances et les changements d'architecture.
- Respecter les conventions et les outils déjà adoptés par le projet.

## 4. Tests et qualité

- Ajouter des tests pour les fonctionnalités importantes.
- Vérifier les cas normaux, les erreurs et les cas limites.
- Exécuter les tests pertinents après chaque changement significatif.
- Rapporter les résultats réels des commandes exécutées.
- Ne pas déclarer une fonctionnalité validée sans preuve suffisante.
- Ne pas supprimer ou affaiblir des tests sans justification et autorisation.

## 5. Sécurité et permissions

- Ne jamais exposer de secrets, clés API ou mots de passe.
- Ne pas accéder aux fichiers en dehors du périmètre autorisé.
- Ne pas supprimer ou modifier des données sans autorisation.
- Ne pas exécuter de commande destructive sans approbation explicite.
- Vérifier les permissions au niveau du code, et pas uniquement dans les instructions adressées au modèle.

## 6. Git et changements

- Examiner les changements avant de les considérer comme terminés.
- Ne pas écraser le travail existant.
- Éviter les modifications sans rapport avec la tâche demandée.
- Ne pas effectuer de commit, push ou opération destructive sans autorisation explicite.

## 7. Règles spécifiques à notre agent de développement

- Le MVP analyse le code et propose des corrections, sans modifier automatiquement les fichiers analysés.
- Les outils accessibles au modèle doivent être explicitement enregistrés et autorisés.
- Limiter les itérations de l'agent et le temps d'exécution des outils.
- Contrôler les chemins de fichiers et les commandes avant leur exécution.
- Conserver une trace exploitable des actions importantes.
- Distinguer les faits observés, les hypothèses et les recommandations.

## 8. Compte rendu de chaque tâche

À la fin d'une tâche, préciser :
- Ce qui a été réalisé.
- Les fichiers concernés.
- Les tests exécutés et leurs résultats.
- Les problèmes restant à résoudre.
- Les décisions ou validations encore nécessaires.
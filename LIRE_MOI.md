# Crypto Lab — extension Rapide ×10

Simulation fictive indépendante de 200 €, LONG et SHORT, sur les cours publics BTC/EUR et ETH/EUR. Aucun compte de trading, clé privée ou ordre réel.

## Installation sur le projet existant

Cette archive est une extension, pas une application autonome. Ajouter `scalp_engine.py`, `scalp.html` et `server_with_scalp.py` à la racine du dépôt existant, à côté de `server.py` et `algo.py`. Garder les fichiers existants et leurs sauvegardes.

L'adaptateur attend `server.Handler` (BaseHTTPRequestHandler) et `server.main()`, avec résolution de Handler lors du démarrage. Il est basé sur la version récupérée du projet ; la compatibilité avec la dernière version déployée reste à vérifier avant mise en production. Si la structure diffère, adapter l'intégration avant de changer le démarrage. Les tests de routes utilisent un serveur représentatif, pas le serveur Render réel.

Après validation, commande de démarrage Render :

    python server_with_scalp.py

La simulation classique reste sur `/`. Ouvrir `/rapide` sur le même domaine pour la nouvelle simulation. Aucun lien n'est injecté dans la page classique. Aucune dépendance Python supplémentaire ; un seul processus et une seule instance pour éviter plusieurs moteurs concurrents. Les nouvelles routes exposent uniquement des données fictives publiques ; si le serveur a une authentification, appliquer sa protection aux nouvelles routes avant publication.

État rapide : `simulation_rapide_200.json`, séparé de l'ancien état. `SCALP_DATA_DIR` peut viser un dossier sur un disque persistant déjà disponible. Sans stockage persistant, un redéploiement ou remplacement d'instance peut réinitialiser la simulation. Sauvegarder les états avant de déployer. Le moteur nécessite un hébergement continuellement actif ; une instance en veille ne surveille pas les positions. Cette archive ne crée ni service ni abonnement.

Pour revenir au fonctionnement précédent, restaurer la commande de démarrage précédente. Ne pas supprimer les sauvegardes.

## Règles expérimentales

- Capital fictif 200 €, une seule position, marge 20 €, levier ×10 : exposition initiale 200 €. Ce n'est pas 200 € de marge multipliés par dix.
- LONG sur cassure haussière, SHORT sur cassure baissière ; moyennes 6/20, cassure des 10 bougies précédentes et volume supérieur à 1,2 fois leur moyenne. Bougies clôturées de 1 minute uniquement.
- Stop à 0,3 % du prix d'entrée, cible à 0,6 %, durée visée maximale 15 minutes. Contrôle visé toutes les 5 secondes ; pause 60 secondes après une sortie.
- Pas d'entrée si spread > 0,1 %, prix éloigné du signal > 0,3 %, ou baisse maximale du portefeuille ≥ 10 %.
- Les frais sont hypothétiques : 0,05 % par côté sur l'exposition ; glissement 0,02 % par côté ; financement simplifié 0,01 % par 8 h au prorata, coût dans les deux sens.
- Liquidation indicative avec maintenance 0,5 %, pénalité 0,5 % et plancher de retour de marge à zéro. Ce plafond fictif ne garantit pas une protection réelle.
- Les cours spot servent de proxy ; absence de carnet complet, contrat dérivé, prix mark officiel, funding réel, latence et exécution réelle. Le financement ne modélise pas les règlements périodiques réels.
- Si la surveillance s'arrête, les seuils franchis entre deux relevés ne sont pas reconstruits. La sortie a lieu au premier prix observé disponible ; les trades concernés sont signalés incomplets. Une sauvegarde illisible bloque le moteur au lieu d'effacer l'historique.

Cette stratégie n'a pas été validée comme rentable. Les tests vérifient la mécanique comptable et certaines protections, pas la qualité prédictive.

## Vérification locale

    python -m unittest discover -v

Les tests couvrent LONG/SHORT, frais, conservation du solde, timeout, interruption, liquidation, arrêt sur baisse, bougies périmées/discontinues, sauvegarde corrompue et coexistence des routes.

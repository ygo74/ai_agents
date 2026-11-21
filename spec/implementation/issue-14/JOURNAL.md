# Journal — issue 14

- 2026-11-21 : demande de traitement de l'issue 14 en Python.
- Dépôt propre, initialement sur `main`. Actualisation `git fetch origin
  --prune` réussie après autorisation d'accès hors restrictions locales.
- Branche créée depuis `origin/main` : `issue-14-corporate-credit-python`.
  Base : `8e2c362c690456a050ddfd57d30af0f229b6f0b7`.
- Lecture de l'issue, AGENTS, WORKFLOW, spécification système et skills de
  développement/spécification. Aucun code d'agent crédit ou configuration
  EDGAR trouvé dans les zones examinées.
- SPEC rédigée ; validation explicite en attente selon le workflow du dépôt.
  Aucun plan ni code d'implémentation produit avant cette validation.
- SPEC approuvée par l'utilisateur (« Ok »). Skill implementation-plan appliqué,
  références d'architecture et intégrations existantes examinées.
- Source officielle EdgarTools examinée via GitHub : version amont 6.3.0,
  serveur edgartools-mcp, outils edgar_search et edgar_company. Pas de serveur
  EdgarTools installé dans l'environnement dev312 examiné.
- Versions locales : MAF core 1.18.0, OpenAI 1.14.3, MCP 1.30.0, runtime agents
  0.8.2. Le checkout runtime déclare 0.9.0 ; compatibilité du nouvel environnement
  et découverte live MCP à vérifier dans la première tâche d'implémentation.
- PLAN rédigé, validation explicite en attente. Aucun code modifié ni test
  d'intégration réel exécuté à cette étape.

- PLAN approuvé par l'utilisateur (« Ok »). TASKS créées sans troisième gate.
- TDD métier : échec initial d'import, 12 cas verts après implémentation ; TDD
  MCP : échec initial d'import, cas verts après adaptateur.
- Serveur officiel 6.3.0 installé séparément ; découverte MCP réelle réussie
  après autorisation et configuration du répertoire de cache accessible.
- Runtime 0.9.0 construit depuis le checkout voisin, framework core 1.18.0,
  framework OpenAI 1.14.3 et MCP 1.30.0. Aucune modification du runtime voisin.
- Identification SEC réelle réussie pour aapl, CIK avec/sans zéros, puis nom
  avec sélection : Apple Inc., 0000320193, SIC 3571, références SEC.
- Métadonnées de place non appariables : null avec avertissement ; secteur
  indépendant non fourni : null. Provenance canonique ajoutée dans l'adaptateur,
  sans requête HTTP SEC supplémentaire. Horodatage de récupération MCP explicite.
- Tests finaux : 25 tests nouveaux ; 36 tests Python 3.12 (nouveaux + MAF) ;
  1497 réussis/900 filtres ignorés Python 3.14 (nouveaux, architecture,
  installation, MAF existant). Ruff et mypy strict réussis, 22 fichiers typés.
- Documentation utilisateurs/contributeurs, configuration, exemples et rapport
  INTEGRATION livrés. Aucune clé modèle réelle utilisée ; framework réel testé
  avec modèle scripté exécutant la skill, données SEC réelles vérifiées séparément.
- Décisions d'architecture conformes au plan : un seul port métier, adaptation
  MCP officielle, aucune persistance conservée, aucune extension de serveur ni
  modification runtime nécessaire. Erreurs libres non classifiables signalées.
- Packaging vérifié : wheels credit/MAF construits et installés ; commande
  credit-agent disponible, validation structurée exécutée sans modèle/MCP ;
  pip check sans dépendance cassée. Vérification du diff avec cr-at-eol
  (les fichiers existants conservent leurs fins de ligne CRLF) réussie.
- Livraison locale prête pour relecture sur issue-14-corporate-credit-python ;
  aucun commit, push, PR, clôture d'issue ou fusion effectué.

## Commit/push explicitement demandé par l'utilisateur

- Skill origin-push appliqué ; branche issue-14-corporate-credit-python,
  origin actualisé, aucune branche homonyme distante avant publication.
- Contrôles Python 3.12 complets : ruff check . réussi ; mypy sans arguments,
  268 fichiers, réussi ; pytest complet avec rapport XML hors dépôt,
  2641 réussis, 900 filtres ignorés, 27 avertissements de dépréciation existants.
- Runtime utilisé via ses chemins publics de source 0.9.0 ; ces distributions
  sont identiques au tag local V0.9.0. Aucun changement dans le dépôt runtime.
- Le contrôle global des bindings livrés a révélé que sa liste Mail/Wiki
  devait inclure edgartools ; test de chargement Credit ajouté, 70 tests de
  configuration réussis puis les trois contrôles complets relancés avec succès.
- Les tests MCP locaux ont nécessité l'exécution hors des restrictions locales,
  comme la découverte initiale. Rapport final : /tmp/issue14-full-test-results.xml,
  exclu du commit. Données de contact et secrets absents des fichiers à publier.
- Commit limité à l'issue 14 préparé pour publication sur la branche de travail.

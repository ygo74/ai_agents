# Implementation Plan

## Issue

#6 — New candidate for migration to `ai-enterprise-agent-runtime`

## Specification

[`./SPEC.md`](./SPEC.md)

## Objectif

Compléter la migration générique de l’issue #6 déjà présente dans les branches
retenues par une intégration native LangChain/LangGraph dans le runtime, puis
faire adopter ce binding et l’hébergement managé par l’agent Wiki. Réutiliser
les contrats d’agent, l’orchestrateur d’approbation, le cache, les endpoints et
les adaptateurs de sortie existants ; garder la composition, les autorisations
et les tickets Wiki dans `ai_agents`.

## Rôle des dépôts

- **Dépôt principal — `ai_agents`**, issue #6. La branche
  `refactor/6-generic-conversation-and-mcp` contient déjà les abstractions
  conversationnelles/MCP de l’issue et porte l’adoption Wiki.
- **Dépôt secondaire — `ai-enterprise-agent-runtime`**. La branche
  `fix/25-openai-responses-python` contient le runtime générique, les adaptateurs
  LangChain de sortie et le précédent MAF. Elle porte le binding LangGraph et
  les tests/publications de la distribution d’intégration.
- Les dépôts gardent leurs historiques et validations séparés. La PR `ai_agents`
  dépend de l’API runtime correspondante.

## État déjà livré à réutiliser

- Le runtime possède `AgentDefinition`, `AgentFactoryContext`, `WorkerSettings`,
  `ManagedAgentWorker`, le cache conversationnel, le moteur HTTP, le protocole
  commun d’approbation et les adaptateurs de sortie LangChain.
- La distribution `agentframework` fournit déjà l’exemple de binding natif,
  de worker, d’admission et de cycle de vie framework-spécifiques.
- `ai_agents` a déjà migré Mail et Wiki vers les conversations et primitives
  MCP génériques de l’issue #6. Wiki conserve un moteur partagé, une factory de
  conversation et une session LangGraph locale.
- Ne pas réimplémenter ni réécrire ces éléments. Les compléter uniquement si
  l’intégration LangGraph révèle un manque générique démontré par les tests.

## Préconditions

- La SPEC révisée est approuvée explicitement.
- Le PLAN ci-dessous doit être approuvé avant tout changement de code.
- Continuer sur les branches explicitement retenues : runtime
  `fix/25-openai-responses-python` et `ai_agents`
  `refactor/6-generic-conversation-and-mcp`. Vérifier leurs remotes et statuts
  avant implémentation ; ne pas écraser, réinitialiser ou rebaser leurs commits.
- Les deux branches sont actuellement des descendants de leurs `origin/main`
  locaux. Le runtime est propre ; le worktree `ai_agents-issue-6` contient la
  SPEC et le PLAN révisés de cette tâche. Préserver ces modifications
  documentaires.
- Ne pas pousser, publier de version PyPI, fusionner ou créer une PR avant que
  le code et les validations aient été revus localement.
- Mesurer le coût local du binding et du dispatch sur des graphes/sessions
  simulés, sans modèle ni MCP distant. Comparer les mêmes fixtures avant/après
  pour appliquer les budgets de la SPEC.

## Vérification de la constitution

- **Réutilisation :** étendre la distribution `langchain` et les services
  génériques existants. Réutiliser les types neutres d’output, le moteur de
  conversation, `ManagedAgentWorker` et l’approbation bornée. Justifier chaque
  nouveau type par une lacune observée.
- **Frontières :** le package `agents` reste sans dépendance LangChain,
  LangGraph ou MAF. La distribution `langchain` dépend du core et des APIs
  framework nécessaires ; elle ne dépend pas du package MAF. Wiki dépend de
  l’intégration LangChain côté application.
- **Contrats et sécurité :** les appels LangGraph, états d’interruption,
  extraction de résultat et événements natifs restent dans l’intégration.
  Identité, gates, ticket store, renderer et admission du domaine restent dans
  l’application Wiki.
- **Typage :** exposer des Protocols/dataclasses annotés et les marqueurs
  `py.typed`. Limiter `Any` aux payloads bruts du SDK aux frontières.
- **Test-first :** couvrir les nouveaux contrats LangChain avec des faux
  graphes et données locales avant de les implémenter. Couvrir ensuite
  l’adoption Wiki et les frontières de packages.
- **Cycle de vie :** chaque flux, portée de factory, conversation mise en cache
  et connexion MCP doit être fermée sur succès, erreur, annulation, éviction et
  arrêt du worker.
- **Observabilité :** journaliser les catégories et identifiants nécessaires
  sans prompts, arguments/résultats d’outils, credentials ou états bruts.
- **Exemples :** inclure un exemple natif minimal avec au plus 30 lignes
  non blanches de glue d’intégration, hors composition métier et configuration
  opérateur.

## Étapes

### Étape 1 — Vérifier les APIs, versions et références existantes

**Objectif :** figer les contrats publics LangChain/LangGraph utilisés et
confirmer les points de réutilisation avant de coder.

**Fichiers/composants :** distribution `packages/python/langchain`, ses
adaptateurs `results.py`/`streaming.py`, `AgentDefinition`,
`ManagedAgentWorker`, `ApprovalLoop`, la composition/session/service Wiki et
leurs tests.

**Modifications :** utiliser les API publiques LangChain/LangGraph déjà
employées par `ai_agents`: `ainvoke`, `astream_events(version="v2")`,
`Command`/interruptions et `thread_id`. La distribution d’agent LangGraph
actuelle déclare `langchain>=1.3.3,<2` et `langgraph>=1.2,<2` ; le package
runtime LangChain déclare actuellement `langchain-core>=1.6.3,<1.7`. Garder
ces bornes compatibles et faire dépendre le binding natif du SDK LangGraph
seulement dans l’extra/distribution d’intégration approprié. Ne pas ajouter
`langchain-openai` au runtime : le choix fournisseur reste à l’application.
Confirmer la forme typée du hook d’admission et la factory de conversation
avancée à partir des call sites existants. Ne pas choisir d’API privée par
analogie avec le hook SDK propre à MAF.

**Validation :** confirmer par inspection des distributions et des tests
existants que les imports LangChain ne contaminent pas `agents`, que les
adaptateurs actuels couvrent les résultats SDK visés et que les branches sont
propres hors SPEC/PLAN approuvés. Vérifier les bornes déclarées par
`agents/langgraph/pyproject.toml`, `agents/wiki/pyproject.toml` et le package
runtime `langchain`. Capturer les timings locaux de référence avec des fixtures
déterministes.

### Étape 2 — Écrire les tests de contrat pour l’exécution LangGraph

**Objectif :** définir le comportement du binding natif à partir des sorties
et événements que `create_agent` produit réellement.

**Fichiers/composants :** nouveaux tests runtime d’intégration LangChain,
tests de packaging/public surface et fixtures de graphe LangGraph.

**Modifications :** écrire d’abord les tests pour : extraction du dernier
message assistant d’un état de graphe ; invocation avec le seul dernier texte
utilisateur et config `thread_id`; conversion d’usage/terminaison ; stream
`astream_events` public avec événements de contenu/outil ; filtrage des
événements d’entrée/chaîne ; diagnostics de conversion ; erreurs,
annulation, fermeture et une terminaison unique. Ajouter les tests des états
d’interruption, reprise/refus et du hook d’admission. Utiliser uniquement de
fausses sorties SDK et aucun appel réseau.

**Validation :** les tests doivent échouer sur l’absence du binding sans
modifier le package neutre ni les tests MAF existants.

### Étape 3 — Ajouter le binding natif à l’intégration LangChain

**Objectif :** exposer une session LangGraph native qui implémente les ports
neutres du runtime et réutilise les adaptateurs de sortie existants.

**Fichiers/composants :**
`packages/python/langchain/ygo74/agent_runtime/integrations/langchain/`,
`packages/python/langchain/pyproject.toml`, tests d’intégration et exports
publics.

**Modifications :** ajouter une classe de binding/scope LangGraph typée qui :

- accepte un graphe LangChain/LangGraph déjà construit et un identifiant de
  conversation ; ne reconstruit pas l’agent ;
- exécute le mode non-streaming par l’API publique et extrait le résultat
  assistant final de l’état sans traiter l’état entier comme une sortie ;
- exécute le vrai mode streaming via l’API publique, convertit les événements
  au moyen de `LangChainStreamAdapter` et conserve leur corrélation ;
- utilise `LangChainResultAdapter` pour résultat, usage, contenu et
  terminaison ; émet des diagnostics explicites pour les éléments non
  représentables ;
- ferme les producteurs et ne publie jamais de succès après erreur ou
  annulation ; n’expose pas les arguments ou résultats d’outils comme activité
  publique ;
- implémente les opérations de l’orchestrateur d’approbation commun en
  traduisant l’interruption LangGraph en objet typé puis en commande de reprise
  ou refus ; garde le nettoyage fail-closed et l’invalidation après état
  irrécupérable.

Déclarer une plage de versions cohérente avec les dépendances Wiki. Garder
FastAPI facultatif pour le binding seul, exporter les nouveaux symboles
documentés et inclure les marqueurs de typage.

**Validation :** faire passer les tests de l’étape 2, le typage strict, Ruff et
les imports/public surface de la seule distribution LangChain. Vérifier que les
imports/installations MAF et core seul restent indépendants.

### Étape 4 — Ajouter la façade worker avec composition avancée

**Objectif :** réduire la plomberie de démarrage tout en laissant Wiki injecter
sa conversation et son approval bridge de domaine.

**Fichiers/composants :** module worker optionnel de l’intégration LangChain,
`ManagedAgentWorker`, `AgentDefinition`/`AgentFactoryContext`, worker MAF de
référence, nouveaux tests de worker.

**Modifications :** composer les APIs neutres `WorkerSettings` et
`ManagedAgentWorker` plutôt que réécrire endpoints, auth, discovery, cache et
lifespan. Fournir une voie simple utilisant factory/definition de confiance
et une voie avancée acceptant une factory typée de conversation pour les
applications avec tickets/runners propres. Accepter les factories sync,
awaitable ou gestionnaires de contexte asynchrones suivant le contrat retenu.
Exiger une authentification opérateur et ne jamais lire la sélection de factory
depuis la requête. Valider la surface d’outils réelle ; si le graphe ne peut pas
être inspecté statiquement, exiger un hook d’admission de confiance.

**Validation :** tester factory et fermeture, auth obligatoire, descriptor et
surfaces, readiness, cache/éviction, fermeture à l’arrêt, factory avancée,
admission outil déclaré/non déclaré, et absence de fuite dans logs. Vérifier
qu’aucun nouvel endpoint ni cache concurrent n’est implémenté hors du runtime
générique.

### Étape 5 — Faire adopter le binding et le worker par Wiki

**Objectif :** conserver `create_agent` et la composition métier existants en
retirant l’exécution et la plomberie HTTP génériques de la session/service.

**Fichiers/composants :** `agents/wiki/.../application/composition.py`,
`session.py`, `entrypoints/conversation.py`, `entrypoints/service.py`,
`wiki_tools_provider.py` uniquement si la portée de ressources l’exige,
`agents/wiki/pyproject.toml`, tests Wiki conversation/LangGraph/service.

**Modifications :** faire utiliser à `WikiAgentSession` le binding natif pour
invocation, streaming neutre, adaptation d’interruption et cycle générique
d’approbation. Garder `WikiTicketApprovalResolver`, `WikiAgentRuntime`, le
ledger, le `WikiToolResultRenderer`, l’autorisation, les confirmations et les
gates dans l’application. Construire le graphe par principal dans la
composition Wiki et préserver `thread_id_of(principal, conversation_id)`.

Faire construire le service par le worker managé et la factory de conversation
avancée Wiki. Construire la définition/descripteur à partir des métadonnées
Wiki existantes, sans introduire une deuxième source de vérité. Conserver le
profil latest-user-text : ne jamais rejouer l’historique client. Activer les
surfaces HTTP déjà prises en charge par Wiki ; le streaming est exposé sur une
surface seulement si le binding et le contrat HTTP existants le supportent.
Préserver l’authentification, la découverte, les réglages opérateur, la
connexion MCP par conversation, l’admission des outils et la politique
read-only.

**Validation :** tests Wiki démontrant même identité/conversation → même état,
isolation entre principals, ticket traité avant invocation modèle, interruption
repris/refusée, sorties normales/stream correctes, aucune répétition de
l’historique client, fermeture MCP à éviction et arrêt, et erreurs d’autorisation
inchangées. Utiliser des graphes/modèles simulés et les fixtures MCP existantes.

### Étape 6 — Mettre à jour dépendances, documentation et exemple natif

**Objectif :** rendre l’intégration découvrable et installable, et démontrer
la réduction de glue sans masquer les responsabilités opérateur/domaine.

**Fichiers/composants :** `pyproject.toml`, `README.md`, `docs/python/langchain.md`,
guide natif runtime, exemple LangChain/FastAPI, guide Wiki/HTTP, règles de
frontière de distributions et documentation d’architecture/parité des deux
dépôts.

**Modifications :** documenter les versions, extras, factories, contexte,
admission, historique, streaming, approbation, limites du worker mono-processus
et responsabilités de déploiement. Ajouter un exemple hors ligne minimal avec
factory, définition et worker dans la limite de glue de la SPEC. Mettre à jour
le service Wiki et son guide selon l’API réelle ; ne pas introduire de secrets
ou de modèle distant dans l’exemple.

**Validation :** vérifier les chemins et commandes documentés, construire
isolément les wheels/sdists requis et contrôler les imports, métadonnées et
typing marker dans les environnements d’installation ciblés.

### Étape 7 — Validation croisée et revue locale

**Objectif :** établir les résultats des deux dépôts indépendamment et confirmer
les limites de la modification.

**Fichiers/composants :** distributions runtime LangChain, core agents, package
MAF en non-régression, agent Wiki, tests, docs et diffs des deux dépôts.

**Modifications :** corriger les écarts du périmètre approuvé ; maintenir les
versions et imports des deux intégrations indépendants. Mettre à jour le PLAN
avec résultats effectifs et toute limite de l’environnement.

**Validation :** exécuter tests ciblés LangChain/worker, tests Wiki et tests de
non-régression nécessaires, Ruff, mypy strict, builds isolés, contrôles de
frontière, `pip check` et `git diff --check` dans chaque dépôt. Relever les
timings sur les mêmes fixtures avant/après ; aucun test ne doit exiger une API
LLM, Confluence, Gmail, secret réel ou transport distant. Vérifier les statuts
et diffs séparément. Ne pas déclarer un contrôle PASS s’il n’a pas été exécuté.

## Tests

- **Binding LangGraph :** invocation normale et stream réel, extraction du
  message final, conversions typées, usage, terminaison, citations/contenu,
  événement inconnu, erreur, annulation et fermeture.
- **Cycle d’approbation :** interruption unique et multiple, reprise, refus,
  limite de question/tour, purge d’autorisation à abandon, erreur pendant le
  nettoyage et invalidation fail-closed.
- **Admission :** accord entre outils réels et déclarations ; surface dynamique
  non inspectable refusée sans hook explicite ; aucune déclaration n’accorde à
  elle seule une autorisation.
- **Worker :** factory synchrone/asynchrone/scopée, factory de conversation
  avancée, auth obligatoire, sélection d’export de confiance, cache, readiness,
  timeout, fermeture à éviction et drainage à l’arrêt.
- **Wiki :** isolation principal/conversation, `thread_id`, commandes avant
  modèle, tickets, formats HTTP, mode normal/stream configuré, configuration
  MCP existante, auth, capacités read-only, logs sans secret et fermeture des
  ressources.
- **Distribution :** core seul, LangChain seul, MAF seul et combinaisons
  supportées ; absence de dépendance croisées entre frameworks, wheel/sdist,
  imports publics et `py.typed`.
- **Qualité et performance :** Ruff, mypy strict, `pip check`, validations
  architecture et mesures locales déterministes selon la SPEC.

## Validation finale

- Les packages neutres du runtime n’importent pas LangChain/LangGraph ou MAF.
- `ygo74-agent-runtime-langchain` fournit le binding natif et la façade de
  worker avec des dépendances et versions documentées, sans partager de
  namespace de framework avec MAF.
- Wiki utilise le worker et le binding sans déplacer son domaine, son
  autorisation, ses tickets ou son modèle de composition.
- Les contrats HTTP/auth/discovery existants et les invariants conversation,
  approbation, identité et fermeture sont couverts par les validations
  effectivement exécutées.
- Les deux diffs Git sont isolés et revus. La PR runtime précède la PR
  `ai_agents` uniquement après validations et résultats présentables ; aucun
  merge ni publication PyPI n’est fait dans cette tâche sans décision
  ultérieure.

## Risques

- Les versions et flux de sortie LangGraph peuvent changer l’enveloppe d’état ;
  l’extracteur doit rester typé et couvert par les versions prises en charge.
- Les événements de chaîne/retriever ou snapshots d’outils peuvent divulguer
  des données internes si le binding ne sélectionne pas strictement les
  événements publics.
- Les graphes peuvent ajouter des outils par middleware/providers de contexte.
  L’admission doit vérifier le graphe construit ou refuser la surface.
- Le ticket bridge Wiki est une orchestration de domaine ; un worker trop simple
  pourrait forcer une seconde boucle d’exécution HTTP. La factory de conversation
  avancée est un point d’extension requis.
- Le streaming peut être interrompu par le client avant la terminaison ; la
  fermeture du graphe et de sa lease doit rester garantie sans déclarer un
  succès complet.
- Les plages de versions doivent rester compatibles avec les dépendances
  LangChain déjà sélectionnées par Wiki et ne pas imposer de mise à niveau
  applicative hors périmètre.
- Les deux dépôts ont un cycle Git et une publication distincts. Les validations
  locales contre le worktree runtime ne prouvent pas la disponibilité d’une
  version publiée dans les workflows distants.

## Décisions techniques

- Étendre `integrations.langchain` existant au lieu de créer un package ou un
  namespace parallèle. Réutiliser `LangChainResultAdapter` et
  `LangChainStreamAdapter`.
- Garder le package de base `agents` indépendant des frameworks. Utiliser
  `AgentDefinition`, `AgentFactoryContext`, `WorkerSettings` et
  `ManagedAgentWorker`; les ajouter seulement si un besoin générique est
  démontré.
- Garder une façade worker LangChain séparée facultativement installable avec
  HTTP. Elle fournit un parcours factory simple et accepte la factory de
  conversation avancée nécessaire aux intégrations domaine.
- Le binding possède les appels natifs et la traduction de résultat/stream ;
  le runtime neutre possède budgets, cache, transport et cycle de vie HTTP ;
  Wiki possède confirmation, politique et admission effective.
- Conserver `thread_id_of` comme frontière d’identité LangGraph ; le contexte
  fournisseur ne contient ni payload HTTP brut ni credentials.
- Ne pas modifier MAF, ses APIs ou Mail hors corrections de non-régression
  directement nécessaires et approuvées.

## Critères de réussite

- Les critères d’acceptation de la SPEC sont satisfaits dans les deux dépôts.
- L’intégration native LangChain/LangGraph réutilise les adaptateurs de sortie
  et les abstractions génériques sans nouvelle implémentation de cache,
  endpoints, transport ou tickets de domaine.
- Wiki délègue l’exécution native au package runtime, tandis que les règles
  Wiki et les confirmations restent locales.
- Les tests et contrôles listés passent ; versions réellement vérifiées et
  limites sont rapportées sans extrapoler au-delà des validations exécutées.

## État de réalisation — 2026-10-10

- Le binding natif LangGraph, son adaptation d’approbation et la façade
  `LangGraphWorker` sont implémentés dans la distribution LangChain du runtime.
  Les dépendances, la surface publique, la documentation et l’exemple hors
  ligne ont été mis à jour.
- Wiki délègue désormais invocation, streaming, approbations et hébergement
  managé au binding et au worker. Les tickets, le ledger, les autorisations,
  les ressources MCP et la composition restent dans l’application Wiki.
- Validations runtime : 28 tests passent ; Ruff, `pip check` et les builds des
  wheels/sdists des distributions LangChain, LangGraph et Wiki passent. Le
  build du sdist runtime signale l’absence d’un README standard.
- Validations Wiki/LangGraph : 332 tests passent, couvrant les tests unitaires,
  d’intégration, HTTP et sécurité. `compileall` passe dans les deux dépôts.
- Ruff passe sur les fichiers modifiés des deux dépôts. Le typage ciblé passe
  avec `mypy --strict --follow-imports=silent
  --disable-error-code=no-any-return` ; les dépendances importées n’ont donc
  pas fait l’objet d’une vérification mypy stricte complète.
- `git diff --check` passe dans le runtime et dans `ai_agents` avec
  `core.whitespace=cr-at-eol`, qui respecte les fins de ligne CRLF existantes
  dans ce dernier dépôt.
- Le démarrage du portal AnyIO était bloqué dans la sandbox ; les tests Wiki
  ont été exécutés hors sandbox après autorisation.
- Aucun baseline de performance n’a été capturé avant les changements. Les
  budgets de performance de la SPEC ne peuvent donc pas être déclarés validés.
- Les deux worktrees contiennent des changements non commités sur les branches
  retenues. Aucun commit, push, merge, publication PyPI ou PR n’a été créé.

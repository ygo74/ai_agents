# Implementation Plan

## Issue

#6 — New candidate for migration to `ai-enterprise-agent-runtime`

## Specification

[`./SPEC.md`](./SPEC.md)

## Objectif

Extraire les mécanismes communs de gestion d’une conversation HTTP et de boucle
d’approbation vers le runtime, puis faire adopter par Mail et Wiki les contrats
conversationnels et MCP génériques du runtime. Les objets de composition, les
sessions framework et les décisions métier restent propres aux agents.

## Préconditions

- La SPEC révisée est approuvée.
- Après l’approbation de ce PLAN, récupérer et vérifier le `main` distant des
  deux dépôts, puis créer des branches et worktrees indépendants :
  - `ai_agents` : `refactor/6-generic-conversation-and-mcp` ;
  - `ai-enterprise-agent-runtime` : `refactor/6-generic-conversation-and-mcp`.
- Le checkout courant de `ai_agents` contient une modification locale non liée
  dans `.vscode/launch.json`. La garder intacte. Reporter uniquement la SPEC et
  le PLAN approuvés dans le worktree `ai_agents` ; le worktree runtime part de
  son propre `origin/main`.
- Ne créer aucune branche et ne modifier aucun code avant approbation de ce
  PLAN. Ne travailler sur `main` ou sur l’un des checkouts courants.
- Mesurer les coûts locaux de référence des deux moteurs de conversation et du
  chargement des bindings avant les changements, sur des sessions simulées et
  les fichiers de configuration livrés. Réutiliser le même environnement et
  les mêmes fixtures après migration.
- Les deux dépôts ciblent Python 3.12. Le runtime MCP et les abstractions de
  conversation concernés sont Python-first ; aucune parité .NET/Java ne sera
  revendiquée pour ces APIs.
- Valider l’intégration de `ai_agents` contre le worktree runtime. Les
  workflows distants de `ai_agents` installent le runtime publié ; ne pas
  publier de version PyPI dans le cadre de cette issue.

## Vérification de la constitution

- **Parité :** consigner dans les documents de compatibilité que les transports
  MCP Python, le cache loué et les nouveaux moteurs de conversation Python
  restent Python-first. Conserver les contrats neutres déjà partagés et ne pas
  annoncer de parité .NET/Java inexistante.
- **Réutilisation :** étendre `domains/contracts/conversation.py`,
  `domains/sessions/`, `domains/humanapproval/` et `domains/mcp/`. Ne pas créer
  de nouveaux types avant d’avoir couvert les contrats et utilitaires existants.
- **Simplicité et frontières :** confier la gestion commune à des classes
  génériques et Protocols explicites. Garder les résultats de composition Mail
  et Wiki distincts ; ne pas créer une classe de base à champs optionnels.
  Garder les appels MAF et LangGraph dans leurs adaptateurs.
- **Typage :** utiliser des Protocols et génériques paramétrés pour les runtimes,
  sessions, états de framework et factories de dialectes. Passer mypy strict,
  éviter `Any` dans les nouvelles API publiques et conserver `py.typed`.
- **Test-first :** commencer chaque étape de comportement par des tests
  hermétiques qui échouent avant l’implémentation ; couvrir les contrats
  runtime, les deux intégrations et les frontières des distributions.
- **UX et erreurs :** garder le même ordre de traitement, le même texte de
  ticket inconnu, les mêmes identifiants de confirmations et les mêmes
  refus métier dans Mail et Wiki. Ne jamais convertir une erreur en succès.
- **Performance :** respecter les plafonds de régression de 10 % de la SPEC,
  sans nouvel aller-retour réseau, reconnexion ou état après la réponse.
- **Observabilité et secrets :** utiliser le logger standard du runtime ; ne
  jamais journaliser les en-têtes d’autorisation, valeurs de variables
  d’environnement, payloads ou décisions d’approbation.
- **Exemples :** actualiser les guides Mail/Wiki et le guide MCP Python pour que
  leurs parcours exécutables illustrent les imports génériques du runtime.

## Étapes

### Étape 1 — Préparer les worktrees isolés et relever les références

**Objectif :** établir deux espaces de travail propres et relever les mesures
de référence avant de toucher au comportement.

**Fichiers/composants :** métadonnées Git de `ai_agents` et
`ai-enterprise-agent-runtime`, SPEC/PLAN de l’issue, tests de conversation et
de bindings existants.

**Modifications :** après approbation du PLAN, synchroniser chaque `origin/main`,
créer les branches nommées dans des worktrees indépendants et y copier les
documents approuvés. Capturer les mesures locales de la SPEC avec les mêmes
faux runtimes/sessions avant et après.

**Validation :** vérifier branche, commit de base et arbre de travail propre de
chaque worktree. Vérifier que le checkout courant et son `.vscode/launch.json`
restent intacts. Enregistrer les médianes initiales, commandes et fixtures.

### Étape 2 — Ajouter les contrats et tests du conteneur et du moteur de conversation

**Objectif :** transformer le protocole et le cache existants en un chemin
générique réutilisable, sans connaître le framework de l’agent.

**Fichiers/composants :**
`packages/python/agents/ygo74/agent_runtime/domains/contracts/conversation.py`,
`domains/sessions/`, nouveaux tests sous
`tests/integration/python/`.

**Modifications :** définir les Protocols minimaux d’un runtime qui expose son
`UserContext` et ferme ses ressources, et d’une session qui répond à
`ask(message)`. Ajouter un conteneur générique portant runtime, session, store
de confirmations, runner, identifiant de conversation et renderer. Ajouter un
moteur concret conforme au protocole `ConversationEngine` existant : il loue
une conversation via `ConversationRuntimeCache`, traite le parseur de
confirmation avant `session.ask`, exécute le runner pour une commande reconnue,
puis construit `AgentReply` avec le texte et les confirmations en attente.
Centraliser le traitement du ticket inconnu. Ne pas modifier le protocole
public `ConversationTurn`/`AgentReply` sans nécessité démontrée par les tests.

**Validation :** écrire d’abord des tests runtime avec faux runtime et session
typés : isolation par principal, partage d’un seul build concurrent, lease
maintenue pendant le tour, commande reconnue avant `ask`, ticket inconnu,
rendu/identifiants des confirmations et fermeture sur éviction. Passer les
tests ciblés et le typage strict du package.

### Étape 3 — Centraliser la politique bornée de boucle d’approbation

**Objectif :** faire porter au runtime les budgets et garanties d’abandon
communs, en laissant chaque adaptateur traduire son état de framework.

**Fichiers/composants :**
`packages/python/agents/ygo74/agent_runtime/domains/humanapproval/`, nouveaux
tests d’intégration Python du runtime, puis
`agents/maf/`, `agents/langgraph/` et les deux `application/session.py` dans
`ai_agents`.

**Modifications :** définir un Protocol générique d’adaptateur de tour qui sait
extraire les approbations en attente d’un résultat, déterminer si la résolution
pose une question, produire les décisions, reprendre le framework et lire son
texte final. Ajouter un coordinateur du runtime qui gère les limites de
questions/tours, demande à l’adaptateur de refuser les opérations restantes et
purge le ledger avant et pendant l’abandon. L’abandon reste borné ; une erreur
du framework pendant le nettoyage est journalisée sans révéler le contenu et
ne réactive jamais une décision abandonnée.

Réduire `MailAgentSession` et `WikiAgentSession` à leurs adaptateurs MAF et
LangGraph : état/session ou `thread_id`, appels initiaux/reprise, extraction des
interruptions et conversion des réponses propres au framework. Conserver les
limites par défaut actuelles et les éventuels paramètres configurables.

**Validation :** tests runtime couvrant chemin sans approbation, compteur
d’approbations, limite totale, succès de reprise, abandon et refus de tous les
appels suspendus, purge du ledger, arrêt borné et erreur de nettoyage. Adapter
les tests d’intégration MAF/LangGraph pour vérifier les deux adaptateurs et
l’absence de changement visible.

### Étape 4 — Compléter les primitives MCP génériques du runtime

**Objectif :** couvrir les besoins de connexion observés dans les agents tout
en gardant les secrets et politiques applicatives hors du runtime.

**Fichiers/composants :**
`packages/python/agents/ygo74/agent_runtime/domains/mcp/binding.py`,
`domains/mcp/dialects.py`, `domains/mcp/mcp_errors.py`,
`tests/integration/python/test_mcp_plumbing.py`,
`spec/mcp/client-and-server.md`, `docs/python/mcp.md`.

**Modifications :** ajouter à `McpConnection` une entrée générique d’en-têtes
HTTP, transmise uniquement au transport HTTP et jamais journalisée. Renforcer
les annotations de `DialectRegistry` avec `ParamSpec`/Protocol plutôt qu’une
factory `Callable[..., Any]`, en gardant son ordre de dispatch documenté.
Accepter des factories d’erreur génériques pour permettre à une application de
conserver ses erreurs `MailToolUnavailableError`/`WikiToolUnavailableError`
sans multiple héritage ; garder les erreurs de binding runtime explicites.
Ne pas déplacer dans cette étape la construction des headers Wiki, le choix
OAuth Mail, la résolution Wiki des sources de variables d’environnement ou
son filtre lecture seule.

**Validation :** écrire d’abord les tests de propagation d’en-têtes HTTP sans
fuite dans logs/représentations, de factory de dialecte typée, d’erreur
personnalisée, et de session paresseuse, concurrente et refermée. Vérifier
l’extra `[mcp]` facultatif et les imports sans framework agentique.

### Étape 5 — Faire adopter les abstractions de conversation par Mail et Wiki

**Objectif :** supprimer les deux implémentations locales du conteneur et du
moteur de requêtes HTTP tout en gardant les runtimes de composition distincts.

**Fichiers/composants :**
`agents/mail/.../application/entrypoints/conversation.py`,
`agents/wiki/.../application/entrypoints/conversation.py`, les deux
`application/composition.py`, les factories, services HTTP, et tests
`tests/integration/test_conversation_engine.py`,
`tests/integration/test_wiki_conversation_engine.py`,
`tests/contract/test_openai_http_surface.py`.

**Modifications :** importer le conteneur et le moteur communs du runtime,
faire construire le conteneur par les factories locales, et supprimer les
classes `MailConversation`/`WikiConversation` et moteurs redondants. Faire
satisfaire à `MailAgentRuntime` et `WikiAgentRuntime` le petit Protocol
structurel sans leur faire hériter d’une base commune. Garder les factories
locales, les renderers et les résolveurs de tickets dans chaque application.
Adapter entrypoints, services et tests aux imports et types génériques.

**Validation :** préserver les scénarios HTTP des deux agents : continuité
isolée par principal, session réutilisée, confirmations traitées avant le
framework, rendu de réponses et de confirmations, arrêt/éviction et libération
des ressources. Exécuter les tests runtime du moteur et les tests HTTP des deux
agents.

### Étape 6 — Faire adopter le client MCP runtime par Mail et Wiki

**Objectif :** remplacer les copies de plomberie MCP dans les deux agents tout
en gardant les dialectes et les politiques locales.

**Fichiers/composants :** modules `mcp/binding.py` et `mcp/connection.py` des
agents Mail/Wiki, leurs fournisseurs, discover/authorise, dialectes, clients
`native`, `gmail` et `atlassian`, tests MCP, pyprojects et test
`tests/architecture/test_distribution_boundaries.py`.

**Modifications :** faire utiliser `McpServerBinding[MailToolName]` et
`McpServerBinding[WikiToolName]`, les loaders, `McpConnection` et
`DialectRegistry` génériques du runtime. Supprimer les copies locales de
binding, loader, connexion et registre ; conserver dans les modules locaux les
factories concrètes et `DialectContext`. Adapter l’ordre et les annotations
des factories au contrat du registre runtime.

Dans Wiki, résoudre les références d’environnement vers des valeurs au moment
de construire le binding transmis à la connexion générique ; refuser une
variable absente et ne jamais la journaliser. Passer les en-têtes Wiki par
utilisateur dans le paramètre HTTP générique. Dans Mail, préserver les modes
OAuth/bearer et les contrats de dialecte Gmail/native. Les catalogues,
énumérations, filtres read-only, traductions de payload et erreurs métier
restent locaux.

Mettre à jour les dépendances pour demander explicitement l’extra MCP du
runtime. Garder les dépendances SDK directes de Mail/Wiki là où leurs propres
clients et adaptateurs importent encore `mcp.types` ou le SDK OAuth. Mettre à
jour la règle d’architecture qui autorise les imports runtime dans les couches
concernées, sans ouvrir de dépendance vers les frameworks dans le runtime.

**Validation :** exécuter les tests de bindings livrés, transports, erreurs,
dialects Mail/Wiki, auth HTTP, résolutions de variables, capacités read-only,
discovery/authorise et clients simulés. Ajouter les tests de frontières qui
garantissent que les catalogues et adaptateurs concrets restent dans
`ai_agents`.

### Étape 7 — Mettre à jour les contrats, exemples et documentation

**Objectif :** documenter l’API commune et l’emplacement des responsabilités
après migration.

**Fichiers/composants :** runtime `docs/python/agent-runtime.md`,
`docs/python/human-in-the-loop.md`, `docs/python/mcp.md`, `spec/mcp/` et
`docs/parity-status.md` ; `ai_agents/spec/architecture/architecture.md`,
`runtime-extraction-candidates.md`, guides Mail/Wiki, guide d’ajout d’agent,
docs MCP et docstrings publiques.

**Modifications :** documenter l’usage générique du conteneur/moteur de
conversation, le Protocol d’adaptateur d’approbation, les limites de chaque
framework, les headers MCP, l’extra d’installation et les règles de secrets.
Réviser les inventaires de migration pour marquer l’adoption du client MCP et
des abstractions conversationnelles. Garder les guides Mail/Wiki comme exemples
exécutables et clarifier que les runtimes de composition, skills et dialectes
restent applicatifs.

**Validation :** vérifier tous les chemins/imports/documentations référencés,
construire les distributions Python concernées et s’assurer que chaque extrait
de démarrage correspond aux signatures publiques finales.

### Étape 8 — Validation croisée, revue et livrables

**Objectif :** valider les deux dépôts séparément et produire des changements
prêts à relire.

**Fichiers/composants :** les deux worktrees, distributions Python, suites
pytest, Ruff/mypy, architecture et diffs finaux.

**Modifications :** corriger seulement les écarts dans le périmètre approuvé.
Vérifier la compatibilité des versions/extras et les imports de packages
installés. Préparer d’abord la PR runtime, puis la PR `ai_agents` qui la
référence. Ne pas fusionner et ne pas publier de release PyPI dans cette issue.

**Validation :** exécuter les suites ciblées puis les contrôles qualité des deux
dépôts, builds des packages, contrôles de frontières et mesures de performance
sur les mêmes fixtures qu’à l’étape 1. Inspecter les deux statuts/diffs,
exécuter `git diff --check` dans les worktrees propres et confirmer que les
modifications locales initiales n’y figurent pas.

## Tests

- **Runtime — conversations :** conteneur, Protocols, moteur, cache loué,
  isolation du principal, commandes de confirmation, ticket inconnu, réponse,
  éviction et fermeture ; tous les tests utilisent des fausses sessions et
  runtime sans fournisseur LLM.
- **Runtime — approbation :** limites, branche sans question, reprise, abandon,
  purge du ledger, refus fail-closed et erreur de nettoyage.
- **Runtime — MCP :** bindings génériques, factories typées, headers, erreurs
  personnalisées, connexion paresseuse/concurrente/fermeture et imports
  facultatifs.
- **Agents :** tests Mail et Wiki des parcours de conversation, adaptateurs MAF
  et LangGraph, providers, auth, config livrée, capacités, dialectes natifs et
  fournisseurs, plus la suite HTTP.
- **Architecture et qualité :** tests de frontières dans `ai_agents`, pytest,
  Ruff et mypy strict dans chaque dépôt, builds/metadata wheel et vérification
  que le runtime n’importe pas de framework agentique.
- **Performance :** médianes sur les mêmes fixtures locales avant/après. Les
  chargements de binding et le dispatch avec faux états restent chacun à moins
  de 10 % du baseline ; aucun aller-retour réseau supplémentaire ni nouvelle
  allocation conservée après réponse.

## Validation finale

- Les deux branches d’issue sont basées sur leurs `origin/main` respectifs et
  contiennent uniquement les changements de l’issue.
- Le runtime contient une seule implémentation générique du conteneur/moteur
  HTTP conversationnel, de la politique commune d’approbation et du client MCP.
- Mail/Wiki utilisent ces APIs publiques. Leurs sessions MAF/LangGraph, runtimes
  de composition, skills, catalogues, secrets et dialectes restent dans
  `ai_agents`.
- Les contrats conversationnels conservent l’isolation, l’ordre sûr des
  confirmations et l’abandon fail-closed. Les contrats MCP conservent les
  comportements Mail/Wiki documentés.
- Tous les contrôles ciblés et qualité spécifiés passent dans les deux dépôts ;
  les budgets de performance restent respectés.
- La PR runtime est créée avant la PR `ai_agents`, qui la référence. Aucun
  merge ni publication PyPI n’est effectué.
- Le checkout initial de `ai_agents`, notamment `.vscode/launch.json`, reste
  inchangé.

## Risques

- Un moteur commun de conversation pourrait lier le runtime aux détails des
  frameworks. Les Protocols doivent rester étroits et les conversions de
  résultats/interruption doivent demeurer dans les adaptateurs locaux.
- Les boucles d’abandon sont des garde-fous de sécurité. Une erreur dans
  l’adaptateur ou dans l’ordre de purge/reprise peut laisser une opération
  suspendue ; les tests doivent prouver que le ledger est purgé avant tout
  nettoyage qui peut échouer.
- Mail et Wiki exposent des hiérarchies d’erreurs métier existantes. Les
  factories d’erreurs runtime doivent les préserver sans multiple héritage et
  sans divulguer d’informations sensibles.
- Les valeurs d’autorisation Wiki et d’environnement stdio ne doivent apparaître
  ni dans un binding livré, ni dans les logs, ni dans une représentation.
- Les clients Mail/Wiki importent toujours certaines parties du SDK MCP pour
  les payloads et OAuth ; retirer à tort leur dépendance directe briserait leurs
  dialectes même si le transport a migré.
- Les workflows de `ai_agents` utilisent une version runtime PyPI plutôt que le
  worktree local. La validation locale croisée ne doit pas être présentée comme
  preuve du résultat CI distant tant que le package runtime correspondant n’est
  pas disponible.
- L’intégration couvre autour de quarante call sites MCP et deux frameworks.
  Garder les changements séparés par étapes et comparer chaque comportement à
  ses tests actuels.

## État de réalisation — 2026-09-27

- Les deux worktrees isolés sont sur `refactor/6-generic-conversation-and-mcp`.
- Les abstractions génériques de conversation et d’approbation sont ajoutées au
  runtime et adoptées par Mail/Wiki ; les mécanismes MCP runtime sont également
  adoptés en conservant les politiques et dialectes propres aux agents.
- La documentation du runtime, la parité Python-first, l’architecture et les
  guides Mail/Wiki ont été mis à jour.
- Python 3.12.14 et les dépendances du projet sont disponibles dans les
  environnements virtuels des checkouts initiaux.
- Validations déjà exécutées : 33 tests runtime, 14 tests Mail de conversation,
  les tests synchrones ciblés de `ai_agents`, Ruff ciblé dans les deux worktrees
  et mypy strict sur les modules runtime et agents touchés. Après les corrections
  de typage, le mypy ciblé passe sur cinq modules runtime et 17 modules agents ;
  les deux registres de dialectes passent leurs cinq tests ciblés.
- Ruff complet passe dans `ai_agents`. Dans le runtime, les modules modifiés
  passent Ruff, mais l’analyse complète signale 34 violations dans
  `docs/examples/`, hors des fichiers de cette issue.
- Les tests Wiki de conversation vérifient leurs assertions, mais restent
  bloqués lors de la fermeture de la boucle `pytest-asyncio`. Le blocage a aussi
  été reproduit sur le checkout initial ; un appel direct au moteur Wiki renvoie
  la réponse attendue. Il reste à diagnostiquer ou à documenter comme limite de
  l’environnement de test.
- Les mesures de référence n’ont pas été prises avant l’implémentation. Les
  budgets de performance de la SPEC ne peuvent donc pas être déclarés validés.
- Les builds de distributions et les vérifications CI distantes restent à
  effectuer : la commande `build` et les backends `setuptools`/`hatchling` ne
  sont pas installés dans les environnements disponibles. Aucune branche n’a
  été poussée et aucune pull request n’a été créée.

## Décisions techniques

- Le runtime fournit le conteneur et le moteur génériques de conversation dans
  `domains.sessions`; `ConversationTurn`, `AgentReply` et le protocole
  `ConversationEngine` existants restent les contrats de bordure.
- Un Protocol structurel minimal relie les runtimes applicatifs au conteneur.
  `MailAgentRuntime` et `WikiAgentRuntime` ne partagent pas de classe de base.
- Le runtime fournit un coordinateur de boucle d’approbation dans
  `domains.humanapproval`. Les adapters MAF/LangGraph implémentent les
  interfaces typées de lecture, reprise et refus de leur état de framework.
- Les erreurs métier Mail/Wiki demeurent locales. Le runtime MCP accepte une
  factory d’erreur typed pour les erreurs de transport/dialecte ; les erreurs
  de binding génériques sont maintenues explicites à la frontière de config.
- Les headers sont un paramètre de transport générique. La création du header
  Wiki, l’OAuth Mail, la résolution des valeurs des variables Wiki et le filtre
  read-only demeurent dans `ai_agents`.
- Les APIs MCP et la nouvelle orchestration de conversation sont Python-first.
  La parité .NET/Java existante n’est pas modifiée ni revendiquée pour ces
  APIs ; ce statut est documenté dans le runtime.
- Les APIs restent dans leurs sous-packages métier publics. Aucun alias de
  compatibilité ne sera ajouté pour les classes génériques supprimées des
  distributions Mail/Wiki.

## Critères de réussite

- Les classes génériques Mail/Wiki identiques sont remplacées par les
  abstractions runtime décrites dans la SPEC ; aucun framework agentique
  n’entre dans une distribution runtime.
- Les runtimes de composition Mail/Wiki restent différents et typés. Le code
  spécifique MAF/LangGraph est réduit à des adaptateurs de session, tandis que
  l’abandon sécurisé est implémenté une fois.
- Les deux ensembles de tests d’agents réussissent contre le runtime du
  worktree, les contrôles qualité passent et les documents décrivent le même
  état que les APIs publiées.
- Les budgets de régression et les limites de secrets de la SPEC sont validés.
- Les PR des deux dépôts sont ouvertes dans l’ordre de dépendance et aucune
  n’est fusionnée.

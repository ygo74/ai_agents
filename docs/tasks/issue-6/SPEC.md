# Specification

## Issue

`ygo74/ai_agents` issue #6, “New candidate for migration to ai-enterprise-agent-runtime”.

## Objectif

Extraire vers `ai-enterprise-agent-runtime` les mécanismes conversationnels et MCP que Mail et Wiki ont en commun, puis faire utiliser ces contrats génériques aux deux agents. Les abstractions doivent réduire le code d’intégration requis sans déplacer dans le runtime les agents, politiques ou décisions propres à Mail, Wiki ou à un framework.

Le développeur d’un agent doit pouvoir réutiliser la gestion d’une conversation HTTP, son cycle de vie et le traitement borné des approbations en fournissant des types/ports typés propres à son framework et à son domaine. Il doit également pouvoir réutiliser le chargement d’un binding, le cycle de vie d’une connexion MCP et l’enregistrement de dialectes. Le runtime ne prend aucune dépendance directe à Microsoft Agent Framework, LangChain, LangGraph ou CrewAI.

## Contexte

Cette issue concerne deux dépôts indépendants :

- `ai_agents` est le dépôt source et le dépôt de l’issue. Il contient les agents Mail (Microsoft Agent Framework) et Wiki (LangChain/LangGraph), ainsi que leurs tests et leur configuration MCP livrée.
- `ai-enterprise-agent-runtime` est la cible de migration. Son package Python `ygo74-agent-runtime-agents` contient déjà `domains.mcp` : `McpServerBinding`, `McpServerBindingLoader`, `McpConnection`, `DialectRegistry` et les erreurs MCP. Le client MCP reste une capacité Python optionnelle via l’extra `[mcp]`.

L’analyse de duplication existante dans `ai_agents/spec/architecture/runtime-extraction-candidates.md` compte des implémentations largement similaires dans Mail et Wiki. Elle indique que la plomberie MCP générique est déjà livrée et testée dans le runtime, mais que les deux agents n’ont pas encore migré leurs consommateurs. La même analyse distingue explicitement le mécanisme générique des décisions propres à un domaine.

La gestion HTTP d’une conversation est elle aussi dupliquée. `MailConversation` et `WikiConversation` ont la même structure et les mêmes opérations (fermeture, tickets en attente, rendu des confirmations). Leurs `MailConversationEngine` et `WikiConversationEngine` prennent tous deux un `ConversationTurn`, louent une entrée de `ConversationRuntimeCache`, reconnaissent une commande de confirmation avant d’appeler le modèle, puis construisent un `AgentReply` avec les confirmations restantes. Le runtime possède déjà `ConversationTurn`, `AgentReply`, le protocole `ConversationEngine` et le cache générique, mais pas cette implémentation réutilisable.

Les sessions d’approbation sont également similaires dans leurs limites de tours et leur obligation de vider/refuser les actions encore suspendues avant d’abandonner un tour. Leurs détails d’exécution diffèrent toutefois : Microsoft Agent Framework porte l’état dans un objet `AgentSession`, tandis que LangGraph le reprend avec un `thread_id` et une commande de reprise. Les adaptateurs de framework doivent rester aux côtés de ces frameworks.

Les autres similitudes relevées ne constituent pas de nouveaux candidats immédiats : le runtime possède déjà les contrats et mécanismes communs de sécurité, approbation, sessions, configuration HTTP et raisonnement. Les compétences, modèles, catalogues, racines de composition et boucles propres aux frameworks restent des responsabilités des agents.

## Problème

Les agents Mail et Wiki conservent des classes conversationnelles et une plomberie MCP très similaires alors que le runtime possède déjà plusieurs contrats et mécanismes génériques adaptés. Les duplications de conversation peuvent laisser dériver la reconnaissance des confirmations, le rendu des tickets et la fermeture des ressources. Les duplications MCP peuvent laisser dériver la validation des bindings et le cycle de vie des connexions. Dans les deux cas, un nouvel agent doit encore réécrire une partie du même code.

La migration doit toutefois préserver des besoins réels du Wiki : envoyer des en-têtes HTTP d’autorisation par utilisateur, résoudre les références de variables d’environnement d’un serveur stdio sans placer les secrets dans le YAML, et retirer les capacités d’écriture en mode lecture seule. Ces règles ne doivent pas être déplacées dans une implémentation générique du runtime lorsqu’elles relèvent de la politique de déploiement ou du domaine Wiki.

Elle doit aussi garder les objets `MailAgentRuntime` et `WikiAgentRuntime` ainsi que les appels de session aux frameworks dans les applications. Ces runtimes contiennent des agents, des outils et des compétences différentes ; les réunir dans une classe de base avec un grand nombre de champs optionnels ne créerait pas un contrat utile. Un petit protocole structurel de cycle de vie peut suffire là où le runtime générique a besoin d’un `UserContext` et d’une opération asynchrone de fermeture.

## Périmètre

### Dans `ai-enterprise-agent-runtime`

- Compléter `domains.sessions` à partir de `domains.contracts.conversation` avec :
  - un conteneur générique de conversation portant un runtime d’application et une session qui expose `ask(message)` ;
  - un moteur de conversation générique qui loue le runtime via `ConversationRuntimeCache`, traite les commandes de confirmation avant la session, exécute un ticket confirmé et construit la réponse avec les confirmations en attente ;
- Compléter `domains.humanapproval` avec un orchestrateur borné et framework-neutre pour la boucle d’approbation, défini par des Protocols explicites pour examiner un état de framework, reprendre l’exécution et refuser ce qui reste en attente.
- Centraliser dans cet orchestrateur les limites de questions/tours et le comportement d’abandon sûr. Il doit vider les autorisations déjà enregistrées et ne jamais laisser des opérations suspendues s’exécuter lors d’un tour ultérieur après abandon.
- Réutiliser et, si nécessaire, faire évoluer les API Python génériques existantes pour couvrir les usages actuels des deux agents :
  - binding MCP et validation du transport, des capacités et des correspondances de noms d’outils ;
  - chargement depuis un chemin fourni par l’application, sans imposer au runtime où résident les fichiers de configuration ;
  - cycle de vie asynchrone d’une connexion stdio ou HTTP streamable ;
  - transmission générique d’en-têtes HTTP à la connexion ;
  - registre de dialectes réutilisable avec le type de résultat et les arguments propres à l’application.
- Conserver l’extra MCP facultatif et la séparation du package : importer les contrats ou le reste du runtime ne doit pas imposer l’installation du SDK MCP.
- Documenter les APIs retenues, les responsabilités de l’application et le statut Python-first dans les documents MCP et de parité pertinents.

### Dans `ai_agents`

- Remplacer `MailConversation` et `WikiConversation` par le conteneur générique du runtime et leurs `MailConversationEngine`/`WikiConversationEngine` par son moteur commun.
- Adapter `MailAgentSession` et `WikiAgentSession` pour déléguer le contrôle générique des limites et de l’abandon au nouvel orchestrateur, tout en gardant dans chaque adaptateur les appels et les formes d’état propres à son framework.
- Garder `MailAgentRuntime` et `WikiAgentRuntime` comme résultats de composition locaux, distincts et typés selon leurs frameworks et domaines. Ils peuvent satisfaire le protocole minimal requis par le conteneur générique sans hériter d’une classe runtime commune.
- Garder les `MailConversationFactory`/`WikiConversationFactory` comme composition locale des outils, stores, renderers et sessions spécifiques ; elles construisent le nouveau conteneur générique.
- Faire utiliser aux fournisseurs Mail et Wiki les types génériques publics du runtime pour les bindings, les connexions et les mécanismes de registre.
- Supprimer les implémentations locales correspondantes qui ne contiennent plus de logique propre aux agents.
- Garder dans `ai_agents` les dialectes et adaptateurs concrets, les ports `MailTools` et `WikiTools`, les catalogues et énumérations de capacités, les filtres de capacités propres à un déploiement, ainsi que les politiques d’authentification Gmail et Wiki.
- Adapter les tests, dépendances de distributions, règles d’architecture et documentation nécessaires à ces nouveaux imports.

## Hors périmètre

- Migrer les compétences, capacités métier, modèles de domaine, catalogues Mail/Wiki, racines de composition ou implémentations concrètes Gmail et Atlassian.
- Fusionner `MailAgentRuntime` et `WikiAgentRuntime` en une classe de base contenant les objets `agent`, `skills`, `tools` et autres champs spécifiques aux applications.
- Remplacer les adaptateurs Microsoft Agent Framework ou LangGraph par un nouvel framework du runtime. Le runtime reçoit des Protocols typés implémentés par les adaptateurs locaux.
- Migrer les adaptateurs Microsoft Agent Framework, LangChain/LangGraph ou CrewAI, ou ajouter l’un de ces frameworks comme dépendance du runtime.
- Déplacer la politique d’autorisation Wiki, le retrait de capacités en lecture seule, la politique OAuth Gmail, les secrets ou les décisions relatives aux identités dans le runtime.
- Ajouter une implémentation MCP .NET ou Java. Le client MCP reste Python-first dans cette issue et son statut de parité doit rester explicite.
- Modifier le format des fichiers YAML déjà livrés sous `config/mcp/`, sauf si l’analyse d’implémentation identifie une incompatibilité bloquante et obtient une décision séparée.
- Migrer l’hébergement des serveurs MCP ; cette issue porte sur les clients MCP utilisés par les agents.

## Comportement attendu

1. Les deux agents chargent leurs bindings avec les API génériques du runtime en fournissant leurs propres énumérations `StrEnum` de capacités. Un binding ne peut déclarer une capacité inconnue de l’application et les capacités ou alias manquants sont signalés avant l’appel d’un outil.
2. Les fichiers de configuration existants continuent à désigner les mêmes serveurs, transports, capacités, dialectes et alias. Les erreurs de configuration restent des refus explicites plutôt qu’une activation partielle du client.
3. Une connexion ouvre paresseusement une seule session MCP, la réutilise lors des appels concurrents, puis libère correctement son transport à la fermeture de la conversation.
4. Les connexions HTTP peuvent transmettre les en-têtes calculés par l’application. Pour Wiki, le jeton ou l’en-tête d’autorisation reste limité à la connexion du bon utilisateur et n’apparaît ni dans les logs ni dans les représentations d’objets.
5. Les environnements stdio continuent à recevoir les variables nécessaires. Wiki résout les noms de variables configurés depuis l’environnement d’exécution, refuse une variable absente et ne journalise jamais sa valeur. Le mécanisme générique ne donne pas au runtime la responsabilité de la politique de secret du Wiki.
6. Les capacités exposées restent celles que le serveur et le déploiement peuvent effectivement servir. En particulier, le mode lecture seule du Wiki retire les capacités d’écriture selon la règle actuelle ; cette interprétation demeure dans l’application Wiki.
7. Les dialectes `native`, `gmail` et `atlassian` continuent à construire les mêmes ports métier et à appliquer leurs traductions actuelles. L’agent Mail continue à choisir ses identifiants OAuth ou bearer selon sa configuration, et Wiki conserve son contexte de dialecte et ses garanties d’identité.
8. Les exceptions observables aux frontières des agents conservent leurs catégories métier et protocolaires actuelles. Les erreurs génériques de transport, de binding et de dialecte ne doivent pas être transformées en succès, en absence de résultat ou en autorisation implicite.
9. Les imports de l’API client MCP du runtime ne requièrent pas les frameworks agentiques. Les installations sans extra `[mcp]` peuvent encore utiliser les autres domaines du runtime.
10. Le nouveau moteur générique de conversation fournit le même traitement avant/après session dans Mail et Wiki : isolation via le principal authentifié et le cache loué, commande de confirmation traitée avant le modèle, récupération sûre d’un ticket inconnu, puis `AgentReply` avec les tickets toujours en attente.
11. La boucle bornée partagée conserve les limites par défaut actuelles, purge les décisions de confirmation à l’abandon et refuse les appels qui restent suspendus. Les adaptateurs de framework restent responsables de l’inspection de leurs résultats, de la reprise et de l’extraction du texte final.
12. `MailAgentRuntime` et `WikiAgentRuntime` restent des types locaux distincts. Les classes locales `MailConversation`/`WikiConversation` et les moteurs de requête spécifiques sont supprimés une fois remplacés par les composants runtime ; les factories locales et les adaptateurs de session framework restent.

## Architecture concernée

- `ai-enterprise-agent-runtime/packages/python/agents/ygo74/agent_runtime/domains/mcp/` : binding, loader, connexion, registre de dialectes et erreurs génériques.
- `ai-enterprise-agent-runtime/packages/python/agents/ygo74/agent_runtime/domains/contracts/conversation.py` et `domains/sessions/` : contrats turn/reply/engine déjà existants, cache générique et nouveaux composants conversationnels.
- `ai-enterprise-agent-runtime/packages/python/agents/ygo74/agent_runtime/domains/humanapproval/` : nouvelles interfaces/implémentation générique de la boucle d’approbation bornée.
- `ai-enterprise-agent-runtime/tests/integration/python/test_mcp_plumbing.py`, `spec/mcp/client-and-server.md`, `docs/python/mcp.md` et `docs/parity-status.md` : couverture et contrats de la capacité MCP.
- Tests d’intégration `test_conversation_engine.py` et `test_wiki_conversation_engine.py`, plus les sessions `MailAgentSession` et `WikiAgentSession`, comme références comportementales des agents.
- `ai_agents/agents/mail/.../mcp/` et `ai_agents/agents/wiki/.../mcp/` : implémentations génériques locales à remplacer ; les sous-modules de dialectes concrets et les clients métier restent locaux.
- `ai_agents/agents/mail/.../application/mail_tools_provider.py` et `ai_agents/agents/wiki/.../application/wiki_tools_provider.py` : composition des abstractions runtime avec les choix propres aux agents.
- Tests MCP, règles de frontières de distributions et guides/configurations concernés dans `ai_agents`.

Le runtime fournit les mécanismes génériques et reste ignorant des noms de capacités, des décisions lecture/écriture et des fournisseurs. Chaque agent conserve un adaptateur typé entre ce mécanisme et ses contrats métier.

## Contraintes

- Respecter la constitution et les instructions Python du runtime : réutilisation avant création, interfaces explicites et typées, aucun enregistrement structuré non typé présenté comme contrat, et tests de contrat, d’intégration et de parité selon le périmètre.
- Ne pas ajouter de dépendance directe à LangChain, LangGraph, Microsoft Agent Framework ou CrewAI dans une distribution du runtime. L’extra `[mcp]` peut fournir le SDK MCP, HTTPX et PyYAML.
- Préserver les limites entre les dépôts et leurs historiques. Les changements du runtime et de `ai_agents` appartiennent à des branches et livrables séparés.
- Préserver la modification locale préexistante de `ai_agents` dans `.vscode/launch.json` et l’exclure des changements de l’issue.
- Comparer les comportements actuels et l’API MCP du runtime avant toute suppression de code. Le registre générique existant utilise une fabrique extensible ; sa signature et les adaptateurs concrets doivent rester vérifiables sous le typage strict du projet.
- La SPEC doit être approuvée avant le PLAN, et le PLAN avant toute implémentation, conformément au workflow habituel de l’issue.

## Critères d’acceptation

1. Les implémentations génériques du binding, de la connexion et du registre ne sont plus dupliquées dans les paquets Mail et Wiki ; les deux agents importent et utilisent les API publiques du runtime.
2. Les deux domaines continuent à fournir leurs propres énumérations de capacités et dialectes ; aucun nom ni aucune règle métier Mail/Wiki n’est introduit dans `domains.mcp`.
3. Les bindings actuellement livrés sont chargés correctement et les règles de validation, de capacités, d’alias, de transport et d’erreurs documentées restent effectives.
4. Le runtime couvre avec des tests les connexions HTTP comportant des en-têtes génériques, le cycle de vie de session et l’usage concurrent ; les tests restent hermétiques et ne nécessitent ni Gmail, ni Confluence, ni identifiants réels.
5. Les tests Wiki démontrent que l’autorisation HTTP reste par utilisateur, que les valeurs d’environnement stdio ne sont jamais exposées et que les variables manquantes provoquent un refus, et que la politique lecture seule continue à retirer les capacités d’écriture.
6. Les tests Mail démontrent que les transports natifs et Gmail continuent à utiliser leurs dialectes, leurs authentifications et leurs contrats de capacités.
7. Les tests de frontières confirment que les domaines et exemples MCP du runtime n’importent aucun framework agentique et que l’extra `[mcp]` demeure optionnel pour les autres usages.
8. Les documentations des deux dépôts décrivent correctement les responsabilités génériques et applicatives ainsi que la parité Python-first.
9. Les commandes ciblées de validation et les contrôles qualité requis des deux dépôts passent ; les mesures locales de chargement des bindings ne régressent pas de plus de 10 % sur les mêmes fixtures. Aucun détour par le réseau ne doit être ajouté au chemin de connexion ou d’appel existant.

## Stratégie de test

- Utiliser `ai-enterprise-agent-runtime/tests/integration/python/test_mcp_plumbing.py` comme couverture de référence pour le binding générique, son loader, son registre, les transports et les erreurs.
- Ajouter des tests runtime hermétiques du conteneur et du moteur de conversation avec des runtimes/sessions factices typés : principal différent, cache partagé, commande de confirmation reconnue avant `ask`, ticket inconnu, rendu des tickets en attente et fermeture à l’éviction.
- Ajouter des tests de l’orchestrateur d’approbation pour les limites de questions/tours, le succès sans approbation, la reprise et l’abandon fail-closed, y compris une erreur de framework pendant le nettoyage.
- Adapter les tests Mail et Wiki pour vérifier leurs adaptateurs de framework et leurs factories avec le moteur/conteneur génériques. Les tests spécifiques aux frameworks restent dans `ai_agents`.
- Réutiliser les tests Mail/Wiki comme références comportementales pour les fichiers de binding livrés, le client natif, Gmail, Atlassian, les en-têtes, l’environnement stdio, les filtres lecture seule, l’autorisation et les échecs protocolaires.
- Ajouter ou adapter des tests unitaires/contractuels côté runtime pour tout besoin générique nouvellement exposé, en particulier l’envoi d’en-têtes HTTP et les factories de dialectes correctement typées.
- Faire les validations d’intégration côté agents au moyen de clients MCP simulés et de jeux de données locaux. Aucun test ne doit exiger une API LLM, un service externe ou de vrais secrets.
- Exécuter les contrôles qualité ciblés et les suites nécessaires dans chaque dépôt indépendamment, puis vérifier les changements, les limites de dépendances et les deux diffs avant livraison.

## Parité et cohérence d’API

Le client MCP et ses transports restent Python-first parce qu’ils reposent sur le SDK MCP et les primitives asynchrones Python. Cette issue ne revendique aucune parité .NET ou Java. Les documents de compatibilité du runtime doivent conserver cet état.

Pour les consommateurs Python, l’API publique générique doit donner aux deux agents le même comportement observable, malgré leurs types de capacités et dialectes différents. Les formats YAML existants et la façon dont chaque agent choisit ses credentials restent cohérents. Les erreurs peuvent être émises par le runtime ou traduites à la frontière de l’adaptateur, mais leur catégorie et le refus associé doivent rester compréhensibles pour l’application.

## Budget de performance

- Le chargement d’un binding MCP dans chaque agent ne doit pas dépasser de plus de 10 % la médiane obtenue avant migration avec les mêmes fichiers et le même environnement local.
- Sur les mêmes faux états de framework, le temps local de dispatch d’un tour et de contrôle de la boucle d’approbation ne doit pas dépasser de plus de 10 % la médiane des implémentations actuelles. Mesurer ce coût sans modèle ni service distant.
- L’adoption ne doit pas introduire d’étape réseau supplémentaire, ni une reconnexion par appel : la session reste paresseuse, unique pour sa connexion et réutilisée jusqu’à fermeture.
- Le moteur garde une seule lease de conversation pendant le tour et ne conserve aucun état supplémentaire après la réponse.
- Mesurer le coût local de validation et de construction du binding séparément du temps du serveur distant. Les tests de performance ne doivent pas dépendre d’un réseau ou d’un fournisseur MCP en production.

## Risques

- L’API générique actuelle est déjà présente, mais le mode d’alimentation d’en-têtes HTTP n’est pas exposé par `McpConnection`. La fermeture de cet écart doit rester générique et ne pas déplacer la construction des credentials Wiki dans le runtime.
- Le binding Wiki utilise `env` comme correspondance entre le nom transmis au processus et le nom de variable source. Cette sémantique de secret doit survivre à la migration sans inclure les valeurs dans les logs ou dans un fichier livré.
- L’erreur de capacité manquante doit demeurer distincte d’une réponse vide ou d’un refus d’autorisation ; les wrappers d’erreur actuels font partie du contrat des domaines.
- Le filtrage read-only et les dialectes Mail/Wiki peuvent sembler proches, mais ils dépendent de catalogues et de politiques propres aux applications. Une généralisation trop large ajouterait au runtime des connaissances métier interdites.
- L’adoption touche les call sites et tests des deux dépôts. Les worktrees issus de `main` distant doivent isoler le travail et garder les modifications locales existantes hors des diffs.

## Questions ouvertes

Aucune question bloquante pour établir la SPEC. Le choix précis entre adaptation des types d’erreurs existants et traduction à la frontière d’application, ainsi que la forme typée des factories de dialecte, sera fixé dans le PLAN après approbation de cette portée et vérification des call sites concernés.

Le protocole précis de l’adaptateur d’approbation (types génériques de résultat, appels de reprise/refus et extraction du texte final) sera détaillé dans le PLAN à partir des tests MAF et LangGraph. Le PLAN devra démontrer que cette interface retire de la duplication sans introduire de dépendance de framework dans le runtime.

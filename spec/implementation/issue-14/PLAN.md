# Plan technique — Corporate Credit Analyst en Python

## Spécification approuvée

`SPEC.md`, validée par l'utilisateur le 21 novembre 2026 (« Ok »).
Branche : `issue-14-corporate-credit-python`. Le dépôt `ai_agents` porte tout
le développement ; aucune modification du runtime partagé n'est prévue.

## Architecture examinée et réutilisation

Le dépôt sépare les distributions métier des adaptateurs de framework. Le
runtime fournit les manifestes, `ConfigurationDirectory`, les chargeurs de
configuration MCP, `McpServerBinding`, `McpConnection`, les contrats de
capacité et les primitives de sécurité/reprise. `McpConnection.session()`
donne accès au client MCP et `aclose()` assure la fermeture. Le SDK expose
`list_tools` et `call_tool`. Réutiliser ces mécanismes plutôt que les copier.
L'adaptateur MAF fournit `MafChatClientFactory` pour OpenAI/Azure OpenAI et
`SkillToolAdapter` pour exposer un registre de capacités au framework.

Versions constatées dans `.venvs/dev312` : framework core 1.18.0, framework
OpenAI 1.14.3, MCP 1.30.0, runtime agents 0.8.2. Cette dernière version est
inférieure au minimum 0.9.0 déclaré par le dépôt. Construire un environnement
isolé avec runtime >=0.9.0,<2 ; utiliser les distributions publiées ou
`scripts.install --runtime-source /data/repos/ai-enterprise-agent-runtime`
(checkout local déclarant 0.9.0), et consigner provenance/versions effectivement
testées. Ne pas prétendre que l'environnement courant est déjà compatible.

## Serveur EDGAR et capacités vérifiées dans le code amont

Le projet officiel https://github.com/dgunning/edgartools fournit un serveur
`edgartools-mcp`, dans `edgar.ai.mcp.server`, via l'extra `edgartools[ai]`.
La branche amont examinée déclare 6.3.0 ; choisir et figer une version distribuée
après vérification de son installation et de ses schémas.
Le serveur accepte stdio et Streamable HTTP. Choix local initial : stdio,
commande configurable, identité `EDGAR_IDENTITY` fournie au processus serveur.
Documenter aussi la connexion à une adresse Streamable HTTP configurée.

Outils examinés :

- `edgar_search(query=..., search_type="companies", limit=...)` : réponse
  `success/data`, candidats `cik`, `name`, `ticker`, `match_score` facultatif.
  Des erreurs peuvent apparaître dans la liste des résultats : les détecter
  avant tout traitement comme absence de correspondance.
- `edgar_company(identifier=..., include=["profile"])` : réponse
  `success/data`, identité et profil `name`, `cik`, `tickers`, `sic`, `industry`,
  `exchanges` facultatifs. `industry` correspond au libellé SIC, pas à un secteur
  indépendant. Ne pas demander financials, filings ou ownership.

Références examinées : `edgar/ai/mcp/server.py`, `tools/search.py`,
`tools/company.py`, `tools/base.py`, `pyproject.toml` dans le dépôt amont.
Ces observations de source doivent être confirmées par `list_tools` contre la
version installée avant l'implémentation du dialecte.

Limites : le profil n'expose pas de référence horodatée ni d'association
garantie entre listes de tickers et places. L'adaptateur construira la référence
canonique des soumissions `https://data.sec.gov/submissions/CIK{cik}.json`
et celle du référentiel des entreprises pour la recherche, d'après la
provenance vérifiée des données amont. L'horodatage UTC désignera la récupération
MCP, potentiellement depuis le cache serveur, sans inventer de date de publication.
En l'absence d'association démontrée, `exchange=null` avec avertissement ; ne
pas associer deux listes par leur position. Aucun mapping sectoriel à ajouter :
`sector` et `sector_origin` restent nuls si aucune donnée explicite n'existe.
Une limite de recherche atteinte entraîne un avertissement et ne permet pas
une confirmation automatique tant que l'unicité n'est pas démontrée.

## Composants et étapes ordonnées

1. **Vérifier les dépendances et découvrir le MCP.** Installer séparément agent
   et serveur afin de préserver l'isolation des dépendances ; capturer version,
   transport et schémas. Tester la connexion sans appeler un modèle. Vérifier
   dans la version installée l'identité SEC, le plafond de requêtes et les
   reprises/cache serveur. Si une capacité indispensable manque, documenter
   précisément le blocage avant de choisir une extension explicite.
2. **Créer la distribution métier** `agents/credit`, namespace
   `ai_agent_lab.credit`, avec `domain`, `application/ports`,
   `application/skills`, `infrastructure/configuration`, `infrastructure/mcp`,
   `adapters/capabilities`, `adapters/cli`, `bootstrap`. Garder le code MAF dans
   la distribution `agents/maf` sous un module dédié si nécessaire. Ajouter
   l'environnement d'installation et les déclarations Ruff/mypy/architecture.
3. **Tester puis définir les contrats Pydantic et enums.** Requête, profil,
   cotation, source, résultat et erreur ; CIK ASCII de dix chiffres non nul,
   validation de l'état, cohérence company/candidates/error, sources UTC SEC
   et références de champs valides. Rejeter les réponses contradictoires.
4. **Tester puis implémenter la skill d'identification.** Port métier injecté,
   normalisation `auto` documentée (numérique → CIK ; forme ticker → ticker ;
   sinon nom), filtrage exact des tickers insensible à la casse, déduplication
   par CIK et regroupement des cotations. Pour un nom, conserver les candidats
   plausibles retournés sans choix arbitraire. Confirmer après récupération du
   profil par CIK ; vérifier CIK et ticker recherché. Une sélection déclenche
   une nouvelle recherche de la requête initiale et une vérification
   d'appartenance, puis récupération du profil. Pas d'état applicatif conservé
   entre opérations ; expliquer que les résultats peuvent évoluer entre deux
   recherches.
5. **Tester puis implémenter le dialecte officiel EDGAR.** Adapter les réponses
   réelles au port métier ; limiter les appels aux deux outils retenus et à
   leurs paramètres d'identification. Valider les schémas découverts, le JSON,
   les enveloppes MCP, erreurs internes et données requises. Ajouter sources,
   horodatages et avertissements ; aucun appel SEC depuis l'agent.
6. **Composer le client et sa résilience.** Chargeurs et connexion du runtime,
   délais configurables, ouverture/fermeture garanties même en erreur. Reprises
   bornées de lectures transitoires, avec délai serveur lorsqu'il est disponible
   et absence de double boucle incontrôlée avec les reprises du serveur.
   Distinguer invalid_input, server_unavailable, timeout, sec_access_error,
   invalid_mcp_response. Ne pas deviner une absence à partir d'une erreur libre.
   Logs avec corrélation, outil, durée, tentative et code, sans secrets/payloads.
7. **Intégrer l'agent et le point d'entrée.** Manifestes
   `config/agents/credit`, instructions `AGENT.md`, skill `identify_company`,
   binding `config/mcp/edgartools.yaml` et exemple d'environnement sans secret.
   Exposer uniquement la skill métier via registre/adapter MAF et construire
   l'agent avec le client configuré. CLI `credit-agent` avec chemin structuré
   déterministe (JSON/requête en arguments) et mode conversation utilisant MAF.
   Le JSON confirmé provient de la skill ; la réponse du modèle ne le remplace
   pas. Fournir une restitution déterministe et des instructions d'assistance,
   refus de décision de crédit et traitement des outils comme données.
8. **Vérifier et documenter.** Guide d'installation, versions/provenance,
   identité SEC, transports, limites, erreurs et exemples nom/ticker/CIK/
   sélection. Relier les guides utilisateurs/contributeurs au nouveau guide.
   Consigner tests et contrôle réel dans le journal et un compte rendu dédié.

## Validation et conditions de livraison

Tests métier avec fakes injectés avant implémentation : tous les critères de
SPEC, notamment ticker partagé, multi-tickers, CIK invalide sans MCP, sélection
étrangère, profil incohérent, métadonnées absentes et résultat tronqué.
Tests d'adaptateur : schémas découverts, enveloppes texte/structurées, erreurs
SEC internes, délais, indisponibilité, reprises bornées et fermeture.
Tests de sécurité : contenu injectant des instructions sans influence sur les
règles, logs sans secret ni réponses complètes. Tests de composition MAF avec
client simulé et runtime réel, configuration/manifeste et CLI.
Exécuter Ruff, mypy strict, tests du nouveau périmètre, tests d'installation
et d'architecture, puis régressions pertinentes Mail/MAF si le code commun change.

Contrôle réel distinct : démarrer le MCP officiel et identifier un ticker puis
son CIK avec références SEC. Nécessite installation, réseau SEC et identité
client valide fournie par l'opérateur ; ne pas inventer de nom/adresse.
Si un prérequis manque, documenter le contrôle non exécuté et sa cause, sans
déclarer l'issue complètement validée. Un test simulé ne remplace pas ce contrôle.

## Risques et périmètre exclu du plan

La recherche amont est bornée et les erreurs ne sont pas toujours codées ;
la confirmation doit rester prudente et la limite explicite. Une version
publiée peut différer de la branche amont ; découverte effective obligatoire.
Le runtime installé doit être actualisé dans l'environnement isolé. Les clés
modèle et l'identité SEC ne sont pas encore connues ; fournir les exemples
configurables et demander uniquement les éléments nécessaires au contrôle réel.
Aucune migration Mail/Wiki, infrastructure de persistance, modification de
runtime, analyse financière, fusion Git ou publication implicite.

## Complément HTTP demandé après création de la PR #15

Réutiliser `ManagedAgentWorker`, `AgentHttpSettingsBuilder`, discovery et
`AgentFrameworkSession` du runtime, comme Mail/Wiki. Aucun routeur ou format
OpenAI à réimplémenter. Charger le manifeste sans MCP/modèle au démarrage puis
composer une application et une session par sujet vérifié/conversation. Le
registre et l'adaptateur MAF existants conservent les règles métier et permissions.
Refuser les commandes d'approbation sans ticket : cette capacité est en lecture.

Ajouter un lanceur `credit-agent-http` (port 8125), configuration API-key avec
clé issue de l'environnement, JWT/OIDC configurable et limites de cache via
le runtime. Préserver les fichiers d'environnement/configuration avec reload
et accepter une paire TLS. L'extra `[http]` est installé dans l'environnement
Credit ; les couches métier restent indépendantes du transport/framework.

Tester d'abord les routes réelles avec modèle/MCP simulés : OpenAI SDK,
Chat/Responses normaux et en flux, refus avant construction, continuité,
isolation JWT, fermeture en échec/arrêt et options TLS. Ajouter les exemples
clients et limites du cache ; relancer les contrôles Python complets avant
commit/push dans la PR existante, sans fusion.

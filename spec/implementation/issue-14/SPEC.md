# Corporate Credit Analyst — identification EDGAR en Python

## Demande et contexte

Source : https://github.com/ygo74/ai_agents/issues/14. Dépôt principal :
`ygo74/ai_agents`. Développement exclusivement en Python, conformément à la
demande utilisateur. Le dépôt possède déjà des agents Mail et Wiki, des
adaptateurs de framework et des intégrations au runtime partagé ; aucune
capacité Corporate Credit ou configuration MCP EDGAR n'a été trouvée.

## Objectif et périmètre

Livrer un agent Corporate Credit Analyst exécutable localement, utilisant
effectivement Microsoft Agent Framework et `ai-enterprise-agent-runtime`, pour
identifier un émetteur dans EDGAR via un serveur MCP local `edgartools`.
L'agent assiste l'analyste et ne prend aucune décision de crédit.

Complément demandé par l'utilisateur après création de la PR #15 : exposer
également l'agent aux clients HTTP, selon la surface OpenAI existante du dépôt.
Ce complément poursuit la même issue et la même branche.

Hors périmètre : analyse financière, ratios, téléchargement/analyse des
formulaires SEC, note de crédit complète, interface graphique, hébergement
Foundry et provisionnement Azure. Aucun accès HTTP direct à EDGAR en secours.

## Comportement attendu

1. Accepter une entrée structurée `query`, `query_type` (`name`, `ticker`,
   `cik`, `auto`) et un `selected_cik` facultatif ; proposer également une
   restitution lisible par l'analyste.
2. Rejeter les recherches vides et les CIK invalides avant tout appel MCP.
   Normaliser les CIK en chaînes de dix chiffres avec zéros initiaux.
3. Rechercher par nom, ticker ou CIK et récupérer le profil SEC avant de
   confirmer l'identité. Vérifier la cohérence du CIK et du nom légal.
4. Comparer les tickers sans sensibilité à la casse, dédupliquer par CIK et
   regrouper les cotations d'un même émetteur sans inventer leur association.
5. Retourner les candidats plausibles lorsqu'il existe plusieurs émetteurs,
   sans sélectionner le premier. Une sélection explicite doit appartenir aux
   candidats de la recherche ; récupérer son profil avant confirmation.
6. Restituer nom légal, CIK, couples ticker/place disponibles, SIC et libellé.
   Fournir un secteur uniquement s'il est explicitement sourcé ou issu d'un
   mapping SIC documenté et versionné. Signaler les données manquantes.
7. Distinguer absence de correspondance et panne technique. `not_found`
   indique uniquement l'absence de résultat dans la recherche effectuée.

## Contrats, sources et sécurité

Le résultat typé et validé contient `status` (`identified`, `ambiguous`,
`not_found`, `error`), `query`, `query_type`, `company`, `candidates`, `sources`,
`warnings`, `error`. Le profil contient `legal_name`, `cik`, `listings`,
`sic_code`, `sic_description`, `sector`, `sector_origin`, `field_sources`.
Chaque champ renseigné est rattaché aux sources utilisées. Une source comprend
un identifiant, une URL SEC, le type de ressource, l'heure de récupération UTC
et la date de dépôt/publication uniquement lorsqu'elle est disponible.
Les scalaires absents valent `null`, les collections absentes sont vides.
Un résultat `identified` exige un nom légal et un CIK cohérents ; une réponse
MCP incomplète ou contradictoire ne permet pas de confirmer l'émetteur.

Les erreurs distinguent entrée invalide, serveur indisponible, délai dépassé,
erreur d'accès SEC et réponse MCP invalide/incomplète. Les reprises sont
bornées, réservées aux erreurs transitoires et respectent les temporisations
du serveur. Aucune reprise sur entrée invalide ou absence de résultat métier.

Les règles d'identification et de sélection sont déterministes. Le modèle
peut interpréter une demande et expliquer les résultats, mais ne confirme pas
une identité sans preuves EDGAR. Les contenus MCP sont des données non fiables,
jamais des instructions. Les accès MCP sont limités aux outils utiles à
l'identification. Configuration et secrets restent hors du code et des logs.
Les journaux portent un identifiant de corrélation, les étapes et les codes
d'erreur sans enregistrer inutilement les réponses complètes.

## Contraintes d'intégration

Respecter les couches et les ports du dépôt ; réutiliser les API publiques du
runtime pour configuration, exécution et mécanique MCP selon leur disponibilité.
Isoler les noms et schémas réels des outils EDGAR dans un adaptateur métier.
Gérer ouverture, fermeture, délais et erreurs de protocole. Configurer le
transport et la commande/les arguments ou l'adresse du serveur hors du code.
Documenter les versions compatibles réellement vérifiées, la provenance des
paquets runtime et le fournisseur de modèle configurable.

Découvrir les outils du serveur retenu et vérifier recherche et profil avant
l'implémentation de l'adaptateur. Documenter une capacité absente comme une
dépendance ou extension explicite, sans supposer un schéma d'outil. Documenter
l'identité client SEC et la limitation des requêtes, avec leur responsable
(serveur/configuration). EDGAR ne nécessite pas de clé API SEC ; cela ne
préjuge pas des authentifications du modèle ou du MCP.

## Critères d'acceptation et validation

- Installation, configuration sans secret et démarrage documentés ; exécution
  réelle via Microsoft Agent Framework et le runtime, avec répartition des rôles.
- Ticker minuscule, CIK avec/sans zéros et nom non ambigu identifient un profil
  SEC cohérent, avec CIK normalisé et références.
- Ambiguïté par nom ou ticker partagé : candidats distincts, aucune confirmation
  avant sélection ; sélection valide confirmée, sélection étrangère rejetée.
- Plusieurs tickers du même CIK sont regroupés ; absence de ticker ou secteur
  n'empêche pas une identification valide, avec avertissements.
- Recherche vide/CIK invalide : erreur sans appel MCP ; absence de résultat :
  `not_found` avec limites de recherche ; panne/délai/erreur SEC : `error`.
- Réponse MCP incohérente/incomplète : aucun profil confirmé ; contrats,
  références de champs, valeurs absentes et provenance du secteur validés.
- Reprises bornées et fermeture de connexion testées ; contenu d'outil avec
  instructions étrangères sans effet sur les règles déterministes.
- Tests reproductibles avec MCP simulé et vérifications de qualité adaptées.
- Contrôle réel séparé des tests, identifiant un émetteur avec sources SEC ;
  prérequis et résultat consignés, sans déclarer réussi un contrôle non exécuté.
- Exemples nom, ticker, CIK et résolution d'ambiguïté ; aucune décision de crédit.
- HTTP : démarrage documenté, modèle découvrable et appels Chat Completions/
  Responses normaux et en flux via les API du runtime ; authentification
  obligatoire, identité issue du transport et conversations isolées par sujet.
- Client OpenAI vérifié avec modèle/MCP simulés ; refus avant construction sans
  authentification, fermeture des ressources après échec et arrêt du service.
- Cache de conversation borné et local au processus ; limites et absence de
  persistance après redémarrage documentées. Aucun état de candidats ajouté.

## Risques et décisions ouvertes

L'implémentation/version exacte du serveur MCP `edgartools`, son transport,
ses outils et sa disponibilité locale restent à confirmer pendant l'étude
technique. La bibliothèque EdgarTools seule ne constitue pas un serveur MCP.
Les plages déjà déclarées dans le dépôt sont Python >=3.12, framework core
>=1.18,<1.19, framework OpenAI >=1.14.2,<1.15 et runtime >=0.9.0,<2 ; elles
ne constituent pas encore une combinaison testée pour ce nouvel agent.
Le fournisseur de modèle, les versions effectivement installables et les
besoins éventuels d'extension MCP seront arrêtés dans le plan technique.

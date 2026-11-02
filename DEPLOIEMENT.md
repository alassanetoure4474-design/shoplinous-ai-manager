# SHOPLINOUS - Preparation au deploiement (branch workflow-v5-fix8-ai-gateway)

Etat : PRET POUR DEPLOIEMENT APRES VALIDATION MANUELLE. Aucune fusion
vers main, aucun deploiement, aucune publication sans autorisation
explicite. allow_publish=False par defaut (mode veille : lecture seule).

## 1. Composants

- workflow/daily.py : workflow quotidien (evaluation produits,
  table SKU->vid, analyse commandes en lecture seule, controle d'integrite
  v5.6).
- workflow/freight_collector_v56.py : moteur de tarifs fret par variante
  (usd_15j, TTL 7 jours, aucune substitution silencieuse).
- workflow/ai_manager.py : acces multi-IA via FreeLLMAPI (mistral, gemini,
  groq, qwen et gpt_oss ; cinq fournisseurs actifs par defaut ; bascule automatique ; cache).
- Redaction des descriptions produit en francais via FreeLLMAPI ; si l'IA
  est indisponible, un texte neutre est utilise. Les prix, stocks, marges,
  frais, delais verifies et commandes restent calcules par le code Python.
- workflow/worker.py : lanceur du worker Mistral Workflows.
- workflow/test_fournisseurs.py : verification des modeles IA declares
  contre l'instance reelle (lecture seule, aucun secret affiche).

## 2. Variables d'environnement requises

Obligatoires (le run est SUSPENDU proprement si absentes) :
- CJ_API_KEY : cle API CJdropshipping (en-tete CJ-API-KEY).
- FREEWEBSTORE_API_KEY : cle API Freewebstore (en-tete x-api-key).
- FREE_LLM_API_BASE : URL de la passerelle FreeLLMAPI.
- FREE_LLM_API_KEY : cle de la passerelle (jamais dans le code).

Facultatives (valeurs par defaut indiquees) :
- PAYMENT_FEE_RATE (0.029), PAYMENT_FEE_FIXED_EUR (0.30)
- CJ_API_BASE, FREEWEBSTORE_API_BASE
- AI_PROVIDER_ORDER (mistral,gemini,groq,qwen,gpt_oss)
- AI_MODEL_MISTRAL / AI_MODEL_GEMINI / AI_MODEL_GROQ / AI_MODEL_QWEN / AI_MODEL_GPT_OSS (modeles autorises)
- AI_TIMEOUT_SECONDS (30), AI_CACHE_TTL_SECONDS (3600)

AVANT LE PREMIER APPEL REEL : verifier les identifiants de modeles
exposes par VOTRE instance FreeLLMAPI (GET {FREE_LLM_API_BASE}/v1/models)
et ajuster AI_MODEL_MISTRAL / AI_MODEL_GEMINI / AI_MODEL_GROQ /
AI_MODEL_QWEN / AI_MODEL_GPT_OSS en consequence. Les valeurs par defaut
du code n ont jamais ete validees contre une instance reelle. Script
fourni (lecture seule, la cle n est JAMAIS affichee ni journalisee) :

    cd workflow && python test_fournisseurs.py

Codes de sortie : 0 = les 5 modeles declares existent sur l'instance ;
1 = au moins un modele est absent (corriger AI_MODEL_*) ;
2 = instance injoignable ou configuration absente (aucun appel reseau).

Secrets GitHub Actions a configurer (supabase-migrate.yml) :
SUPABASE_ACCESS_TOKEN, SUPABASE_PROJECT_ID, SUPABASE_DB_PASSWORD.

Les secrets GitHub Actions ne sont pas automatiquement transmis au worker
heberge. Definir aussi FREE_LLM_API_BASE et FREE_LLM_API_KEY dans les
variables d'environnement du service qui execute le worker, sans les
inscrire dans le depot ni les journaux.

## 3. Installation

    cd workflow
    pip install -r requirements.txt -r requirements-dev.txt
    python -m pytest -v   # doit etre VERT avant tout lancement

## 4. Lancement du worker

    python worker.py

Le worker enregistre le workflow shoplinous_daily. Parametres d'appel :
DailyParams(allow_publish=False par defaut, checkout_shipping_eur
requis si publication). Conteneur : docker build -t shoplinous . &&
docker run --env-file .env shoplinous.

## 5. Controles de sante

- CI verte sur le dernier commit (.github/workflows/python-tests.yml),
  y compris le job build-docker (construction reelle de l'image +
  demarrage du conteneur + imports du worker).
- AVANT le premier appel IA reel : python test_fournisseurs.py doit
  sortir 0 (les 5 modeles declares existent sur l'instance FreeLLMAPI).
- Au demarrage : le worker doit s'enregistrer sans EvaluationSuspended.
- Chaque run : report["errors"] vide, report["fret_v56"] avec 2 variantes
  a 255 tarifs / 51 pays chacune, report["mode"] == "veille".
- AiManager : ai.quotas() montre bascules/erreurs par fournisseur ; aucune
  cle dans les logs.

## 6. Retour arriere

- Worker : arret du processus/conteneur (docker stop shoplinous).
- Code : git revert <sha> sur la branche de travail ; aucune migration
  destructive (le schema Supabase est additif).
- Le mode veille ne modifie RIEN cote Freewebstore/CJ : un run arrete
  n'a aucun effet a annuler.

## 7. Regles de securite permanentes

- Aucun achat fournisseur automatique, aucun paiement, aucune creation
  ni modification de commande CJ.
- Aucune modification de prix/stocks Freewebstore sans allow_publish=True
  explicite et checkout_shipping_eur fourni.
- Aucune publication automatique ; allow_publish=False par defaut.
- Les cles API vivent uniquement dans les secrets/environnement.
- Les calculs financiers, stocks et commandes restent en Python
  deterministe ; l'IA (ai_manager) ne fait que du textuel.

## 8. Deploiement gere Mistral Workflows (option retenue)

Le worker est publie en DEPLOIEMENT GERE (Managed deployment, public
preview) : Mistral Cloud clone le depot GitHub, construit l'image a
partir du Dockerfile et execute le worker. Aucun serveur a gerer, aucune
cle API Mistral dans le depot (jeton de service-account injecte par la
plateforme).

Pre-requis (doc officielle docs.mistral.ai / managed deployments) :
- Compte Mistral avec pay-as-you-go active sur l organisation (le plan
  gratuit ne peut PAS executer de deploiements geres ; Pro/Team seul ne
  suffit pas non plus).
- mistralai-workflows >= 3.10 dans l image ( requis pour lire le jeton
  de service-account ; pin dans workflow/requirements.txt).
- Dockerfile : CMD demarre le worker (deja conforme :
  CMD ["python", "worker.py"]).
- Chemins de build : Dockerfile imbrique -> indiquer workflow/Dockerfile ;
  repertoire de build = racine du depot (le Dockerfile copie workflow/).
- Region d execution : nl-north-1 (Pays-Bas).

Etapes :
1. Installer la Mistral GitHub App (github.com/apps/mistralai) sur CE
   depot, puis connecter le credential dans Studio > GitHub App.
2. Creer les secrets du workspace (Studio > Secrets Manager) :
   CJ_API_KEY, FREEWEBSTORE_API_KEY, FREE_LLM_API_BASE,
   FREE_LLM_API_KEY.
3. Creer le deploiement (console Studio ou API
   client.workflows.deployments.create_deployment) avec github_url du
   depot, revision = branche a deployer, chemin Dockerfile
   workflow/Dockerfile, build directory = racine, et lier les secrets :
   GITHUB_TOKEN -> non requis ; CJ_API_KEY / FREEWEBSTORE_API_KEY /
   FREE_LLM_API_BASE / FREE_LLM_API_KEY -> secret:workspace:...
   Nom de deploiement UNIQUE (deux deploiements du meme nom se volent
   les executions).
4. Attendre le statut Active (le worker enregistre
   ShoplinousDailyWorkflow) ; en cas d echec de build, reproduire avec
   docker build -f workflow/Dockerfile .
5. IMPORTANT : un changement de valeur de secret ne redemarre PAS le
   worker ; redemarrer le deploiement pour prendre la nouvelle valeur.
6. Premier appel IA reel : d abord valider les modeles via
   python test_fournisseurs.py (code 0), puis lancer le workflow en
   mode veille (allow_publish=False).

Aucune fusion vers main ni deploiement sans autorisation explicite.

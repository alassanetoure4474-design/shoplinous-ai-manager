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
- workflow/shoplinous_global/geniuspay_wave.py : diagnostic du gateway Wave Direct en Sandbox uniquement.

## 2. Variables d'environnement requises

Obligatoires (le run est SUSPENDU proprement si absentes) :
- CJ_API_KEY : cle API CJdropshipping (en-tete CJ-API-KEY).
- FREEWEBSTORE_API_KEY : cle API Freewebstore (en-tete x-api-key).
- FREE_LLM_API_BASE : URL de la passerelle FreeLLMAPI.
- FREE_LLM_API_KEY : cle de la passerelle (jamais dans le code).
- GENIUSPAY_API_KEY / GENIUSPAY_API_SECRET : cles marchandes GeniusPay (serveur uniquement).
- GENIUSPAY_ENVIRONMENT=sandbox (defaut ; ne jamais activer live pendant les tests).
- GENIUSPAY_WEBHOOK_SECRET : secret retourne lors de la creation du webhook, a stocker apres deploiement de l'endpoint HTTPS.
- GENIUSPAY_ALLOW_LIVE=false : verrou de production ; ne passer a true qu'apres tests et autorisation explicite.

Controle du compte marchand (lecture seule, aucun paiement) :

    cd workflow && python test_geniuspay_connection.py

Ce script verifie le statut du compte et liste les pays/opérateurs renvoyes
par l'API PawaPay. Il ne teste pas les autres passerelles GeniusPay et ne
cree aucune transaction.

Diagnostic Wave Direct (Sandbox uniquement) :

    cd workflow && python test_geniuspay_wave_sandbox.py

Ce test envoie un POST /payments avec payment_method=wave, gateway=wave,
amount=200, currency=XOF et customer.country=CI, puis relit la transaction
avec GET /payments/{reference}. La documentation GeniusPay indique que
les transactions Sandbox sont simulees et sans frais ; ce test cree donc
une transaction technique dans l'historique Sandbox mais ne debite aucun
compte reel. Le code refuse le mode Live avant toute requete reseau.
Le journal affiche la reference, le statut et le gateway confirme ; aucune
cle ni URL de paiement n'est affichee.

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
Pour GeniusPay, ajouter aussi GENIUSPAY_API_KEY et GENIUSPAY_API_SECRET
dans Actions secrets, et GENIUSPAY_WEBHOOK_SECRET dans les secrets du
service qui executera les paiements apres creation du webhook HTTPS.

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

## 6. Paiements GeniusPay (Sandbox uniquement au demarrage)

- Le client GeniusPay utilise `https://geniuspay.ci/api/v1/merchant`.
- Premier controle : `GET /account` (lecture seule) et `GET /pawapay/providers` (decouverte PawaPay des pays/opérateurs, pas de la passerelle Wave Direct).
- Le checkout heberge standard est cree par `POST /payments` sans `payment_method` : GeniusPay affiche les canaux disponibles. La reference de commande est transmise dans `metadata.order_id`.
- Pour Wave Direct, `GestionnaireCommandes.initier_paiement` transmet le choix explicite `payment_method=wave` et `gateway=wave`. Le code limite ce chemin a CI/XOF et refuse le checkout si la reponse API ne confirme pas la route Wave, le montant, la devise, la commande et l'environnement. Le checkout generique reste disponible separement.
- `GestionnaireCommandes` conserve l'association entre le numero de commande et l'identifiant interne de transaction. Le webhook est verifie contre cette transaction ; une redirection navigateur ne change jamais le statut de la commande.
- Le test specifique Wave Direct utilise `payment_method=wave` et `gateway=wave` pour la CI, en Sandbox et pour 200 XOF. Il relit ensuite la transaction par reference et exige que le gateway Wave, l'environnement, le montant, la devise et les metadata correspondent.
- Ce test technique cree une transaction simulee dans l'historique Sandbox. Il n'effectue aucun debit reel. Le code refuse le mode Live avant tout appel reseau.
- Les paiements clients restent bloques par le module tant que les deux cles API et le secret webhook ne sont pas configures.
- Le webhook doit etre expose sur une URL HTTPS publique, verifier HMAC-SHA256 + timestamp (fenetre 300 s), puis lier reference, commande, montant, devise et environnement. Une redirection navigateur ne confirme jamais un paiement.
- La documentation GeniusPay indique que le secret webhook n'est fourni qu'a la creation du webhook : le sauvegarder immediatement dans `GENIUSPAY_WEBHOOK_SECRET`.
- Ne pas enregistrer le webhook tant qu'un endpoint HTTPS reel n'est pas deploye. Le worker Mistral seul n'expose pas automatiquement une route HTTP de webhook.
- Ne jamais mettre les cles dans GitHub, dans le code, dans les captures ou dans les journaux. Les saisir uniquement dans les secrets de l'hebergeur qui executera le client et le receveur webhook.

## 7. Retour arriere

- Worker : arret du processus/conteneur (docker stop shoplinous).
- Code : git revert <sha> sur la branche de travail ; aucune migration
  destructive (le schema Supabase est additif).
- Le mode veille ne modifie RIEN cote Freewebstore/CJ : un run arrete
  n'a aucun effet a annuler.

## 8. Regles de securite permanentes

- Aucun achat fournisseur automatique, aucun paiement reel non autorise,
  aucune creation ni modification de commande CJ.
- Aucune modification de prix/stocks Freewebstore sans allow_publish=True
  explicite et checkout_shipping_eur fourni.
- Aucune publication automatique ; allow_publish=False par defaut.
- Les cles API vivent uniquement dans les secrets/environnement.
- Les calculs financiers, stocks et commandes restent en Python
  deterministe ; l'IA (ai_manager) ne fait que du textuel.

## 9. Deploiement gere Mistral Workflows (option retenue)

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


Etat d'activation Wave Direct : le routage technique est valide en Sandbox, mais cela ne constitue pas une mise en production. Le serveur qui execute les paiements doit avoir ses propres cles API et son secret webhook ; les secrets GitHub Actions ne sont pas automatiquement transmis au worker. Un endpoint HTTPS public de reception des webhooks et l'interface qui redirige le client vers `checkout_url` doivent etre deployes et testes en Sandbox avant toute activation Live ou utilisation par des clients. Aucun reglage de paiement Freewebstore n'est modifie par ces modules Python.

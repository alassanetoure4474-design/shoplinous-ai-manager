# SHOPLINOUS - Preparation au deploiement (branch workflow-v5-fix7)

Etat : PRET POUR DEPLOIEMENT APRES VALIDATION MANUELLE. Aucune fusion
vers main, aucun deploiement, aucune publication sans autorisation
explicite. allow_publish=False par defaut (mode veille : lecture seule).

## 1. Composants

- workflow/daily.py : workflow quotidien Mistral (evaluation produits,
  table SKU->vid, analyse commandes en lecture seule, controle d'integrite
  v5.6).
- workflow/freight_collector_v56.py : moteur de tarifs fret par variante
  (usd_15j, TTL 7 jours, aucune substitution silencieuse).
- workflow/ai_manager.py : acces multi-IA via FreeLLMAPI (mistral, gemini,
  groq ; bascule automatique ; cache ; aucune cle dans le code).
- workflow/worker.py : lanceur du worker Mistral Workflows.

## 2. Variables d'environnement requises

Obligatoires (le run est SUSPENDU proprement si absentes) :
- CJ_API_KEY : cle API CJdropshipping (en-tete CJ-API-KEY).
- FREEWEBSTORE_API_KEY : cle API Freewebstore (en-tete x-api-key).
- FREE_LLM_API_BASE : URL de la passerelle FreeLLMAPI.
- FREE_LLM_API_KEY : cle de la passerelle (jamais dans le code).

Facultatives (valeurs par defaut indiquees) :
- PAYMENT_FEE_RATE (0.029), PAYMENT_FEE_FIXED_EUR (0.30)
- CJ_API_BASE, FREEWEBSTORE_API_BASE
- AI_PROVIDER_ORDER (mistral,gemini,groq)
- AI_MODEL_MISTRAL / AI_MODEL_GEMINI / AI_MODEL_GROQ (modeles libres)
- AI_TIMEOUT_SECONDS (30), AI_CACHE_TTL_SECONDS (3600)

Secrets GitHub Actions a configurer (supabase-migrate.yml) :
SUPABASE_ACCESS_TOKEN, SUPABASE_PROJECT_ID, SUPABASE_DB_PASSWORD.

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

- CI verte sur le dernier commit (.github/workflows/python-tests.yml).
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

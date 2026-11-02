# shoplinous-ai-manager

Gestionnaire e-commerce intelligent SHOPLINOUS : gestion de produits,
recherche de fournisseurs, analyse des marges et automatisation securisee
de la boutique Freewebstore avec assistance IA.

## Contenu

- `workflow/daily.py` : workflow quotidien Mistral Workflows (evaluation
  produits, table SKU->vid, analyse de commandes en lecture seule,
  controle d'integrite fret v5.6). Mode VEILLE par defaut :
  `allow_publish=False` (aucune creation ni modification boutique).
- `workflow/freight_collector_v56.py` : moteur de tarifs fret par variante
  (usd_15j, TTL 7 jours, aucune substitution silencieuse, aucun melange
  entre variantes).
- `workflow/ai_manager.py` : acces multi-IA via FreeLLMAPI (mistral,
  gemini, groq ; bascule automatique sur 429/5xx/timeout ; cache ;
  modeles payants interdits ; aucune cle dans le code).
- `workflow/pricing_v55.py`, `workflow/freight_collector_v55.py` :
  socles deterministes des calculs financiers (reutilises par v5.6).
- `workflow/worker.py` + `workflow/Dockerfile` : lanceur du worker.

## Securite

- Aucun achat fournisseur automatique, aucun paiement, aucune commande CJ.
- Aucune modification de prix/stocks Freewebstore sans autorisation.
- Les cles API vivent uniquement dans les variables d'environnement /
  secrets (CJ_API_KEY, FREEWEBSTORE_API_KEY, FREE_LLM_API_KEY,
  FREE_LLM_API_BASE). Aucune cle dans le depot ni les journaux.
- Les calculs financiers, stocks et commandes restent en Python
  deterministe ; l'IA n'intervient que sur du textuel.

## Installation et deploiement

Voir `DEPLOIEMENT.md` (variables d'environnement, tests, lancement du
worker, controles de sante, retour arriere). CI pytest :
`.github/workflows/python-tests.yml` (doit etre VERTE avant tout
deploiement). Migration Supabase : `.github/workflows/supabase-migrate.yml`
(manuelle, `workflow_dispatch`).

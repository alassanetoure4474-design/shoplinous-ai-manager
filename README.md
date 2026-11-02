# shoplinous-ai-manager

Gestionnaire e-commerce intelligent SHOPLINOUS : gestion de produits,
recherche de fournisseurs, analyse des marges et automatisation securisee
de la boutique Freewebstore avec assistance IA.

## Contenu

- `workflow/daily.py` : workflow quotidien Mistral Workflows (32 outils :
  15 activites + 17 fonctions publiques ; evaluation produits, table
  SKU->vid, analyse de commandes en lecture seule, controle d'integrite
  fret v5.6, devis CJ dynamique a quantite exacte). Mode VEILLE par
  defaut : `allow_publish=False` (aucune creation ni modification
  boutique).
- `workflow/freight_collector_v56.py` : moteur de tarifs fret par variante
  (usd_15j, TTL 7 jours, aucune substitution silencieuse, aucun melange
  entre variantes ; devis CJ en direct au-dela de 5 unites).
- `workflow/shoplinous_global/geniuspay.py` : client serveur GeniusPay (Sandbox par defaut, checkout heberge, decouverte mobile money, verification HMAC des webhooks) ; aucun secret dans le depot.
- `workflow/ai_manager.py` : acces multi-IA via FreeLLMAPI (cinq
  fournisseurs actifs par defaut : mistral, gemini, groq, qwen, gpt_oss ;
  bascule automatique sur 429/5xx/timeout ; cache ; modeles payants
  interdits ; 4xx -> erreur immediate sans bascule ; aucune cle dans le
  code).
- `workflow/test_fournisseurs.py` : verification des 5 modeles IA
  declares contre l'instance reelle (GET /v1/models, lecture seule,
  aucun secret affiche). A lancer avant le premier appel IA reel.
- `workflow/pricing_v55.py`, `workflow/freight_collector_v55.py` :
  socles deterministes des calculs financiers (reutilises par v5.6).
- `workflow/worker.py` + `workflow/Dockerfile` : lanceur du worker
  (image validee en CI par le job build-docker + smoke test d'imports).

## Securite

- Aucun achat fournisseur automatique, aucun paiement, aucune commande CJ.
- Aucune modification de prix/stocks Freewebstore sans autorisation.
- Les cles API vivent uniquement dans les variables d'environnement /
  secrets (CJ_API_KEY, FREEWEBSTORE_API_KEY, FREE_LLM_API_KEY,
  FREE_LLM_API_BASE). Aucune cle dans le depot ni les journaux
  (redaction [REDACTE] verifiee par les tests).
- Les calculs financiers, stocks et commandes restent en Python
  deterministe ; l'IA n'intervient que sur du textuel.
- Aucune donnee personnelle client n'est copiee (adaptateur a liste
  blanche, verifie par les tests).

## Installation et deploiement

Voir `DEPLOIEMENT.md` (variables d'environnement, tests, lancement du
worker, deploiement gere Mistral Workflows, controles de sante, retour
arriere). CI pytest + build Docker :
`.github/workflows/python-tests.yml` (doit etre VERTE avant tout
deploiement). Migration Supabase :
`.github/workflows/supabase-migrate.yml` (manuelle, workflow_dispatch).

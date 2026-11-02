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
- `workflow/shoplinous_global/geniuspay.py` : client serveur GeniusPay (Sandbox par defaut, checkout heberge et Wave Direct CI/XOF, verification HMAC des webhooks) ; aucun secret dans le depot.
- `workflow/shoplinous_global/payment_manager.py` et `payment_providers.py` : selection des moyens, creation idempotente des transactions et adaptateur GeniusPay Wave Direct.
- `workflow/shoplinous_global/order_manager.py` : association commande/transaction ; une commande ne passe a `payee` qu'apres webhook valide.
- `workflow/shoplinous_global/geniuspay_wave.py` : diagnostic Wave Direct reserve au Sandbox ; refuse le mode Live avant toute requete.
- `workflow/test_geniuspay_connection.py` : controle en lecture seule du compte GeniusPay et des pays/opérateurs PawaPay ; ne cree aucune transaction.
- `workflow/test_geniuspay_wave_sandbox.py` : test technique Wave Direct en Sandbox ; cree une transaction simulee de 200 XOF puis la relit par reference.
- `workflow/test_geniuspay_wave.py` : tests automatises du routage Wave, du mode Sandbox et des controles de securite (sans appels reseau reels).
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

- Aucun achat fournisseur automatique, aucun paiement Live declenche par les diagnostics, aucune commande CJ.
- Aucune modification de prix/stocks Freewebstore sans autorisation.
- Les cles API vivent uniquement dans les variables d'environnement /
  secrets (CJ_API_KEY, FREEWEBSTORE_API_KEY, FREE_LLM_API_KEY,
  FREE_LLM_API_BASE). Aucune cle dans le depot ni les journaux
  (redaction [REDACTE] verifiee par les tests).
- Les calculs financiers, stocks, marges et commandes restent calcules
  par le code Python ; l'IA n'intervient que sur du textuel.
- Aucune donnee personnelle client n'est copiee (adaptateur a liste
  blanche, verifie par les tests).

## Installation et deploiement

Voir `DEPLOIEMENT.md` (variables d'environnement, tests, lancement du
worker, deploiement gere Mistral Workflows, controles de sante, retour
arriere). CI pytest + build Docker :
`.github/workflows/python-tests.yml` (doit etre VERTE avant tout
deploiement). Migration Supabase :
`.github/workflows/supabase-migrate.yml` (manuelle, workflow_dispatch).

## Verifier GeniusPay avec GitHub Actions (Sandbox)

1. Dans GitHub : **Settings → Secrets and variables → Actions**.
2. Les secrets `GENIUSPAY_API_KEY` et `GENIUSPAY_API_SECRET` doivent contenir les cles Sandbox.
3. Apres fusion de la PR vers `main`, ouvrir **Actions → GeniusPay - verification Sandbox et Wave Direct → Run workflow**.
4. Le workflow verifie le compte et les fournisseurs PawaPay en lecture seule, puis cree une transaction technique Wave Direct de **200 XOF en Sandbox uniquement** et la relit par reference.
5. GeniusPay indique que les transactions Sandbox sont simulees : ce test ne debite aucun compte reel. Il cree toutefois une transaction de test dans l'historique Sandbox. Le code refuse tout lancement en mode Live.

Les secrets GitHub Actions ne sont transmis qu'aux workflows qui les referencent ; ils ne deviennent pas les variables du worker Mistral ou d'un autre hebergeur. Voir la documentation GitHub : https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets


## Parcours de commande Wave Direct (CI/XOF)

- Pour une commande ivoirienne en XOF, `GestionnaireCommandes.initier_paiement(..., moyen="wave", ...)` demande un checkout Wave Direct a GeniusPay (`payment_method=wave`, `gateway=wave`).
- Wave Direct n'est propose que si l'adaptateur GeniusPay est connecte (cles API + secret webhook) et que le pays/devise sont CI/XOF. La reponse de GeniusPay doit confirmer la passerelle, le montant, la devise, la commande et l'environnement avant que l'URL soit retournee.
- Le retour navigateur ne confirme jamais le paiement. Seul le webhook GeniusPay signe, horodate et lie a la reference, au montant, a la devise et a la commande peut faire passer cette commande a `payee`.
- Le test technique Wave Direct a reussi en Sandbox. Cela ne valide pas encore les cles Live, le webhook de production ni la configuration du moyen de paiement dans Freewebstore. L'endpoint HTTPS recevant les webhooks et le branchement de l'interface de checkout doivent etre deployes avant toute commande client reelle.

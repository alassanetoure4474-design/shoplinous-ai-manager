# SHOPLINOUS GLOBAL v6 - Architecture definitive

Evolution du SHOPLINOUS AI MANAGER existant vers une plateforme
e-commerce internationale (Afrique, Europe, monde). Les 32 outils du
workflow (workflow/daily.py), les cinq modeles IA (ai_manager) et les
integrations Freewebstore / CJdropshipping sont CONSERVES tels quels.

## Les 19 modules (workflow/shoplinous_global/)

| # | Module | Role | Etat |
|---|--------|------|------|
| 1 | market_manager | 9 marches mondiaux, regroupements pays | Operationnel (hors ligne) |
| 2 | country_manager | Config par pays : 9 champs ISO/devise/fuseau/paiements/fournisseurs/transporteurs/restrictions/regles livraison ; geo INDICATIVE, client peut toujours changer de pays | Operationnel |
| 3 | currency_manager | XOF XAF EUR USD GBP CAD GHS NGN MAD KES ZAR ; arrondis par exposant ; coherence affiche/encaisse ; devise comptable configurable | Operationnel |
| 4 | exchange_rate_manager | Taux horodates, cache TTL, indisponibilite = ECHEC (aucun taux invente), historique | Operationnel |
| 5 | pricing_manager | Composition complete (fournisseur+transport+frais paiement+plateforme+taxe+marge min) ; donnee manquante = prix BLOQUE avec champ exact | Operationnel |
| 6 | payment_manager | Transactions idempotentes, checkout GeniusPay Wave Direct CI/XOF, webhook signe = SEULE preuve de paiement (redirection ignoree), rapprochement comptable | Code operationnel ; activation reelle conditionnee aux cles API, secret webhook et endpoint HTTPS |
| 7 | payment_providers | GeniusPay checkout heberge + Wave Direct CI/XOF ; CinetPay, PayDunya, KoraPay, Stripe, PayPal en attente de contrats | GeniusPay actif uniquement avec cles API et secret webhook ; autres non connectes |
| 8 | supplier_manager | API + import CSV STRICT + saisie manuelle ; provenance tracable | Operationnel |
| 9 | supplier_adapters | Registre extensible ; CJ remonte catalogue, variantes, stock CN, images GET validées et devis réels en lecture seule ; origine fournisseur/entrepôt informative | CJ normalisé actif ; conformité produit et restrictions douanières restent bloquantes faute de preuves ; autres connecteurs non connectés |
| 10 | product_catalog | Catalogue multi-fournisseurs, anti-doublons ; publication = workflow existant sous autorisation | Operationnel |
| 11 | inventory | Stocks agreges, non mesure = non garanti, alertes seuil | Operationnel |
| 12 | shipping_manager | Comparaison devis REELS (destination/quantite exacte/poids/delai/restrictions) ; AUCUNE extrapolation | Operationnel |
| 13 | order_manager | Machine a etats, association transaction/commande, webhook obligatoire pour payer, transmission fournisseur = autorisation EXPLICITE, journal | Operationnel en memoire ; persistance/deploiement HTTP a finaliser |
| 14 | tracking_manager | Evenements de suivi, historique, aucune invention | Operationnel |
| 15 | ai_decision_engine | Recommandations deterministes sur donnees verifiees ; IA (5 modeles) pour justification ; JAMAIS d achat automatique | Operationnel |
| 16 | notification_manager | Canaux journal (actif) / email / sms / webhook (non connectes) ; redaction systematique | Operationnel |
| 17 | security_audit | Redaction secrets, HMAC webhooks, journal audit chainage SHA-256, liste blanche PII | Operationnel |
| 18 | monitoring | Compteurs, sante des modules, panorama des connexions REELLES | Operationnel |
| 19 | supplier_qualification | Qualification mondiale par offre/destination/quantité : preuve fournisseur, conformité produit, stock >= 1000, >= 2 images vérifiées, achat <= 8 EUR/unité, fret réel <= 6 EUR/unité, délai <= 15 jours, restrictions levées, marge x3 ; aucune restriction sur pays d'origine | Moteur et tests opérationnels ; CJ alimente maintenant le moteur, mais ses offres restent refusées si conformité produit ou restrictions douanières ne sont pas prouvées |

## Honnetete des etats (ne jamais confondre)

- REEL : integration CJ (recherche normalisee deleguee aux outils existants ; catalogue, variantes, stock CN, GET images et devis exacts en lecture seule), tests CI.
- SIMULE (mocks) : tests paiement/webhooks/fournisseurs sans reseau.
- NON CONNECTE : prestataires de paiement et fournisseurs sans contrat/API
  actif (AliExpress, BigBuy, Spocket, Printful et catalogues personnalisés).
  Aucun appel n'est simulé comme réel.

## Regles absolues du systeme (testees)

1. Un paiement n est jamais confirme par une redirection navigateur ;
   seule la signature webhook (HMAC-SHA256) fait foi.
2. Aucun fournisseur non connecté ou offre non qualifiée n'est proposé au client.
   Le pays d'origine du fournisseur ne constitue pas un motif de rejet.
3. Aucun devis de transport absent n est extrapole.
4. Toute donnee financiere manquante BLOQUE le prix concerne.
5. La transmission fournisseur exige une autorisation distincte.
6. Aucun achat, paiement, remboursement ni publication reels sans
   confirmation explicite (allow_publish=False par defaut conserve).
7. Detection geographique indicative ; choix du pays par le client.

## Pour connecter reellement (a faire cote client)

1. Pour GeniusPay, configurer les cles API et le secret webhook dans le service serveur, deployer un endpoint HTTPS receveur puis valider le flux de bout en bout en Sandbox avant d autoriser Live. Les autres prestataires exigent leurs contrats marchands et secrets webhook.
2. Pour chaque fournisseur supplémentaire : contrat/autorisation API,
   adaptateur normalisé, tests de stock/images et devis transport réels.
   Une fois connecté, il peut proposer des produits depuis n'importe quelle
   origine ISO ; chaque offre est qualifiée pour chaque destination.
3. Service de taux de change reel a brancher sur FournisseurTaux.
4. Deploiement gere Mistral Workflows (voir DEPLOIEMENT.md section 8).

## Modules complementaires v6.1 (novembre 2026)

| # | Module | Role | Etat |
|---|--------|------|------|
| 19 | intl (workflow/intl.py) | 30 pays enregistres dont 29 marches verifies (UE27 + GB/CH/NO, Malte exclue : aucune option CJ <= 15 jours) ; statuts distincts enregistre/livrable/paiement/taxes/ouvert a la vente ; devises extensible (EUR USD XOF XAF GBP CAD CNY JPY NGN GHS MAD ZAR KES) ; conversion UNIQUEMENT avec des taux fournis (BCE/Frankfurter au runtime), jamais inventes ; langues fr/en/es/pt/ar extensibles avec traductions completes exigees | Operationnel ; un pays non enregistre ne peut pas etre propose |
| 20 | ad_engine (workflow/ad_engine.py) | Moteur publicitaire : scoring produits (stock, marge >= 3x, images >= 2, livrabilite), annonces honnetes multilingues (aucun faux avis, aucune fausse reduction, aucune offre dans un pays non ouvert ou non livrable), calendrier organique max 3 publications/jour sur canaux autorises UNIQUEMENT, campagnes payantes en brouillon budget 0 strictement, tableau de bord sans statistique fictive | Operationnel ; AUCUN canal social n est autorise (aucun connecteur actif) : aucune publication reelle possible |

Securite publicitaire absolue :

1. Un produit rupture, non rentable, sans images ou non livrable
   n est jamais promu.
2. Une annonce n est jamais generee pour un pays non ouvert a la vente.
3. Une campagne payante ne peut JAMAIS avoir un budget > 0 sans
   autorisation reelle ; elle reste en brouillon.
4. Le tableau de bord n invente aucune statistique : les champs sans
   donnee reelle valent None.
5. Le calendrier refuse tout canal non autorise (facebook, instagram,
   tiktok, google, pinterest : tous a False tant qu aucun connecteur
   n est active).

# SHOPLINOUS GLOBAL v6 - Architecture definitive

Evolution du SHOPLINOUS AI MANAGER existant vers une plateforme
e-commerce internationale (Afrique, Europe, monde). Les 32 outils du
workflow (workflow/daily.py), les cinq modeles IA (ai_manager) et les
integrations Freewebstore / CJdropshipping sont CONSERVES tels quels.

## Les 18 modules (workflow/shoplinous_global/)

| # | Module | Role | Etat |
|---|--------|------|------|
| 1 | market_manager | 9 marches mondiaux, regroupements pays | Operationnel (hors ligne) |
| 2 | country_manager | Config par pays : 9 champs ISO/devise/fuseau/paiements/fournisseurs/transporteurs/restrictions/regles livraison ; geo INDICATIVE, client peut toujours changer de pays | Operationnel |
| 3 | currency_manager | XOF XAF EUR USD GBP CAD GHS NGN MAD KES ZAR ; arrondis par exposant ; coherence affiche/encaisse ; devise comptable configurable | Operationnel |
| 4 | exchange_rate_manager | Taux horodates, cache TTL, indisponibilite = ECHEC (aucun taux invente), historique | Operationnel |
| 5 | pricing_manager | Composition complete (fournisseur+transport+frais paiement+plateforme+taxe+marge min) ; donnee manquante = prix BLOQUE avec champ exact | Operationnel |
| 6 | payment_manager | Transactions, idempotence par cle, webhook signe = SEULE preuve de paiement (redirection ignoree), rapprochement comptable | Operationnel (aucun prestataire actif) |
| 7 | payment_providers | CinetPay, PayDunya, KoraPay, Stripe, PayPal : pays, devises de reglement, frais, delais, KYC documents ; connected=False tant que pas de contrat marchand | En attente de contrats marchands |
| 8 | supplier_manager | API + import CSV STRICT + saisie manuelle ; provenance tracable | Operationnel |
| 9 | supplier_adapters | CJ = REEL (delegue aux outils daily.py) ; AliExpress, BigBuy, Spocket, Printful, fournisseurs africains/ivoiriens/personnalises = registres NON CONNECTES | CJ actif, autres en attente |
| 10 | product_catalog | Catalogue multi-fournisseurs, anti-doublons ; publication = workflow existant sous autorisation | Operationnel |
| 11 | inventory | Stocks agreges, non mesure = non garanti, alertes seuil | Operationnel |
| 12 | shipping_manager | Comparaison devis REELS (destination/quantite exacte/poids/delai/restrictions) ; AUCUNE extrapolation | Operationnel |
| 13 | order_manager | Machine a etats complete, anti-doublons, transmission fournisseur = autorisation EXPLICITE, journal | Operationnel |
| 14 | tracking_manager | Evenements de suivi, historique, aucune invention | Operationnel |
| 15 | ai_decision_engine | Recommandations deterministes sur donnees verifiees ; IA (5 modeles) pour justification ; JAMAIS d achat automatique | Operationnel |
| 16 | notification_manager | Canaux journal (actif) / email / sms / webhook (non connectes) ; redaction systematique | Operationnel |
| 17 | security_audit | Redaction secrets, HMAC webhooks, journal audit chainage SHA-256, liste blanche PII | Operationnel |
| 18 | monitoring | Compteurs, sante des 18 modules, panorama des connections REELLES | Operationnel |

## Honnetete des etats (ne jamais confondre)

- REEL : integration CJ (deleguee aux outils existants), tests CI.
- SIMULE (mocks) : tests paiement/webhooks/fournisseurs sans reseau.
- NON CONNECTE : tous les prestataires de paiement et fournisseurs
  autres que CJ ; aucun appel n est simule comme reel.

## Regles absolues du systeme (testees)

1. Un paiement n est jamais confirme par une redirection navigateur ;
   seule la signature webhook (HMAC-SHA256) fait foi.
2. Aucun operateur/fournisseur non active n est propose au client.
3. Aucun devis de transport absent n est extrapole.
4. Toute donnee financiere manquante BLOQUE le prix concerne.
5. La transmission fournisseur exige une autorisation distincte.
6. Aucun achat, paiement, remboursement ni publication reels sans
   confirmation explicite (allow_publish=False par defaut conserve).
7. Detection geographique indicative ; choix du pays par le client.

## Pour connecter reellement (a faire cote client)

1. Contrats marchands (CinetPay/PayDunya/KoraPay/Stripe/PayPal) puis
   variables d environnement des secrets webhook par prestataire.
2. Contrats fournisseurs additionnels (AliExpress, BigBuy, ...) puis
   adaptateurs a implementer sur la base AdaptateurFournisseur.
3. Service de taux de change reel a brancher sur FournisseurTaux.
4. Deploiement gere Mistral Workflows (voir DEPLOIEMENT.md section 8).

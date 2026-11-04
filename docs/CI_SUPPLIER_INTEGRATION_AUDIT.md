# SHOPLINOUS AFRICA — audit et intégration des partenaires Côte d’Ivoire

Date de l'audit : 2026-11-04  
Branche de travail : `feat/ci-supplier-integration-audit`  
Marché initial : Côte d’Ivoire (CI / XOF)  
Statut : audit documentaire ; aucun partenaire externe n'est déclaré connecté tant que ses identifiants, son contrat et ses tests réels ne sont pas validés.

## 1. Décision d'architecture

Ne pas brancher chaque entreprise directement au storefront. SHOPLINOUS doit utiliser un adaptateur serveur par partenaire et un format canonique commun :

- catalogue : produit, SKU/variante, images, prix d'achat, disponibilité et horodatage ;
- destination : CI, commune/ville, zone desservie et tarif ;
- commande : création idempotente, référence SHOPLINOUS et référence partenaire ;
- livraison : statut, tracking, preuve de livraison, frais COD ;
- après-vente : annulation, refus, retour, remboursement, produit défectueux ;
- rapprochement : montant encaissé, coûts facturés, solde marchand, frais et date de reversement.

Les clés et secrets restent dans les secrets du serveur. Aucun secret fournisseur dans `storefront/config.js` ni dans le navigateur. Les webhooks doivent être authentifiés, idempotents et journalisés sans données personnelles superflues.

## 2. Candidats dropshipping CI

### A. Swift Dropshipping / ColiSwift — priorité d'intégration P1, non connecté

Site : https://coliswift.com/fr/dropshipping/  
Éléments annoncés publiquement :
- catalogue avec produits indiqués en stock en Côte d'Ivoire ;
- confirmation téléphonique, préparation, livraison et encaissement COD ;
- coût produit et livraison facturés uniquement après livraison réussie ;
- aucun abonnement/frais d'inscription annoncé ;
- synchronisation annoncée avec Shopify, WooCommerce et boutiques sur mesure ;
- pays actifs affichés : Côte d'Ivoire, Congo-Brazzaville et Cameroun.

Exemples affichés par le site (à confirmer par devis marchand, non garantis) :
- Smartwatch S8 : vente 25 000 XOF, coût produit 8 000 XOF, livraison 5 500 XOF, marge brute affichée 11 500 XOF avant publicité ;
- sérum vitamine C : vente 15 000 XOF, coût 3 500 XOF, livraison 5 500 XOF, marge brute affichée 6 000 XOF ;
- brosse soufflante : vente 22 000 XOF, coût 7 500 XOF, livraison 5 500 XOF, marge brute affichée 9 000 XOF.

À obtenir avant connexion :
1. identité juridique et coordonnées contractuelles exactes de l'entité qui opère le domaine `coliswift.com` ;
2. documentation API/SDK ou spécification de synchronisation pour une boutique sur mesure ;
3. sandbox, clés de test, authentification, endpoints catalogue/stock/commande/tracking ;
4. webhook signé et politique de retry/idempotence ;
5. grille de livraison par commune, notamment Anyama, Abidjan et villes intérieures ;
6. preuve écrite des règles COD, frais de refus/retour, dommages/pertes, délai de reversement et méthode de paiement ;
7. preuve des stocks CI et historique agrégé de livraison par SKU.

**Blocage actuel :** documentation API publique non trouvée. La synchronisation « boutique sur mesure » est annoncée, mais le protocole n'est pas publié. Aucun adaptateur réel ne doit être codé sur la base d'endpoints supposés.

### B. Yehadé — priorité d'intégration P1, non connecté

Site : https://www.yehade.com/  
FAQ officielle : https://www.yehade.com/faq.php  
Contact affiché : contact@yehade.com ; +225 07 69 83 02 28.

Éléments annoncés par Yehadé :
- plateforme ivoirienne de dropshipping avec catalogue, stockage, préparation et livraison ;
- inscription gratuite et absence de stock à acheter annoncées ;
- livraison annoncée dans les principales villes et zones urbaines de Côte d'Ivoire ;
- gains annoncés reversés sur Wave ;
- service après-vente annoncé pour retours, échanges et réclamations ;
- commandes non retirées retournées à l'entrepôt ; facturation annoncée seulement après livraison réussie ;
- aucune commission annoncée par la FAQ.

À obtenir avant connexion :
1. statut juridique, raison sociale, adresse et contrat marchand ;
2. API ou flux CSV/XML/JSON autorisé, ou accord d'intégration personnalisée ;
3. catalogue marchand avec prix de revient et stock par SKU ;
4. prix de livraison par commune, frais éventuels de retour et de refus ;
5. preuve et délai de reversement Wave, seuils et frais éventuels ;
6. règles de responsabilité, SAV, garantie, remboursements ;
7. sandbox et procédure de commande test.

**Blocage actuel :** aucune documentation API publique trouvée. Les conditions sont déclaratives et doivent être confirmées par écrit.

### C. ExpressNK — priorité P2, à vérifier

Site : https://expressnk.com/

Éléments annoncés :
- plateforme mettant en relation marchands, fournisseurs et livreurs ;
- couverture annoncée incluant la Côte d'Ivoire ;
- paiement à la livraison, confirmation téléphonique, suivi et portefeuille marchand ;
- fournisseurs capables de publier prix de gros et stocks.

À obtenir :
- preuve de présence opérationnelle et d'adresses de livraison en CI ;
- catalogue fournisseur réellement disponible en CI, pas uniquement un catalogue e-commerce générique ;
- documentation API/webhook et accès sandbox ;
- tarifs XOF, commissions, délais de reversement, refus/retours ;
- identité juridique et références marchands vérifiables.

**Blocage actuel :** aucun endpoint API ni documentation technique publique repérés. La page publique présente également un catalogue générique avec certains prix en EUR ; ne pas assimiler la présence d'une devise XOF à une preuve d'exécution COD en CI.

## 3. Fournisseurs locaux / grossistes à qualifier (pas des dropshippers vérifiés)

Ces pistes peuvent fournir des produits, mais leur capacité à expédier directement au client final et à gérer les retours n'est pas établie :

- Admarket CI — https://admarket.ci/ — marketplace/service e-commerce à Abidjan ; demander accès vendeur, tarifs revendeur, stock et expédition directe.
- Djami / DJAMI CI — vendeur électronique référencé au Marché Samsung, Treichville ; demander tarif revendeur, facture, stock, livraison et dropshipping.
- EasyShop — électronique et électroménager à Port-Bouët ; demander catalogue professionnel et livraison directe.
- William Service — pièces et accessoires de téléphonie à Koumassi ; demander catalogue B2B, stock et conditions de garantie.
- Fouta Communication — téléphonie/électronique à Adjamé ; demander prix grossiste et exécution des commandes.
- PDASHOP / DEVAX — distribution électronique et téléphonie à Abidjan ; demander conditions B2B.
- Achagros, Lahidou, NOGROX, Uma uja, La Centrale Ivoir, Le Point Parfait, Tieba Market — pistes de sourcing/marketplaces précédemment recensées ; qualification juridique, catalogue et service dropshipping à effectuer avant utilisation.

Aucun de ces acteurs ne doit être présenté comme « API connectée » ou « fournisseur agréé » sans preuve technique et contractuelle.

## 4. Logisticiens à qualifier (transport uniquement, sauf preuve contraire)

- Coursier.ci — livraison dernier kilomètre ; demander contrat e-commerce, API, COD, reversement et preuve de livraison.
- Delifast — livraison de colis à Abidjan ; demander couverture Anyama, tarif professionnel, COD et retours.
- Weni — service de livraison via application ; demander intégration entreprise, tracking et COD.
- Licy Express — livraison urbaine et points relais ; demander API, tarifs, COD et couverture.
- Africolis — logistique internationale/réception de colis ; plutôt import et acheminement.
- Afrety — freight forwarding et achats assistés ; plutôt import international, pas dropshipping local.
- Jexport — import-export et transport ; à étudier pour approvisionnement international.
- Bleu Eagle Group — piste de logistique/fulfillment ; vérifier capacité opérationnelle et contrats e-commerce.
- WeGoo — piste de livraison/fulfillment avec présence annoncée à Abidjan ; demander spécification API et conditions commerciales.
- MONTAL Coursier — achats internationaux et acheminement ; à considérer pour l'importation, pas comme fournisseur catalogue.
- Cart'In — achat/acheminement depuis des plateformes étrangères ; pas un fournisseur dropshipping.

Un transporteur ne remplace pas un fournisseur : il faut identifier qui détient le stock, prépare le colis, assume la garantie et encaisse le client.

## 5. Fournisseur international existant : CJdropshipping

L'adaptateur CJ existant dans le dépôt est en lecture seule. Il ne crée pas d'achat fournisseur ni de commande client.

La politique officielle CJ cite explicitement la Côte d'Ivoire parmi les destinations pour lesquelles CJ n'accepte pas les litiges. CJ ne doit donc pas être utilisé comme fournisseur principal pour les commandes CI. Il reste utilisable uniquement pour les autres destinations après qualification individuelle des routes et conditions.

Politique : https://www.cjdropshipping.com/dispute-policy.html

## 6. Calcul de rentabilité obligatoire

Ne pas confondre marge affichée et bénéfice net. Calculer par SKU, commune et mode de paiement :

`marge nette livrée = prix encaissé - coût produit - livraison - frais COD/paiement - publicité attribuée - provision SAV/retours - taxes et autres frais`

Pour un funnel COD, calculer aussi :

`contribution par commande reçue = taux de livraison × marge nette par commande livrée - coût de confirmation/marketing supporté par commande reçue - coût des refus non remboursés`

Ne publier un SKU que si :
- stock et prix fournisseur sont frais ;
- livraison CI et commune exacte confirmée ;
- prix de vente supporte tous les coûts ;
- taux de livraison historique est disponible ou le produit est marqué « test » ;
- conformité, sécurité et droits de marque sont vérifiés ;
- la marge reste positive dans un scénario prudent.

Ne jamais imposer la règle de marge x3 de l'ancien moteur à un modèle COD local sans l'adapter : le contrôle doit comparer les coûts réellement supportés par commande livrée et par commande reçue.

## 7. Plan de connexion par étapes

1. Obtenir les documents API et conditions écrites de Swift Dropshipping et Yehadé ; ouvrir ExpressNK en parallèle.
2. Tester les accès en lecture seule : catalogue, stock, prix, villes et tarifs.
3. Importer les produits en zone de staging privée ; aucun produit n'est publié automatiquement.
4. Comparer les prix et taux de livraison ; calculer les marges nettes par ville.
5. Créer un adaptateur serveur par fournisseur avec idempotence, webhook signé et mapping des statuts.
6. Brancher les commandes après activation du backend Supabase et tests sandbox ; le client ne doit pas payer via un flux COD et un checkout prépayé simultanément.
7. Exécuter une commande pilote autorisée par le propriétaire et mesurer livraison, reversement et marge.
8. Publier uniquement les produits gagnants, après validation humaine.

## 8. État technique actuel de la vitrine

La vitrine est dans la PR #35 (branche `feat/shoplinous-africa-storefront`). Elle est encore en brouillon. Le fichier `storefront/config.js` n'a pas encore de Project URL ni de clé publique Supabase ; le catalogue est donc non connecté. Le bouton de commande est désactivé, et la démonstration de paiement n'appelle pas GeniusPay.

PR : https://github.com/alassanetoure4474-design/shoplinous-ai-manager/pull/35

Aucune migration Supabase de production, fusion, commande fournisseur, transaction réelle, publicité ou publication produit ne doit être déclenchée sans autorisation explicite.

## 9. Informations à demander aux partenaires

Objet : Intégration technique SHOPLINOUS AFRICA — fournisseur / dropshipping Côte d'Ivoire

Nous souhaitons connecter votre catalogue et votre gestion des commandes à notre boutique e-commerce SHOPLINOUS AFRICA. Merci de nous communiquer :
- votre raison sociale et vos coordonnées contractuelles ;
- vos conditions marchands, commissions, frais et modalités de reversement ;
- les villes et communes couvertes, avec tarifs et délais ;
- vos règles COD, refus, retours, colis perdus et produits défectueux ;
- votre documentation API, webhooks, sandbox et procédure d'accès partenaire ;
- un catalogue test avec SKU, prix d'achat, stock, images et frais de livraison ;
- les étapes nécessaires pour réaliser une commande pilote sans risque.

Nous ne publierons pas de produit avant validation du stock, du prix total, de la livraison, du service après-vente et de la marge nette.

---
Dernière règle : « site consulté » ne signifie pas « partenaire approuvé », « compte marchand créé » ne signifie pas « API intégrée », et « API connectée » ne signifie pas « commandes rentables ».

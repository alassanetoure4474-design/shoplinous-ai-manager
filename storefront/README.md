# SHOPLINOUS AFRICA — vitrine et parcours boutique

Ce dossier contient le site public, indépendant de Freewebstore et distinct de l'ancien tableau de gestion. Tout le contenu est en français ; l'architecture est prête pour des traductions ultérieures (contenus regroupés par page, aucun texte codé en dur dans les composants partagés).

## Pages livrées

Boutique :
- `index.html` : accueil (identité, univers, sélection, parcours de paiement interactif, manifeste).
- `catalogue.html` : catalogue dynamique avec recherche, filtre par catégorie et sélection du marché.
- `produit.html` : fiche produit, galerie, ajout au panier et gestion des favoris.
- `favoris.html` : liste des favoris enregistrés dans le navigateur (revalidée contre le catalogue publié).
- `panier.html` : quantités, retrait d'articles, sous-total indicatif.

Parcours et compte (inactifs jusqu'à activation serveur) :
- `commande.html` : explication du parcours de commande ; bouton de paiement désactivé.
- `connexion.html` / `compte.html` : formulaires inactifs en attendant l'authentification sécurisée (Supabase Auth).

Pages éditoriales et légales :
- `a-propos.html`, `contact.html`, `faq.html`, `blog.html`.
- `livraison.html`, `remboursement.html`, `cgv.html`, `confidentialite.html` (les champs d'immatriculation sont explicitement marqués « à compléter par le propriétaire »).

Fichiers communs :
- `shop.js` : logique catalogue/produit/panier/favoris (favoris : clé locale `shoplinous_favs_v1`).
- `shop.css` / `pages.css` : styles boutique et éditoriaux (palette ivoire, vert forêt, terre cuite, or doux).
- `animations.js` : contrôleur du parcours de paiement interactif et des apparitions au défilement.
- `config.js` : emplacement de la configuration publique Supabase.

## Règles de sécurité et de vérité commerciale

- Le catalogue public lit uniquement `storefront_products`, protégée par RLS.
- Seuls les produits publiés, qualifiés et dont les contrôles fournisseur, conformité, images, stock et transport sont suffisamment récents sont visibles.
- La clé Supabase dans `config.js` doit être une clé publique publishable/anon. Ne jamais y mettre une clé `service_role` ou un secret.
- Le panier et les favoris restent locaux au navigateur et ne réservent pas de stock.
- Le bouton de commande est désactivé : aucune commande, aucun paiement et aucun achat fournisseur ne sont déclenchés.
- Aucun produit, prix, stock, avis, délai ou coordonnée fictif n'est affiché ; les valeurs manquantes sont explicitement marquées « à compléter ».

## Configuration requise avant catalogue dynamique

Renseigner `supabaseUrl` et `supabaseAnonKey` dans `config.js` après création/vérification du projet Supabase. Appliquer la migration `supabase/migrations/20261104000500_storefront_public_catalog.sql` (avec autorisation explicite).

## Étapes restantes

1. Configurer Supabase, appliquer la migration et tester les politiques RLS.
2. Ajouter le service serveur qui alimente les fiches de marché après qualification complète.
3. Construire l'API de commande, le calcul final par destination et la réservation idempotente.
4. Relier GeniusPay en Sandbox et vérifier les webhooks signés.
5. Activer l'authentification client (connexion, compte, espace client, suivi de colis).
6. Ajouter sitemap.xml, robots.txt et canonical URLs dès que le domaine officiel sera connu.
7. Exécuter les tests et déployer sur un environnement de préproduction avant toute ouverture réelle.

## Contrôles

Le workflow `.github/workflows/storefront-check.yml` vérifie la syntaxe JavaScript, la structure des pages boutique, la présence, la langue et les métadonnées des pages éditoriales, l'absence de clé secrète dans `config.js` et le maintien du bouton de commande désactivé.

## Identité et animations

- `assets/logo-animated.svg` : emblème vectoriel animé, avec prise en charge de `prefers-reduced-motion`.
- `assets/hero-motion.svg` : illustration de couverture SVG animée.
- Le parcours de paiement interactif de l'accueil est une démonstration visuelle : aucun appel à GeniusPay, aucune transaction.

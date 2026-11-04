# SHOPLINOUS AFRICA — vitrine et parcours boutique

Ce dossier contient le nouveau site public, indépendant de Freewebstore et distinct de l'ancien tableau de gestion.

## Pages livrées

- `index.html` : accueil mobile-first et présentation de la marque.
- `catalogue.html` : recherche, filtres par catégorie et sélection du marché.
- `produit.html` : fiche produit, galerie et ajout au panier.
- `panier.html` : modification des quantités et retrait d'articles.
- `shop.js` / `shop.css` : logique et styles communs.
- `config.js` : emplacement de la configuration publique Supabase.

## Règles de sécurité et de vérité commerciale

- Le catalogue public lit uniquement `storefront_products`, protégée par RLS.
- Une ligne représente un produit pour un marché précis : prix, devise et contrôles sont propres au pays.
- Seuls les produits publiés, qualifiés et dont les contrôles fournisseur, conformité, images, stock et transport sont suffisamment récents sont visibles.
- La clé Supabase dans `config.js` doit être une clé publique publishable/anon. Ne jamais y mettre une clé `service_role` ou un secret.
- Le panier reste local au navigateur et ne réserve pas de stock.
- Le bouton de commande est désactivé : aucune commande, aucun paiement et aucun achat fournisseur ne sont déclenchés.
- Aucun produit de démonstration, prix, stock, avis ou délai fictif n'est affiché.

## Configuration requise avant catalogue dynamique

Renseigner `supabaseUrl` et `supabaseAnonKey` dans `config.js` après création/vérification du projet Supabase. Appliquer la migration `supabase/migrations/20261104000500_storefront_public_catalog.sql`.

La table publique est volontairement en lecture seule pour les visiteurs. La publication doit être effectuée par un service serveur après qualification complète par les moteurs existants ; aucun navigateur ne peut publier un produit.

## Étapes restantes

1. Ajouter le service serveur qui alimente les fiches de marché après qualification complète.
2. Configurer Supabase et tester les politiques RLS.
3. Construire l'API de commande, le calcul final par destination et la réservation idempotente.
4. Relier GeniusPay en Sandbox et vérifier les webhooks signés.
5. Ajouter suivi de commande, comptes clients et support.
6. Exécuter les tests et déployer sur un environnement de préproduction avant toute ouverture réelle.

## Contrôles

Le workflow `.github/workflows/storefront-check.yml` vérifie la syntaxe JavaScript et la structure des pages sans dépendance payante.

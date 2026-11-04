# SHOPLINOUS AFRICA — reprise du projet

## État actuel
- La vitrine publique est dans `storefront/`, sur la branche `feat/shoplinous-africa-storefront`.
- L'accueil, le catalogue, la fiche produit et le panier sont en français.
- Direction artistique : ivoire, vert forêt, terre cuite et or doux ; typographie éditoriale, compositions asymétriques et animations mesurées.
- Les animations respectent `prefers-reduced-motion`.
- Le catalogue n'affiche aucun produit fictif.
- Le panier est local ; aucune commande ni aucun paiement réel ne peut être déclenché.
- La PR #35 reste ouverte en brouillon. Rien n'a été fusionné ni déployé.

## À faire par l'administratrice / le propriétaire
1. Ouvrir le projet Supabase SHOPLINOUS.
2. Dans **Project Settings → API Keys**, récupérer uniquement le **Project URL** et la clé publique **publishable** (ou l'ancienne clé **anon**).
3. Ne jamais transmettre la clé `service_role`, une clé `sb_secret` ou le mot de passe de base de données.
4. Envoyer le Project URL et la clé publique pour configurer `storefront/config.js`.
5. Lire la migration `supabase/migrations/20261104000500_storefront_public_catalog.sql`. Son application sur le projet réel devra être autorisée explicitement avant toute modification de la base.
6. Après connexion et validation des contrôles, préparer l'aperçu Cloudflare Pages. Le déploiement public attendra une autorisation explicite.

## Garde-fous
- Ne pas fusionner la PR et ne pas déployer en production sans accord explicite.
- Ne pas activer de paiement réel, d'achat fournisseur ou de publicité.
- N'afficher que des produits dont le fournisseur, l'authenticité, le stock, le prix total, le pays et le délai de livraison sont vérifiés.
- Aucun achat fournisseur avant réception effective et vérification du paiement client.

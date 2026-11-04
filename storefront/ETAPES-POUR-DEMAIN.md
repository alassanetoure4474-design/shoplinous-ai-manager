# SHOPLINOUS AFRICA — reprise du projet

## État actuel
- La vitrine publique est dans `storefront/`, sur la branche `feat/shoplinous-africa-storefront` (PR #35, ouverte, non fusionnée).
- Pages livrées : accueil, catalogue, fiche produit, favoris, panier, commande (désactivée), connexion et compte (inactifs), à propos, contact, FAQ, blog, livraison, remboursements, CGV, confidentialité.
- Direction artistique : ivoire, vert forêt, terre cuite et or doux ; typographie éditoriale, compositions asymétriques et animations mesurées (`prefers-reduced-motion` respecté).
- Favoris : enregistrés dans le navigateur (`shoplinous_favs_v1`), revalidés contre le catalogue publié.
- Le catalogue n'affiche aucun produit fictif ; le panier et la commande ne déclenchent rien.
- Tous les textes sont en français ; l'ajout de langues se fera par duplication contrôlée des contenus de page.
- Champs à compléter par le propriétaire avant la première vente : raison sociale/registre de commerce (CGV), responsable de traitement (confidentialité), coordonnées de contact, tribunal compétent.

## À faire par l'administratrice / le propriétaire
1. Ouvrir le projet Supabase SHOPLINOUS.
2. Dans **Project Settings → API Keys**, récupérer uniquement le **Project URL** et la clé publique **publishable** (ou l'ancienne clé **anon**).
3. Ne jamais transmettre la clé `service_role`, une clé `sb_secret` ou le mot de passe de base de données.
4. Envoyer le Project URL et la clé publique pour configurer `storefront/config.js`.
5. Autoriser explicitement l'application de `supabase/migrations/20261104000500_storefront_public_catalog.sql` sur le projet réel.
6. Compléter les champs légaux marqués « à compléter » (CGV, confidentialité, contact).
7. Après connexion et validation des contrôles, préparer l'aperçu Cloudflare Pages. Le déploiement public attendra une autorisation explicite.

## Garde-fous
- Ne pas fusionner la PR et ne pas déployer en production sans accord explicite.
- Ne pas activer de paiement réel, d'achat fournisseur ou de publicité.
- N'afficher que des produits dont le fournisseur, l'authenticité, le stock, le prix total, le pays et le délai de livraison sont vérifiés.
- Aucun achat fournisseur avant réception effective et vérification du paiement client.

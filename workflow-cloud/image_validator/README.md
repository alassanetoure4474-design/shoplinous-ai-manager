# SHOPLINOUS — Validateur HTTP GET d'images produits

Workflow cloud (Mistral Workflows) qui valide par de veritables requetes HTTP GET
que les images produits (CJdropshipping) sont accessibles et exploitables.

## Regles
- HTTPS obligatoire, liste blanche stricte de domaines, redirections recontrolees.
- Statut 200, Content-Type image, taille >= 1 Ko, signature binaire (JPEG/PNG/GIF/WEBP/BMP).
- 1 requete par seconde maximum, cache 6 h, timeout 15 s par requete.
- Une URL non verifiee ou refusee est INVALIDE. Aucune validation simulee.

## Integration SHOPLINOUS
Remplace la validation simulee : un produit exige au moins 2 images reellement
validees pour rester qualifie ; les criteres de qualification ne changent pas.

## Deploiement
Build directory : workflow-cloud/image_validator ; Dockerfile a la racine du build.

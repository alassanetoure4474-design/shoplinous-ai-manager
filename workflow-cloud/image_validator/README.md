# SHOPLINOUS — Validateur HTTP GET d'images produits (PR #29)

Workflow cloud Mistral qui verifie par de VERITABLES requetes HTTP GET que les
images produits CJ sont accessibles et exploitables. Une URL HTTPS n'est jamais
consideree comme validee sans preuve HTTP reelle.

## Corrections v2 (exigences de la PR #29)

1. **Streaming avec interruption immediate** : `reponse.aiter_bytes()`, arret
   des le depassement de 20 Mo (`TAILLE_MAX_OCTETS`), le corps n'est pas lu
   en entier.
2. **Cadence GLOBALE 1 req/s verrouee** : verrou `asyncio.Lock` module +
   horodatage `time.monotonic()` ; les executions concurrentes servies par le
   meme processus sont serialisees.
3. **Cache TTL 6 h — LIMITE DOCUMENTEE** : le cache est en memoire du processus
   worker. Il persiste entre les executions du meme processus mais il n'est
   **pas partage entre plusieurs processus workers (scaling horizontal)** ni
   persiste aux redemarrages. Aucun stockage partage (Supabase, KV) n'est
   disponible sans credentials ; remplacer `_CACHE` par un backend partage si
   un stockage est configure.
4. **SSRF renforce** : parsing `httpx.URL` (HTTPS et port 443 uniquement,
   identifiants refuses, liste blanche stricte de domaines), resolution DNS
   verifiee — toute IP non globale/privee/locale/reservee est refusee —
   redirections (max 3) revalidees a chaque saut (statique + reseau).

## Determinisme SDK Workflows

Aucune horloge ni aleatoire dans le workflow (`entrypoint`) : les horodatages
sont produits dans l'activite (`date_rapport` retourne par `verifier_images`),
conformement aux regles de determinisme du SDK Mistral Workflows.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Couverture : URL statiques (schema, port, liste blanche, identifiants),
SSRF (IP privees, DNS echoue), streaming > taille max, redirections (autorisee,
interdite, boucle), MIME incoherent, Content-Type non image, cadence globale
concurrente, cache TTL. Aucun reseau reel (httpx.MockTransport + resolveur DNS
factice injectes).

## Securite

Lecture seule : aucun achat, aucune commande, aucun paiement, aucune
publication Freewebstore. Domaines limites a `cf.cjdropshipping.com` et
`oss-cf.cjdropshipping.com` ; ajouter les fournisseurs futurs a
`DOMAINES_AUTORISES`.

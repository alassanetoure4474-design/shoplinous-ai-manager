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
4. **SSRF — FAIL-CLOSED** : HTTPS, port 443, liste blanche, identifiants refuses
   et resolution DNS sont controles. Toutefois, HTTPX peut refaire une resolution
   DNS au moment de la connexion : l'adresse validee n'est donc pas encore
   epinglee a la socket (risque DNS rebinding/TOCTOU). En consequence, le code
   refuse toute connexion reseau de production tant qu'un transport DNS pinne
   conservant TLS/SNI n'est pas disponible. Aucune image ne peut etre validee
   en production dans cet etat. Les transports injectes servent uniquement aux
   tests MockTransport. Les redirections sont revalidees mais restent bloquees
   en production par la meme protection fail-closed.

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
factice injectes). Un test confirme que l'appel de production sans transport
DNS pinne est refuse.

## Etat de mise en service

Le worker ne demarre pas si le SDK Mistral Workflows reel est absent. Le shim
est reserve aux tests (`SHOPLINOUS_TEST_MODE=1`). Le validateur reste volontairement
bloque en production jusqu'a l'implementation et aux tests d'un transport DNS
pinne. Ne pas fusionner ni qualifier de produits tant que ce point n'est pas leve.

## Securite

Lecture seule : aucun achat, aucune commande, aucun paiement, aucune
publication Freewebstore. Domaines limites a `cf.cjdropshipping.com` et
`oss-cf.cjdropshipping.com` ; ajouter les fournisseurs futurs a
`DOMAINES_AUTORISES`.

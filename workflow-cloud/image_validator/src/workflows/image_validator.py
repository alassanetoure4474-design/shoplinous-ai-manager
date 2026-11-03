"""Validateur HTTP GET reel des images produits SHOPLINOUS.

Mission : confirmer par une veritable requete HTTP GET qu'une image produit
CJ (ou d'un autre fournisseur) est accessible et exploitable. Une URL HTTPS
n'est JAMAIS consideree comme validee sans preuve HTTP reelle.

Securite :
- liste blanche stricte de domaines autorises (pas de redirection hors liste) ;
- HTTPS obligatoire, aucune URL avec identifiants, aucun hote interne/prive ;
- 1 requete par seconde maximum, cache avec TTL ;
- lecture seule : aucun achat, aucune commande, aucun paiement, aucune ecriture.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

import mistralai.workflows as workflows

import httpx

# ---------------------------------------------------------------- constantes
DOMAINES_AUTORISES = (
    "cf.cjdropshipping.com",
    "oss-cf.cjdropshipping.com",
)

SCHEMA_OBLIGATOIRE = "https"
TAILLE_MIN_OCTETS = 1024
TAILLE_MAX_OCTETS = 20 * 1024 * 1024
DELAI_EXPIRATION_REQUETE_S = 15.0
REDIRECTIONS_MAX = 3
INTERVALLE_REQ_S = 1.0
TTL_CACHE_S = 6 * 3600

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "SHOPLINOUS-ImageValidator/1.0"
)

_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)

_HOTES_PRIVES = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "169.254.169.254",
    "metadata.google.internal",
)


# ------------------------------------------------------------------- modeles
class ResultatImage(BaseModel):
    """Resultat de verification d'une seule image."""

    url: str
    statut_http: Optional[int] = None
    type_mime: Optional[str] = None
    taille_octets: Optional[int] = None
    date_verification: Optional[str] = None
    url_finale: Optional[str] = None
    valide: bool = False
    motif_echec: Optional[str] = None


class EntreeValidateur(BaseModel):
    """Entree du workflow : liste d'URL d'images a verifier."""

    urls: list[str] = Field(default_factory=list)


def _maintenant_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _erreur(url: str, motif: str) -> ResultatImage:
    return ResultatImage(
        url=url,
        date_verification=_maintenant_utc(),
        valide=False,
        motif_echec=motif,
    )


def _url_autorisee(url: str) -> tuple[bool, str]:
    """Controles de securite statiques avant toute requete."""
    if "://" not in url:
        return False, "URL invalide : pas de schema"
    schema, reste = url.split("://", 1)
    if schema.lower() != SCHEMA_OBLIGATOIRE:
        return False, f"Schema non autorise ({schema}) : HTTPS obligatoire"
    hote_brut = reste.split("/", 1)[0]
    if "@" in hote_brut:
        return False, "Identifiants embarques dans l'URL : refuse"
    hote = hote_brut.split(":")[0].strip().lower()
    if not hote:
        return False, "Hote vide"
    if hote in _HOTES_PRIVES or hote.endswith(".local") or hote.endswith(".internal"):
        return False, f"Hote interne non autorise ({hote})"
    if hote not in DOMAINES_AUTORISES:
        return False, f"Domaine non autorise ({hote}) : hors liste blanche"
    return True, ""


def _signature_binaire_valide(donnees: bytes) -> Optional[str]:
    if donnees[:4] == b"RIFF" and donnees[8:12] == b"WEBP":
        return "image/webp"
    for sig, mime in _SIGNATURES:
        if donnees.startswith(sig):
            return mime
    return None


async def _verifier_une_image(url: str) -> ResultatImage:
    ok, motif = _url_autorisee(url)
    if not ok:
        return _erreur(url, motif)

    url_courante = url
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(DELAI_EXPIRATION_REQUETE_S),
        headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"},
        trust_env=False,
    ) as client:
        for _ in range(REDIRECTIONS_MAX + 1):
            try:
                reponse = await client.get(url_courante)
            except httpx.TimeoutException:
                return _erreur(
                    url, f"Delai d'attente depasse (> {DELAI_EXPIRATION_REQUETE_S}s)"
                )
            except httpx.ConnectError as exc:
                return _erreur(url, f"Erreur reseau (connexion) : {type(exc).__name__}")
            except httpx.HTTPError as exc:
                return _erreur(url, f"Erreur HTTP client : {type(exc).__name__}")

            statut = reponse.status_code

            if 300 <= statut < 400:
                cible = reponse.headers.get("location", "")
                if not cible:
                    return ResultatImage(
                        url=url,
                        statut_http=statut,
                        date_verification=_maintenant_utc(),
                        url_finale=url_courante,
                        valide=False,
                        motif_echec=f"Redirection {statut} sans cible",
                    )
                suivante = str(httpx.URL(url_courante).join(cible))
                ok, motif = _url_autorisee(suivante)
                if not ok:
                    return ResultatImage(
                        url=url,
                        statut_http=statut,
                        date_verification=_maintenant_utc(),
                        url_finale=url_courante,
                        valide=False,
                        motif_echec=f"Redirection vers destination interdite : {motif}",
                    )
                url_courante = suivante
                await asyncio.sleep(INTERVALLE_REQ_S)
                continue

            if statut != 200:
                return ResultatImage(
                    url=url,
                    statut_http=statut,
                    date_verification=_maintenant_utc(),
                    url_finale=url_courante,
                    valide=False,
                    motif_echec=f"Statut HTTP {statut} != 200",
                )

            type_mime = (
                (reponse.headers.get("content-type") or "")
                .split(";")[0]
                .strip()
                .lower()
            )
            if not type_mime.startswith("image/"):
                return ResultatImage(
                    url=url,
                    statut_http=statut,
                    type_mime=type_mime or None,
                    date_verification=_maintenant_utc(),
                    url_finale=url_courante,
                    valide=False,
                    motif_echec=f"Content-Type non image ({type_mime or 'absent'})",
                )

            octets = b""
            async for morceau in reponse.aiter_bytes():
                octets += morceau
                if len(octets) > TAILLE_MAX_OCTETS:
                    return ResultatImage(
                        url=url,
                        statut_http=statut,
                        type_mime=type_mime,
                        taille_octets=len(octets),
                        date_verification=_maintenant_utc(),
                        url_finale=url_courante,
                        valide=False,
                        motif_echec=f"Contenu plus grand que {TAILLE_MAX_OCTETS} octets",
                    )

            if len(octets) < TAILLE_MIN_OCTETS:
                return ResultatImage(
                    url=url,
                    statut_http=statut,
                    type_mime=type_mime,
                    taille_octets=len(octets),
                    date_verification=_maintenant_utc(),
                    url_finale=url_courante,
                    valide=False,
                    motif_echec=(
                        f"Contenu trop petit ({len(octets)} octets < {TAILLE_MIN_OCTETS})"
                    ),
                )

            mime_binaire = _signature_binaire_valide(octets)
            if mime_binaire is None:
                return ResultatImage(
                    url=url,
                    statut_http=statut,
                    type_mime=type_mime,
                    taille_octets=len(octets),
                    date_verification=_maintenant_utc(),
                    url_finale=url_courante,
                    valide=False,
                    motif_echec="Donnees binaires invalides : signature d'image inconnue",
                )

            mime_final = (
                mime_binaire
                if type_mime
                not in (mime_binaire, "application/octet-stream", "binary/octet-stream")
                else type_mime
            )

            return ResultatImage(
                url=url,
                statut_http=statut,
                type_mime=mime_final,
                taille_octets=len(octets),
                date_verification=_maintenant_utc(),
                url_finale=url_courante,
                valide=True,
                motif_echec=None,
            )

    return _erreur(url, f"Trop de redirections (>{REDIRECTIONS_MAX})")


# ------------------------------------------------------------------ activite
_CACHE: dict = {}


def _cache_frais(url: str) -> Optional[ResultatImage]:
    entree = _CACHE.get(url)
    if not entree:
        return None
    horodatage, resultat = entree
    if time.time() - horodatage <= TTL_CACHE_S:
        return resultat
    _CACHE.pop(url, None)
    return None


@workflows.activity()
async def verifier_images(urls: list[str]) -> list[dict]:
    """Verifie chaque URL par un veritable HTTP GET, cadence 1 req/s, avec cache."""
    resultats: list[dict] = []
    for index, url in enumerate(urls):
        en_cache = _cache_frais(url)
        if en_cache is not None:
            resultats.append(en_cache.model_dump())
            continue

        resultat = await _verifier_une_image(url)
        _CACHE[url] = (time.time(), resultat)
        resultats.append(resultat.model_dump())

        if index < len(urls) - 1:
            await asyncio.sleep(INTERVALLE_REQ_S)
    return resultats


# ------------------------------------------------------------------ workflow
@workflows.workflow.define(
    name="shoplinous-image-validator",
    workflow_display_name="SHOPLINOUS — Validateur HTTP GET d'images produits",
    workflow_description=(
        "Effectue de veritables requetes HTTP GET sur les URL d'images produits "
        "(statut, Content-Type, taille, signature binaire), avec liste blanche de "
        "domaines, cadence 1 req/s et cache 6h. Une image non verifiee est invalide."
    ),
)
class ValidateurImagesWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, input: EntreeValidateur) -> dict:
        resultats = await verifier_images(input.urls)
        validees = sum(1 for r in resultats if r.get("valide"))
        return {
            "resultats": resultats,
            "validees": validees,
            "rejetees": len(resultats) - validees,
            "date_rapport": _maintenant_utc(),
        }

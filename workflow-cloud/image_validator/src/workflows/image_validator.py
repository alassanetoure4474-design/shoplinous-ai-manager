"""Validateur HTTP GET reel des images produits SHOPLINOUS.

Mission : confirmer par une veritable requete HTTP GET qu'une image produit
CJ (ou d'un autre fournisseur) est accessible et exploitable. Une URL HTTPS
n'est JAMAIS consideree comme validee sans preuve HTTP reelle.

Securite :
- protection SSRF renforcee : parsing URL robuste (httpx.URL), HTTPS obligatoire,
  port 443 uniquement, identifiants refuses, liste blanche stricte de domaines ;
- DNS PINNING : resolution DNS unique par le backend epingle (_BackendEpingle).
  L'IP validee (publique uniquement) est epinglee puis utilisee par la socket :
  aucune seconde resolution DNS non controlee (anti-TOCTOU / DNS rebinding).
  TLS, SNI et la verification du certificat restent geres par httpx/httpcore
  avec le NOM DE DOMAINE d'origine (connect_sni_tls_stream herite tel quel) ;
- redirections suivies une par une (max 3), chaque saut revalide completement
  (statique + epinglage DNS du nouveau hote) ;
- requete en STREAMING via client.stream("GET", ...) : chaque bloc du corps est
  controle avant de poursuivre la lecture, interruption immediate au-dela de
  20 Mo, reponse fermee proprement (redirection, erreur, limite depassee) ;
- cadence GLOBALE maximale de 1 requete/s, verrouee entre executions concurrentes ;
- FAIL-CLOSED conserve : sans IP publique validee epinglee, aucune connexion.

LIMITE DOCUMENTEE (cache) : le cache est en memoire du processus worker. Il
persiste entre les executions servies par le MEME processus (TTL 6 h) mais il
n'est PAS partage entre plusieurs processus workers (scaling horizontal) ni
persiste aux redemarrages. Aucun stockage partage (Supabase, KV) n'est
disponible sans credentials : le remplacer si un stockage partage est configure.

Lecture seule : aucun achat, aucune commande, aucun paiement, aucune ecriture.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from pydantic import BaseModel, Field

import httpx

try:  # production : SDK Mistral Workflows reellement installe
    import mistralai.workflows as workflows
except ImportError:
    if os.environ.get("SHOPLINOUS_TEST_MODE") != "1":
        raise RuntimeError("SDK mistralai-workflows absent : demarrage production refuse")
    # Tests unitaires uniquement : shim explicite, jamais en production.
    class _RepliWorkflows:
        """Shim hors-ligne pour les tests unitaires (SDK non installe).

        Les decorateurs deviennent des identites : les fonctions et classes
        restent inchangees, seule la declaration Mistral est ignoree. En
        production, le SDK reel est importe et les decorateurs s'appliquent.
        """

        class _FabriqueActivite:
            def __call__(self, fonction):
                return fonction

        class _FabriqueWorkflow:
            @staticmethod
            def define(**kwargs):
                def decorateur(cls):
                    return cls
                return decorateur

            @staticmethod
            def entrypoint(fonction):
                return fonction

        def activity(self, *args, **kwargs):
            return self._FabriqueActivite()

        workflow = _FabriqueWorkflow()

    workflows = _RepliWorkflows()


try:  # httpcore >= 1.0 (dependance d'httpx) : backend async public
    from httpcore.backends.asyncio import AsyncIOBackend as _BackendAsynchrone
except ImportError:  # httpcore < 1.0 : emplacement historique
    from httpcore._backends.asyncio import AsyncIOBackend as _BackendAsynchrone


# ---------------------------------------------------------------- constantes
DOMAINES_AUTORISES = (
    "cf.cjdropshipping.com",
    "oss-cf.cjdropshipping.com",
)

SCHEMA_OBLIGATOIRE = "https"
PORT_AUTORISE = 443
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


# ------------------------------------------------- cadence globale 1 req/s
_VERROU_CADENCE: asyncio.Lock = asyncio.Lock()
_DERNIER_ENVOI: float = 0.0


async def _attendre_tour() -> None:
    """Garantit au plus INTERVALLE_REQ_S entre deux requetes reelles.

    Le verrou est garde pendant l'attente : les executions concurrentes
    servies par le meme processus worker sont serialisees sur une cadence
    globale. Limite documentee : avec plusieurs processus workers
    (scaling), chaque processus applique sa propre cadence de 1 req/s.
    """
    global _DERNIER_ENVOI
    async with _VERROU_CADENCE:
        maintenant = time.monotonic()
        attente = _DERNIER_ENVOI + INTERVALLE_REQ_S - maintenant
        if attente > 0:
            await asyncio.sleep(attente)
        _DERNIER_ENVOI = time.monotonic()


# ------------------------------------------------------- protection SSRF
def _url_statique_valide(url: str) -> tuple[Optional[httpx.URL], str]:
    """Parsing robuste et controles statiques (schema, port, liste blanche)."""
    try:
        u = httpx.URL(url)
    except Exception:
        return None, "URL inparseable"
    if u.scheme.lower() != SCHEMA_OBLIGATOIRE:
        return None, f"Schema non autorise ({u.scheme}) : HTTPS obligatoire"
    hote = (u.host or "").lower().strip(".")
    if not hote:
        return None, "Hote absent"
    if u.username or u.password or "@" in hote:
        return None, "Identifiants embarques dans l'URL : refuses"
    if u.port is not None and u.port != PORT_AUTORISE:
        return None, f"Port non autorise ({u.port}) : {PORT_AUTORISE} uniquement"
    if hote == "localhost" or hote.endswith(".local") or hote.endswith(".internal"):
        return None, f"Hote interne non autorise ({hote})"
    if hote not in DOMAINES_AUTORISES:
        return None, f"Domaine non autorise ({hote}) : hors liste blanche"
    return u, ""


def _adresse_ip_publique(texte_ip: str) -> tuple[bool, str]:
    try:
        ip = ipaddress.ip_address(texte_ip)
    except ValueError:
        return False, f"Adresse IP invalide ({texte_ip})"
    if (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False, f"Adresse non publique refusee ({ip})"
    return True, ""


async def _resoudre_dns(hote: str) -> list[str]:
    """Resolveur DNS reel par defaut (injectable dans les tests)."""
    infos = await asyncio.getaddrinfo(hote, PORT_AUTORISE)
    return sorted({entree[4][0].split("%")[0] for entree in infos})


# ----------------------------------------------- epinglage DNS (DNS pinning)
class ErreurEpingle(Exception):
    """Echec d'epinglage DNS : aucune IP publique valide disponible."""


class _BackendEpingle(_BackendAsynchrone):
    """Backend reseau httpcore avec epinglage DNS veritable.

    - `epingler(hote)` resout UNE SEULE fois via le resolveur controle et
      exige que TOUTES les adresses renvoyees soient publiques ; la premiere
      adresse validee est memorisee (epinglee) pour ce hote.
    - `connect_tcp` se connecte TOUJOURS a l'IP epinglee : aucune seconde
      resolution DNS non controlee n'a lieu entre validation et connexion
      (protection TOCTOU / DNS rebinding).
    - TLS, SNI et la verification du certificat du NOM DE DOMAINE d'origine
      restent geres par httpcore (`connect_sni_tls_stream` herite tel quel) :
      seul le transport TCP est epingle.
    - `connecteur_brut` injectable pour les tests unitaires : capture l'IP
      cible de la socket sans creer de socket reelle.
    """

    def __init__(self, resolveur, connecteur_brut=None):
        super().__init__()
        self._resolveur = resolveur
        self._connecteur_brut = connecteur_brut
        self._ip_epinglees: dict[str, str] = {}

    async def epingler(self, hote: str) -> str:
        """Valide puis epingle l'adresse IP du hote (resolution unique)."""
        hote = (hote or "").lower().strip(".")
        if hote in self._ip_epinglees:
            return self._ip_epinglees[hote]
        try:
            ipaddress.ip_address(hote)
        except ValueError:
            pass
        else:
            ok, motif = _adresse_ip_publique(hote)
            if not ok:
                raise ErreurEpingle(motif)
            self._ip_epinglees[hote] = hote
            return hote
        try:
            adresses = await self._resolveur(hote)
        except Exception:
            raise ErreurEpingle("Resolution DNS impossible")
        if not adresses:
            raise ErreurEpingle("Aucune adresse resolue par le DNS")
        for texte_ip in adresses:
            ok, motif = _adresse_ip_publique(texte_ip)
            if not ok:
                raise ErreurEpingle(motif)
        ip_choisie = sorted(adresses)[0]
        self._ip_epinglees[hote] = ip_choisie
        return ip_choisie

    async def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        hote = (host or "").lower().strip(".")
        ip_epinglee = self._ip_epinglees.get(hote)
        if ip_epinglee is None:
            # Fail-closed : aucune connexion sans epinglage prealable
            # (revalidation complete, jamais de resolution aveugle).
            ip_epinglee = await self.epingler(hote)
        if self._connecteur_brut is not None:
            return await self._connecteur_brut(
                ip_epinglee, port, timeout, local_address, socket_options
            )
        return await super().connect_tcp(
            ip_epinglee, port,
            timeout=timeout, local_address=local_address,
            socket_options=socket_options,
        )


def _construire_transport_production(epingle: _BackendEpingle) -> httpx.AsyncBaseTransport:
    """Transport HTTPX reel : IP epinglee + TLS/SNI/certificat du domaine d'origine.

    `verify=True` (defaut) conserve la verification complete du certificat,
    et httpcore utilise le nom de domaine d'origine pour le SNI : seul le
    transport TCP est remplace par le backend epingle.
    """
    return httpx.AsyncHTTPTransport(
        verify=True,
        trust_env=False,
        network_backend=epingle,
    )


# --------------------------------------------------------------- signature
def _signature_binaire_valide(donnees: bytes) -> Optional[str]:
    if donnees[:4] == b"RIFF" and donnees[8:12] == b"WEBP":
        return "image/webp"
    for sig, mime in _SIGNATURES:
        if donnees.startswith(sig):
            return mime
    return None


# ------------------------------------------------------------- verification
async def _verifier_une_image(
    url: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    resolveur: Optional[Callable[[str], Awaitable[list[str]]]] = None,
) -> ResultatImage:
    """Verifie une image par un HTTP GET en STREAMING reellement emis.

    DNS PINNING : le backend epingle resout et valide l'IP UNE SEULE fois,
    puis la socket se connecte exactement a cette IP validee — aucune seconde
    resolution DNS non controlee. TLS/SNI/certificat : nom de domaine d'origine.

    `client.stream("GET", ...)` : la reponse n'est jamais chargee entiere en
    memoire. Chaque bloc du corps est controle avant de poursuivre la
    lecture ; au-dela de TAILLE_MAX_OCTETS la lecture est interrompue
    immediatement et la reponse fermee proprement (`aclose` + sortie du
    gestionnaire de contexte). Idem en cas de redirection, d'erreur ou de
    statut non 200 : le contexte ferme la reponse.

    `transport` et `resolveur` sont injectables pour les tests unitaires.
    """
    if resolveur is None:
        resolveur = _resoudre_dns

    u, motif = _url_statique_valide(url)
    if u is None:
        return _erreur(url, motif)

    # Resolution unique : epinglage DNS du hote d'origine (IP publiques
    # uniquement). FAIL-CLOSED : sans IP validee epinglee, aucune connexion.
    epingle = _BackendEpingle(resolveur)
    try:
        await epingle.epingler((u.host or "").lower().strip("."))
    except ErreurEpingle as exc:
        return _erreur(url, str(exc))

    if transport is None:
        # PRODUCTION : transport reseau epingle (TLS/SNI/certificat d'origine).
        transport = _construire_transport_production(epingle)

    url_courante = u
    arguments_client: dict = {
        "follow_redirects": False,
        "timeout": httpx.Timeout(DELAI_EXPIRATION_REQUETE_S),
        "headers": {"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"},
        "trust_env": False,
        "transport": transport,
    }

    async with httpx.AsyncClient(**arguments_client) as client:
        for _ in range(REDIRECTIONS_MAX + 1):
            await _attendre_tour()
            octets = b""
            trop_grand = False
            try:
                # Requete en STREAMING : le corps n'est lu que bloc par bloc.
                async with client.stream("GET", url_courante) as reponse:
                    statut = reponse.status_code

                    if 300 <= statut < 400:
                        cible = reponse.headers.get("location", "")
                        if not cible:
                            # sortie du contexte : reponse fermee proprement
                            return ResultatImage(
                                url=url, statut_http=statut,
                                date_verification=_maintenant_utc(),
                                url_finale=str(url_courante), valide=False,
                                motif_echec=f"Redirection {statut} sans cible",
                            )
                        suivante = httpx.URL(str(url_courante)).join(cible)
                        u2, motif = _url_statique_valide(str(suivante))
                        if u2 is None:
                            return ResultatImage(
                                url=url, statut_http=statut,
                                date_verification=_maintenant_utc(),
                                url_finale=str(url_courante), valide=False,
                                motif_echec=f"Redirection vers destination interdite : {motif}",
                            )
                        # Revalidation REELLE du saut : epinglage DNS du nouveau
                        # hote (IP publiques uniquement) avant toute connexion.
                        try:
                            await epingle.epingler(
                                (u2.host or "").lower().strip(".")
                            )
                        except ErreurEpingle as exc:
                            return ResultatImage(
                                url=url, statut_http=statut,
                                date_verification=_maintenant_utc(),
                                url_finale=str(url_courante), valide=False,
                                motif_echec=f"Redirection vers destination interdite : {exc}",
                            )
                        url_courante = u2
                        continue  # fermeture propre via le gestionnaire de contexte

                    if statut != 200:
                        # sortie du contexte : reponse fermee proprement
                        return ResultatImage(
                            url=url, statut_http=statut,
                            date_verification=_maintenant_utc(),
                            url_finale=str(url_courante), valide=False,
                            motif_echec=f"Statut HTTP {statut} != 200",
                        )

                    type_mime = (
                        (reponse.headers.get("content-type") or "")
                        .split(";")[0]
                        .strip()
                        .lower()
                    )
                    if not type_mime.startswith("image/"):
                        # sortie du contexte : reponse fermee proprement
                        return ResultatImage(
                            url=url, statut_http=statut, type_mime=type_mime or None,
                            date_verification=_maintenant_utc(),
                            url_finale=str(url_courante), valide=False,
                            motif_echec=f"Content-Type non image ({type_mime or 'absent'})",
                        )

                    # Chaque bloc est controle AVANT de poursuivre la lecture.
                    async for morceau in reponse.aiter_bytes():
                        octets += morceau
                        if len(octets) > TAILLE_MAX_OCTETS:
                            trop_grand = True
                            # Fermeture immediate : la lecture s'arrete net,
                            # le reste du corps n'est PAS telecharge.
                            await reponse.aclose()
                            break
            except ErreurEpingle as exc:
                return _erreur(url, f"Connexion bloquee (epinglage DNS) : {exc}")
            except httpx.TimeoutException:
                return _erreur(
                    url,
                    f"Delai d'attente depasse (> {DELAI_EXPIRATION_REQUETE_S}s)",
                )
            except httpx.ConnectError as exc:
                return _erreur(url, f"Erreur reseau (connexion) : {type(exc).__name__}")
            except httpx.HTTPError as exc:
                return _erreur(url, f"Erreur HTTP client : {type(exc).__name__}")

            if trop_grand:
                return ResultatImage(
                    url=url, statut_http=statut, type_mime=type_mime,
                    taille_octets=len(octets),
                    date_verification=_maintenant_utc(),
                    url_finale=str(url_courante), valide=False,
                    motif_echec=f"Contenu plus grand que {TAILLE_MAX_OCTETS} octets",
                )

            if len(octets) < TAILLE_MIN_OCTETS:
                return ResultatImage(
                    url=url, statut_http=statut, type_mime=type_mime,
                    taille_octets=len(octets),
                    date_verification=_maintenant_utc(),
                    url_finale=str(url_courante), valide=False,
                    motif_echec=(
                        f"Contenu trop petit ({len(octets)} octets < {TAILLE_MIN_OCTETS})"
                    ),
                )

            mime_binaire = _signature_binaire_valide(octets)
            if mime_binaire is None:
                return ResultatImage(
                    url=url, statut_http=statut, type_mime=type_mime,
                    taille_octets=len(octets),
                    date_verification=_maintenant_utc(),
                    url_finale=str(url_courante), valide=False,
                    motif_echec="Donnees binaires invalides : signature d'image inconnue",
                )

            mime_final = (
                mime_binaire
                if type_mime
                not in (mime_binaire, "application/octet-stream", "binary/octet-stream")
                else type_mime
            )

            return ResultatImage(
                url=url, statut_http=statut, type_mime=mime_final,
                taille_octets=len(octets),
                date_verification=_maintenant_utc(),
                url_finale=str(url_courante), valide=True, motif_echec=None,
            )

    return _erreur(url, f"Trop de redirections (>{REDIRECTIONS_MAX})")


# ------------------------------------------------------------------ activite
# LIMITE DOCUMENTEE : cache en memoire du processus worker (TTL 6 h).
# Non partage entre plusieurs processus workers, non persiste aux redemarrages.
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
async def verifier_images(urls: list[str]) -> dict:
    """Verifie chaque URL par un veritable HTTP GET, cadence globale 1 req/s.

    Les horodatages sont calcules dans l'activite (jamais dans le workflow),
    pour respecter la contrainte de determinisme du SDK.
    """
    resultats: list[dict] = []
    for url in urls:
        en_cache = _cache_frais(url)
        if en_cache is not None:
            resultats.append(en_cache.model_dump())
            continue

        resultat = await _verifier_une_image(url)
        _CACHE[url] = (time.time(), resultat)
        resultats.append(resultat.model_dump())

    validees = sum(1 for r in resultats if r.get("valide"))
    return {
        "resultats": resultats,
        "validees": validees,
        "rejetees": len(resultats) - validees,
        "date_rapport": _maintenant_utc(),
    }


# ------------------------------------------------------------------ workflow
@workflows.workflow.define(
    name="shoplinous-image-validator",
    workflow_display_name="SHOPLINOUS — Validateur HTTP GET d'images produits",
    workflow_description=(
        "Effectue de veritables requetes HTTP GET sur les URL d'images produits "
        "(statut, Content-Type, taille, signature binaire), avec liste blanche "
        "de domaines, DNS pinning, protection SSRF, cadence globale 1 req/s et "
        "cache 6h. Une image non verifiee est invalide."
    ),
)
class ValidateurImagesWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, input: EntreeValidateur) -> dict:
        # Aucune horloge ni aleatoire ici : le rapport horodate vient de
        # l'activite, conformement a la regle de determinisme du SDK.
        return await verifier_images(input.urls)

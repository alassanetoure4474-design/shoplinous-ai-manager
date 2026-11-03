"""Tests unitaires du validateur HTTP GET d'images SHOPLINOUS (v3).

Couverture :
- validation statique des URL (schema, port, liste blanche, identifiants) ;
- protection SSRF dynamique : IP privees/locales refusees, DNS echoue ;
- streaming REEL (client.stream) : chaque bloc est controle, interruption
  immediate au-dela de la taille max, corps NON telecharge entierement ;
- redirections autorisees (meme domaine), interdites (hors liste), en boucle ;
- MIME incoherent (Content-Type != signature binaire) et Content-Type non image ;
- cadence globale 1 req/s verrouee entre executions concurrentes ;
- cache TTL 6 h (entrees fraiches servies, entrees expirees evincees).

Aucun reseau reel : httpx.MockTransport + resolveur DNS factice injectes.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["SHOPLINOUS_TEST_MODE"] = "1"

import src.workflows.image_validator as iv  # noqa: E402
from src.workflows.image_validator import (  # noqa: E402
    _adresse_ip_publique,
    _cache_frais,
    _signature_binaire_valide,
    _url_statique_valide,
)

IP_PUBLIQUE = "104.18.7.42"
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 2000  # > 1024 octets, signature JPEG


@pytest.fixture(autouse=True)
def _cadence_rapide(monkeypatch):
    """Accelere la cadence et reinitialise l'etat global entre les tests."""
    monkeypatch.setattr(iv, "INTERVALLE_REQ_S", 0.01)
    monkeypatch.setattr(iv, "_DERNIER_ENVOI", 0.0)
    iv._CACHE.clear()
    yield


async def _resoudre_publique(hote: str) -> list[str]:
    return [IP_PUBLIQUE]


def _transport(handler):
    return httpx.MockTransport(handler)


def _reponse_image(contenu=JPG, mime="image/jpeg", statut=200):
    return httpx.Response(statut, headers={"content-type": mime}, content=contenu)


class FluxServeurCompteur(httpx.AsyncByteStream):
    """Flux serveur factice qui COMPTE les blocs reellement consommes.

    Prouve que le validateur n'aspire pas le corps entier : si la lecture est
    interrompue (limite depassee), le compteur s'arrete avant la fin.
    """

    def __init__(self, morceaux):
        self.morceaux = morceaux
        self.blocs_consommes = 0

    async def __aiter__(self):
        for morceau in self.morceaux:
            self.blocs_consommes += 1
            yield morceau


# ------------------------------------------------------- validation statique
def test_schema_https_obligatoire():
    u, motif = _url_statique_valide("http://cf.cjdropshipping.com/img.jpg")
    assert u is None and "HTTPS" in motif


def test_domaine_non_autorise():
    u, motif = _url_statique_valide("https://evil.example.com/img.jpg")
    assert u is None and "non autorise" in motif


def test_hote_interne_refuse():
    u, motif = _url_statique_valide("https://localhost/img.jpg")
    assert u is None and "interne" in motif


def test_identifiants_refuses():
    u, _ = _url_statique_valide("https://user:pass@cf.cjdropshipping.com/img.jpg")
    assert u is None


def test_port_non_autorise():
    u, motif = _url_statique_valide("https://cf.cjdropshipping.com:8443/img.jpg")
    assert u is None and "Port" in motif


def test_url_cj_acceptee():
    u, motif = _url_statique_valide("https://cf.cjdropshipping.com/quick/product/a.jpg")
    assert u is not None, motif


def test_signatures_binaires():
    assert _signature_binaire_valide(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert _signature_binaire_valide(b"\x89PNG\r\n\x1a\n") == "image/png"
    assert _signature_binaire_valide(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert _signature_binaire_valide(b"<html>pas une image</html>") is None


def test_ip_privee_refusee():
    ok, motif = _adresse_ip_publique("192.168.1.10")
    assert not ok and "non publique" in motif
    ok, _ = _adresse_ip_publique("127.0.0.1")
    assert not ok
    ok, _ = _adresse_ip_publique("169.254.169.254")
    assert not ok
    ok, _ = _adresse_ip_publique(IP_PUBLIQUE)
    assert ok


# ------------------------------------------------- SSRF dynamique et reseau
def test_ssrf_ip_privee_resolue():
    async def resoud_prive(hote):
        return ["192.168.1.10"]

    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/img.jpg",
            transport=_transport(lambda req: _reponse_image()),
            resolveur=resoud_prive,
        )

    resultat = asyncio.run(go())
    assert not resultat.valide and "non publique" in resultat.motif_echec


def test_dns_echoue():
    async def resoud_echec(hote):
        raise OSError("DNS")

    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/img.jpg", resolveur=resoud_echec
        )

    resultat = asyncio.run(go())
    assert not resultat.valide and "DNS" in resultat.motif_echec


# ----------------------------------------------------------- image valide
def test_image_valide():
    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/img.jpg",
            transport=_transport(lambda req: _reponse_image()),
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert resultat.valide
    assert resultat.statut_http == 200
    assert resultat.type_mime == "image/jpeg"
    assert resultat.taille_octets == len(JPG)
    assert resultat.url_finale.endswith("img.jpg")
    assert resultat.date_verification is not None


def test_content_type_non_image_rejete():
    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/img.jpg",
            transport=_transport(
                lambda req: httpx.Response(
                    200, headers={"content-type": "text/html"}, content=b"<html></html>"
                )
            ),
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert not resultat.valide and "Content-Type" in resultat.motif_echec


def test_mime_incoherent_binaire_prioritaire():
    async def go():
        # Content-Type annonce PNG, corps reellement JPEG
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/img.jpg",
            transport=_transport(lambda req: _reponse_image(mime="image/png")),
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert resultat.valide and resultat.type_mime == "image/jpeg"


def test_contenu_trop_petit_rejete():
    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/img.jpg",
            transport=_transport(
                lambda req: _reponse_image(contenu=b"\xff\xd8\xff")
            ),
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert not resultat.valide and "trop petit" in resultat.motif_echec


def test_statut_erreur_rejete():
    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/img.jpg",
            transport=_transport(lambda req: _reponse_image(statut=404)),
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert not resultat.valide and "404" in resultat.motif_echec


# --------------------------------- streaming : corps non telecharge entier
def test_corps_non_telecharge_entierement_hors_limite(monkeypatch):
    """Preuve : quand la limite est depassee, le flux serveur n'est PAS
    consomme jusqu'au bout — seuls les premiers blocs sont lus."""
    monkeypatch.setattr(iv, "TAILLE_MAX_OCTETS", 10 * 1024)
    morceaux = [b"\xff\xd8\xff\xe0" + b"\x42" * 1020]
    morceaux += [b"\x42" * 1024 for _ in range(400)]  # ~401 Ko au total
    flux = FluxServeurCompteur(morceaux)

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "image/jpeg"}, stream=flux
        )

    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/gros.jpg",
            transport=_transport(handler),
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert not resultat.valide and "plus grand" in resultat.motif_echec
    # Preuve centrale : le serveur n'a servi qu'une petite partie du corps.
    assert flux.blocs_consommes < len(morceaux), (
        f"Le corps a ete integralement lu ({flux.blocs_consommes} blocs / "
        f"{len(morceaux)}) : le streaming n'interrompt pas la lecture"
    )
    assert resultat.taille_octets < sum(len(m) for m in morceaux)


def test_streaming_interruption_au_dela_taille_max(monkeypatch):
    """Le corps est servi bloc par bloc : la lecture s'arrete avant la fin."""
    monkeypatch.setattr(iv, "TAILLE_MAX_OCTETS", 10 * 1024)
    morceaux = [b"\xff\xd8\xff\xe0" + b"\x42" * 1020]
    morceaux += [b"\x42" * 1024 for _ in range(200)]  # ~201 Ko
    flux = FluxServeurCompteur(morceaux)

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "image/jpeg"}, stream=flux
        )

    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/gros.jpg",
            transport=_transport(handler),
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert not resultat.valide and "plus grand" in resultat.motif_echec
    assert resultat.taille_octets < sum(len(m) for m in morceaux)
    assert flux.blocs_consommes < len(morceaux)


def test_streaming_corps_petit_lu_entierement():
    """Un corps sous la limite est lu entierement (aucune coupure prematuree)."""
    flux = FluxServeurCompteur([JPG])

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "image/jpeg"}, stream=flux
        )

    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/petit.jpg",
            transport=_transport(handler),
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert resultat.valide
    assert flux.blocs_consommes == 1
    assert resultat.taille_octets == len(JPG)


# ------------------------------------------------------- redirections
def test_redirection_meme_domaine_autorisee():
    def handler(request):
        if request.url.path == "/a.jpg":
            return httpx.Response(
                302, headers={"location": "https://cf.cjdropshipping.com/b.jpg"}
            )
        return _reponse_image()

    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/a.jpg",
            transport=_transport(handler),
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert resultat.valide
    assert resultat.url_finale.endswith("b.jpg")


def test_redirection_vers_domaine_interdit():
    def handler(request):
        return httpx.Response(
            302, headers={"location": "https://evil.example.com/pirate.jpg"}
        )

    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/a.jpg",
            transport=_transport(handler),
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert not resultat.valide and "destination interdite" in resultat.motif_echec


def test_trop_de_redirections():
    def handler(request):
        return httpx.Response(
            302, headers={"location": "https://cf.cjdropshipping.com/a.jpg"}
        )

    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/a.jpg",
            transport=_transport(handler),
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert not resultat.valide and "Trop de redirections" in resultat.motif_echec


# --------------------------------------------- cadence globale concurrente
def test_cadence_globale_concurrente(monkeypatch):
    # 3 executions concurrentes : duree totale >= (3 - 1) * intervalle.
    monkeypatch.setattr(iv, "INTERVALLE_REQ_S", 0.05)
    monkeypatch.setattr(iv, "_DERNIER_ENVOI", 0.0)

    urls = [
        "https://cf.cjdropshipping.com/i1.jpg",
        "https://cf.cjdropshipping.com/i2.jpg",
        "https://cf.cjdropshipping.com/i3.jpg",
    ]

    async def go():
        debut = time.monotonic()
        resultats = await asyncio.gather(
            *(
                iv._verifier_une_image(
                    url,
                    transport=_transport(lambda req: _reponse_image()),
                    resolveur=_resoudre_publique,
                )
                for url in urls
            )
        )
        return time.monotonic() - debut, resultats

    duree, resultats = asyncio.run(go())
    assert all(r.valide for r in resultats), [r.motif_echec for r in resultats]
    assert duree >= 2 * 0.05 - 0.01, f"Cadence globale non respectee : {duree}s"


# ------------------------------------------------------------------ cache
def test_cache_ttl():
    url = "https://cf.cjdropshipping.com/cache.jpg"
    resultat = iv.ResultatImage(url=url, valide=True)
    assert _cache_frais(url) is None  # vide

    iv._CACHE[url] = (time.time(), resultat)
    frais = _cache_frais(url)
    assert frais is not None and frais.valide

    # Entree expiree (TTL depasse) : evincee.
    iv._CACHE[url] = (time.time() - (iv.TTL_CACHE_S + 1), resultat)
    assert _cache_frais(url) is None
    assert url not in iv._CACHE


def test_rapport_vide_coherent():
    async def go():
        return await iv.verifier_images([])

    rapport = asyncio.run(go())
    assert rapport["validees"] == 0
    assert rapport["rejetees"] == 0
    assert rapport["resultats"] == []
    assert rapport["date_rapport"] is not None


def test_production_sans_transport_reseau_est_bloquee():
    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/img.jpg",
            resolveur=_resoudre_publique,
        )

    resultat = asyncio.run(go())
    assert not resultat.valide
    assert "DNS pinning" in resultat.motif_echec

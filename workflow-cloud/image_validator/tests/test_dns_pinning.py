"""Tests d'epinglage DNS (DNS pinning) — anti-SSRF / anti-rebinding.

Prouve que :
1. la socket se connecte EXACTEMENT a l'IP publique validee par epinglage ;
2. une resolution DNS MODIFIEE apres validation (DNS rebinding) ne permet
   AUCUNE connexion vers une IP interdite : aucune seconde resolution n'a
   lieu, le resolveur n'est appele qu'une seule fois ;
3. une IP privee/locale/reservee est refusee AVANT toute tentative de
   connexion (fail-closed) ;
4. le transport HTTPX de production installe REELLEMENT le backend epingle
   dans le pool httpcore (integration, pas seulement test isole) ;
5. en production reelle (marqueur reseau_reel, CI) : TLS + SNI + verification
   du certificat fonctionnent sur l'IP epinglee pour le domaine d'origine.
"""

import asyncio
import ipaddress
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SHOPLINOUS_TEST_MODE", "1")

import src.workflows.image_validator as iv  # noqa: E402

IP_PUBLIQUE = "104.18.7.42"
IP_PRIVEE = "192.168.1.10"


class ConnecteurFactice:
    """Capture l'IP cible reelle de la socket sans creer de socket reelle."""

    def __init__(self):
        self.ip_connectees = []

    async def __call__(self, ip, port, timeout, local_address, socket_options):
        self.ip_connectees.append(ip)
        return None  # jamais utilise : on n'envoie aucune requete ici


def test_socket_connecte_exactement_a_ip_validee():
    """L'IP utilisee par la socket est l'IP publique epinglee, pas autre chose."""
    connecteur = ConnecteurFactice()

    async def resoud(hote):
        return [IP_PUBLIQUE]

    async def go():
        backend = iv._BackendEpingle(resoud, connecteur_brut=connecteur)
        ip = await backend.epingler("cf.cjdropshipping.com")
        await backend.connect_tcp("cf.cjdropshipping.com", 443)
        return ip

    ip_epinglee = asyncio.run(go())
    assert ip_epinglee == IP_PUBLIQUE
    assert connecteur.ip_connectees == [IP_PUBLIQUE]


def test_anti_dns_rebinding_resolution_modifiee_apres_validation():
    """DNS rebinding : le resolveur change d'avis APRES l'epinglage (reponse
    suivante : IP privee). La socket doit rester sur l'IP publique validee et
    le resolveur ne doit JAMAIS etre rappele (aucune seconde resolution)."""
    appels = {"n": 0}

    async def resolveur_trompeur(hote):
        appels["n"] += 1
        if appels["n"] == 1:
            return [IP_PUBLIQUE]  # validation initiale : IP publique
        return [IP_PRIVEE]  # "rebinding" : reponse ulterieure interdite

    connecteur = ConnecteurFactice()

    async def go():
        backend = iv._BackendEpingle(resolveur_trompeur, connecteur_brut=connecteur)
        ip = await backend.epingler("cf.cjdropshipping.com")
        # Deux connexions successives (ex. redirection, reessai)
        await backend.connect_tcp("cf.cjdropshipping.com", 443)
        await backend.connect_tcp("cf.cjdropshipping.com", 443)
        return ip

    ip_epinglee = asyncio.run(go())
    assert appels["n"] == 1, "Une seconde resolution DNS a eu lieu : TOCTOU possible"
    assert ip_epinglee == IP_PUBLIQUE
    assert connecteur.ip_connectees == [IP_PUBLIQUE, IP_PUBLIQUE], (
        "La socket a ete dirigee ailleurs que sur l'IP validee"
    )


def test_ip_privee_refusee_avant_toute_connexion():
    """Fail-closed : IP privee resolue => aucune tentative de connexion."""
    connecteur = ConnecteurFactice()

    async def resoud_prive(hote):
        return [IP_PRIVEE]

    async def go():
        backend = iv._BackendEpingle(resoud_prive, connecteur_brut=connecteur)
        await backend.epingler("cf.cjdropshipping.com")

    with pytest.raises(iv.ErreurEpingle) as excinfo:
        asyncio.run(go())
    assert "non publique" in str(excinfo.value)
    assert connecteur.ip_connectees == []


def test_connect_tcp_hote_non_epingle_fail_closed():
    """Un hote non epingle ne peut PAS contourner : connect_tcp re-epingle
    (validation complete) et refuse l'IP privee sans se connecter."""
    connecteur = ConnecteurFactice()

    async def resoud_prive(hote):
        return ["10.0.0.5"]

    async def go():
        backend = iv._BackendEpingle(resoud_prive, connecteur_brut=connecteur)
        await backend.connect_tcp("cf.cjdropshipping.com", 443)

    with pytest.raises(iv.ErreurEpingle) as excinfo:
        asyncio.run(go())
    assert "non publique" in str(excinfo.value)
    assert connecteur.ip_connectees == []


def test_ip_litterale_privee_refusee():
    """Une URL IP litterale privee serait deja bloquee par la liste blanche ;
    le backend reste de ceinture et bretelles : IP litterale refusee aussi."""
    connecteur = ConnecteurFactice()

    async def go():
        backend = iv._BackendEpingle(iv._resoudre_dns, connecteur_brut=connecteur)
        await backend.connect_tcp("127.0.0.1", 443)

    with pytest.raises(iv.ErreurEpingle) as excinfo:
        asyncio.run(go())
    assert "non publique" in str(excinfo.value)
    assert connecteur.ip_connectees == []


def test_epingle_dns_echoue():
    connecteur = ConnecteurFactice()

    async def resoud_echec(hote):
        raise OSError("DNS")

    async def go():
        backend = iv._BackendEpingle(resoud_echec, connecteur_brut=connecteur)
        await backend.epingler("cf.cjdropshipping.com")

    with pytest.raises(iv.ErreurEpingle) as excinfo:
        asyncio.run(go())
    assert "Resolution DNS impossible" in str(excinfo.value)
    assert connecteur.ip_connectees == []


def test_redirection_reepingle_nouveau_hote(monkeypatch):
    """Chaque saut de redirection REVALIDE le nouveau hote par epinglage :
    une redirection vers un hote resolvant vers une IP privee est bloquee,
    meme si le domaine est dans la liste blanche."""
    async def resoud_selon_hote(hote):
        if hote == "oss-cf.cjdropshipping.com":
            return [IP_PRIVEE]  # rebinding sur le domaine de redirection
        return [IP_PUBLIQUE]

    def handler(request):
        if request.url.path == "/a.jpg":
            return httpx.Response(
                302,
                headers={"location": "https://oss-cf.cjdropshipping.com/b.jpg"},
            )
        return httpx.Response(
            200, headers={"content-type": "image/jpeg"},
            content=b"\xff\xd8\xff\xe0" + b"\x00" * 2000,
        )

    async def go():
        return await iv._verifier_une_image(
            "https://cf.cjdropshipping.com/a.jpg",
            transport=httpx.MockTransport(handler),
            resolveur=resoud_selon_hote,
        )

    resultat = asyncio.run(go())
    assert not resultat.valide
    assert "destination interdite" in resultat.motif_echec
    assert IP_PRIVEE in resultat.motif_echec


def test_transport_httpx_installe_backend_epingle_dans_pool():
    """Le transport HTTPX de production doit reellement utiliser le backend
    epingle dans son pool, pas seulement tester le backend isole."""
    backend = iv._BackendEpingle(iv._resoudre_dns)
    transport = iv._construire_transport_production(backend)
    try:
        pool = getattr(transport, "_pool", None)
        assert pool is not None
        assert getattr(pool, "_network_backend", None) is backend
    finally:
        asyncio.run(transport.aclose())


# ---------------------------- preuve en reseau REEL (CI uniquement)
@pytest.mark.reseau_reel
@pytest.mark.skipif(
    os.environ.get("TEST_RESEAU_REEL") != "1",
    reason="test reseau reel : activer avec TEST_RESEAU_REEL=1 (CI)",
)
def test_reel_epingle_cj_tls_sni_certificat():
    """Preuve de bout en bout vers CJ : resolution+validation+epinglage,
    socket sur l'IP epinglee (verifiee cote backend), TLS/SNI/certificat
    verifies pour le domaine d'origine. Toute reponse HTTP valide (statut
    quelconque) prouve que la chaine TLS a reussi sur l'IP epinglee.

    3 essais (DNS ou reseau transitoire) ; en cas d'echec, l'exception
    EXACTE (type + message + traceback) est publiee en annotation publique
    (::error::) car les logs CI exigent une connexion.
    """
    import time as _time
    import traceback as _tb

    async def go():
        epingle = iv._BackendEpingle(iv._resoudre_dns)
        transport = iv._construire_transport_production(epingle)
        async with httpx.AsyncClient(
            transport=transport, trust_env=False, timeout=20.0
        ) as client:
            reponse = await client.get("https://cf.cjdropshipping.com/")
        return epingle, reponse

    derniere = None
    for essai in range(3):
        try:
            epingle, reponse = asyncio.run(go())
            ip_epinglee = epingle._ip_epinglees.get("cf.cjdropshipping.com")
            assert ip_epinglee, "Aucune IP epinglee"
            assert ipaddress.ip_address(ip_epinglee).is_global, (
                f"IP epinglee non publique : {ip_epinglee}"
            )
            assert isinstance(reponse.status_code, int) and reponse.status_code > 0
            print(
                f"DNS PINNING REEL : IP epinglee={ip_epinglee} "
                f"statut HTTP={reponse.status_code} TLS+SNI+certificat OK"
            )
            return
        except Exception as exc:
            derniere = exc
            print(
                f"::error::SMOKE_REEL essai {essai + 1}/3 echoue : "
                f"{type(exc).__name__} : {exc}"
            )
            _tb.print_exc()
            _time.sleep(3)
    raise AssertionError(
        f"Preuve reseau reel CJ impossible apres 3 essais : "
        f"{type(derniere).__name__} : {derniere}"
    )

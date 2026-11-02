"""Tests pytest SHOPLINOUS ai_manager (FreeLLMAPI multi-IA).

Couverture :
- succes fournisseur par defaut + normalisation de la reponse ;
- bascule AUTOMATIQUE sur 429 (quota), 5xx, timeout reseau ;
- tous fournisseurs indisponibles -> AiIndisponible ;
- cache (aucun 2e appel reseau), compteur cache_hits ;
- journalisation SANS AUCUNE cle API (redaction verifiee) ;
- suivi des quotas par fournisseur (bascules, erreurs, restant) ;
- modeles payants REFUSES (ValueError, aucun appel emise) ;
- cle ou base absente -> refus immediat, aucun appel ;
- ordre des fournisseurs via AI_PROVIDER_ORDER ;
- SEPARATION DETERMINISTE : ai_manager n'importe aucun module metier
  (daily, pricing, freight) et ne declenche aucune ecriture.

Tous les appels reseau sont MOQUES (httpx.MockTransport) : aucun appel
reel a FreeLLMAPI, aucune cle reelle.
"""
import asyncio
import inspect
import json

import httpx
import os
import pytest
import sys

# Bootstrap robuste : le dossier du test est garanti sur sys.path
# quelle que soit la politique d import de la version de pytest.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_manager as ai


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


OK = {"choices": [{"message": {"content": "Analyse IA"}}]}
MESSAGES = [{"role": "user", "content": "Resume ce texte."}]


@pytest.fixture(autouse=True)
def _nettoyage():
    ai.reinitialiser_etat()
    yield
    ai.reinitialiser_etat()


def _patch(monkeypatch, handler, cle="cle-test-123"):
    """Mock httpx + env : retourne la liste des appels emis."""
    appels = []

    def h(request):
        appels.append((request.method, request.url.path,
                       request.headers.get("authorization"),
                       request.url.host))
        return handler(request)

    class Patched(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(h)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    monkeypatch.setenv("FREE_LLM_API_KEY", cle)
    monkeypatch.setenv("FREE_LLM_API_BASE", "https://freellm.test/v1")
    return appels


class TestAppels:

    def test_succes_fournisseur_par_defaut(self, monkeypatch):
        appels = _patch(monkeypatch, lambda r: httpx.Response(200, json=OK))
        res = run(ai.appeler_ia(MESSAGES))
        assert res["fournisseur"] == "mistral"
        assert res["contenu"] == "Analyse IA"
        assert res["depuis_cache"] is False
        assert len(appels) == 1
        assert appels[0][0] == "POST"
        assert appels[0][1] == "/v1/chat/completions"
        assert appels[0][2] == "Bearer cle-test-123"

    def test_messages_invalides_refuses(self, monkeypatch):
        appels = _patch(monkeypatch, lambda r: httpx.Response(200, json=OK))
        with pytest.raises(ValueError):
            run(ai.appeler_ia([]))
        assert appels == []

    def test_cle_absente_aucun_appel(self, monkeypatch):
        appels = _patch(monkeypatch, lambda r: httpx.Response(200, json=OK))
        monkeypatch.delenv("FREE_LLM_API_KEY")
        with pytest.raises(ValueError):
            run(ai.appeler_ia(MESSAGES))
        assert appels == []

    def test_base_absente_aucun_appel(self, monkeypatch):
        appels = _patch(monkeypatch, lambda r: httpx.Response(200, json=OK))
        monkeypatch.delenv("FREE_LLM_API_BASE")
        with pytest.raises(ValueError):
            run(ai.appeler_ia(MESSAGES))
        assert appels == []


class TestBasculeAutomatique:

    def test_bascule_sur_429(self, monkeypatch):
        def handler(request):
            corps = json.loads(request.content)
            if corps["model"].startswith("mistral"):
                return httpx.Response(429, json={"error": "quota"})
            return httpx.Response(200, json=OK)
        appels = _patch(monkeypatch, handler)
        res = run(ai.appeler_ia(MESSAGES))
        assert res["fournisseur"] == "gemini"
        assert len(appels) == 2
        q = ai.quotas()
        assert q["mistral"]["bascules"] == 1
        assert q["gemini"]["requetes"] == 1
        evenements = [e["evenement"] for e in ai.journal()]
        assert "quota_depasse" in evenements and "succes" in evenements

    def test_bascule_sur_5xx(self, monkeypatch):
        def handler(request):
            corps = json.loads(request.content)
            if corps["model"].startswith("mistral"):
                return httpx.Response(503, json={})
            return httpx.Response(200, json=OK)
        appels = _patch(monkeypatch, handler)
        res = run(ai.appeler_ia(MESSAGES))
        assert res["fournisseur"] == "gemini"
        assert ai.quotas()["mistral"]["bascules"] == 1

    def test_bascule_sur_timeout(self, monkeypatch):
        def handler(request):
            corps = json.loads(request.content)
            if corps["model"].startswith("mistral"):
                raise httpx.ReadTimeout("delai depasse")
            return httpx.Response(200, json=OK)
        appels = _patch(monkeypatch, handler)
        res = run(ai.appeler_ia(MESSAGES))
        assert res["fournisseur"] == "gemini"

    def test_bascule_sur_reponse_invalide(self, monkeypatch):
        def handler(request):
            corps = json.loads(request.content)
            if corps["model"].startswith("mistral"):
                return httpx.Response(200, json={"foo": "bar"})
            return httpx.Response(200, json=OK)
        _patch(monkeypatch, handler)
        res = run(ai.appeler_ia(MESSAGES))
        assert res["fournisseur"] == "gemini"
        assert ai.quotas()["mistral"]["erreurs"] == 1

    def test_tous_indisponibles(self, monkeypatch):
        _patch(monkeypatch, lambda r: httpx.Response(429, json={}))
        with pytest.raises(ai.AiIndisponible):
            run(ai.appeler_ia(MESSAGES))
        assert len(ai.quotas()) == 3

    def test_ordre_via_env(self, monkeypatch):
        _patch(monkeypatch, lambda r: httpx.Response(200, json=OK),
               cle="cle-2")
        monkeypatch.setenv("AI_PROVIDER_ORDER", "groq,mistral")
        res = run(ai.appeler_ia(MESSAGES))
        assert res["fournisseur"] == "groq"

    def test_fournisseur_inconnu_ignore(self, monkeypatch):
        _patch(monkeypatch, lambda r: httpx.Response(200, json=OK))
        res = run(ai.appeler_ia(MESSAGES, fournisseurs=["openai", "mistral"]))
        assert res["fournisseur"] == "mistral"


class TestCache:

    def test_cache_evite_le_second_appel(self, monkeypatch):
        appels = _patch(monkeypatch, lambda r: httpx.Response(200, json=OK))
        r1 = run(ai.appeler_ia(MESSAGES))
        r2 = run(ai.appeler_ia(MESSAGES))
        assert r1["depuis_cache"] is False
        assert r2["depuis_cache"] is True
        assert len(appels) == 1
        assert ai.quotas()["mistral"]["cache_hits"] == 1

    def test_ignorer_cache_force_l_appel(self, monkeypatch):
        appels = _patch(monkeypatch, lambda r: httpx.Response(200, json=OK))
        run(ai.appeler_ia(MESSAGES))
        res = run(ai.appeler_ia(MESSAGES, ignorer_cache=True))
        assert res["depuis_cache"] is False
        assert len(appels) == 2


class TestSecurite:

    def test_modele_payant_refuse(self, monkeypatch):
        appels = _patch(monkeypatch, lambda r: httpx.Response(200, json=OK))
        with pytest.raises(ValueError):
            run(ai.appeler_ia(MESSAGES, modele="gpt-4-turbo-premium"))
        assert appels == []

    def test_cle_jamais_dans_le_journal(self, monkeypatch):
        def handler(request):
            corps = json.loads(request.content)
            if corps["model"].startswith("mistral"):
                return httpx.Response(429,
                                      json={"error": "quota cle-test-123"})
            return httpx.Response(200, json=OK)
        _patch(monkeypatch, handler, cle="cle-super-secrète-789")
        run(ai.appeler_ia(MESSAGES))
        blob = json.dumps(ai.journal())
        assert "cle-super-secrète-789" not in blob
        assert "[REDACTE]" in blob

    def test_aucune_cle_en_dur(self):
        source = inspect.getsource(ai)
        for secret in ("sk-", "Bearer eyJ", "FREE_LLM_API_KEY=",
                        "FREE_LLM_API_KEY='"):
            assert secret not in source

    def test_separation_deterministe(self):
        """L'IA ne touche JAMAIS aux calculs metier : ai_manager
        n'importe aucun module deterministe et n'emet aucune ecriture."""
        source = inspect.getsource(ai)
        for interdit in ("import daily", "import pricing_v55",
                         "import freight_collector", "fw_create",
                         "cj_freight", "shopping/order", "purchase"):
            assert interdit not in source, interdit

    def test_quotas_restants_lus(self, monkeypatch):
        corps = {"choices": [{"message": {"content": "ok"}}],
                 "usage": {"remaining": 42}}
        _patch(monkeypatch, lambda r: httpx.Response(200, json=corps))
        run(ai.appeler_ia(MESSAGES))
        assert ai.quotas()["mistral"]["restant"] == 42

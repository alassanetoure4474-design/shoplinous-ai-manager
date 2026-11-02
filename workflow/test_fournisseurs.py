"""SHOPLINOUS - Verification des modeles declares (FreeLLMAPI).

Script de sante AVANT LE PREMIER APPEL REEL : interroge
GET {FREE_LLM_API_BASE}/v1/models en lecture seule et verifie UN PAR UN
que les 5 modeles libres declares (AI_MODEL_*) existent sur l'instance
reelle. Les valeurs par defaut du code n ont jamais ete validees contre
une instance reelle : ce script comble ce trou sans lancer le worker.

Securite :
- CE SCRIPT N'AFFICHE JAMAIS LA CLE : tout detail passe par le filtre de
  redaction (meme regle que ai_manager).
- Aucune ecriture, aucun appel de chat, aucune operation commerciale :
  lecture seule de la liste des modeles.
- Sans FREE_LLM_API_KEY / FREE_LLM_API_BASE : sortie immediate (code 2)
  sans AUCUN appel reseau.

Usage :
    python test_fournisseurs.py
Codes de sortie : 0 = tous les modeles declares existent ;
1 = au moins un modele absent ; 2 = instance injoignable ou non configuree.

Ce fichier sert aussi de suite pytest (classes Test*) : les tests CI
utilisent des transports simules (httpx.MockTransport), jamais le reseau.
"""

import os
import sys

import httpx

import ai_manager


def _sans_secret(texte):
    """Redaction : la cle API n'apparait JAMAIS (meme filtre que
    ai_manager._sans_secret)."""
    cle = ai_manager._cle_api()
    if cle:
        texte = str(texte).replace(cle, "[REDACTE]")
    return str(texte)[:300]


def _client(delai, transport=None):
    if transport is not None:
        return httpx.Client(transport=transport, timeout=delai)
    return httpx.Client(timeout=delai)


def _extraire_ids(corps):
    """Extrait les identifiants de /v1/models. Formats reconnus : OpenAI
    ({"data": [{"id": ...}, ...]}) et liste simple de chaines. Toute
    structure inattendue -> liste vide (AUCUNE invention)."""
    ids = []
    if isinstance(corps, dict):
        donnees = corps.get("data")
        if isinstance(donnees, list):
            for entree in donnees:
                if isinstance(entree, dict) and isinstance(
                        entree.get("id"), str):
                    ids.append(entree["id"])
                elif isinstance(entree, str):
                    ids.append(entree)
    elif isinstance(corps, list):
        for entree in corps:
            if isinstance(entree, str):
                ids.append(entree)
    return ids


def lister_modeles(base, cle, transport=None, delai=10.0):
    """GET {base}/v1/models en lecture seule.

    Retourne (statut_http, ids). Statut 0 = erreur reseau / JSON invalide
    / delai depasse ; ids vides si structure inattendue.
    """
    if not base or not cle:
        return 0, []
    reponse = None
    try:
        with _client(delai, transport) as client:
            reponse = client.get(
                base + "/v1/models",
                headers={"Authorization": "Bearer " + cle})
        corps = reponse.json()
    except Exception:
        return (reponse.status_code
                if reponse is not None else 0), []
    return reponse.status_code, _extraire_ids(corps)


def verifier_modeles(transport=None):
    """Verifie UN PAR UN les modeles declares contre l'instance reelle.

    Retourne {"joignable": bool, "statut": int,
              "modeles": {nom_du_modele: bool},
              "detail": str} avec detail redacte (jamais la cle).
    Respecte AI_MODEL_* : les surcharges d'environnement sont verifies
    elles aussi. Ne lance AUCUN appel de chat.
    """
    cle = ai_manager._cle_api()
    base = ai_manager._base_url()
    modeles = ai_manager._modeles()
    if not cle or not base:
        return {"joignable": False, "statut": 0, "modeles": {},
                "detail": "FREE_LLM_API_KEY ou FREE_LLM_API_BASE "
                          "absent : verification refusee (aucune "
                          "valeur par defaut inventee)"}
    statut, ids = lister_modeles(base, cle, transport=transport)
    if statut != 200 or not ids:
        return {"joignable": False, "statut": statut, "modeles": {},
                "detail": _sans_secret("GET /v1/models -> HTTP "
                                       + str(statut)
                                       + " ou reponse sans modele")}
    presents = set(ids)
    return {"joignable": True, "statut": statut,
            "modeles": {m: m in presents for m in modeles.values()},
            "detail": _sans_secret("instance joignable : "
                                   + str(len(ids))
                                   + " modeles exposes")}


def main():
    verif = verifier_modeles()
    print("Verification FreeLLMAPI - GET /v1/models (lecture seule)")
    print("joignable :", verif["joignable"],
          "| statut HTTP :", verif["statut"])
    if not verif["joignable"]:
        print("detail :", verif["detail"])
        print("INSTANCE INJOIGNABLE OU NON CONFIGUREE : corriger "
              "FREE_LLM_API_BASE / FREE_LLM_API_KEY avant le premier "
              "appel reel.")
        return 2
    manquants = []
    for nom, present in sorted(verif["modeles"].items()):
        print(("  [OK]     " if present else "  [ABSENT] ") + nom)
        if not present:
            manquants.append(nom)
    print("detail :", verif["detail"])
    if manquants:
        print("MODELES ABSENTS DE L'INSTANCE (" + str(len(manquants))
              + ") : ajuster AI_MODEL_MISTRAL / AI_MODEL_GEMINI / "
              "AI_MODEL_GROQ / AI_MODEL_QWEN / AI_MODEL_GPT_OSS en "
              "consequence (modeles payants INTERDITS).")
        return 1
    print("TOUS LES MODELES DECLARES EXISTENT SUR L'INSTANCE : "
          "l'ordre AI_PROVIDER_ORDER peut etre utilise tel quel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ---------------------------------------------------------------------------
# Tests unitaires CI (aucun reseau : transports simules).
# ---------------------------------------------------------------------------

import pytest  # noqa: E402

CLE = "cle-test-a-ne-jamais-afficher"
BASE = "https://passerelle.test"


def _env_defaut(monkeypatch):
    """Configuration minimale : les 5 modeles par defaut du code."""
    monkeypatch.setenv("FREE_LLM_API_KEY", CLE)
    monkeypatch.setenv("FREE_LLM_API_BASE", BASE)
    for var in ("AI_MODEL_MISTRAL", "AI_MODEL_GEMINI", "AI_MODEL_GROQ",
                "AI_MODEL_QWEN", "AI_MODEL_GPT_OSS",
                "AI_PROVIDER_ORDER"):
        monkeypatch.delenv(var, raising=False)


def _transport_ids(modeles):
    def handler(request):
        assert request.url.path == "/v1/models"
        assert request.headers.get("Authorization") == "Bearer " + CLE
        return httpx.Response(
            200, json={"data": [{"id": m} for m in modeles]})
    return httpx.MockTransport(handler)


class TestListageModeles:
    def test_format_openai(self):
        transport = _transport_ids(["m1", "m2"])
        statut, ids = lister_modeles(BASE, CLE, transport=transport)
        assert statut == 200
        assert ids == ["m1", "m2"]

    def test_format_liste_simple(self):
        def handler(request):
            return httpx.Response(200, json=["a", "b"])
        statut, ids = lister_modeles(
            BASE, CLE, transport=httpx.MockTransport(handler))
        assert statut == 200
        assert ids == ["a", "b"]

    def test_erreur_reseau_statut_zero(self):
        def handler(request):
            raise httpx.ConnectError("injoignable")
        statut, ids = lister_modeles(
            BASE, CLE, transport=httpx.MockTransport(handler))
        assert statut == 0
        assert ids == []

    def test_structure_inattendue_aucune_invention(self):
        def handler(request):
            return httpx.Response(200, json={"data": "bizarre"})
        statut, ids = lister_modeles(
            BASE, CLE, transport=httpx.MockTransport(handler))
        assert statut == 200
        assert ids == []

    def test_sans_configuration_aucun_appel(self):
        def handler(request):
            raise AssertionError("aucun appel reseau attendu")
        statut, ids = lister_modeles(
            "", "", transport=httpx.MockTransport(handler))
        assert statut == 0
        assert ids == []


class TestVerificationModeles:
    def test_tous_les_modeles_declares_presents(self, monkeypatch):
        _env_defaut(monkeypatch)
        transport = _transport_ids(
            list(ai_manager.MODELES_LIBRES_PAR_DEFAUT.values()))
        verif = verifier_modeles(transport=transport)
        assert verif["joignable"] is True
        assert verif["statut"] == 200
        assert verif["modeles"] == {
            m: True for m in ai_manager.MODELES_LIBRES_PAR_DEFAUT.values()}

    def test_modele_manquant_signale_un_par_un(self, monkeypatch):
        _env_defaut(monkeypatch)
        attendus = list(ai_manager.MODELES_LIBRES_PAR_DEFAUT.values())
        exposes = [m for m in attendus if m != attendus[2]]
        verif = verifier_modeles(transport=_transport_ids(exposes))
        assert verif["joignable"] is True
        assert verif["modeles"][attendus[2]] is False
        assert sum(1 for v in verif["modeles"].values() if v) == 4

    def test_surcharge_environnement_respectee(self, monkeypatch):
        _env_defaut(monkeypatch)
        monkeypatch.setenv("AI_MODEL_MISTRAL", "mon-mistral-local")
        verif = verifier_modeles(transport=_transport_ids(
            ["mon-mistral-local"]))
        assert verif["modeles"]["mon-mistral-local"] is True
        assert sum(1 for v in verif["modeles"].values() if v) == 1

    def test_http_500_injoignable_et_detail_sans_cle(self, monkeypatch):
        _env_defaut(monkeypatch)

        def handler(request):
            return httpx.Response(500, json={})
        verif = verifier_modeles(transport=httpx.MockTransport(handler))
        assert verif["joignable"] is False
        assert verif["statut"] == 500
        assert verif["modeles"] == {}
        assert CLE not in verif["detail"]

    def test_sans_cle_refus_sans_appel_reseau(self, monkeypatch):
        monkeypatch.delenv("FREE_LLM_API_KEY", raising=False)
        monkeypatch.delenv("FREE_LLM_API_BASE", raising=False)

        def handler(request):
            raise AssertionError("aucun appel reseau attendu")
        verif = verifier_modeles(transport=httpx.MockTransport(handler))
        assert verif["joignable"] is False
        assert verif["modeles"] == {}
        assert "absent" in verif["detail"]


class TestCodesSortie:
    def test_main_sans_configuration_code_2(self, monkeypatch, capsys):
        monkeypatch.delenv("FREE_LLM_API_KEY", raising=False)
        monkeypatch.delenv("FREE_LLM_API_BASE", raising=False)
        assert main() == 2
        assert CLE not in capsys.readouterr().out

    def test_main_modele_absent_code_1(self, monkeypatch, capsys):
        _env_defaut(monkeypatch)
        attendus = list(ai_manager.MODELES_LIBRES_PAR_DEFAUT.values())

        def faux_lister(base, cle, transport=None, delai=10.0):
            return 200, attendus[:4]  # le 5e modele manque
        monkeypatch.setattr(
            "test_fournisseurs.lister_modeles", faux_lister)
        assert main() == 1
        sortie = capsys.readouterr().out
        assert "[ABSENT] " + attendus[4] in sortie
        assert "MODELES ABSENTS" in sortie
        assert CLE not in sortie

"""Tests des 4 outils daily sans couverture dediee (audit 32 outils).

Couvre : cj_stock, cj_product_detail, rapport_fret_v56,
controle_vid_seed_v56. Reseau MOQUE (httpx.MockTransport) : aucun appel
reel CJ, aucune cle reelle.
"""
import asyncio
import json
from datetime import date, timedelta

import httpx
import pytest

import daily


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _patch(monkeypatch, handler):
    class Patched(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    monkeypatch.setenv("CJ_API_KEY", "test-key")


class TestCjStock:
    def test_stock_valide_retourne_la_reponse(self, monkeypatch):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={
                "code": 200, "data": [
                    {"countryCode": "CN", "storageNum": 11347,
                     "totalInventoryNum": 11347,
                     "stock": [{"inventory": 0}]}]})
        _patch(monkeypatch, handler)
        res = run(daily.cj_stock("vid123"))
        assert seen == {"vid": "vid123"}
        assert daily.cn_stock_of(res) == 11347

    def test_stock_structure_inattendue_leve(self, monkeypatch):
        _patch(monkeypatch, lambda r: httpx.Response(
            200, json={"code": 200, "data": {"pas": "une liste"}}))
        with pytest.raises(RuntimeError, match="structure inattendue"):
            run(daily.cj_stock("vid123"))

    def test_stock_erreur_metier_cj_leve(self, monkeypatch):
        _patch(monkeypatch, lambda r: httpx.Response(
            200, json={"code": 1600200, "message": "QPS limit",
                       "data": None}))
        with pytest.raises(RuntimeError, match="1600200"):
            run(daily.cj_stock("vid123"))


class TestCjProductDetail:
    def test_detail_valide_retourne_le_payload(self, monkeypatch):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={
                "code": 200, "data": [{
                    "productImage": json.dumps(
                        ["https://img/a.jpg", "https://img/b.jpg"])}]})
        _patch(monkeypatch, handler)
        res = run(daily.cj_product_detail("pid1"))
        assert seen == {"pid": "pid1"}
        urls = daily.parse_cj_images(res)
        assert urls == ["https://img/a.jpg", "https://img/b.jpg"]

    def test_detail_data_absent_leve(self, monkeypatch):
        _patch(monkeypatch, lambda r: httpx.Response(
            200, json={"code": 200}))
        with pytest.raises(RuntimeError, match="champ data absent"):
            run(daily.cj_product_detail("pid1"))


class TestRapportFretV56:
    def test_rapport_lecture_seule_2_variantes_255_tarifs_51_pays(self):
        import freight_collector_v56 as fc
        rap = daily.rapport_fret_v56(aujourdhui=date(2026, 11, 2))
        assert set(rap) == {fc.VID_BLANCHE, fc.VID_NOIRE}
        for vid, info in rap.items():
            assert info["nb_tarifs"] == 255
            assert info["nb_pays"] == 51
            assert info["nb_expires"] == 0

    def test_rapport_signale_les_tarifs_expires(self):
        # donnees perimees (> TTL 7 jours) : nb_expires > 0, AUCUN reseau.
        import freight_collector_v56 as fc
        donnees = {"schema_version": "5.6", "variantes": [{
            "vid_cj": fc.VID_NOIRE, "sku_variante": "X", "couleur": "Noir",
            "tarifs": [{"pays": "FR", "quantite": 1, "usd": 4.0,
                        "canal": "A", "delai": "4-10", "usd_15j": 4.0,
                        "date_collecte": "2026-10-01"}]}]}
        rap = daily.rapport_fret_v56(
            donnees, aujourdhui=date(2026, 11, 2))
        assert rap[fc.VID_NOIRE]["nb_expires"] == 1


class TestControleVidSeedV56:
    def test_amorce_coherente_par_defaut(self):
        # les vids de l'amorce existent dans le jeu v5.6 -> liste vide
        assert daily.controle_vid_seed_v56() == []

    def test_vid_incoherent_signale(self, monkeypatch):
        # un vid d'amorce absent du jeu v5.6 doit etre signale par SKU
        daily.VID_TABLE_SEED["CJJT205244501AZ"] = {
            "vid": "vid-inconnu-999", "fw_product_id": "1",
            "fw_variant_id": "Z", "cj_pid": "2"}
        try:
            incoherents = daily.controle_vid_seed_v56()
            assert incoherents == ["CJJT205244501AZ"]
        finally:
            # restauration : ne jamais modifier l'amorce pour de vrai
            daily.VID_TABLE_SEED["CJJT205244501AZ"] = {
                "vid": "1797521453382905856",
                "fw_product_id": "18809643",
                "fw_variant_id": "ZsKQFt",
                "cj_pid": "1797521453303214080"}
        assert daily.controle_vid_seed_v56() == []

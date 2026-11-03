"""Tests d'integration v5.7 : surveillance du catalogue publie dans daily.

HONNETETE : non executes dans l'environnement de preparation (aucun
Python disponible). EXECUTION REELLE via GitHub Actions (job pytest,
dossier workflow/) ou localement :
    python -m pytest test_catalog_watch_integration.py -v

Couverture :
- daily.surveiller_catalogue_publie : cas normal conforme, stock sous
  seuil, derive du stock affiche (regle 9), cout hors regle, marge sous
  3x, variante disparue, erreur CJ isolee (fail-closed sans arret),
  stock indisponible, fw_records absent (amorce seule, marge non
  verifiable signalee), table vide ;
- reutilisation : UN appel cj_variants par produit CJ, un cj_stock par
  variante (comptage exact), aucune donnee inventee ;
- fw_variant_records capture desormais prix boutique et stock affiche ;
- lecture seule : inspection de la source (aucun endpoint d'ecriture,
  aucun acces reseau direct), allow_publish=False inchange ;
- integration workflow : bloc present, place APRES vid_table et
  AVANT la surveillance des commandes, erreur jamais fatale.
"""
import asyncio
import inspect

import pytest

import daily
import catalog_watch as cw


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


VID_TABLE_REEL = {"table": {
    "CJJT205244501AZ": {"vid": "1797521453382905856",
                        "fw_product_id": "18809643",
                        "fw_variant_id": "ZsKQFt",
                        "cj_pid": "1797521453303214080"},
    "CJJT205244502BY": {"vid": "1797521453454209024",
                        "fw_product_id": "18809643",
                        "fw_variant_id": "WPPmLB",
                        "cj_pid": "1797521453303214080"},
}, "absents": [], "ambigus": []}

CJ_VARIANTES_REEL = {"code": 200, "result": True, "data": [
    {"vid": "1797521453382905856", "variantSku": "CJJT205244501AZ",
     "variantSellPrice": "2.81"},
    {"vid": "1797521453454209024", "variantSku": "CJJT205244502BY",
     "variantSellPrice": "2.81"},
]}

FW_RECORDS_REEL = [
    {"fw_product_id": "18809643", "fw_product_sku": "SHP-CJT2052445",
     "fw_variant_id": "ZsKQFt", "variant_sku": "CJJT205244501AZ",
     "prix_fw": 24.9, "stock_affiche_fw": 100},
    {"fw_product_id": "18809643", "fw_product_sku": "SHP-CJT2052445",
     "fw_variant_id": "WPPmLB", "variant_sku": "CJJT205244502BY",
     "prix_fw": 24.9, "stock_affiche_fw": 100},
]


def payload_stock(stock_cn):
    return {"data": [{"countryCode": "CN", "storageNum": stock_cn,
                      "totalInventoryNum": stock_cn,
                      "stock": [{"inventory": 0}]}]}


def make_fns(stock_par_vid=None, variantes=None, appels=None,
             erreur_variants=False):
    async def variants_fn(pid):
        if appels is not None:
            appels.append(("variants", pid))
        if erreur_variants:
            raise RuntimeError("CJ indisponible")
        return variantes if variantes is not None else CJ_VARIANTES_REEL

    async def stock_fn(vid):
        if appels is not None:
            appels.append(("stock", vid))
        return payload_stock((stock_par_vid or {}).get(vid, 11347))

    return variants_fn, stock_fn


# ------------------------- surveiller_catalogue_publie : cas normaux ----
class TestSurveillanceCataloguePublie:
    def test_catalogue_sain_conforme(self):
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            *make_fns({"1797521453382905856": 11347,
                       "1797521453454209024": 11347})))
        assert resume["statut"] == "conforme"
        assert resume["nb_variantes"] == 2
        assert resume["nb_conformes"] == 2
        assert resume["lecture_seule"] is True
        assert alertes == []

    def test_stock_sous_seuil(self):
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            *make_fns({"1797521453382905856": 420,
                       "1797521453454209024": 11347})))
        assert resume["statut"] == "alertes"
        assert resume["nb_non_conformes"] == 1
        assert any("stock_sous_seuil" in a["alerte"] for a in alertes)
        assert all(a["gravite"] == "haute" for a in alertes)

    def test_derive_stock_affiche(self):
        """Stock CN 150 -> attendu 50 affiche ; FW affiche 100 (regle 9)."""
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            *make_fns({"1797521453382905856": 150,
                       "1797521453454209024": 11347})))
        assert any("stock_affiche_derive" in a["alerte"] for a in alertes)

    def test_cout_hors_regle(self):
        chere = {"code": 200, "result": True, "data": [
            {"vid": "1797521453382905856", "variantSku": "CJJT205244501AZ",
             "variantSellPrice": "12.00"},
            {"vid": "1797521453454209024", "variantSku": "CJJT205244502BY",
             "variantSellPrice": "2.81"}]}
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            *make_fns(variantes=chere)))
        assert any("cout_hors_regle" in a["alerte"] for a in alertes)

    def test_marge_sous_multiple(self):
        pas_chers = [dict(r, prix_fw=5.0) for r in FW_RECORDS_REEL]
        resume, alertes = run(daily.surveiller_catalogue_publie(
            pas_chers, VID_TABLE_REEL, 0.895, *make_fns()))
        assert resume["nb_non_conformes"] == 2
        marges = [a for a in alertes if "marge_sous_multiple" in a["alerte"]]
        assert len(marges) == 2

    def test_variante_disparue(self):
        une_seule = {"code": 200, "result": True, "data": [
            {"vid": "1797521453382905856", "variantSku": "CJJT205244501AZ",
             "variantSellPrice": "2.81"}]}
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            *make_fns(variantes=une_seule)))
        assert any("variante_disparue" in a["alerte"] for a in alertes)
        assert any(a["catalog_watch"] == "CJJT205244502BY" for a in alertes)


# ------------------------------ erreurs CJ : fail-closed sans arret ----
class TestErreursCJ:
    def test_erreur_variants_isolee_fail_closed(self):
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            *make_fns(erreur_variants=True)))
        assert resume["statut"] == "alertes"
        assert len(alertes) == 2
        assert all("controle_indisponible" in a["alerte"] for a in alertes)

    def test_erreur_stock_alerte_pas_invention(self):
        async def variants_fn(pid):
            return CJ_VARIANTES_REEL

        async def stock_fn(vid):
            raise RuntimeError("CJ QPS")

        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895, variants_fn, stock_fn))
        assert any("stock_indisponible" in a["alerte"] for a in alertes)

    def test_fw_records_absent_amorce_seule(self):
        """Reconstruction vid_table impossible -> fw_records vide : la
        surveillance tourne sur l'amorce, la marge non verifiable est
        signalee (fail-closed), aucune exception."""
        resume, alertes = run(daily.surveiller_catalogue_publie(
            None, VID_TABLE_REEL, 0.895, *make_fns()))
        assert resume["nb_variantes"] == 2
        assert any("prix_boutique_indisponible" in a["alerte"]
                   for a in alertes)

    def test_table_vide_aucune_variante(self):
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, {"table": {}}, 0.895, *make_fns()))
        assert resume["statut"] == "aucune_variante"
        assert alertes == []


# ------------------------- reutilisation : appels CJ comptes exactement ----
class TestReutilisation:
    def test_un_seul_appel_variants_par_produit(self):
        appels = []
        run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895, *make_fns(appels=appels)))
        assert appels.count(("variants", "1797521453303214080")) == 1
        assert len([a for a in appels if a[0] == "stock"]) == 2
        assert len(appels) == 3

    def test_resume_uniquement_des_compteurs(self):
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895, *make_fns()))
        AUTORISES = {"statut", "nb_variantes", "nb_conformes",
                     "nb_non_conformes", "nb_alertes", "lecture_seule",
                     "catalog_watch", "gravite", "alerte"}
        cles = set()

        def collecte(obj):
            if isinstance(obj, dict):
                cles.update(obj.keys())
                for v in obj.values():
                    collecte(v)
            elif isinstance(obj, list):
                for v in obj:
                    collecte(v)
        collecte(resume)
        collecte(alertes)
        assert not (cles - AUTORISES)


# ------------------- fw_variant_records : capture prix et stock affiche ----
class TestFwVariantRecordsV57:
    def test_capture_prix_et_stock_affiche(self, monkeypatch):
        detail = {"core": {"id": "18809643", "price": 24.9},
                  "variants": [
                      {"uvid": "ZsKQFt", "sku": "CJJT205244501AZ",
                       "stock": 100},
                      {"uvid": "WPPmLB", "sku": "CJJT205244502BY",
                       "stock": 50}]}

        async def fake_get(pid):
            return detail

        monkeypatch.setattr(daily, "fw_get_product", fake_get)
        catalogue = [{"id": "18809643", "sku": "SHP-CJT2052445",
                      "name": "Attrape-reves"}]
        recs = run(daily.fw_variant_records(catalogue))
        assert len(recs) == 2
        assert all(r["prix_fw"] == 24.9 for r in recs)
        assert recs[0]["stock_affiche_fw"] == 100
        assert recs[1]["stock_affiche_fw"] == 50

    def test_structure_sans_prix_ni_stock_ne_plante_pas(self, monkeypatch):
        detail = {"core": {}, "variants": [{"uvid": "Z", "sku": "SKU-X"}]}

        async def fake_get(pid):
            return detail

        monkeypatch.setattr(daily, "fw_get_product", fake_get)
        recs = run(daily.fw_variant_records([{"id": "1", "name": "p"}]))
        assert recs[0]["prix_fw"] is None
        assert recs[0]["stock_affiche_fw"] is None


# --------------------------------------------- securite : lecture seule ----
class TestLectureSeuleV57:
    def test_fonction_sans_reseau_ni_ecriture(self):
        src = inspect.getsource(daily.surveiller_catalogue_publie)
        for interdit in ("httpx", "AsyncClient", "requests",
                         "shopping/order", "purchase", "createOrder",
                         "cancelOrder", "payOrder", "fw_create"):
            assert interdit not in src, "interdit present : " + interdit

    def test_module_catalog_watch_importe(self):
        assert daily.cw is cw

    def test_allow_publish_false_inchange(self):
        assert daily.DailyParams().allow_publish is False


# ------------------------------------------ integration dans run() ----
class TestIntegrationWorkflowV57:
    def test_bloc_present_place_et_non_fatal(self):
        src = inspect.getsource(daily.ShoplinousDailyWorkflow)
        assert "await surveiller_catalogue_publie(" in src
        assert 'report["catalog_watch"]' in src
        pos_table = src.index('report["vid_table"]')
        pos_cw = src.index("surveiller_catalogue_publie(")
        pos_orders = src.index("# Surveillance commandes")
        assert pos_table < pos_cw < pos_orders
        assert 'report["errors"].append(f"catalog_watch: {exc}")' in src

    def test_fw_records_defini_meme_si_vid_table_echoue(self):
        """Si la reconstruction echoue, fw_records = [] : le bloc de
        surveillance ne leve jamais NameError."""
        src = inspect.getsource(daily.ShoplinousDailyWorkflow)
        assert "fw_records = []" in src

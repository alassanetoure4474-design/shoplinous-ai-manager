"""Tests pytest du module catalog_watch (surveillance du catalogue
publie) - branche feat/catalog-watch.

HONNETETE : non executes dans l'environnement de preparation (aucun
Python disponible). EXECUTION REELLE via GitHub Actions
(.github/workflows/python-tests.yml, job pytest sur le dossier
workflow/), egalement executable localement :
    pip install -r requirements.txt -r requirements-dev.txt
    python -m pytest test_catalog_watch.py -v

Couverture v1.0 :
- display_stock (regle 9) : bornes 0/100, stock - 100, valeurs invalides ;
- controler_variante : conforme, stock sous seuil (1000), cout hors
  regle (> 8 EUR), marge sous 3x, variante disparue, sku divergent,
  stock affiche derive, donnees indisponibles (taux, stock, cout,
  prix boutique) -> alerte, jamais d'invention ;
- construire_rapport : aggregation, statuts, lecture_seule True ;
- surveiller_catalogue : groupement par pid (UN appel cj_variants par
  produit), appel cj_stock par vid, sequenciel, erreur CJ isolee
  (fail-closed, surveillance continue), zero ecriture (inspection de
  la source : aucun POST/PUT, aucun endpoint d'ordre fournisseur,
  aucun import SDK Mistral).
"""
import asyncio
import inspect

import pytest

import catalog_watch as cw


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


VARIANTE_CJ = {"vid": "1797521453454209024",
               "variantSku": "CJJT205244502BY",
               "variantSellPrice": "2.81"}
ENTREE_OK = {"variant_sku": "CJJT205244502BY",
             "fw_product_id": "18809643",
             "fw_variant_id": "WPPmLB",
             "prix_fw": 24.9,
             "stock_affiche_fw": 100}


# ----------------------------------------------------------- regle 9 ----
class TestDisplayStock:
    def test_regle_9_identique_a_daily(self):
        assert cw.display_stock(11347) == 100
        assert cw.display_stock(150) == 50
        assert cw.display_stock(100) == 0
        assert cw.display_stock(0) == 0
        assert cw.display_stock(-10) == 0

    def test_valeurs_invalides_none(self):
        assert cw.display_stock(None) is None
        assert cw.display_stock("beaucoup") is None
        assert cw.display_stock(True) is None
        assert cw.display_stock([1000]) is None

    def test_bornes_partagees_avec_daily(self):
        assert cw.MIN_STOCK_CN == 1000
        assert cw.MAX_COST_EUR == 8.0
        assert cw.MARGIN_MULTIPLE == 3.0
        assert cw.SAFETY_STOCK == 100
        assert cw.DISPLAY_STOCK_CAP == 100


# ------------------------------------------------- controler_variante ----
class TestControlerVariante:
    def test_conforme_aucune_alerte(self):
        verdict = cw.controler_variante(ENTREE_OK, VARIANTE_CJ, 11347, 0.895)
        assert verdict["conforme"] is True
        assert verdict["alertes"] == []
        assert verdict["infos"]["cout_eur"] == pytest.approx(2.5150, abs=1e-3)
        assert verdict["infos"]["stock_affiche_attendu"] == 100

    def test_stock_sous_seuil(self):
        verdict = cw.controler_variante(ENTREE_OK, VARIANTE_CJ, 420, 0.895)
        codes = [a["code"] for a in verdict["alertes"]]
        assert "stock_sous_seuil" in codes
        assert verdict["conforme"] is False

    def test_stock_affiche_derive(self):
        """Stock CN 150 -> attendu 50 affiche ; FW affiche 100."""
        entree = dict(ENTREE_OK, stock_affiche_fw=100)
        verdict = cw.controler_variante(entree, VARIANTE_CJ, 150, 0.895)
        codes = [a["code"] for a in verdict["alertes"]]
        assert "stock_affiche_derive" in codes
        assert cw.display_stock(150) == 50

    def test_stock_affiche_concordant_pas_d_alerte(self):
        entree = dict(ENTREE_OK, stock_affiche_fw=50)
        verdict = cw.controler_variante(entree, VARIANTE_CJ, 150, 0.895)
        codes = [a["code"] for a in verdict["alertes"]]
        assert "stock_affiche_derive" not in codes

    def test_cout_hors_regle(self):
        """variantSellPrice 12 USD -> ~10,74 EUR > 8 EUR."""
        chere = dict(VARIANTE_CJ, variantSellPrice="12.00")
        verdict = cw.controler_variante(ENTREE_OK, chere, 11347, 0.895)
        codes = [a["code"] for a in verdict["alertes"]]
        assert "cout_hors_regle" in codes
        assert verdict["conforme"] is False

    def test_marge_sous_multiple(self):
        """Prix boutique 8 EUR < 3x (2.81*0.895 + 0.5) ~ 8,05 EUR."""
        verdict = cw.controler_variante(
            dict(ENTREE_OK, prix_fw=8.0), VARIANTE_CJ, 11347, 0.895,
            cout_livraison_eur=0.5)
        codes = [a["code"] for a in verdict["alertes"]]
        assert "marge_sous_multiple" in codes

    def test_marge_juste_conforme(self):
        verdict = cw.controler_variante(
            dict(ENTREE_OK, prix_fw=24.9), VARIANTE_CJ, 11347, 0.895,
            cout_livraison_eur=4.2)
        assert verdict["conforme"] is True

    def test_variante_disparue(self):
        verdict = cw.controler_variante(ENTREE_OK, None, 11347, 0.895)
        codes = [a["code"] for a in verdict["alertes"]]
        assert "variante_disparue" in codes
        assert verdict["conforme"] is False

    def test_sku_divergent(self):
        autre = dict(VARIANTE_CJ, variantSku="CJJT205244501AZ")
        verdict = cw.controler_variante(ENTREE_OK, autre, 11347, 0.895)
        codes = [a["code"] for a in verdict["alertes"]]
        assert "sku_divergent" in codes

    def test_stock_indisponible_alerte_pas_invention(self):
        verdict = cw.controler_variante(ENTREE_OK, VARIANTE_CJ, None, 0.895)
        codes = [a["code"] for a in verdict["alertes"]]
        assert "stock_indisponible" in codes
        assert verdict["conforme"] is False
        assert verdict["infos"]["stock_cn"] is None

    def test_taux_indisponible_annule_controles_cout(self):
        verdict = cw.controler_variante(ENTREE_OK, VARIANTE_CJ, 11347, None)
        codes = [a["code"] for a in verdict["alertes"]]
        assert "taux_indisponible" in codes
        assert verdict["conforme"] is False
        assert verdict["infos"]["cout_eur"] is None

    def test_cout_indisponible(self):
        sans_prix = dict(VARIANTE_CJ, variantSellPrice=None)
        verdict = cw.controler_variante(ENTREE_OK, sans_prix, 11347, 0.895)
        codes = [a["code"] for a in verdict["alertes"]]
        assert "cout_indisponible" in codes

    def test_prix_boutique_indisponible_marge_non_verifiable(self):
        entree = {k: v for k, v in ENTREE_OK.items() if k != "prix_fw"}
        verdict = cw.controler_variante(entree, VARIANTE_CJ, 11347, 0.895)
        codes = [a["code"] for a in verdict["alertes"]]
        assert "prix_boutique_indisponible" in codes
        assert verdict["conforme"] is False


# -------------------------------------------------- construire_rapport ----
class TestConstruireRapport:
    def test_rapport_vide(self):
        rapport = cw.construire_rapport([])
        assert rapport["statut"] == "aucune_variante"
        assert rapport["nb_variantes"] == 0
        assert rapport["lecture_seule"] is True

    def test_rapport_conforme(self):
        v = cw.controler_variante(ENTREE_OK, VARIANTE_CJ, 11347, 0.895)
        rapport = cw.construire_rapport([v])
        assert rapport["statut"] == "conforme"
        assert rapport["nb_conformes"] == 1
        assert rapport["nb_alertes"] == 0

    def test_rapport_agrege_les_alertes(self):
        ok = cw.controler_variante(ENTREE_OK, VARIANTE_CJ, 11347, 0.895)
        ko = cw.controler_variante(ENTREE_OK, VARIANTE_CJ, 42, 0.895)
        rapport = cw.construire_rapport([ok, ko])
        assert rapport["statut"] == "alertes"
        assert rapport["nb_non_conformes"] == 1
        assert rapport["nb_alertes"] == 1
        assert rapport["alertes"][0]["variant_sku"] == "CJJT205244502BY"


# ------------------------------- surveiller_catalogue (orchestrateur) ----
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
VARIANTES_CJ_REEL = {"code": 200, "result": True, "data": [
    {"vid": "1797521453382905856", "variantSku": "CJJT205244501AZ",
     "variantSellPrice": "2.81"},
    {"vid": "1797521453454209024", "variantSku": "CJJT205244502BY",
     "variantSellPrice": "2.81"},
]}


class TestSurveillerCatalogue:
    def test_un_seul_appel_cj_variants_par_produit(self):
        appels = []

        async def variants_fn(pid):
            appels.append(("variants", pid))
            return VARIANTES_CJ_REEL

        async def stock_fn(vid):
            appels.append(("stock", vid))
            return 11347

        verdicts, rapport = run(cw.surveiller_catalogue(
            variants_fn, stock_fn, 0.895, VID_TABLE_REEL))
        assert appels.count(("variants", "1797521453303214080")) == 1
        assert len([a for a in appels if a[0] == "stock"]) == 2
        assert rapport["nb_variantes"] == 2
        assert rapport["statut"] == "conforme"

    def test_deux_produits_deux_appels_variants(self):
        table = {"table": {
            "SKU-A": {"vid": "v1", "fw_product_id": "P1",
                      "fw_variant_id": "f1", "cj_pid": "pid1"},
            "SKU-B": {"vid": "v2", "fw_product_id": "P2",
                      "fw_variant_id": "f2", "cj_pid": "pid2"},
        }}
        appels = []

        async def variants_fn(pid):
            appels.append(pid)
            return {"data": [{"vid": "v" + pid[-1],
                              "variantSku": "SKU-" + pid[-1],
                              "variantSellPrice": "2.81"}]}

        async def stock_fn(vid):
            return 2000

        verdicts, rapport = run(cw.surveiller_catalogue(
            variants_fn, stock_fn, 0.895, table))
        assert sorted(appels) == ["pid1", "pid2"]
        assert rapport["nb_variantes"] == 2

    def test_erreur_cj_isolee_fail_closed_sans_arret(self):
        """Erreur sur le produit 1 : alerte controle_indisponible, le
        produit 2 est quand meme surveille."""
        table = {"table": {
            "SKU-A": {"vid": "v1", "fw_product_id": "P1",
                      "fw_variant_id": "f1", "cj_pid": "pid1"},
            "SKU-B": {"vid": "v2", "fw_product_id": "P2",
                      "fw_variant_id": "f2", "cj_pid": "pid2"},
        }}

        async def variants_fn(pid):
            if pid == "pid1":
                raise RuntimeError("CJ indisponible")
            return {"data": [{"vid": "v2", "variantSku": "SKU-B",
                              "variantSellPrice": "2.81"}]}

        async def stock_fn(vid):
            return 1500

        verdicts, rapport = run(cw.surveiller_catalogue(
            variants_fn, stock_fn, 0.895, table))
        codes = []
        for v in verdicts:
            codes.extend(a["code"] for a in v["alertes"])
        assert "controle_indisponible" in codes
        par_sku = {v["variant_sku"]: v for v in verdicts}
        assert par_sku["SKU-B"]["conforme"] is True
        assert rapport["statut"] == "alertes"

    def test_cadence_respectee_entre_chaque_appel(self):
        pauses = []

        async def attendre():
            pauses.append(1)

        async def variants_fn(pid):
            return VARIANTES_CJ_REEL

        async def stock_fn(vid):
            return 11347

        run(cw.surveiller_catalogue(variants_fn, stock_fn, 0.895,
                                     VID_TABLE_REEL, attendre=attendre))
        # 1 appel variants + 2 appels stock -> 3 pauses (QPS 1 req/s)
        assert len(pauses) == 3

    def test_table_vide_sans_appel(self):
        appels = []

        async def variants_fn(pid):
            appels.append(pid)
            return {"data": []}

        async def stock_fn(vid):
            appels.append(vid)
            return 0

        verdicts, rapport = run(cw.surveiller_catalogue(
            variants_fn, stock_fn, 0.895, {"table": {}}))
        assert verdicts == []
        assert appels == []
        assert rapport["statut"] == "aucune_variante"

    def test_prix_fw_transmis_marge_verifiee(self):
        async def variants_fn(pid):
            return VARIANTES_CJ_REEL

        async def stock_fn(vid):
            return 11347

        verdicts, _ = run(cw.surveiller_catalogue(
            variants_fn, stock_fn, 0.895, VID_TABLE_REEL,
            prix_fw={"CJJT205244501AZ": 24.9, "CJJT205244502BY": 5.0}))
        par_sku = {v["variant_sku"]: v for v in verdicts}
        assert par_sku["CJJT205244501AZ"]["conforme"] is True
        codes = [a["code"] for a in par_sku["CJJT205244502BY"]["alertes"]]
        assert "marge_sous_multiple" in codes

    def test_stock_fn_en_erreur_alerte_pas_invention(self):
        async def variants_fn(pid):
            return VARIANTES_CJ_REEL

        async def stock_fn(vid):
            raise RuntimeError("CJ QPS")

        verdicts, rapport = run(cw.surveiller_catalogue(
            variants_fn, stock_fn, 0.895, VID_TABLE_REEL))
        codes = []
        for v in verdicts:
            codes.extend(a["code"] for a in v["alertes"])
        assert "stock_indisponible" in codes
        assert rapport["statut"] == "alertes"

    def test_table_absents_ambigus_ignores(self):
        """absents/ambigus ne sont pas dans la table : jamais contrôles,
        jamais inventes."""
        table = {"table": {}, "absents": [
            {"variant_sku": "yellow0001"}], "ambigus": [
            {"variant_sku": "X", "candidats_vid": ["1", "2"]}]}

        async def variants_fn(pid):
            raise AssertionError("aucun appel attendu")

        async def stock_fn(vid):
            raise AssertionError("aucun appel attendu")

        verdicts, rapport = run(cw.surveiller_catalogue(
            variants_fn, stock_fn, 0.895, table))
        assert verdicts == []
        assert rapport["statut"] == "aucune_variante"


# ------------------------------------------- securite : lecture seule ----
class TestSecurite:
    def test_aucune_ecriture_ni_sdk_dans_le_module(self):
        import catalog_watch
        src = inspect.getsource(catalog_watch)
        for interdit in ("httpx", "requests", "aiohttp", "urllib",
                         "mistralai", "os.environ", "subprocess",
                         "shopping/order", "purchase", "createOrder",
                         "cancelOrder", "payOrder", "fw_create",
                         "requests.post", "httpx.post"):
            assert interdit not in src, "interdit present : " + interdit

    def test_rapport_ne_contient_que_des_identifiants_metier(self):
        v = cw.controler_variante(ENTREE_OK, VARIANTE_CJ, 11347, 0.895)
        rapport = cw.construire_rapport([v])
        AUTORISES = {"module", "version", "lecture_seule", "statut",
                     "nb_variantes", "nb_conformes", "nb_non_conformes",
                     "nb_alertes", "alertes", "verdicts",
                     "code", "gravite", "message", "variant_sku",
                     "fw_product_id", "fw_variant_id", "stock_cn",
                     "cout_eur", "stock_affiche_attendu", "conforme",
                     "infos", "cj_pid"}
        cles = set()

        def collecte(obj):
            if isinstance(obj, dict):
                cles.update(obj.keys())
                for valeur in obj.values():
                    collecte(valeur)
            elif isinstance(obj, list):
                for valeur in obj:
                    collecte(valeur)
        collecte(rapport)
        hors = cles - AUTORISES
        assert not hors, "cles hors liste blanche : " + repr(hors)

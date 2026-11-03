"""Tests d'integration v5.8 : surveillance du catalogue publie dans daily.

HONNETETE : non executes dans l'environnement de preparation (aucun
Python disponible). EXECUTION REELLE via GitHub Actions (job pytest,
dossier workflow/) ou localement :
    python -m pytest test_catalog_watch_integration.py -v

Couverture :
- daily.surveiller_catalogue_publie : cas normal conforme, stock sous
  seuil, derive du stock affiche (regle 9), cout hors regle, marge sous
  3x APRES livraison reelle, variante disparue, erreur CJ isolee
  (fail-closed sans arret), stock indisponible, fw_records absent
  (amorce seule, marge non verifiable signalee), table vide ;
- MARGE v5.8 (regle 8 STRICT) :
  * devis cj_freight reel (quantity=1) par (vid, pays) : reference
    France + pire pays du marche, options CONFORMES uniquement
    (<= 6 EUR, <= 15 j) ;
  * fret indisponible (fn en erreur) -> livraison_indisponible, marge
    NON verifiable ;
  * cj_freight_fn ABSENT -> fail-closed, aucune requete, marge non
    verifiable ;
  * marge insuffisante APRES livraison reelle ;
  * alerte INFO marge_pire_pays sans casser la conformite France ;
  * prix boutique NON CONFIRME (source != pricing.baseprice) ->
    marge non verifiable ;
- fw_variant_records : capture core.pricing.baseprice en priorite
  (source confirmee), repli core.price signale NON CONFIRME, prix
  PRODUIT applicable a chaque variante (les variants[] FW ne portent
  aucun prix propre - structure reelle verifiee 03/11/2026) ;
- reutilisation : UN appel cj_variants par produit CJ, un cj_stock par
  variante, comptage exact des appels fret ;
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
     "prix_fw": 24.9, "prix_fw_source": "pricing.baseprice",
     "stock_affiche_fw": 100},
    {"fw_product_id": "18809643", "fw_product_sku": "SHP-CJT2052445",
     "fw_variant_id": "WPPmLB", "variant_sku": "CJJT205244502BY",
     "prix_fw": 24.9, "prix_fw_source": "pricing.baseprice",
     "stock_affiche_fw": 100},
]

# Marche reduit pour les tests (France = reference, Suisse = pire pays)
PAYS_MARCHE_TEST = ["FR", "CH"]


def payload_stock(stock_cn):
    return {"data": [{"countryCode": "CN", "storageNum": stock_cn,
                      "totalInventoryNum": stock_cn,
                      "stock": [{"inventory": 0}]}]}


def payload_fret(prix_usd):
    """Option CJ conforme : logisticPrice USD, delai <= 15 jours.
    4.69 USD x 0.895 = 4.20 EUR <= 6 EUR ; 6.50 USD x 0.895 = 5.82 EUR."""
    return {"data": [{"logisticName": "CJPacket Ordinary",
                      "logisticPrice": prix_usd,
                      "logisticAging": "4-10"}]}


def make_fns(stock_par_vid=None, variantes=None, appels=None,
             erreur_variants=False, fret_usd_par_pays=None,
             erreur_fret=False):
    """fret_usd_par_pays : dict pays -> prix USD (defaut 4.69 partout)."""

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

    async def freight_fn(vid, country, quantity=1):
        if appels is not None:
            appels.append(("fret", vid, country))
        if erreur_fret:
            raise RuntimeError("CJ fret indisponible")
        prix = (fret_usd_par_pays or {}).get(country, 4.69)
        return payload_fret(prix)

    return variants_fn, stock_fn, freight_fn


# ------------------------- surveiller_catalogue_publie : cas normaux ----
class TestSurveillanceCataloguePublie:
    def test_catalogue_sain_conforme(self):
        variants_fn, stock_fn, freight_fn = make_fns({
            "1797521453382905856": 11347,
            "1797521453454209024": 11347})
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["statut"] == "conforme"
        assert resume["nb_variantes"] == 2
        assert resume["nb_conformes"] == 2
        assert resume["lecture_seule"] is True
        assert alertes == []

    def test_stock_sous_seuil(self):
        variants_fn, stock_fn, freight_fn = make_fns({
            "1797521453382905856": 420,
            "1797521453454209024": 11347})
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["statut"] == "alertes"
        assert resume["nb_non_conformes"] == 1
        assert any("stock_sous_seuil" in a["alerte"] for a in alertes)
        assert all(a["gravite"] == "haute" for a in alertes)

    def test_derive_stock_affiche(self):
        """Stock CN 150 -> attendu 50 affiche ; FW affiche 100 (regle 9)."""
        variants_fn, stock_fn, freight_fn = make_fns({
            "1797521453382905856": 150,
            "1797521453454209024": 11347})
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert any("stock_affiche_derive" in a["alerte"] for a in alertes)

    def test_cout_hors_regle(self):
        chere = {"code": 200, "result": True, "data": [
            {"vid": "1797521453382905856", "variantSku": "CJJT205244501AZ",
             "variantSellPrice": "12.00"},
            {"vid": "1797521453454209024", "variantSku": "CJJT205244502BY",
             "variantSellPrice": "2.81"}]}
        variants_fn, stock_fn, freight_fn = make_fns(variantes=chere)
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert any("cout_hors_regle" in a["alerte"] for a in alertes)

    def test_marge_sous_multiple(self):
        pas_chers = [dict(r, prix_fw=5.0) for r in FW_RECORDS_REEL]
        variants_fn, stock_fn, freight_fn = make_fns()
        resume, alertes = run(daily.surveiller_catalogue_publie(
            pas_chers, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["nb_non_conformes"] == 2
        marges = [a for a in alertes if "marge_sous_multiple" in a["alerte"]]
        assert len(marges) == 2

    def test_variante_disparue(self):
        une_seule = {"code": 200, "result": True, "data": [
            {"vid": "1797521453382905856", "variantSku": "CJJT205244501AZ",
             "variantSellPrice": "2.81"}]}
        variants_fn, stock_fn, freight_fn = make_fns(variantes=une_seule)
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert any("variante_disparue" in a["alerte"] for a in alertes)
        assert any(a["catalog_watch"] == "CJJT205244502BY" for a in alertes)


# ------------------------------ erreurs CJ : fail-closed sans arret ----
class TestErreursCJ:
    def test_erreur_variants_isolee_fail_closed(self):
        variants_fn, stock_fn, freight_fn = make_fns(erreur_variants=True)
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["statut"] == "alertes"
        assert len(alertes) == 2
        assert all("controle_indisponible" in a["alerte"] for a in alertes)

    def test_erreur_stock_alerte_pas_invention(self):
        variants_fn, stock_fn, freight_fn = make_fns()
        freight_only = freight_fn

        async def stock_fn_err(vid):
            raise RuntimeError("CJ QPS")

        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn_err, freight_only,
            pays_marche=PAYS_MARCHE_TEST))
        assert any("stock_indisponible" in a["alerte"] for a in alertes)

    def test_erreur_fret_livraison_indisponible_marge_non_verifiable(self):
        """Devis CJ indisponible : la marge n'est JAMAIS validee par
        defaut - livraison inconnue, alerte par variante, pas d'arret."""
        variants_fn, stock_fn, freight_fn = make_fns(erreur_fret=True)
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["statut"] == "alertes"
        assert resume["nb_non_conformes"] == 2
        livraisons = [a for a in alertes
                      if "livraison_indisponible" in a["alerte"]]
        assert len(livraisons) == 2
        assert all(a["gravite"] == "moyenne" for a in livraisons)

    def test_freight_fn_absent_fail_closed_sans_reseau(self):
        """cj_freight_fn ABSENT : aucune requete fret, livraison
        inconnue -> marge non verifiable (fail-closed)."""
        variants_fn, stock_fn, _ = make_fns()
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn))
        assert resume["statut"] == "alertes"
        assert resume["nb_non_conformes"] == 2
        assert len([a for a in alertes
                    if "livraison_indisponible" in a["alerte"]]) == 2

    def test_fw_records_absent_amorce_seule(self):
        """Reconstruction vid_table impossible -> fw_records vide : la
        surveillance tourne sur l'amorce, la marge non verifiable est
        signalee (fail-closed), aucune exception."""
        variants_fn, stock_fn, freight_fn = make_fns()
        resume, alertes = run(daily.surveiller_catalogue_publie(
            None, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["nb_variantes"] == 2
        assert any("prix_boutique_indisponible" in a["alerte"]
                   for a in alertes)

    def test_table_vide_aucune_variante(self):
        variants_fn, stock_fn, freight_fn = make_fns()
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, {"table": {}}, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["statut"] == "aucune_variante"
        assert alertes == []


# ------------------- v5.8 : controle de marge strict (regle 8) ----
class TestMargeStrictV58:
    def test_reference_reelle_conforme(self):
        """Reference validee : cout 2,81 USD (2,51 EUR) + fret FR reel
        4,20 EUR -> 3x = 20,14 EUR <= 24,90 EUR : conforme."""
        variants_fn, stock_fn, freight_fn = make_fns()
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["statut"] == "conforme"
        assert alertes == []

    def test_marge_insuffisante_apres_livraison_reelle(self):
        """Prix 8,0 EUR >= 3x cout seul (7,55 EUR) : v5.7 (livraison
        0.0 par defaut) l'aurait declaree CONFORME. Avec la livraison
        reelle FR (4,20 EUR) : 3x (2,51 + 4,20) = 20,14 EUR > 8,0 ->
        marge insuffisante UNE FOIS la livraison comptee."""
        pas_chers = [dict(r, prix_fw=8.0) for r in FW_RECORDS_REEL]
        variants_fn, stock_fn, freight_fn = make_fns()
        resume, alertes = run(daily.surveiller_catalogue_publie(
            pas_chers, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        marges = [a for a in alertes if "marge_sous_multiple" in a["alerte"]]
        assert len(marges) == 2
        assert all(a["gravite"] == "haute" for a in marges)
        assert resume["nb_non_conformes"] == 2

    def test_pire_pays_alerte_info_sans_casser_conformite(self):
        """Fret CH 6,50 USD (5,82 EUR) : 3x (2,51 + 5,82) = 25,00 EUR
        > 24,90 EUR -> alerte INFO marge_pire_pays, mais conforme sur
        la France (3x (2,51 + 4,20) = 20,14 <= 24,90)."""
        variants_fn, stock_fn, freight_fn = make_fns(
            fret_usd_par_pays={"FR": 4.69, "CH": 6.50})
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["statut"] == "conforme"
        assert resume["nb_conformes"] == 2
        pire = [a for a in alertes if "marge_pire_pays" in a["alerte"]]
        assert len(pire) == 2
        assert all(a["gravite"] == "info" for a in pire)

    def test_prix_non_confirme_marge_non_verifiable(self):
        """Prix de source non confirmee (core.price, non baseprice) :
        marge NON verifiable - jamais conforme par defaut."""
        non_confirmes = [dict(r, prix_fw_source="core.price")
                         for r in FW_RECORDS_REEL]
        variants_fn, stock_fn, freight_fn = make_fns()
        resume, alertes = run(daily.surveiller_catalogue_publie(
            non_confirmes, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["nb_non_conformes"] == 2
        assert len([a for a in alertes
                     if "prix_boutique_non_confirme" in a["alerte"]]) == 2
        # aucune marge declaree conforme OU insuffisante : non verifiable
        assert not any("marge_sous_multiple" in a["alerte"] for a in alertes)

    def test_fret_non_conforme_ignore_pays(self):
        """Option fret hors regle (> 6 EUR ou > 15 jours) ignoree :
        pays sans option conforme -> fail-closed sur ce pays. La CH
        n'offre rien de conforme ici, la France reste la reference."""
        variants_fn, stock_fn, freight_fn = make_fns(
            fret_usd_par_pays={"FR": 4.69, "CH": 20.00})
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["statut"] == "conforme"
        assert not any("marge_pire_pays" in a["alerte"] for a in alertes)

    def test_pays_reference_sans_fret_fail_closed(self):
        """France sans option conforme : livraison de reference
        inconnue -> marge non verifiable (jamais 0 EUR)."""
        variants_fn, stock_fn, freight_fn = make_fns(
            fret_usd_par_pays={"FR": 20.00, "CH": 4.69})
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert resume["nb_non_conformes"] == 2
        assert len([a for a in alertes
                    if "livraison_indisponible" in a["alerte"]]) == 2


# ------------------------- reutilisation : appels CJ comptes exactement ----
class TestReutilisation:
    def test_comptage_exact_des_appels(self):
        """1 cj_variants par produit + 1 cj_stock par variante +
        1 cj_freight par (vid, pays du marche) = 1 + 2 + 4 = 7 appels.
        Chaque appel fret porte quantity=1 (devis unitaire reel)."""
        appels = []
        variants_fn, stock_fn, freight_fn = make_fns(appels=appels)
        run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
        assert appels.count(("variants", "1797521453303214080")) == 1
        assert len([a for a in appels if a[0] == "stock"]) == 2
        frets = [a for a in appels if a[0] == "fret"]
        assert len(frets) == 4   # 2 variantes x 2 pays (FR, CH)
        couples = {(vid, pays) for _, vid, pays in frets}
        assert couples == {("1797521453382905856", "FR"),
                           ("1797521453382905856", "CH"),
                           ("1797521453454209024", "FR"),
                           ("1797521453454209024", "CH")}
        assert len(appels) == 7

    def test_resume_uniquement_des_compteurs(self):
        variants_fn, stock_fn, freight_fn = make_fns()
        resume, alertes = run(daily.surveiller_catalogue_publie(
            FW_RECORDS_REEL, VID_TABLE_REEL, 0.895,
            variants_fn, stock_fn, freight_fn,
            pays_marche=PAYS_MARCHE_TEST))
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
class TestFwVariantRecordsV58:
    def test_capture_baseprice_source_confirmee(self, monkeypatch):
        """Structure FW reelle (03/11/2026) : core.pricing.baseprice
        fait foi ; core.price divergent est IGNORE au profit du
        baseprice (prix de vente reellement applique)."""
        detail = {"core": {"id": "18809643", "price": 19.9,
                            "pricing": {"baseprice": 24.9}},
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
        # le prix PRODUIT s'applique a CHAQUE variante (les variants[]
        # FW ne portent aucun prix propre - verifie en reel)
        assert all(r["prix_fw"] == 24.9 for r in recs)
        assert all(r["prix_fw_source"] == "pricing.baseprice"
                   for r in recs)
        assert recs[0]["stock_affiche_fw"] == 100
        assert recs[1]["stock_affiche_fw"] == 50

    def test_repli_core_price_signale_non_confirme(self, monkeypatch):
        """Sans baseprice, le repli core.price est capture mais marque
        NON CONFIRME : la surveillance traitera la marge comme non
        verifiable, jamais conforme par defaut."""
        detail = {"core": {"id": "18809643", "price": 24.9},
                  "variants": [{"uvid": "ZsKQFt", "sku": "CJJT205244501AZ",
                                "stock": 100}]}

        async def fake_get(pid):
            return detail

        monkeypatch.setattr(daily, "fw_get_product", fake_get)
        recs = run(daily.fw_variant_records([{"id": "18809643",
                                              "name": "p"}]))
        assert recs[0]["prix_fw"] == 24.9
        assert recs[0]["prix_fw_source"] == "core.price"

    def test_structure_sans_prix_ni_stock_ne_plante_pas(self, monkeypatch):
        detail = {"core": {}, "variants": [{"uvid": "Z", "sku": "SKU-X"}]}

        async def fake_get(pid):
            return detail

        monkeypatch.setattr(daily, "fw_get_product", fake_get)
        recs = run(daily.fw_variant_records([{"id": "1", "name": "p"}]))
        assert recs[0]["prix_fw"] is None
        assert recs[0]["prix_fw_source"] is None
        assert recs[0]["stock_affiche_fw"] is None


# --------------------------------------------- securite : lecture seule ----
class TestLectureSeuleV58:
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

    def test_cj_freight_injecte_dans_le_workflow(self):
        """Le bloc workflow passe le VRAI cj_freight (activite
        throtlee 1 req/s) : les devis de livraison sont reels, jamais
        inventes ni mis a 0."""
        src = inspect.getsource(daily.ShoplinousDailyWorkflow)
        assert "cj_freight_fn=cj_freight" in src


# ------------------------------------------ integration dans run() ----
class TestIntegrationWorkflowV58:
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

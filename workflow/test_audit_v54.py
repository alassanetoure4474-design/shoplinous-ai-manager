"""Tests pytest SHOPLINOUS audit global v5.4 (branche workflow-v5-fix4).

HONNETETE : non executes en local (aucun Python disponible ici).
EXECUTION REELLE via GitHub Actions sur workflow-v5-fix4.
Couverture v5.4 :
- audit_catalogue : 12 produits reels (11 demo + 1 publie), anomalies ;
- audit_vid_matches : couverture exacte SKU->vid, absents, ambigus ;
- audit_cj_variant : regles 1-2 (stock CN >= 1000, achat <= 8 EUR),
  structure reelle storageNum, vid introuvable ;
- audit_freight_by_quantity : fret CJ mesure quantites 1 a 5, options
  conformes (<= 6 EUR, <= 15 j), alerte multi-unites ;
- simulation_scenarios / simulate_order : 6 scenaris DONNEES FICTIVES
  etiquetees SIM- (valide, SKU absent, SKU ambigu, stock insuffisant,
  livraison non couverte, quantite > 5) - jamais de commandes reelles ;
- build_audit_report : verdict pret/non_pret, risques bloquants,
  actions manuelles, logique defectueuse BLOQUANTE ;
- audit_report_from_real_data : rapport complet depuis les donnees
  reelles du 02/11/2026 ;
- securite : aucune donnee personnelle, lecture seule, allow_publish
  inchang, aucune ecriture FW/CJ, aucun achat fournisseur.
"""
import json

import pytest

import audit_v54
import daily


RATE = 0.92   # taux explicite pour des tests deterministes


def _frets(audit_freight_par_sku, sku):
    """Extrait {quantite: prix_eur} de la meilleure option mesuree."""
    out = {}
    for q, fa in audit_freight_par_sku[sku].items():
        mo = fa.get("meilleure_option")
        if mo:
            out[q] = mo["prix_eur"]
    return out


class TestAuditCatalogue:
    def test_catalogue_reel_12_produits(self):
        res = audit_v54.audit_catalogue(audit_v54.REAL_DATA["catalogue"])
        assert res["nb_produits"] == 12
        assert res["anomalies"] == []
        assert len(res["publies"]) == 1
        assert len(res["demos"]) == 11
        assert res["autres"] == []
        p = res["publies"][0]
        assert p["id"] == "18809643"
        assert p["sku"] == "SHP-CJT2052445"
        assert p["prix"] == 24.90
        assert p["stock"] == 200
        assert p["demo"] is False

    def test_catalogue_detecte_sku_manquant(self):
        catalogue = [{"id": "1", "sku": "", "name": "x",
                      "abstract": "ok", "published": True,
                      "price": 10.0, "pricing": {"baseprice": 10.0},
                      "stock": 5}]
        res = audit_v54.audit_catalogue(catalogue)
        assert any("SKU absent" in a["anomalie"] for a in res["anomalies"])

    def test_catalogue_detecte_prix_incoherent(self):
        catalogue = [{"id": "2", "sku": "a", "name": "x",
                      "abstract": "ok", "published": False,
                      "price": 25.0,
                      "pricing": {"baseprice": 20.0,
                                  "discount": {"value": 10.0}},
                      "stock": 5}]
        res = audit_v54.audit_catalogue(catalogue)
        assert any("superieur au prix de base" in a["anomalie"]
                   for a in res["anomalies"])

    def test_catalogue_produit_mal_forme(self):
        res = audit_v54.audit_catalogue([{"pas": "d id"}, "junk", None])
        assert res["nb_produits"] == 0
        assert len(res["anomalies"]) == 3

    def test_catalogue_demo_publie_detectable(self):
        catalogue = [{"id": "3", "sku": "d1", "name": "demo",
                      "abstract": "This is a demo product. Edit.",
                      "published": True, "price": 5.0,
                      "pricing": {"baseprice": 5.0}, "stock": 1}]
        res = audit_v54.audit_catalogue(catalogue)
        assert res["demos"] and res["demos"][0]["publie"] is True


class TestAuditVidMatches:
    def test_couverture_exacte_reelle(self):
        res = audit_v54.audit_vid_matches(audit_v54.REAL_DATA["vid_table"],
                                          audit_v54.REAL_DATA["fw_records"])
        assert res["nb_variantes_fw"] == 2
        assert res["nb_correspondances_exactes"] == 2
        assert res["taux_couverture"] == 1.0
        assert res["skus_correspondus"] == ["CJJT205244501AZ",
                                            "CJJT205244502BY"]

    def test_absents_et_ambigus_signales(self):
        vid_table = {"table": {},
                     "absents": [{"variant_sku": "X1", "motif": "aucun"}],
                     "ambigus": [{"variant_sku": "X2",
                                  "candidats_vid": ["1", "2"]}],
                     "nb_variantes_fw": 2}
        res = audit_v54.audit_vid_matches(vid_table, [
            {"variant_sku": "X1"}, {"variant_sku": "X2"}])
        assert res["nb_correspondances_exactes"] == 0
        assert res["taux_couverture"] == 0.0
        assert len(res["absents"]) == 1 and len(res["ambigus"]) == 1


class TestAuditCjVariant:
    def test_variantes_reelles_conformes(self):
        for sku in ("CJJT205244501AZ", "CJJT205244502BY"):
            entry = {"sku": sku,
                     "vid": audit_v54.REAL_DATA["vid_table"]["table"][sku]["vid"]}
            res = audit_v54.audit_cj_variant(
                entry, audit_v54.REAL_DATA["cj_variants"],
                audit_v54.REAL_DATA["stocks"][sku], RATE)
            assert res["statut"] == "conforme", res
            assert res["anomalies"] == []
            assert res["stock_chine"] >= 1000
            assert res["prix_achat_eur"] == pytest.approx(2.81 * RATE, abs=0.01)
            assert res["poids_g"] == 80

    def test_stock_insuffisant_non_conforme(self):
        entry = {"sku": "CJJT205244501AZ", "vid": "1797521453382905856"}
        stock_faible = {"code": 200, "data": [
            {"countryCode": "CN", "storageNum": 5,
             "stock": [{"inventory": 0}]}]}
        res = audit_v54.audit_cj_variant(
            entry, audit_v54.REAL_DATA["cj_variants"], stock_faible, RATE)
        assert res["statut"] == "non_conforme"
        assert any("regle 1" in a for a in res["anomalies"])

    def test_achat_trop_cher_non_conforme(self):
        variantes_cheres = {"code": 200, "data": [
            {"vid": "1797521453382905856",
             "variantSku": "CJJT205244501AZ",
             "variantSellPrice": "30.0"}]}
        stock = audit_v54.REAL_DATA["stocks"]["CJJT205244501AZ"]
        res = audit_v54.audit_cj_variant(
            {"sku": "CJJT205244501AZ", "vid": "1797521453382905856"},
            variantes_cheres, stock, RATE)
        assert res["statut"] == "non_conforme"
        assert any("regle 2" in a for a in res["anomalies"])

    def test_sku_non_exact_signalé(self):
        variantes = {"code": 200, "data": [
            {"vid": "1797521453382905856",
             "variantSku": "CJJT205244501AZ",
             "variantSellPrice": "2.81"}]}
        res = audit_v54.audit_cj_variant(
            {"sku": "CJJT205244501", "vid": "1797521453382905856"},
            variantes, audit_v54.REAL_DATA["stocks"]["CJJT205244501AZ"],
            RATE)
        assert res["statut"] == "non_conforme"
        assert any("NON EXACTE" in a for a in res["anomalies"])

    def test_vid_introuvable(self):
        res = audit_v54.audit_cj_variant(
            {"sku": "X", "vid": "inconnu"},
            audit_v54.REAL_DATA["cj_variants"], {}, RATE)
        assert res["statut"] == "variante_introuvable"


class TestAuditFreight:
    def test_fret_mesure_quantites_1_a_5(self):
        for q in (1, 2, 3, 4, 5):
            fa = audit_v54.audit_freight_by_quantity(
                q, audit_v54.REAL_DATA["fret_fr"][q], RATE)
            assert fa["quantite"] == q
            mo = fa["meilleure_option"]
            attendu = {1: 4.69, 2: 5.65, 3: 6.62, 4: 7.58, 5: 8.54}[q]
            assert mo["option"] == "CJPacket Ordinary"
            assert mo["prix_eur"] == pytest.approx(attendu * RATE, abs=0.01)

    def test_options_conformes_unite_seule(self):
        fa1 = audit_v54.audit_freight_by_quantity(
            1, audit_v54.REAL_DATA["fret_fr"][1], RATE)
        # CJPacket Ordinary 4-10 j : conforme ; Eub 12-50 j et
        # Ordinary I 8-18 j : delai max > 15 j -> NON conformes.
        assert [c["option"] for c in fa1["conformes"]] == ["CJPacket Ordinary"]
        assert "alerte" not in fa1

    def test_alerte_multi_unites_hors_seuil(self):
        # quantites 3 a 5 : meilleure option > 6 EUR (rate 0.92)
        # -> alerte honnete, jamais de tarif invente
        for q in (3, 4, 5):
            fa = audit_v54.audit_freight_by_quantity(
                q, audit_v54.REAL_DATA["fret_fr"][q], RATE)
            assert fa["conformes"] == []
            assert "bande de quantite" in fa["alerte"]

    def test_options_invalides_ignorees(self):
        fa = audit_v54.audit_freight_by_quantity(1, [
            {"logisticPrice": "n/a", "logisticAging": "4-10"},
            {"logisticPrice": 5.0},
            {"logisticName": "ok", "logisticPrice": 5.0,
             "logisticAging": "4-10"},
        ], RATE)
        assert len(fa["options"]) == 1

    def test_quantite_superieure_a_cinq_acceptee_sans_tarif_invente(self):
        result = audit_v54.audit_freight_by_quantity(6, [], RATE)
        assert result["quantite"] == 6
        assert result["options"] == []
        assert result["conformes"] == []
        assert "quantite 6" in result["alerte"]


class TestSimulations:
    def test_six_scenarios_tous_fictifs(self):
        scenaris = audit_v54.simulation_scenarios(
            audit_v54.REAL_DATA["vid_table"])
        assert len(scenaris) == 6
        ids = {s["id"] for s in scenaris}
        assert all(i.startswith("SIM-") for i in ids)
        assert ids == {"SIM-VALIDE", "SIM-SKU-ABSENT", "SIM-SKU-AMBIGU",
                       "SIM-STOCK-INSUFFISANT",
                       "SIM-LIVRAISON-NON-COUVERTE",
                       "SIM-QUANTITE-SUPERIEURE-A-5"}

    def _frets_reels(self):
        per_sku = {sku: {q: audit_v54.audit_freight_by_quantity(
            q, opts, RATE)
            for q, opts in audit_v54.REAL_DATA["fret_fr"].items()}
            for sku in audit_v54.REAL_DATA["vid_table"]["table"]}
        return _frets(per_sku, sorted(
            audit_v54.REAL_DATA["vid_table"]["table"])[0])

    def test_sim_valide(self):
        s = next(x for x in audit_v54.simulation_scenarios(
            audit_v54.REAL_DATA["vid_table"]) if x["id"] == "SIM-VALIDE")
        res = audit_v54.simulate_order(s, audit_v54.REAL_DATA["vid_table"],
                                       freight_by_qty=self._frets_reels())
        assert res["simulation"] is True
        assert res["statut"] == "verifie"
        assert "FICTIVES" in res["donnees"]

    def test_sim_sku_absent(self):
        s = next(x for x in audit_v54.simulation_scenarios(
            audit_v54.REAL_DATA["vid_table"]) if x["id"] == "SIM-SKU-ABSENT")
        res = audit_v54.simulate_order(s, audit_v54.REAL_DATA["vid_table"],
                                       freight_by_qty=self._frets_reels())
        assert res["statut"] == "sans_vid"
        assert res["motif"] == "ABSENT"
        assert "verification manuelle" in res["action_manuelle"]

    def test_sim_sku_ambigu(self):
        s = next(x for x in audit_v54.simulation_scenarios(
            audit_v54.REAL_DATA["vid_table"]) if x["id"] == "SIM-SKU-AMBIGU")
        res = audit_v54.simulate_order(s, audit_v54.REAL_DATA["vid_table"],
                                       freight_by_qty=self._frets_reels())
        assert res["statut"] == "sans_vid"
        assert res["motif"] == "AMBIGUE"

    def test_sim_stock_insuffisant(self):
        s = next(x for x in audit_v54.simulation_scenarios(
            audit_v54.REAL_DATA["vid_table"])
            if x["id"] == "SIM-STOCK-INSUFFISANT")
        res = audit_v54.simulate_order(s, audit_v54.REAL_DATA["vid_table"],
                                       freight_by_qty=self._frets_reels())
        assert res["statut"] == "stock_insuffisant"
        assert res["stock_chine_simule"] == 5
        assert "regle 1" in res["motif"]
        assert "INTERDITE" in res["motif"]

    def test_sim_livraison_non_couverte(self):
        s = next(x for x in audit_v54.simulation_scenarios(
            audit_v54.REAL_DATA["vid_table"])
            if x["id"] == "SIM-LIVRAISON-NON-COUVERTE")
        res = audit_v54.simulate_order(s, audit_v54.REAL_DATA["vid_table"],
                                       freight_by_qty=self._frets_reels())
        assert res["statut"] == "livraison_non_couverte"
        assert "non couverte" in res["motif"]
        assert res["tarif_facture_eur"] == 0.0

    def test_sim_quantite_superieure_a_cinq_sans_fret_fourni(self):
        s = next(x for x in audit_v54.simulation_scenarios(
            audit_v54.REAL_DATA["vid_table"])
            if x["id"] == "SIM-QUANTITE-SUPERIEURE-A-5")
        res = audit_v54.simulate_order(s, audit_v54.REAL_DATA["vid_table"],
                                       freight_by_qty=self._frets_reels())
        assert res["statut"] == "fret_indisponible_en_simulation"
        assert "jamais invente" in res["motif"]

    def test_sim_fret_non_fourni_jamais_invente(self):
        s = next(x for x in audit_v54.simulation_scenarios(
            audit_v54.REAL_DATA["vid_table"]) if x["id"] == "SIM-VALIDE")
        res = audit_v54.simulate_order(s, audit_v54.REAL_DATA["vid_table"],
                                       freight_by_qty=None)
        assert res["statut"] == "fret_indisponible_en_simulation"
        assert "jamais invente" in res["motif"]


class TestBuildAuditReport:
    def _rapport_reel(self):
        return audit_v54.audit_report_from_real_data(RATE)

    def test_rapport_reel_verdict_non_pret(self):
        """Verdict honnete : zones de livraison NON configurees
        (postage reel 0.00 EUR) -> risque BLOQUANT -> non_pret."""
        r = self._rapport_reel()
        assert r["verdict"] == "non_pret"
        assert any("NON CONFIGURE" in rb for rb in r["risques_bloquants"])

    def test_rapport_reel_produit_compatible(self):
        r = self._rapport_reel()
        assert r["produits_compatibles"] == ["CJJT205244501AZ",
                                             "CJJT205244502BY"]
        assert r["produits_incompatibles"] == []
        assert r["correspondances_sku_vid"] == ["CJJT205244501AZ",
                                               "CJJT205244502BY"]

    def test_rapport_reel_simulations_toutes_conformes(self):
        """Les 6 simulations fictives produisent EXACTEMENT les statuts
        attendus : la logique de traitement est validee."""
        r = self._rapport_reel()
        assert len(r["simulations"]) == 6
        assert not any("DEFECTUEUSE" in rb for rb in r["risques_bloquants"])

    def test_rapport_reel_actions_manuelles(self):
        r = self._rapport_reel()
        am = " | ".join(r["actions_manuelles"])
        assert "aucune commande reelle" in am

    def test_rapport_verdict_pret_sans_bloquant(self):
        """Sans risque bloquant (tarif configure, tout conforme),
        le verdict est 'pret' (les alertes multi-unites restent des
        anomalies non bloquantes)."""
        r = audit_v54.audit_report_from_real_data(RATE)
        # reimagine le meme rapport avec un tarif checkout configure
        d = audit_v54.REAL_DATA
        catalogue_audit = audit_v54.audit_catalogue(d["catalogue"])
        vid_audit = audit_v54.audit_vid_matches(d["vid_table"],
                                                d["fw_records"])
        cj = []
        for sku, e in d["vid_table"]["table"].items():
            cj.append(audit_v54.audit_cj_variant(
                {"sku": sku, "vid": e["vid"], "cj_pid": e["cj_pid"]},
                d["cj_variants"], d["stocks"][sku], RATE))
        per_sku = {sku: {q: audit_v54.audit_freight_by_quantity(
            q, opts, RATE) for q, opts in d["fret_fr"].items()}
            for sku in d["vid_table"]["table"]}
        fa = {"par_quantite": per_sku, "erreurs": []}
        frets = _frets(per_sku, sorted(d["vid_table"]["table"])[0])
        sims = [audit_v54.simulate_order(s, d["vid_table"],
                                         freight_by_qty=frets)
                for s in audit_v54.simulation_scenarios(d["vid_table"])]
        r2 = audit_v54.build_audit_report(catalogue_audit, vid_audit, cj,
                                          fa, sims, {"found": 3}, 6.0)
        assert r2["verdict"] == "pret"
        assert r2["risques_bloquants"] == []

    def test_logique_defectueuse_bloquante(self):
        sims = [{"simulation": True, "scenario": "SIM-VALIDE",
                 "statut": "sans_vid", "motif": "bug"}]
        r = audit_v54.build_audit_report(
            {"anomalies": [], "publies": [], "demos": []},
            {"absents": [], "ambigus": []}, [], {"erreurs": []},
            sims, {"found": 0}, 6.0)
        assert r["verdict"] == "non_pret"
        assert any("DEFECTUEUSE" in rb for rb in r["risques_bloquants"])

    def test_sim_fret_manquant_action_manuelle_non_bloquante(self):
        sims = [{"simulation": True, "scenario": "SIM-VALIDE",
                 "statut": "fret_indisponible_en_simulation",
                 "motif": "fret manquant"}]
        r = audit_v54.build_audit_report(
            {"anomalies": [], "publies": [], "demos": []},
            {"absents": [], "ambigus": []}, [], {"erreurs": []},
            sims, {"found": 0}, 6.0)
        assert r["verdict"] == "pret"
        assert any("non verifiable" in a for a in r["actions_manuelles"])

    def test_demo_publie_bloquant(self):
        r = audit_v54.build_audit_report(
            {"anomalies": [], "publies": [], "demos": [{"publie": True}]},
            {"absents": [], "ambigus": []}, [], {"erreurs": []},
            [], {"found": 0}, 6.0)
        assert any("DEMO" in rb for rb in r["risques_bloquants"])


class TestSecuriteV54:
    def test_aucune_donnee_personnelle_dans_l_audit(self):
        r = audit_v54.audit_report_from_real_data(RATE)
        blob = json.dumps(r).lower()
        for interdit in ("anonyme", "email", "forename", "surname",
                         "telephone", "address1", "0000000000", "@"):
            assert interdit not in blob, interdit

    def test_simulations_jamais_presentees_comme_reelles(self):
        r = audit_v54.audit_report_from_real_data(RATE)
        for s in r["simulations"]:
            assert s["simulation"] is True
            assert "FICTIVES" in s["donnees"]
            assert str(s["scenario"]).startswith("SIM-")

    def test_audit_ne_modifie_rien(self):
        """Le module d'audit n'emmet AUCUN appel reseau : aucun httpx,
        aucune ecriture FW/CJ, aucun achat."""
        import inspect
        src = inspect.getsource(audit_v54)
        assert "httpx" not in src
        assert "AsyncClient" not in src
        for interdit in ("createOrder", "purchase", "payOrder",
                         "shopping/order", "requests.post"):
            assert interdit not in src, interdit

    def test_allow_publish_false_inchange(self):
        assert daily.DailyParams().allow_publish is False

    def test_regles_partagees_coherentes(self):
        assert audit_v54.MIN_STOCK_CN == daily.MIN_STOCK_CN == 1000
        assert audit_v54.MAX_COST_EUR == daily.MAX_COST_EUR
        assert audit_v54.MAX_SHIP_EUR == daily.MAX_SHIP_EUR
        assert audit_v54.MAX_ORDER_QTY == daily.MAX_ORDER_QTY == 5
        assert audit_v54.MAX_SHIP_DAYS == daily.MAX_SHIP_DAYS == 15

    def test_donnees_reelles_completes(self):
        """Les donnees de reference contiennent les mesures reelles du
        02/11/2026 : 12 produits, 2 variantes, stocks 11347/12657,
        fret 1-5 mesure, postage reel 0.00 EUR."""
        d = audit_v54.REAL_DATA
        assert len(d["catalogue"]) == 12
        assert len(d["fw_records"]) == 2
        assert d["stocks"]["CJJT205244501AZ"]["data"][0]["storageNum"] == 11347
        assert d["stocks"]["CJJT205244502BY"]["data"][0]["storageNum"] == 12657
        assert sorted(d["fret_fr"]) == [1, 2, 3, 4, 5]
        assert d["orders_found"] == 0
        assert d["checkout_shipping_eur"] is None

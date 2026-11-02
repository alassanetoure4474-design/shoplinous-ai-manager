"""Tests pytest SHOPLINOUS v5.6 (branche workflow-v5-fix7).

CORRECTIONS VERIFIEES :
1. Fiabilite du fret : la table utilise usd_15j (jamais usd, plus lent) ;
   aucune substitution silencieuse ; aucun transporteur <= 15 j =>
   statut aucun_transporteur_15j + "verification manuelle requise",
   AUCUN prix calcule.
2. Variantes blanche et noire : 255 tarifs par variante, 51 pays,
   identification (vid, sku, couleur, pays, quantite) ; AUCUN melange
   entre variantes ; echec de collecte => donnees precedentes conservees.
3. Expiration TTL 7 jours : un tarif expire n'est JAMAIS present comme
   actuel ; entree sans date => expiree.
4. Verifications : cout total = unitaire x quantite ; prix, benefice,
   marge, frais verifies par formule ; 255 = 51 pays x 5 quantites.

SECURITE : allow_publish=False ; module sans reseau direct (le reseau est
injecte via fetch_fn) ; daily.py non modifiee.

HONNETETE : non executes en local (aucun Python disponible ici).
EXECUTION REELLE via GitHub Actions sur workflow-v5-fix7.
"""

import json
import os
from datetime import date, timedelta

import pytest

import freight_collector_v56 as fc
import pricing_v55 as p55

TAUX = p55.EXCHANGE_RATE_USD_EUR
VID_B = fc.VID_BLANCHE
VID_N = fc.VID_NOIRE
DATE_COLLECTE = date(2026, 11, 2)


@pytest.fixture(scope="module")
def donnees():
    return fc.charger_donnees()


# ------------------------------------------------ donnees v5.6 (fix #2, #4) -
class TestDonneesV56:

    def test_deux_variantes_identifiees(self, donnees):
        rap = fc.rapport_variantes(donnees, aujourdhui=DATE_COLLECTE)
        assert set(rap) == {VID_B, VID_N}
        assert rap[VID_B]["couleur"] == "Blanc"
        assert rap[VID_B]["sku_variante"] == "CJJT205244501AZ"
        assert rap[VID_N]["couleur"] == "Noir"
        assert rap[VID_N]["sku_variante"] == "CJJT205244502BY"

    def test_255_tarifs_par_variante(self, donnees):
        # 255 = 51 pays x 5 quantites ; l'ecart annonce "255 vs 50 pays"
        # etait un decompte errone : il y a bien 51 pays.
        rap = fc.rapport_variantes(donnees, aujourdhui=DATE_COLLECTE)
        assert rap[VID_B]["nb_tarifs"] == 255
        assert rap[VID_N]["nb_tarifs"] == 255
        assert rap[VID_B]["nb_pays"] == 51
        assert rap[VID_N]["nb_pays"] == 51

    def test_aucun_doublon_par_variante(self, donnees):
        for var in donnees["variantes"]:
            cles = [(t["pays"], t["quantite"]) for t in var["tarifs"]]
            assert len(cles) == len(set(cles))

    def test_chaque_tarif_identifie_completement(self, donnees):
        for var in donnees["variantes"]:
            assert var["vid_cj"] and var["sku_variante"] and var["couleur"]
            for t in var["tarifs"]:
                assert t["pays"] and t["quantite"] in (1, 2, 3, 4, 5)
                assert t["usd"] > 0 and t["usd_15j"] > 0
                assert t["date_collecte"] == "2026-11-02"

    def test_aucun_tarif_expire_aujourdhui(self, donnees):
        rap = fc.rapport_variantes(donnees, aujourdhui=DATE_COLLECTE)
        assert rap[VID_B]["nb_expires"] == 0
        assert rap[VID_N]["nb_expires"] == 0

    def test_les_deux_variantes_ont_les_memes_51_pays(self, donnees):
        rap = fc.rapport_variantes(donnees, aujourdhui=DATE_COLLECTE)
        assert rap[VID_B]["pays"] == rap[VID_N]["pays"]
        assert len(rap[VID_B]["pays"]) == 51


# ------------------------------------------- fret 15 jours (fix #1) ---------
class TestFret15Jours:

    def test_table_utilise_usd_15j_pas_usd(self, donnees):
        # Noire MT q1 : usd 3.20 (12-50 j) vs usd_15j 8.55 (8-15 j).
        # La table DOIT contenir 8.55, jamais 3.20.
        ent = fc.table_frets_v56(donnees, VID_N)["entrees"]
        assert ent["MT"][1]["usd"] == 8.55
        assert ent["MT"][1]["usd"] != 3.20

    def test_aucune_substitution_silencieuse(self, donnees):
        # Blanche BE q1 : usd 5.31 (12-18 j) vs usd_15j 5.38 (4-12 j).
        # Le moteur doit payer 5.38, pas le moins cher plus lent.
        res = fc.compute_pricing_v56(2.81, VID_B, "BE", 1,
                                     donnees=donnees,
                                     aujourdhui=DATE_COLLECTE)
        assert res["statut"] == "recommandation_ok"
        assert res["fret"]["usd"] == 5.38

    def test_delai_du_tarif_choisi_toujours_conforme(self, donnees):
        for vid in (VID_B, VID_N):
            ent = fc.table_frets_v56(donnees, vid)["entrees"]
            for pays in ent:
                for q, t in ent[pays].items():
                    dmax = fc._delai_max(t["delai"])
                    if dmax is not None:
                        assert dmax <= 15

    def test_aucun_transporteur_15j_signalé_clairement(self):
        donnees = {"variantes": [{
            "vid_cj": VID_N, "sku_variante": "X", "couleur": "Noir",
            "tarifs": [{"pays": "ZZ", "quantite": 1, "usd": 3.0,
                        "canal": "Lent", "delai": "20-60",
                        "usd_15j": None, "date_collecte": "2026-11-02"}],
        }]}
        res = fc.compute_pricing_v56(2.81, VID_N, "ZZ", 1,
                                     donnees=donnees,
                                     aujourdhui=DATE_COLLECTE)
        assert res["statut"] == "aucun_transporteur_15j"
        assert res["verification_manuelle"] is True
        assert "verification manuelle requise" in res["message"]
        assert "calcul" not in res        # AUCUN prix calcule

    def test_delai_15j_incoherent_rejete_defensivement(self):
        donnees = {"variantes": [{
            "vid_cj": VID_N, "sku_variante": "X", "couleur": "Noir",
            "tarifs": [{"pays": "ZZ", "quantite": 1, "usd": 3.0,
                        "canal": "L", "delai": "20-60",
                        "usd_15j": 4.0, "canal_15j": "M",
                        "delai_15j": "5-25",       # > 15 j : douteux
                        "date_collecte": "2026-11-02"}],
        }]}
        res = fc.compute_pricing_v56(2.81, VID_N, "ZZ", 1,
                                     donnees=donnees,
                                     aujourdhui=DATE_COLLECTE)
        assert res["statut"] == "aucun_transporteur_15j"
        assert "calcul" not in res


# -------------------------------- isolation des variantes (fix #2) ----------
class TestIsolationVariantes:

    def test_moteur_refuse_la_table_de_l_autre_variante(self, donnees):
        # Table de la BLANCHE passee au moteur de la NOIRE : refus.
        table_b = fc.table_frets_v56(donnees, VID_B)
        res = fc.compute_pricing_v56(2.81, VID_N, "FR", 1, table=table_b,
                                     aujourdhui=DATE_COLLECTE)
        assert res["statut"] == "variante_inconnue"
        assert res["verification_manuelle"] is True
        assert "calcul" not in res

    def test_variante_inconnue_aucun_prix(self, donnees):
        res = fc.compute_pricing_v56(2.81, "1799999999999999999", "FR", 1,
                                     donnees=donnees,
                                     aujourdhui=DATE_COLLECTE)
        assert res["statut"] == "variante_inconnue"
        assert "calcul" not in res

    def test_tarifs_differents_par_variante_ne_se_melangent_pas(self, donnees):
        # Noire MT : option 15j a 8.55 ; blanche MT : 8.55 aussi mais le
        # canal releve doit rester celui de SA propre collecte.
        ent_b = fc.table_frets_v56(donnees, VID_B)["entrees"]
        ent_n = fc.table_frets_v56(donnees, VID_N)["entrees"]
        # BE : les deux variantes ont des tables distinctes par vid
        assert ent_b["BE"][1]["usd"] == 5.38
        assert ent_n["BE"][1]["usd"] == 5.38
        # le vid embarque dans chaque table interdit tout melange
        assert fc.table_frets_v56(donnees, VID_B)["vid"] == VID_B
        assert fc.table_frets_v56(donnees, VID_N)["vid"] == VID_N

    def test_statut_tarif_par_variante(self, donnees):
        assert fc.statut_tarif(donnees, VID_B, "FR", 1,
                               aujourdhui=DATE_COLLECTE) == "actif"
        assert fc.statut_tarif(donnees, VID_N, "FR", 1,
                               aujourdhui=DATE_COLLECTE) == "actif"
        assert fc.statut_tarif(donnees, "xxx", "FR", 1) == "variante_inconnue"


# ------------------------------------------- expiration (fix #3) ------------
class TestExpiration:

    def test_tarif_expire_jamais_actuel(self):
        vieux = date(2026, 10, 1)
        donnees = {"variantes": [{
            "vid_cj": VID_N, "sku_variante": "X", "couleur": "Noir",
            "tarifs": [{"pays": "FR", "quantite": 1, "usd": 4.0,
                        "canal": "L", "delai": "4-10",
                        "usd_15j": 4.0, "canal_15j": "M",
                        "delai_15j": "4-10",
                        "date_collecte": "2026-10-01"}],
        }]}
        aujourdhui = vieux + timedelta(days=8)     # > TTL 7 jours
        res = fc.compute_pricing_v56(2.81, VID_N, "FR", 1,
                                     donnees=donnees, aujourdhui=aujourdhui)
        assert res["statut"] == "expire"
        assert res["verification_manuelle"] is True
        assert "jamais present comme actuel" in res["message"]
        assert "verification manuelle requise" in res["message"]
        assert "calcul" not in res

    def test_entree_sans_date_est_expiree(self):
        assert fc.est_expire({"date_collecte": None}) is True
        assert fc.est_expire({}) is True

    def test_ttl_tout_juste_valide(self):
        assert fc.est_expire({"date_collecte": "2026-10-26"},
                             aujourdhui=date(2026, 11, 2)) is False
        assert fc.est_expire({"date_collecte": "2026-10-25"},
                             aujourdhui=date(2026, 11, 2)) is True


# -------------------------------- calculs commerciaux (fix #4) --------------
class TestCalculs:

    def test_cout_total_egale_unitaire_fois_quantite(self, donnees):
        res = fc.compute_pricing_v56(2.81, VID_N, "FR", 3,
                                     donnees=donnees,
                                     aujourdhui=DATE_COLLECTE)
        c = res["calcul"]
        assert res["statut"] == "recommandation_ok"
        assert c["cout_produit_unitaire_eur"] == round(2.81 * TAUX, 2)
        assert c["cout_produit_total_eur"] == round(
            c["cout_produit_unitaire_eur"] * 3, 2)
        # v5.5 (non corrige) aurait donne le cout unitaire seulement :
        assert c["cout_produit_total_eur"] != c["cout_produit_unitaire_eur"]

    def test_fret_conforme_15j_utilise(self, donnees):
        res = fc.compute_pricing_v56(2.81, VID_N, "FR", 1,
                                     donnees=donnees,
                                     aujourdhui=DATE_COLLECTE)
        assert res["fret"]["usd"] == 4.69
        assert res["fret"]["eur"] == round(4.69 * TAUX, 2)

    def test_formules_prix_marge_benefice(self, donnees):
        taux, fixe, marge = 0.02, 0.10, 0.20
        res = fc.compute_pricing_v56(2.81, VID_B, "FR", 2,
                                     donnees=donnees,
                                     frais_paiement_taux=taux,
                                     frais_paiement_fixe_eur=fixe,
                                     marge_min=marge,
                                     aujourdhui=DATE_COLLECTE)
        c = res["calcul"]
        attendu = round((c["cout_produit_total_eur"]
                         + c["frais_livraison_eur"] + fixe)
                        / (1 - taux - marge), 2)
        assert c["prix_vente_recommande_eur"] == attendu
        assert c["frais_paiement_eur"] == round(
            attendu * taux + fixe, 2)
        assert c["cout_total_eur"] == round(
            c["cout_produit_total_eur"] + c["frais_livraison_eur"]
            + c["frais_paiement_eur"], 2)
        assert c["benefice_estime_eur"] == round(
            attendu - c["cout_total_eur"], 2)
        assert abs(c["marge_pourcentage"] - marge * 100) <= 0.5
        assert res["statut"] == "recommandation_ok"

    def test_quantites_invalides_et_plafond(self, donnees):
        for q in (0, -1, 6, "2", 2.5, True):
            res = fc.compute_pricing_v56(2.81, VID_B, "FR", q,
                                         donnees=donnees,
                                         aujourdhui=DATE_COLLECTE)
            assert res["statut"] in ("quantite_invalide", "depasse_plafond")
            assert "calcul" not in res

    def test_destination_inconnue(self, donnees):
        res = fc.compute_pricing_v56(2.81, VID_B, "ZZ", 1,
                                     donnees=donnees,
                                     aujourdhui=DATE_COLLECTE)
        assert res["statut"] == "destination_inconnue"
        assert "verification manuelle requise" in res["message"]
        assert "calcul" not in res

    def test_cout_invalide_et_parametres_invalides(self, donnees):
        res = fc.compute_pricing_v56(0, VID_B, "FR", 1, donnees=donnees,
                                     aujourdhui=DATE_COLLECTE)
        assert res["statut"] == "cout_invalide"
        res = fc.compute_pricing_v56(2.81, VID_B, "FR", 1, donnees=donnees,
                                     frais_paiement_taux=0.9,
                                     marge_min=0.2,
                                     aujourdhui=DATE_COLLECTE)
        assert res["statut"] == "parametres_invalides"


# ------------------------------- collecte : echec conserve (fix #2) ---------
class TestCollecteConserveEnEchec:

    def test_echec_collecte_conserve_les_donnees_precedentes(self):
        donnees = {"variantes": [{
            "vid_cj": VID_N, "sku_variante": "X", "couleur": "Noir",
            "tarifs": [{"pays": "FR", "quantite": 1, "usd": 4.69,
                        "canal": "A", "delai": "4-10",
                        "usd_15j": 4.69, "canal_15j": "A",
                        "delai_15j": "4-10",
                        "date_collecte": "2026-11-02"}],
        }]}

        def fetch_qui_echoue(vid, pays, q):
            raise RuntimeError("reseau indisponible")

        rapport = fc.collecte_v56(fetch_qui_echoue, ["FR"], donnees, VID_N,
                                  "X", "Noir", aujourdhui=DATE_COLLECTE)
        assert rapport["collectes"] == 0
        assert rapport["conserves"] == 1
        # l'entree precedente est INCHANGEE
        t = donnees["variantes"][0]["tarifs"][0]
        assert t["usd"] == 4.69 and t["date_collecte"] == "2026-11-02"

    def test_succes_collecte_remplace_pour_la_variante_demandee(self):
        donnees = {"variantes": [{
            "vid_cj": VID_N, "sku_variante": "X", "couleur": "Noir",
            "tarifs": [{"pays": "FR", "quantite": 1, "usd": 4.69,
                        "canal": "A", "delai": "4-10",
                        "usd_15j": 4.69, "canal_15j": "A",
                        "delai_15j": "4-10",
                        "date_collecte": "2026-10-01"}],
        }]}

        def fetch(vid, pays, q):
            assert vid == VID_N
            return [{"logisticName": "B", "logisticAging": "3-7",
                     "logisticPrice": 9.99},
                    {"logisticName": "C", "logisticAging": "4-10",
                     "logisticPrice": 5.55}]

        rapport = fc.collecte_v56(fetch, ["FR"], donnees, VID_N,
                                  "X", "Noir", aujourdhui=DATE_COLLECTE)
        assert rapport["collectes"] == 1
        t = donnees["variantes"][0]["tarifs"][0]
        assert t["usd"] == 5.55           # le moins cher
        assert t["usd_15j"] == 5.55       # le moins cher conforme 15 j
        assert t["date_collecte"] == "2026-11-02"
        assert t["delai_15j"] == "4-10"

    def test_collecte_ne_touche_jamais_les_autres_variantes(self):
        donnees = {"variantes": [
            {"vid_cj": VID_B, "sku_variante": "B", "couleur": "Blanc",
             "tarifs": [{"pays": "FR", "quantite": 1, "usd": 4.69,
                         "canal": "A", "delai": "4-10", "usd_15j": 4.69,
                         "date_collecte": "2026-11-02"}]},
            {"vid_cj": VID_N, "sku_variante": "N", "couleur": "Noir",
             "tarifs": []},
        ]}

        def fetch(vid, pays, q):
            assert vid == VID_N
            return [{"logisticName": "B", "logisticAging": "4-10",
                     "logisticPrice": 5.0}]

        fc.collecte_v56(fetch, ["FR"], donnees, VID_N, "N", "Noir",
                        aujourdhui=DATE_COLLECTE)
        # la variante blanche est intacte
        tb = donnees["variantes"][0]["tarifs"][0]
        assert tb["usd"] == 4.69 and len(donnees["variantes"][0]["tarifs"]) == 1
        # la noire a ete collectee
        tn = donnees["variantes"][1]["tarifs"][0]
        assert tn["usd_15j"] == 5.0 and tn["pays"] == "FR"


# --------------------------------------------------------------- securite ---
class TestSecurite:

    def test_allow_publish_false(self):
        assert fc.ALLOW_PUBLISH is False
        assert p55.ALLOW_PUBLISH is False

    def test_module_sans_reseau_direct(self):
        chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "freight_collector_v56.py")
        with open(chemin, "r", encoding="utf-8") as f:
            source = f.read()
        for interdit in ("import requests", "import httpx", "import urllib",
                         "import socket", "import subprocess"):
            assert interdit not in source

    def test_daily_non_modifiee(self):
        chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "daily.py")
        with open(chemin, "r", encoding="utf-8") as f:
            source = f.read()
        assert "allow_publish: bool = False" in source
        assert "freight_collector_v56" not in source

    def test_schema_v56(self, donnees):
        assert donnees["schema_version"] == "5.6"
        assert fc.SCHEMA_V56 == "5.6"

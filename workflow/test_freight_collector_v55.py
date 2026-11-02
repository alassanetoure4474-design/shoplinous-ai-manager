"""Tests pytest SHOPLINOUS v5.5 (chantier complementaire, branche
workflow-v5-fix6) - collecteur de tarifs CJ et moteur de prix corrige.

HONNETETE : non executes en local (aucun Python disponible ici).
EXECUTION REELLE via GitHub Actions sur workflow-v5-fix6.

Couverture :
- donnees reelles collectees : 30 pays Europe (regle UE27+GB/CH/NO,
  Malte documente) + 21 destinations mondiales, quantites 1 a 5 ;
- regle 3 : 29 pays europeens conformes, Malte non conforme (reel) ;
- expiration des tarifs (TTL 7 jours) et actualisation automatique ;
- cache (aucun rappel reseau pour une entree fraiche), reprise sur erreur,
  limitation de debit (sleep avant chaque appel), JAMAIS d'estimation ;
- moteur v5.5.1 corrige : cout total = cout unitaire x quantite.
"""

import json
import os

import pytest

import freight_collector_v55 as fc
import pricing_v55 as p55

UE27_GB_CH_NO = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE", "GB", "CH", "NO",
}


@pytest.fixture()
def donnees():
    # Copie profonde : chaque test peut muter ses donnees sans effet de bord.
    import copy
    return copy.deepcopy(fc.charger_donnees())


# ------------------------------------------------ donnees reelles --------
class TestDonneesReelles:
    def test_255_tarifs_51_pays(self, donnees):
        tarifs = donnees["tarifs"]
        assert len(tarifs) == 255
        pays = {t["pays"] for t in tarifs}
        assert len(pays) == 51

    def test_30_pays_europe_regle_actuelle(self, donnees):
        pays = {t["pays"] for t in donnees["tarifs"]}
        assert set(fc.EUROPE_30) == UE27_GB_CH_NO
        assert len(fc.EUROPE_30) == 30
        assert set(fc.EUROPE_30) <= pays

    def test_chaque_pays_5_quantites(self, donnees):
        par_pays = {}
        for t in donnees["tarifs"]:
            par_pays.setdefault(t["pays"], set()).add(t["quantite"])
        for pays, qs in par_pays.items():
            assert qs == {1, 2, 3, 4, 5}, pays

    def test_21_destinations_mondiales(self, donnees):
        assert len(fc.MONDE_21) == 21
        pays = {t["pays"] for t in donnees["tarifs"]}
        assert set(fc.MONDE_21) <= pays

    def test_champs_complets_et_dates(self, donnees):
        for t in donnees["tarifs"]:
            assert isinstance(t["usd"], (int, float)) and t["usd"] > 0, t
            assert t["canal"], t
            assert t["delai"] and "-" in t["delai"], t
            assert t["date_collecte"] == "2026-11-02", t
            if t.get("usd_15j") is not None:
                assert t["usd_15j"] > 0, t

    def test_produit_et_variante_stocks(self, donnees):
        assert donnees["produit"]["pid_cj"] == "1797521453303214080"
        assert donnees["variante"]["vid_cj"] == "1797521453382905856"
        assert donnees["variante"]["sku_variante"] == "CJJT205244501AZ"
        assert donnees["taux_change"]["usd_eur"] == 0.89509

    def test_regles_daily_toutes_couvertes(self, donnees):
        import daily
        pays = {t["pays"] for t in donnees["tarifs"]}
        for pays_regle in daily.DEST_COUNTRIES:
            assert pays_regle in pays, pays_regle


# -------------------------------------------------- regle 3 ---------------
class TestRegle3:
    def test_29_pays_conformes_malte_exclu(self, donnees):
        rapport = fc.rapport_couverture(donnees, aujourdhui="2026-11-02")
        # Regle 3 a la quantite de reference 1 (validation du 01/11/2026) :
        # 29 pays conformes, Malte exclu (option <= 15 j a 8.55 USD > 6 EUR).
        assert len(rapport["europe_30_regle3_conformes_q1"]) == 29
        assert rapport["europe_30_regle3_non_conformes_q1"] == ["MT"]
        assert "MT" not in rapport["europe_30_regle3_conformes_q1"]
        # HONNETETE : sur les quantites 1 a 5, seuls GB et PL restent
        # <= 6 EUR (fret croissant avec la quantite, donnees reelles).
        assert rapport["europe_30_regle3_conformes_q1_a_5"] == ["GB", "PL"]

    def test_malte_option_15j_trop_chere(self, donnees):
        index = fc._index_tarifs(donnees)
        mt = index[("MT", 1)]
        assert mt["usd_15j"] == 8.55        # reellement releve
        assert not fc.est_conforme_regle3(mt)   # 8.55 USD > 6 EUR

    def test_france_conforme(self, donnees):
        index = fc._index_tarifs(donnees)
        # FR : conforme a la quantite de reference 1 (4.69 USD = 4.20 EUR
        # <= 6 EUR) et jusqu'a q3 (6.62 USD = 5.93 EUR).
        for q in (1, 2, 3):
            assert fc.est_conforme_regle3(index[("FR", q)]), q
        # HONNETETE : a partir de q4 le fret reel depasse la regle 3
        # (7.58 USD = 6.79 EUR ; 8.54 USD = 7.64 EUR) : alerte a prevoir
        # cote checkout (bandes de quantite), aucune donnee masquee.
        assert index[("FR", 4)]["usd_15j"] == 7.58
        assert index[("FR", 5)]["usd_15j"] == 8.54
        assert not fc.est_conforme_regle3(index[("FR", 4)])
        assert not fc.est_conforme_regle3(index[("FR", 5)])


# ------------------------------------------------ couverture -------------
class TestCouverture:
    def test_rapport_complet(self, donnees):
        rapport = fc.rapport_couverture(donnees, aujourdhui="2026-11-02")
        assert len(rapport["pays_couverts_q1_a_5"]) == 51
        assert rapport["non_desservis"] == []
        assert rapport["pays_partiels"] == []
        assert len(rapport["destinations_mondiales_couvertes"]) == 21
        assert rapport["tarifs_expires"] == []


# ------------------------------------------------ expiration -------------
class TestExpiration:
    def test_frais_avant_ttl(self, donnees):
        magasin = fc.MagasinTarifs(donnees, aujourdhui="2026-11-08")
        assert magasin.statut("FR", 1) == "frais"

    def test_expire_apres_ttl_7_jours(self, donnees):
        magasin = fc.MagasinTarifs(donnees, aujourdhui="2026-11-10")
        assert magasin.statut("FR", 1) == "expire"
        rapport = fc.rapport_couverture(donnees, aujourdhui="2026-11-10")
        assert "FR" in rapport["tarifs_expires"]

    def test_entree_sans_date_expiree(self):
        assert fc.est_expire({"usd": 4.0}, aujourdhui="2026-11-02") is True


# ------------------------------------------------ collecte ---------------
class TestCollecte:
    def _options_bidon(self, prix=4.69):
        return [
            {"logisticPrice": prix, "logisticName": "Canal A", "logisticAging": "4-10"},
            {"logisticPrice": prix + 3, "logisticName": "Canal B", "logisticAging": "20-50"},
        ]

    def test_cache_aucun_appel_si_frais(self, donnees):
        appels = []

        def fetch(pays, q):
            appels.append((pays, q))
            return self._options_bidon()

        res = fc.collecte(fetch, ["FR"], donnees, aujourdhui="2026-11-03")
        assert res["appels_reseau"] == 0
        assert res["cache_hits"] == 5
        assert appels == []

    def test_actualisation_si_expire(self, donnees):
        appels = []

        def fetch(pays, q):
            appels.append((pays, q))
            return self._options_bidon(4.99)

        res = fc.collecte(fetch, ["FR"], donnees, aujourdhui="2026-11-10")
        assert res["appels_reseau"] == 5
        index = fc._index_tarifs(res["donnees"])
        assert index[("FR", 1)]["usd"] == 4.99
        assert index[("FR", 1)]["date_collecte"] == "2026-11-10"

    def test_pays_absent_collecte(self):
        donnees = {"tarifs": []}

        def fetch(pays, q):
            return self._options_bidon()

        res = fc.collecte(fetch, ["PL"], donnees, aujourdhui="2026-11-02")
        assert res["appels_reseau"] == 5
        index = fc._index_tarifs(res["donnees"])
        assert index[("PL", 1)]["usd"] == 4.69
        assert index[("PL", 1)]["usd_15j"] == 4.69
        assert index[("PL", 3)]["canal"] == "Canal A"

    def test_echec_definitif_jamais_estime(self):
        donnees = {"tarifs": []}

        def fetch(pays, q):
            raise RuntimeError("erreur CJ")

        res = fc.collecte(fetch, ["XX"], donnees, aujourdhui="2026-11-02",
                          tentatives=2)
        assert res["appels_reseau"] == 10          # 5 quantites x 2 tentatives
        assert len(res["echecs"]) == 5
        index = fc._index_tarifs(res["donnees"])
        assert ("XX", 1) not in index              # AUCUN tarif invente

    def test_aucune_option_est_en_echec(self):
        donnees = {"tarifs": []}

        def fetch(pays, q):
            return []

        res = fc.collecte(fetch, ["ZZ"], donnees, aujourdhui="2026-11-02")
        assert len(res["echecs"]) == 5
        assert "aucune option" in res["echecs"][0]["motif"]

    def test_reprise_sur_erreur_deux_fois_puis_succes(self):
        donnees = {"tarifs": []}
        essais = []

        def fetch(pays, q):
            essais.append((pays, q))
            if len(essais) < 3:
                raise RuntimeError("panne reseau")
            return self._options_bidon()

        # Une seule quantite : les 2 premiers appels echouent, le 3e
        # reussit -> exactement 3 appels reseau (reprise sur erreur).
        res = fc.collecte(fetch, ["PL"], donnees, aujourdhui="2026-11-02",
                          quantites=[1], tentatives=3)
        assert res["appels_reseau"] == 3
        assert res["echecs"] == []
        index = fc._index_tarifs(res["donnees"])
        assert index[("PL", 1)]["usd"] == 4.69

    def test_limitation_debit_sleep_avant_chaque_appel(self):
        donnees = {"tarifs": []}
        compte = {"fetch": 0, "sleep": 0}

        def fetch(pays, q):
            compte["fetch"] += 1
            return self._options_bidon()

        def sleep():
            compte["sleep"] += 1

        res = fc.collecte(fetch, ["PL"], donnees, aujourdhui="2026-11-02",
                          sleep_fn=sleep)
        # 5 quantites collectees : chaque appel reseau est precede d'un
        # sleep (limitation de debit QPS CJ 1 req/s).
        assert compte["fetch"] == 5
        assert compte["sleep"] == 5
        assert res["appels_reseau"] == 5


# ------------------------------------------------ choisir_option ---------
class TestChoisirOption:
    def test_minimum_et_minimum_15j(self):
        options = [
            {"logisticPrice": 3.0, "logisticName": "Lent", "logisticAging": "20-60"},
            {"logisticPrice": 5.0, "logisticName": "Rapide", "logisticAging": "4-10"},
            {"logisticPrice": 6.0, "logisticName": "Moyen", "logisticAging": "7-15"},
        ]
        mini, mini15 = fc.choisir_option(options)
        assert mini["usd"] == 3.0 and mini["canal"] == "Lent"
        assert mini15["usd"] == 5.0 and mini15["canal"] == "Rapide"

    def test_aucune_option(self):
        assert fc.choisir_option([]) == (None, None)
        assert fc.choisir_option(None) == (None, None)

    def test_prix_invalide_ignore(self):
        options = [{"logisticPrice": "x", "logisticName": "A", "logisticAging": "4-9"}]
        assert fc.choisir_option(options) == (None, None)


# --------------------------------- moteur corrige v5.5.1 -----------------
class TestMoteurV551:
    def test_cout_multiplie_par_quantite_fr_q3(self, donnees):
        r = fc.compute_pricing_v551(2.81, "FR", 3, donnees=donnees,
                                    marge_min=0.20)
        assert r["statut"] == "recommandation_ok"
        c = r["calcul"]
        assert c["cout_produit_unitaire_eur"] == 2.52
        assert c["cout_produit_total_eur"] == 7.56       # 2.52 x 3
        assert c["frais_livraison_eur"] == 5.93
        assert c["prix_vente_recommande_eur"] == 16.86
        assert c["benefice_estime_eur"] == 3.37
        assert c["marge_pourcentage"] == 19.99

    def test_fr_q5(self, donnees):
        r = fc.compute_pricing_v551(2.81, "FR", 5, donnees=donnees,
                                    marge_min=0.20)
        c = r["calcul"]
        assert c["cout_produit_total_eur"] == 12.60     # 2.52 x 5
        assert c["prix_vente_recommande_eur"] == 25.30
        assert c["benefice_estime_eur"] == 5.06
        assert c["marge_pourcentage"] == 20.0

    def test_fr_q3_avec_frais_paiement(self, donnees):
        r = fc.compute_pricing_v551(2.81, "FR", 3, donnees=donnees,
                                    frais_paiement_taux=0.029,
                                    frais_paiement_fixe_eur=0.30,
                                    marge_min=0.20)
        c = r["calcul"]
        assert c["prix_vente_recommande_eur"] == 17.89
        assert c["frais_paiement_eur"] == 0.82
        assert c["benefice_estime_eur"] == 3.58
        assert c["marge_pourcentage"] == 20.01

    def test_pays_non_dans_real_freight_via_table(self, donnees):
        # PL absent de p55.REAL_FREIGHT (7 pays) mais present dans la table
        # des 51 pays collectes.
        assert "PL" not in p55.REAL_FREIGHT
        r = fc.compute_pricing_v551(2.81, "PL", 1, donnees=donnees,
                                    marge_min=0.20)
        assert r["statut"] == "recommandation_ok"
        c = r["calcul"]
        assert c["frais_livraison_eur"] == 2.87
        assert c["prix_vente_recommande_eur"] > c["cout_total_eur"]
        assert c["marge_pourcentage"] >= 19.5

    def test_q1_identique_a_v5_5(self, donnees):
        r = fc.compute_pricing_v551(2.81, "FR", 1, donnees=donnees,
                                    frais_paiement_taux=0.029,
                                    frais_paiement_fixe_eur=0.30,
                                    marge_min=0.20)
        c = r["calcul"]
        assert c["prix_vente_recommande_eur"] == 9.11
        assert c["benefice_estime_eur"] == 1.83
        assert c["marge_pourcentage"] == 20.09

    def test_erreurs(self, donnees):
        assert fc.compute_pricing_v551(2.81, "FR", 6, donnees=donnees)[
            "statut"] == "depasse_plafond"
        assert fc.compute_pricing_v551(2.81, "XX", 1, donnees=donnees)[
            "statut"] == "tarif_indisponible"
        assert fc.compute_pricing_v551(0, "FR", 1, donnees=donnees)[
            "statut"] == "cout_invalide"
        assert fc.compute_pricing_v551(2.81, "FR", 1, donnees=donnees,
                                       marge_min=0)["statut"] == \
            "parametres_invalides"

    def test_marge_respectee_51_pays(self, donnees):
        table = fc.table_frets(donnees)
        for pays in table:
            for q in range(1, 6):
                r = fc.compute_pricing_v551(2.81, pays, q, table=table,
                                            marge_min=0.20)
                assert r["statut"] == "recommandation_ok", (pays, q)
                assert r["calcul"]["marge_pourcentage"] >= 19.5, (pays, q)
                assert r["calcul"]["prix_vente_recommande_eur"] >= \
                    r["calcul"]["cout_produit_total_eur"] + \
                    r["calcul"]["frais_livraison_eur"], (pays, q)


# ------------------------------------------------ securite ---------------
class TestSecurite:
    def test_allow_publish_false(self):
        assert fc.ALLOW_PUBLISH is False
        assert p55.ALLOW_PUBLISH is False

    def test_module_sans_reseau(self):
        chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "freight_collector_v55.py")
        with open(chemin, "r", encoding="utf-8") as f:
            source = f.read()
        for interdit in ("import requests", "import httpx", "import urllib",
                         "import socket", "import subprocess"):
            assert interdit not in source

    def test_jamais_d_estimation_dans_les_donnees(self, donnees):
        for t in donnees["tarifs"]:
            assert t["usd"] is not None and t["usd"] > 0
            # chaque tarif porte sa date de collecte reelle
            assert t["date_collecte"] == "2026-11-02"

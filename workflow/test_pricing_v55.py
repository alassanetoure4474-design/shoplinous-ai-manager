"""Tests pytest SHOPLINOUS v5.5 - moteur de prix (branche workflow-v5-fix5b).

HONNETETE : non executes en local (aucun Python disponible ici).
EXECUTION REELLE via GitHub Actions sur workflow-v5-fix5b.
Couverture v5.5 :
- quantites 1 a 5, > 5 (depasse_plafond + verification manuelle), invalides ;
- destinations mesurees (FR, GB, US, CI, BR, AU, CN) et inconnues ;
- tarifs manquants : aucune extrapolation, verification manuelle ;
- calcul commercial complet avec frais de paiement et marge minimale ;
- livraison gratuite integree au prix (fret reel pour SHOPLINOUS) ;
- securite : aucun reseau, allow_publish=False, aucun prix calcule hors donnees.
"""

import os

import pytest

import pricing_v55 as p


# ---------------------------------------------------------------- Quantites
class TestQuantites:
    def test_q1_a_5_ok(self):
        for q in range(1, 6):
            r = p.compute_pricing(2.81, "FR", q)
            assert r["statut"] == "recommandation_ok", q

    def test_q6_depasse_plafond(self):
        r = p.compute_pricing(2.81, "FR", 6)
        assert r["statut"] == "depasse_plafond"
        assert r["verification_manuelle"] is True
        assert "QUANTITE_SUPERIEURE_A_5" in r["message"]
        assert "calcul" not in r

    def test_q10_depasse_plafond(self):
        r = p.compute_pricing(2.81, "US", 10)
        assert r["statut"] == "depasse_plafond"
        assert r["verification_manuelle"] is True

    def test_q0_invalide(self):
        r = p.compute_pricing(2.81, "FR", 0)
        assert r["statut"] == "quantite_invalide"
        assert r["verification_manuelle"] is True

    def test_q_negative_invalide(self):
        assert p.compute_pricing(2.81, "FR", -2)["statut"] == "quantite_invalide"

    def test_q_float_invalide(self):
        assert p.compute_pricing(2.81, "FR", 2.5)["statut"] == "quantite_invalide"

    def test_q_bool_invalide(self):
        assert p.compute_pricing(2.81, "FR", True)["statut"] == "quantite_invalide"


# ------------------------------------------------------------ Destinations
class TestDestinations:
    def test_7_destinations_mesurees(self):
        for pays in p.REAL_FREIGHT:
            for q in range(1, 6):
                quote = p.get_freight_quote(pays, q)
                assert quote is not None, (pays, q)
                assert quote["usd"] > 0

    def test_regions(self):
        assert p.REGIONS["FR"] == "europe"
        assert p.REGIONS["GB"] == "europe"
        assert p.REGIONS["US"] == "amerique_du_nord"
        assert p.REGIONS["CI"] == "afrique"
        assert p.REGIONS["BR"] == "amerique_du_sud"
        assert p.REGIONS["AU"] == "oceanie"
        assert p.REGIONS["CN"] == "asie"

    def test_destination_inconnue(self):
        r = p.compute_pricing(2.81, "XX", 1)
        assert r["statut"] == "tarif_indisponible"
        assert r["verification_manuelle"] is True
        assert "TARIF_INDISPONIBLE" in r["message"]
        assert "calcul" not in r

    def test_destination_minuscule(self):
        r = p.compute_pricing(2.81, "fr", 1)
        assert r["statut"] == "recommandation_ok"

    def test_quantite_manquante_table_partielle(self):
        table = {"FR": {1: {"usd": 4.69, "canal": "CJPacket Ordinary", "delai": "4-10"}}}
        assert p.get_freight_quote("FR", 1, table=table) is not None
        assert p.get_freight_quote("FR", 3, table=table) is None

    def test_cn_tarif_plat(self):
        for q in range(1, 6):
            quote = p.get_freight_quote("CN", q)
            assert quote["usd"] == 1.43
            assert quote["canal"] == "YTO China Domestic"


# ------------------------------------------------------- Calcul commercial
class TestCalculCommercial:
    def test_fr_q1_avec_frais_paiement(self):
        r = p.compute_pricing(2.81, "FR", 1,
                              frais_paiement_taux=0.029,
                              frais_paiement_fixe_eur=0.30,
                              marge_min=0.20)
        assert r["statut"] == "recommandation_ok"
        c = r["calcul"]
        assert c["cout_produit_eur"] == 2.52
        assert c["frais_livraison_eur"] == 4.20
        assert c["frais_paiement_eur"] == 0.56
        assert c["cout_total_eur"] == 7.28
        assert c["prix_vente_recommande_eur"] == 9.11
        assert c["benefice_estime_eur"] == 1.83
        assert c["marge_pourcentage"] == 20.09

    def test_fr_q1_sans_frais_paiement(self):
        r = p.compute_pricing(2.81, "FR", 1, marge_min=0.20)
        c = r["calcul"]
        assert c["prix_vente_recommande_eur"] == 8.40
        assert c["benefice_estime_eur"] == 1.68
        assert c["marge_pourcentage"] == 20.0

    def test_gb_q1_sans_frais(self):
        r = p.compute_pricing(2.81, "GB", 1, marge_min=0.20)
        c = r["calcul"]
        assert c["frais_livraison_eur"] == 3.29
        assert c["prix_vente_recommande_eur"] == 7.26
        assert c["marge_pourcentage"] >= 19.5

    def test_marge_respectee_toutes_destinations(self):
        for pays in p.REAL_FREIGHT:
            for q in range(1, 6):
                r = p.compute_pricing(2.81, pays, q, marge_min=0.20)
                assert r["statut"] == "recommandation_ok", (pays, q)
                assert r["calcul"]["marge_pourcentage"] >= 19.5, (pays, q)

    def test_fret_croissant_par_quantite(self):
        frets = [p.compute_pricing(2.81, "FR", q)["calcul"]["frais_livraison_eur"]
                 for q in range(1, 6)]
        assert frets == [4.20, 5.06, 5.93, 6.78, 7.64]
        assert frets == sorted(frets)

    def test_prix_integre_le_fret(self):
        for pays in p.REAL_FREIGHT:
            for q in range(1, 6):
                c = p.compute_pricing(2.81, pays, q)["calcul"]
                assert c["prix_vente_recommande_eur"] >= \
                    c["cout_produit_eur"] + c["frais_livraison_eur"], (pays, q)

    def test_livraison_gratuite_integree(self):
        r = p.compute_pricing(2.81, "FR", 1)
        lg = r["livraison_gratuite"]
        assert lg["integree_au_prix"] is True
        assert lg["fret_facture_au_client_eur"] == 0.00
        assert "cout reel" in lg["note"]
        # Le fret n'est PAS gratuit pour SHOPLINOUS : il reste dans le cout total.
        assert r["calcul"]["frais_livraison_eur"] == 4.20

    def test_exchange_rate_constant(self):
        assert p.EXCHANGE_RATE_USD_EUR == 0.89509
        assert p.EXCHANGE_RATE_DATE == "2026-10-30"

    def test_table_rapport_complete(self):
        table = p.build_pricing_table(marge_min=0.20)
        assert sorted(table.keys()) == ["AU", "BR", "CI", "CN", "FR", "GB", "US"]
        for pays, bloc in table.items():
            assert len(bloc["lignes"]) == 5
            for ligne in bloc["lignes"]:
                assert ligne["statut"] == "recommandation_ok"
                assert ligne["prix_vente_recommande_eur"] > 0


# ----------------------------------------------------------------- Erreurs
class TestErreurs:
    def test_cout_invalide(self):
        assert p.compute_pricing(0, "FR", 1)["statut"] == "cout_invalide"
        assert p.compute_pricing(-1, "FR", 1)["statut"] == "cout_invalide"
        assert p.compute_pricing("x", "FR", 1)["statut"] == "cout_invalide"

    def test_marge_nulle_ou_negative(self):
        assert p.compute_pricing(2.81, "FR", 1, marge_min=0)["statut"] == \
            "parametres_invalides"
        assert p.compute_pricing(2.81, "FR", 1, marge_min=-0.1)["statut"] == \
            "parametres_invalides"

    def test_marge_plus_frais_trop_eleves(self):
        r = p.compute_pricing(2.81, "FR", 1, marge_min=0.98,
                              frais_paiement_taux=0.029)
        assert r["statut"] == "parametres_invalides"
        assert r["verification_manuelle"] is True

    def test_taux_frais_negatif(self):
        assert p.compute_pricing(2.81, "FR", 1, frais_paiement_taux=-0.01)[
            "statut"] == "parametres_invalides"

    def test_fixe_frais_negatif(self):
        assert p.compute_pricing(2.81, "FR", 1, frais_paiement_fixe_eur=-1)[
            "statut"] == "parametres_invalides"

    def test_exchange_rate_invalide(self):
        assert p.compute_pricing(2.81, "FR", 1, exchange_rate=0)["statut"] == \
            "parametres_invalides"

    def test_pays_non_chaine(self):
        assert p.compute_pricing(2.81, None, 1)["statut"] == "tarif_indisponible"


# ---------------------------------------------------------------- Securite
class TestSecuriteV55:
    def test_allow_publish_false(self):
        assert p.ALLOW_PUBLISH is False

    def test_module_sans_reseau(self):
        chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "pricing_v55.py")
        with open(chemin, "r", encoding="utf-8") as f:
            source = f.read()
        for interdit in ("import requests", "import httpx", "import urllib",
                         "import socket", "import subprocess"):
            assert interdit not in source

    def test_aucun_prix_hors_donnees_mesurees(self):
        # Quantite > 5 : aucun prix calcule.
        assert "calcul" not in p.compute_pricing(2.81, "FR", 6)
        # Destination inconnue : aucun prix calcule.
        assert "calcul" not in p.compute_pricing(2.81, "ZZ", 1)

    def test_frets_tous_dates_mesurees(self):
        for pays in p.REAL_FREIGHT:
            for q, quote in p.REAL_FREIGHT[pays].items():
                assert p.get_freight_quote(pays, q)["date_mesure"] == "2026-11-02"

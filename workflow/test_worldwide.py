"""Tests mondiaux SHOPLINOUS : referentiel ISO 3166-1, devises ISO 4217,
langues, livraison CJ produit/destination, paiements, statuts de marche.

Pays couverts : Cote d'Ivoire, France, Etats-Unis, Canada, Bresil,
Inde, Japon, Emirats arabes unis, Australie, Afrique du Sud, plus un
pays non encore commercialement verifie (Antarctique, sans devise).
"""
import pytest

import intl
import ad_engine
from shoplinous_global import world_countries
from shoplinous_global import world_currencies
from shoplinous_global import world_shipping
from shoplinous_global import world_payments
from shoplinous_global import currency_manager

PAYS_CIBLES = ["CI", "FR", "US", "CA", "BR", "IN", "JP", "AE", "AU", "ZA"]
DEVISES_CIBLES = {"CI": ("XOF", 0), "FR": ("EUR", 2), "US": ("USD", 2),
                  "CA": ("CAD", 2), "BR": ("BRL", 2), "IN": ("INR", 2),
                  "JP": ("JPY", 0), "AE": ("AED", 2), "AU": ("AUD", 2),
                  "ZA": ("ZAR", 2)}


class TestReferentiel:
    def test_nb_pays_repertories(self):
        assert len(world_countries.PAYS) == 253
        assert len(world_countries.selecteur_mondial()) == 253

    def test_pays_cibles_tous_repertories(self):
        for c in PAYS_CIBLES + ["AQ", "MT", "GB", "CH", "NO"]:
            assert c in world_countries.PAYS

    def test_champs_complets(self):
        for c in PAYS_CIBLES:
            p = world_countries.pays(c)
            assert p.iso3 and p.nom_fr and p.nom_en and p.indicatif
            assert p.langues and p.region

    def test_antartique_sans_devise_non_ouvert(self):
        s = world_countries.statut("AQ")
        assert s["support_technique"] is False
        assert s["ouvert_commande"] is False
        assert "devise_non_exploitable" in s["raisons_fermeture"]

    def test_aucun_doublon_de_code(self):
        codes = [p.code for p in world_countries.PAYS.values()]
        assert len(codes) == len(set(codes))


class TestDevises:
    def test_exposants_iso_4217(self):
        for pays, (devise, exp) in DEVISES_CIBLES.items():
            p = world_countries.pays(pays)
            assert p.devise_principale == devise
            assert world_currencies.exposant(devise) == exp

    def test_formatage_local(self):
        assert world_currencies.formater(1234.5, "USD", "en") == "$1,234.50"
        assert world_currencies.formater(1234.5, "EUR", "fr") == "1 234,50 EUR"
        assert world_currencies.formater(1234.5, "XOF", "fr") == "1 235 FCFA"
        assert world_currencies.formater(12.5, "JPY", "fr") == "13 JPY"

    def test_protection_arrondi(self):
        assert currency_manager.arrondir("10.455", "EUR") == \
            currency_manager.arrondir(10.455, "EUR")
        assert str(currency_manager.arrondir(10.455, "EUR")) == "10.46"
        assert str(currency_manager.arrondir(10.455, "JPY")) == "10"

    def test_conversion_tracee(self):
        tr = world_currencies.convertir_trace(
            17.90, "EUR", "USD", 1.08, "ECB", "2026-11-03")
        assert tr["montant_converti"] == "19.33"
        assert tr["source_taux"] == "ECB" and tr["date_taux"] == "2026-11-03"
        assert tr["prix_garanti"] is False
        with pytest.raises(ValueError):
            world_currencies.convertir_trace(10, "EUR", "USD", 1.08,
                                            "", "2026-11-03")


class TestLangues:
    def test_cinq_langues_completes(self):
        assert intl.langues_disponibles() == ["fr", "en", "es", "pt", "ar"]

    def test_langues_par_pays(self):
        assert "fr" in world_countries.langues_boutique("CI")
        assert "ar" in world_countries.langues_boutique("AE")
        assert world_countries.langues_boutique("JP") == ("en",)

    def test_rtl(self):
        assert intl.rtl("ar") is True
        assert intl.rtl("ja") is False

    def test_langue_incomplete_rejetee(self):
        with pytest.raises(ValueError):
            intl.add_language("de", {"panier": "Warenkorb"})


class TestStatutsMarche:
    def test_france_seul_marche_ouvert(self):
        s = world_countries.statut("FR")
        assert s["ouvert_commande"] is True
        assert s["evidence"]["paiement"]

    def test_pays_non_valides_fermes_meme_en_europe(self):
        for c in ("DE", "ES", "IT", "MT", "GB"):
            s = world_countries.statut(c)
            assert s["ouvert_commande"] is False
            assert s["raisons_fermeture"]

    def test_hors_europe_ferme(self):
        for c in ("US", "CA", "BR", "IN", "JP", "AE", "AU", "ZA", "CI"):
            s = world_countries.statut(c)
            assert s["livraison_verifiee"] is False
            assert s["ouvert_commande"] is False
            assert "livraison_non_verifiee" in s["raisons_fermeture"]

    def test_selecteur_explicite_pour_les_fermetures(self):
        sel = {e["code"]: e for e in world_countries.selecteur_mondial()}
        for c in PAYS_CIBLES:
            assert sel[c]["ouvert_commande"] is False
            assert sel[c]["raisons_fermeture"]
        assert sel["FR"]["ouvert_commande"] is True


class TestLivraisonCJ:
    def devis_fr(self, **kw):
        d = {"vid": "v1", "destination": "FR",
             "canal": "CJPacket Ordinary", "cout_eur": 5.12,
             "delai": "4-10", "stock_cn": 6792}
        d.update(kw)
        return d

    def test_devis_conforme_fr(self):
        r = world_shipping.verifier_produit_destination(
            "SPL-COINBOX-EUR", "FR", [self.devis_fr()])
        assert r["vendable"] is True
        assert r["canal_retenu"] == "CJPacket Ordinary"

    def test_pays_non_valide_ne_peut_pas_commander(self):
        # MEME avec un devis CJ parfait, un marche non ouvert reste ferme
        r = world_shipping.verifier_produit_destination(
            "S1", "US", [self.devis_fr(destination="US")])
        assert r["vendable"] is False
        assert r["raison"].startswith("marche_ferme")

    def test_aucune_extrapolation_entre_pays(self):
        # un devis valable pour DE ne vaut rien pour FR : chaque couple
        # produit/destination exige SON devis CJ reel
        r = world_shipping.verifier_produit_destination(
            "S1", "FR", [self.devis_fr(destination="DE")])
        assert r["vendable"] is False
        assert r["raison"] == "aucun_devis_pour_cette_destination"

    def test_regles_lient_cout_delai_stock(self):
        cas = (("delai", {"delai": "12-50"}, "delai_trop_long"),
               ("cout", {"cout_eur": 9.0}, "cout_trop_eleve"),
               ("stock", {"stock_cn": 500}, "stock_cn_insuffisant"))
        for champ, kw, refus in cas:
            e = world_shipping.evaluer_devis(self.devis_fr(**kw))
            assert champ == champ  # couple documente
            assert refus in e["refus"], (champ, e["refus"])
            assert e["eligible"] is False


class TestPaiements:
    def test_geniuspay_verifie_france_uniquement(self):
        assert world_payments.operationnel("geniuspay", "FR") is True
        for c in ("CI", "US", "SN", "AE"):
            assert world_payments.operationnel("geniuspay", c) is False

    def test_capacites_declarees_ne_sont_pas_operationnelles(self):
        assert "Wave" in world_payments.moyens_declares("CI")
        assert world_payments.operationnel("wave", "CI") is False

    def test_activation_exige_une_preuve(self):
        with pytest.raises(ValueError):
            world_payments.activer_prestataire("stripe", "CI", "", "")


class TestAnnoncesMondiales:
    def test_annonce_adaptee_pays_langue_devise(self):
        p = ad_engine.Produit("S1", "Deco murale", 24.9, 7.75, 100, 5,
                              ["FR"])
        a = ad_engine.generer_annonce(p, "ar", "FR")
        assert a["devise"] == "EUR" and a["rtl"] is True
        # prix formate dans la devise du marche, pas en EUR texte dur
        assert "EUR" in a["accroche"]

    def test_annonce_pays_ferme_refusee(self):
        p = ad_engine.Produit("S1", "Deco", 24.9, 7.75, 100, 5, ["US"])
        with pytest.raises(ValueError):
            ad_engine.generer_annonce(p, "en", "US")

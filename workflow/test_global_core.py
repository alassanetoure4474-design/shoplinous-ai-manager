"""Tests des modules coeur SHOPLINOUS GLOBAL v6.

market_manager, country_manager, currency_manager,
exchange_rate_manager, pricing_manager. Aucun reseau.
"""
import pytest

import global as g
from global import market_manager as mm
from global import country_manager as cm
from global import currency_manager as cu
from global import exchange_rate_manager as fx
from global import pricing_manager as pm


class TestInventaireModules:
    def test_18_modules_presents_et_charges(self):
        assert len(g.MODULES) == 18
        statut = g.module_status()
        assert statut and all(s["charge"] for s in statut.values())


class TestMarketManager:
    def test_neuf_marches(self):
        assert mm.marches() == ["afrique_autres", "afrique_centrale",
                                "afrique_nord", "afrique_ouest",
                                "amerique_latine", "amerique_nord",
                                "asie", "europe", "oceanie"]

    def test_chaque_pays_dans_exactement_un_marche(self):
        coherence = mm.coherence()
        assert coherence["pays_sans_marche"] == []
        assert coherence["pays_doubles"] == []

    def test_restriction_fiscale_detectee(self):
        assert mm.restriction_active("FR", "tva_20_pourcent") is True
        assert mm.restriction_active("CI", "tva_20_pourcent") is False


class TestCountryManager:
    def test_chaque_pays_a_les_9_champs(self):
        assert cm.coherence_config() == []

    def test_pays_inconnu_refuse(self):
        with pytest.raises(ValueError):
            cm.pays("XX")

    def test_detection_indicative_et_modifiable(self):
        s = cm.suggest_country("ci")
        assert s["nature"] == "indicative" and s["modifiable"] is True
        commande = {"pays": "SN"}
        cm.changer_pays(commande, "CI")
        assert commande["pays"] == "CI"
        assert commande["devise"] == "XOF"

    def test_client_peut_toujours_changer_de_pays(self):
        # meme apres detection, le changement reste possible
        commande = cm.changer_pays({"pays": None}, "FR")
        commande = cm.changer_pays(commande, "TG")
        assert commande["pays"] == "TG"
        assert commande["pays_detecte_initial"] == "FR"


class TestCurrencyManager:
    def test_arrondi_xof_sans_decimale(self):
        assert cu.arrondir("1234.567", "XOF") == 1235

    def test_arrondi_eur_half_up(self):
        assert cu.arrondir("10.455", "EUR") == Decimal("10.46")

    def test_devise_inconnue_refusee(self):
        with pytest.raises(ValueError):
            cu.arrondir(10, "XYZ")

    def test_conversion_taux_explicite(self):
        assert cu.convertir("10", "USD", "XOF", "655.957") == 6560

    def test_conversion_taux_invalide_refusee(self):
        with pytest.raises(ValueError):
            cu.convertir(10, "USD", "XOF", 0)

    def test_coherence_affiche_encaisse(self):
        assert cu.coherent_prix_affiche_encaisse("10.45", "10.45", "EUR")
        assert not cu.coherent_prix_affiche_encaisse("10.45", "12.00", "EUR")


class TestExchangeRateManager:
    class FournisseurFixe(fx.FournisseurTaux):
        def __init__(self, valeur, en_panne=False, appels=None):
            self.valeur, self.en_panne, self.appels = valeur, en_panne, (
                appels if appels is not None else [])

        def taux(self, source, cible):
            self.appels.append((source, cible))
            if self.en_panne:
                raise fx.ErreurTauxIndisponible("hors ligne")
            return fx.TauxHorodate((source, cible), self.valeur)

    def test_taux_horodate_et_cache(self):
        appels = []
        f = self.FournisseurFixe(655.0, appels=appels)
        mgr = fx.ExchangeRateManager(f, ttl_secondes=3600)
        t1 = mgr.taux("USD", "XOF")
        t2 = mgr.taux("USD", "XOF")
        assert t1.valeur == t2.valeur == 655.0
        assert len(appels) == 1  # cache utilise
        assert mgr.historique[-1]["paire"] == ("USD", "XOF")

    def test_indisponibilite_ninvente_rien(self):
        mgr = fx.ExchangeRateManager(self.FournisseurFixe(0, en_panne=True))
        with pytest.raises(fx.ErreurTauxIndisponible):
            mgr.taux("USD", "XOF")
        assert mgr.historique == []


class TestPricingManager:
    ENTREE = {
        "prix_fournisseur": "4.00",  # USD
        "transport": "2.00",         # USD
        "taux_vers_reference": "0.92",  # USD->EUR
        "frais_paiement_taux": "0.029",
        "frais_paiement_fixe": "0.30",
        "frais_plateforme": "0.20",
        "taxe_taux": "0.00",
        "marge_minimale": "2.00",
        "devise_reference": "EUR",
    }

    def test_donnee_manquante_bloquee_avec_nom_exact(self):
        e = dict(self.ENTREE)
        del e["transport"]
        with pytest.raises(pm.DonneesPrixIncompletes) as exc:
            pm.calculer_prix_final(e)
        assert exc.value.manquants == ["transport"]

    def test_composition_complete_et_prix_plancher(self):
        r = pm.calculer_prix_final(self.ENTREE)
        assert r["statut"] == "ok"
        comp = r["composition"]
        assert comp["cout_fournisseur"] == "3.68"
        assert comp["cout_transport"] == "1.84"
        # couts 5.52 + paiement (5.52*0.029+0.30=0.46) + plateforme 0.20
        assert r["cout_total"] == "6.18"
        assert float(r["prix_plancher"]) >= 8.18  # + marge 2.00

    def test_marge_insuffisante_bloque_le_prix(self):
        r = pm.verifier_prix_propose("6.50", self.ENTREE)
        assert r["statut"] == "marge_insuffisante"
        assert float(r["manque"]) > 0

    def test_prix_correct_accepte(self):
        r = pm.verifier_prix_propose("9.00", self.ENTREE)
        assert r["statut"] == "ok"
        assert float(r["benefice_net"]) >= 2.00

    def test_taux_negatif_refuse(self):
        e = dict(self.ENTREE, marge_minimale="-1")
        with pytest.raises(ValueError):
            pm.calculer_prix_final(e)

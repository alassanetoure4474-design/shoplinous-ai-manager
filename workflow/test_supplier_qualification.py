"""Qualification fournisseurs mondiale : aucune origine géographique exclue."""
import pytest

from shoplinous_global.exchange_rate_manager import TauxHorodate
from shoplinous_global import supplier_qualification as qualification
from shoplinous_global import supplier_adapters as adapters
from shoplinous_global import supplier_manager as manager


NOW = 2_000_000_000.0


def rates():
    return {
        "USD": TauxHorodate(("USD", "EUR"), 0.92, horodatage=NOW - 60),
        "GBP": TauxHorodate(("GBP", "EUR"), 1.17, horodatage=NOW - 60),
        "CNY": TauxHorodate(("CNY", "EUR"), 0.13, horodatage=NOW - 60),
        "XOF": TauxHorodate(("XOF", "EUR"), 0.001524, horodatage=NOW - 60),
    }


def offer(origin="US", warehouse="US", supplier="Global Supply", sku="SKU-1",
          destination="FR", quantity=1, purchase=2.0, purchase_currency="USD",
          stock=1500, shipping=3.0, shipping_currency="USD",
          min_days=4, max_days=8, images=3, retail=None):
    return {
        "fournisseur": supplier,
        "pays_fournisseur": origin,
        "pays_entrepot": warehouse,
        "sku": sku,
        "nom_produit": "Rangement maison pliable",
        "prix_achat": purchase,
        "devise_achat": purchase_currency,
        "stock": stock,
        "stock_verifie": True,
        "stock_verifie_le": NOW - 90,
        "images_validees": images,
        "images_verifiees_le": NOW - 90,
        "preuve_images": "img-check-2026-001",
        "fournisseur_verifie": True,
        "preuve_fournisseur": "supplier-kyc-verified-001",
        "conformite_verifiee": True,
        "preuve_conformite": "compliance-check-001",
        "prix_vente_eur": retail,
        "devis_livraison": {
            "reference": "SHIP-QUOTE-001",
            "verifie": True,
            "destination": destination,
            "quantite": quantity,
            "cout": shipping,
            "devise": shipping_currency,
            "delai_min_jours": min_days,
            "delai_max_jours": max_days,
            "restrictions_ok": True,
            "verifie_le": NOW - 60,
            "expire_le": NOW + 900,
        },
    }


class TestOriginesMondiales:
    @pytest.mark.parametrize(
        "origin,warehouse",
        [
            ("CN", "CN"),
            ("US", "US"),
            ("GB", "GB"),
            ("ES", "ES"),
            ("CI", "CI"),
            ("ZA", "ZA"),
            ("JP", "JP"),
            ("AU", "AU"),
        ],
    )
    def test_toute_origine_iso_est_admissible_si_offre_conforme(
        self, origin, warehouse
    ):
        result = qualification.evaluer_offre(
            offer(origin=origin, warehouse=warehouse),
            "FR", 1, rates(), maintenant=NOW,
        )
        assert result["eligible"] is True, result["refus"]
        assert result["pays_fournisseur"] == origin
        assert result["pays_entrepot"] == warehouse
        assert result["destination"] == "FR"

    def test_origine_fournisseur_distincte_de_l_entrepot(self):
        result = qualification.evaluer_offre(
            offer(origin="US", warehouse="CN"),
            "FR", 1, rates(), maintenant=NOW,
        )
        assert result["eligible"] is True
        assert result["pays_fournisseur"] == "US"
        assert result["pays_entrepot"] == "CN"

    def test_la_provenance_ne_remplace_pas_le_devis_vers_le_client(self):
        candidate = offer(origin="US", warehouse="US")
        candidate["devis_livraison"]["destination"] = "GB"
        result = qualification.evaluer_offre(
            candidate, "FR", 1, rates(), maintenant=NOW
        )
        assert result["eligible"] is False
        assert "devis transport pour une autre destination" in result["refus"]


class TestReglesBoutique:
    def test_couts_normalises_et_prix_minimum_x90(self):
        result = qualification.evaluer_offre(
            offer(purchase=2, shipping=3), "FR", 1, rates(), maintenant=NOW
        )
        assert result["eligible"] is True
        assert result["cout_achat_eur"] == "1.84"
        assert result["transport_unitaire_eur"] == "2.76"
        assert result["cout_rendu_eur"] == "4.60"
        assert result["prix_vente_min_eur"] == "13.90"

    def test_stock_sous_1000_refuse(self):
        result = qualification.evaluer_offre(
            offer(stock=999), "FR", 1, rates(), maintenant=NOW
        )
        assert result["eligible"] is False
        assert "stock inférieur au minimum de 1000 unités" in result["refus"]

    def test_cout_achat_superieur_a_8_eur_refuse(self):
        result = qualification.evaluer_offre(
            offer(purchase=10, purchase_currency="EUR"),
            "FR", 1, rates(), maintenant=NOW
        )
        assert "coût fournisseur supérieur à 8 EUR par unité" in result["refus"]

    def test_transport_limite_par_unite_sur_quantite_exacte(self):
        result = qualification.evaluer_offre(
            offer(quantity=2, shipping=14, shipping_currency="EUR"),
            "FR", 2, rates(), maintenant=NOW
        )
        assert result["eligible"] is False
        assert "transport supérieur à 6 EUR par unité" in result["refus"]

    def test_delai_superieur_a_15_jours_refuse(self):
        result = qualification.evaluer_offre(
            offer(max_days=16), "FR", 1, rates(), maintenant=NOW
        )
        assert "délai de livraison supérieur à 15 jours" in result["refus"]

    def test_images_insuffisantes_refusees(self):
        result = qualification.evaluer_offre(
            offer(images=1), "FR", 1, rates(), maintenant=NOW
        )
        assert "moins de 2 images réellement validées" in result["refus"]

    def test_identite_et_conformite_obligatoires(self):
        candidate = offer()
        candidate["fournisseur_verifie"] = False
        candidate["conformite_verifiee"] = False
        result = qualification.evaluer_offre(
            candidate, "FR", 1, rates(), maintenant=NOW
        )
        assert any("identité du fournisseur" in reason for reason in result["refus"])
        assert any("conformité produit" in reason for reason in result["refus"])

    def test_produit_interdit_refuse(self):
        candidate = offer()
        candidate["nom_produit"] = "Bluetooth speaker rechargeable"
        result = qualification.evaluer_offre(
            candidate, "FR", 1, rates(), maintenant=NOW
        )
        assert "produit appartenant à une catégorie interdite" in result["refus"]

    def test_prix_de_vente_inferieur_a_la_regle_x3_refuse(self):
        result = qualification.evaluer_offre(
            offer(retail=10), "FR", 1, rates(), maintenant=NOW
        )
        assert "prix de vente inférieur au minimum de marge x3" in result["refus"]

    def test_stock_non_mesure_ou_perime_refuse(self):
        candidate = offer()
        candidate["stock_verifie"] = False
        candidate["stock_verifie_le"] = NOW - 5000
        result = qualification.evaluer_offre(
            candidate, "FR", 1, rates(), maintenant=NOW
        )
        assert any("stock non vérifié" in reason for reason in result["refus"])
        assert any("stock périmée" in reason for reason in result["refus"])

    def test_devis_non_valide_expire_ou_restriction_refuse(self):
        candidate = offer()
        candidate["devis_livraison"]["restrictions_ok"] = False
        candidate["devis_livraison"]["expire_le"] = NOW - 1
        result = qualification.evaluer_offre(
            candidate, "FR", 1, rates(), maintenant=NOW
        )
        assert "restrictions douanières ou d'importation non levées" in result["refus"]
        assert "devis transport expiré" in result["refus"]

    def test_taux_manquant_ou_perime_refuse(self):
        result = qualification.evaluer_offre(
            offer(), "FR", 1, {}, maintenant=NOW
        )
        assert any("taux réel USD->EUR manquant" in reason for reason in result["refus"])
        stale = {"USD": TauxHorodate(("USD", "EUR"), 0.92, horodatage=NOW - 5000)}
        result = qualification.evaluer_offre(
            offer(), "FR", 1, stale, maintenant=NOW
        )
        assert any("périmé" in reason for reason in result["refus"])

    def test_marche_non_ouvert_refuse_meme_si_origine_ok(self):
        result = qualification.evaluer_offre(
            offer(origin="US"), "CI", 1, rates(), maintenant=NOW
        )
        assert result["eligible"] is False
        assert "destination non ouverte à la vente" in result["refus"]


class TestComparaisonMondiale:
    def test_selectionne_le_moins_cher_par_cout_rendu_puis_delai(self):
        expensive = offer(origin="US", supplier="US supplier", sku="US-1",
                          purchase=4, shipping=4)
        cheap = offer(origin="CN", supplier="CN supplier", sku="CN-1",
                      purchase=2, shipping=2)
        report = qualification.evaluer_offres(
            [expensive, cheap], "FR", 1, rates(), maintenant=NOW
        )
        assert report["nombre_offres"] == 2
        assert report["nombre_conformes"] == 2
        assert report["meilleure_offre"]["fournisseur"] == "CN supplier"

    def test_offres_non_conformes_ecartees_sans_bloquer_les_autres(self):
        good = offer(origin="ZA", supplier="Good", sku="GOOD")
        bad = offer(origin="US", supplier="Bad", sku="BAD", stock=50)
        report = qualification.evaluer_offres(
            [good, bad], "FR", 1, rates(), maintenant=NOW
        )
        assert report["nombre_conformes"] == 1
        assert report["meilleure_offre"]["fournisseur"] == "Good"
        assert report["offres_refusees"][0]["fournisseur"] == "Bad"

    def test_aucune_offre_conforme_ne_donne_aucun_meilleur_fournisseur(self):
        bad = offer(origin="AU", stock=3)
        report = qualification.evaluer_offres(
            [bad], "FR", 1, rates(), maintenant=NOW
        )
        assert report["meilleure_offre"] is None
        assert report["nombre_conformes"] == 0


class TestRegistreEtGestionnaire:
    def test_adaptateur_connecte_depuis_une_nouvelle_origine(self):
        class Provider(adapter_test_base()):
            nom = "provider_us"
            connected = True
            capacites = ("produits_recherche", "stock", "fret")
            pays_expedition = ("US",)

            def produits_recherche(self, query):
                return []

        registry = adapters.RegistreFournisseurs()
        registry.enregistrer(Provider())
        assert "provider_us" in registry.connectes()
        # Un adaptateur d'origine US reste accessible pour un client FR.
        assert "provider_us" in registry.pour_pays("FR")
        assert registry.par_origine("US") == ["provider_us"]

    def test_adaptateur_non_connecte_ne_se_presente_pas_comme_actif(self):
        registry = adapters.RegistreFournisseurs()
        assert "aliexpress" not in registry.connectes()
        assert "aliexpress" not in registry.pour_pays("FR")
        assert registry.etat()["aliexpress"]["candidature_mondiale"] is False

    def test_recherche_mondiale_interroge_un_fournisseur_us_pour_client_fr(self):
        class Provider(adapter_test_base()):
            nom = "provider_global"
            connected = True
            capacites = ("rechercher_offres",)
            pays_expedition = ("US",)

            def rechercher_offres(self, keyword, destination, quantity):
                assert keyword == "storage"
                assert destination == "FR"
                assert quantity == 1
                return [offer(origin="US", warehouse="US", supplier="ignored")]

        registry = adapters.RegistreFournisseurs()
        registry.enregistrer(Provider())
        result = registry.rechercher_offres("storage", "FR", 1)
        assert len(result["offres"]) == 1
        assert result["offres"][0]["fournisseur"] == "provider_global"
        assert result["offres"][0]["pays_fournisseur"] == "US"
        assert result["erreurs"] == []

    def test_gestionnaire_recherche_et_qualifie_les_offres_mondiales(self):
        class Provider(adapter_test_base()):
            nom = "provider_world"
            connected = True
            capacites = ("rechercher_offres",)
            pays_expedition = ("ZA",)

            def rechercher_offres(self, keyword, destination, quantity):
                return [offer(origin="ZA", warehouse="ZA")]

        registry = adapters.RegistreFournisseurs()
        registry.enregistrer(Provider())
        supplier_manager = manager.GestionnaireFournisseurs(registry)
        report = supplier_manager.rechercher_et_qualifier(
            "home organizer", "FR", 1, rates(), maintenant=NOW
        )
        assert report["nombre_conformes"] == 1
        assert report["meilleure_offre"]["pays_fournisseur"] == "ZA"
        assert report["fournisseurs_interroges"] == ["provider_world"]

    def test_import_csv_accepte_origine_iso_mondiale_sans_le_rendre_vendable(self):
        csv_data = (
            "nom_fournisseur,sku,nom_produit,prix_achat,devise,stock,"
            "pays_expedition,delai_jours\n"
            "Global,US-1,Rangement,4.50,USD,1200,US,8\n"
        )
        supplier_manager = manager.GestionnaireFournisseurs(
            adapters.RegistreFournisseurs()
        )
        result = supplier_manager.importer_csv(csv_data)
        assert result["ajoutes"] == [2]
        item = supplier_manager.catalogue()[0]
        assert item["pays_expedition"] == "US"
        assert item["verifie"] is False
        assert item["vendable"] is False

    def test_saisie_manuelle_rejette_code_pays_invalide(self):
        supplier_manager = manager.GestionnaireFournisseurs(
            adapters.RegistreFournisseurs()
        )
        with pytest.raises(ValueError, match="ISO"):
            supplier_manager.saisie_manuelle(
                nom_fournisseur="Remote", sku="R-1", nom_produit="Shelf",
                prix_achat=4, devise="USD", stock=10,
                pays_expedition="XX", delai_jours=5
            )


def adapter_test_base():
    return adapters.AdaptateurFournisseur

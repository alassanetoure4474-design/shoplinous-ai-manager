"""Tests du moteur publicitaire et de l'internationalisation SHOPLINOUS."""
import pytest
import intl
import ad_engine


def test_marches_ouverts():
    opened = [code for code, country in intl.COUNTRIES.items()
              if country.open_for_sale]
    assert len(opened) == 29
    assert "MT" not in opened


def test_malte_fermee_sans_verification():
    status = intl.country_status("MT")
    assert status["ouvert_vente"] is False
    assert status["livrable"] is False


def test_pays_inconnu_rejete():
    with pytest.raises(KeyError):
        intl.country_status("ZZ")


def test_conversion_sans_taux_rejetee():
    with pytest.raises(ValueError):
        intl.convert(10.0, "USD", "EUR", {})
    assert intl.convert(10.0, "EUR", "EUR", {}) == 10.0
    assert round(intl.convert(
        2.82, "USD", "EUR", {"USD": 1.1181, "EUR": 1.0}), 2) == 2.52


def test_devises_et_langues():
    for currency in ("XOF", "XAF", "USD", "EUR", "GBP", "CAD", "CNY",
                     "JPY", "NGN", "GHS", "MAD", "ZAR", "KES"):
        assert currency in intl.CURRENCIES
    for lang in ("fr", "en", "es", "pt", "ar"):
        assert intl.t("panier", lang)
    assert intl.t("panier", "ar") != intl.t("panier", "en")
    assert intl.text_direction("ar") == "rtl"
    assert intl.text_direction("fr") == "ltr"
    with pytest.raises(ValueError):
        intl.t("panier", "xx")


def test_score_produit():
    product = ad_engine.Produit(
        "S1", "Deco murale", 24.9, 7.75, 100, 5, ["FR"])
    score = ad_engine.score_produit(product)
    assert score["eligible"] is True and score["score"] == 100
    out_of_stock = ad_engine.Produit(
        "S2", "Deco", 24.9, 7.75, 0, 5, ["FR"])
    assert ad_engine.score_produit(out_of_stock)["eligible"] is False


def test_annonce_multilingue_et_marche_ferme():
    product = ad_engine.Produit(
        "S1", "Tenture boheme", 24.9, 7.75, 100, 5, ["FR"])
    for lang in ("fr", "en", "es", "pt", "ar"):
        ad = ad_engine.generer_annonce(product, lang, "FR")
        assert ad["sku"] == "S1" and ad["titre"] and ad["cta"]
    assert ad_engine.generer_annonce(product, "ar", "FR")["direction"] == "rtl"
    with pytest.raises(ValueError):
        ad_engine.generer_annonce(product, "fr", "MT")
    with pytest.raises(ValueError):
        ad_engine.generer_annonce(product, "fr", "DE")


def test_annonce_exige_un_taux_pour_une_devise_differente(monkeypatch):
    country = intl.get_country("US")
    monkeypatch.setattr(country, "shippable", True)
    monkeypatch.setattr(country, "payment_available", True)
    monkeypatch.setattr(country, "taxes_configured", True)
    product = ad_engine.Produit(
        "US1", "Desk lamp", 25.0, 7.0, 100, 3, ["US"], "EUR")
    with pytest.raises(ValueError, match="Taux de change horodate requis"):
        ad_engine.generer_annonce(product, "en", "US")
    ad = ad_engine.generer_annonce(
        product, "en", "US", taux={"EUR": 1.0, "USD": 1.1})
    assert ad["devise"] == "USD"
    assert "$" in ad["accroche"]


def test_campagne_payante_budget_zero():
    campaign = ad_engine.creer_campagne_payante("test", ["FR"])
    assert campaign.budget == 0.0 and campaign.statut == "brouillon"
    with pytest.raises(ValueError):
        ad_engine.creer_campagne_payante("test", ["FR"], budget=50.0)
    with pytest.raises(ValueError):
        ad_engine.creer_campagne_payante("test", ["MT"])


def test_calendrier_max_3_et_canal_non_autorise():
    calendar = ad_engine.CalendrierOrganique()
    ad = ad_engine.generer_annonce(
        ad_engine.Produit("S1", "Deco", 24.9, 7.75, 100, 5, ["FR"]),
        "fr", "FR")
    with pytest.raises(ValueError):
        calendar.planifier("2026-11-04", ad, "facebook")


def test_tableau_de_bord_sans_statistique_fictive():
    dashboard = ad_engine.tableau_de_bord({"jour1": [1, 2]}, None)
    assert dashboard["publications_planifiees"] == 2
    assert dashboard["impressions"] is None and dashboard["clics"] is None
    dashboard2 = ad_engine.tableau_de_bord({}, {"clics": 12})
    assert dashboard2["clics"] == 12 and dashboard2["impressions"] is None

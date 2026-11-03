"""Tests du moteur publicitaire et de l'internationalisation SHOPLINOUS."""
import pytest
import intl
import ad_engine


def test_referentiel_iso_mondial_complet():
    assert len(intl.COUNTRIES) == 249
    assert len({country.alpha3 for country in intl.COUNTRIES.values()}) == 249
    assert len({country.numeric for country in intl.COUNTRIES.values()}) == 249
    assert intl.get_country("CI").name_fr == "Côte d’Ivoire"
    assert intl.get_country("US").name_en == "United States"
    assert intl.get_country("CI").region == "Afrique"
    assert all(country.region != "Autre" for country in intl.COUNTRIES.values())


def test_seuls_les_marches_verifies_sont_ouverts():
    ouverts = [code for code, country in intl.COUNTRIES.items() if country.open_for_sale]
    assert len(ouverts) == 29
    assert set(ouverts) == set(intl.VERIFIED_MARKETS)
    assert "MT" not in ouverts


@pytest.mark.parametrize(
    "code,currency",
    [
        ("CI", "XOF"),
        ("FR", "EUR"),
        ("US", "USD"),
        ("CA", "CAD"),
        ("BR", "BRL"),
        ("IN", "INR"),
        ("JP", "JPY"),
        ("AE", "AED"),
        ("AU", "AUD"),
        ("ZA", "ZAR"),
    ],
)
def test_pays_mondiaux_repertories_mais_fermes_par_defaut(code, currency):
    status = intl.country_status(code)
    assert status["enregistre"] is True
    assert currency in status["devises"]
    assert status["livrable"] is False
    assert status["paiement_disponible"] is False
    assert status["taxes_configurees"] is False
    assert status["ouvert_vente"] is False


def test_pays_a_plusieurs_devises_ne_choisit_pas_arbitrairement():
    assert set(intl.country_currencies("HT")) == {"HTG", "USD"}
    assert intl.get_country("HT").currency is None


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
    assert round(
        intl.convert(2.82, "USD", "EUR", {"USD": 1.1181, "EUR": 1.0}), 2
    ) == 2.52
    with pytest.raises(ValueError):
        intl.convert(10, "USD", "EUR", {"USD": 0, "EUR": 1})


def test_referentiel_devises_et_langues():
    for currency in ("XOF", "XAF", "USD", "EUR", "GBP", "CAD", "CNY",
                     "JPY", "NGN", "GHS", "MAD", "ZAR", "KES", "BRL",
                     "INR", "AED", "AUD", "CHF", "NOK"):
        assert currency in intl.CURRENCIES
    for lang in ("fr", "en", "es", "pt", "ar"):
        assert intl.t("panier", lang)
        assert set(intl.TRANSLATIONS[lang]) == set(intl.TRANSLATIONS["fr"])
    assert intl.t("panier", "ar") == "سلة التسوق"
    assert intl.is_rtl("ar") is True
    assert intl.is_rtl("fr") is False
    with pytest.raises(ValueError):
        intl.t("panier", "xx")


def test_format_price_utilise_decimales_iso_et_symbole():
    assert "€" in intl.format_price(12.5, "EUR")
    assert intl.format_price(12.5, "JPY").startswith("13 ")
    with pytest.raises(ValueError):
        intl.format_price(10, "ZZZ")


def test_score_produit():
    product = ad_engine.Produit("S1", "Déco murale", 24.9, 7.75, 100, 5, ["FR", "DE"])
    score = ad_engine.score_produit(product)
    assert score["eligible"] is True and score["score"] == 100
    out_of_stock = ad_engine.Produit("S2", "Déco", 24.9, 7.75, 0, 5, ["FR"])
    assert ad_engine.score_produit(out_of_stock)["eligible"] is False
    no_cost = ad_engine.Produit("S3", "Déco", 24.9, 0, 10, 5, ["FR"])
    assert ad_engine.score_produit(no_cost)["eligible"] is False


def test_annonce_multilingue_et_marche_ferme():
    product = ad_engine.Produit("S1", "Tenture bohème", 24.9, 7.75, 100, 5, ["FR"])
    for lang in ("fr", "en", "es", "pt", "ar"):
        advert = ad_engine.generer_annonce(product, lang, "FR")
        assert advert["sku"] == "S1"
        assert advert["titre"] and advert["cta"]
        assert advert["devise"] == "EUR"
        assert "EUR" not in advert["accroche"]
    arabic = ad_engine.generer_annonce(product, "ar", "FR")
    assert arabic["direction"] == "rtl"
    assert "الشحن" in arabic["accroche"]
    with pytest.raises(ValueError):
        ad_engine.generer_annonce(product, "fr", "MT")
    with pytest.raises(ValueError):
        ad_engine.generer_annonce(product, "fr", "DE")


def test_annonce_devise_locale_et_taux_obligatoire():
    product = ad_engine.Produit(
        "S1", "Wall art", 24.9, 7.75, 100, 5, ["GB"], devise_base="EUR"
    )
    with pytest.raises(ValueError, match="Taux de change réel requis"):
        ad_engine.generer_annonce(product, "en", "GB")
    advert = ad_engine.generer_annonce(
        product, "en", "GB", taux={"EUR": 1.0, "GBP": 0.86}
    )
    assert advert["devise"] == "GBP"
    assert "£" in advert["accroche"]


def test_annonce_refuse_devise_non_associee_au_pays():
    product = ad_engine.Produit("S1", "Item", 20, 5, 100, 3, ["FR"])
    with pytest.raises(ValueError, match="Devise non associée"):
        ad_engine.generer_annonce(product, "fr", "FR", devise="USD")


def test_campagne_payante_budget_zero():
    campaign = ad_engine.creer_campagne_payante("test", ["FR"])
    assert campaign.budget == 0.0 and campaign.statut == "brouillon"
    with pytest.raises(ValueError):
        ad_engine.creer_campagne_payante("test", ["FR"], budget=50.0)
    with pytest.raises(ValueError):
        ad_engine.creer_campagne_payante("test", ["MT"])
    with pytest.raises(ValueError):
        ad_engine.creer_campagne_payante("test", ["US"])


def test_calendrier_canal_non_autorise():
    calendar = ad_engine.CalendrierOrganique()
    advert = ad_engine.generer_annonce(
        ad_engine.Produit("S1", "Déco", 24.9, 7.75, 100, 5, ["FR"]),
        "fr", "FR"
    )
    with pytest.raises(ValueError):
        calendar.planifier("2026-11-04", advert, "facebook")


def test_tableau_de_bord_sans_statistique_fictive():
    dashboard = ad_engine.tableau_de_bord({"jour1": [1, 2]}, None)
    assert dashboard["publications_planifiees"] == 2
    assert dashboard["impressions"] is None and dashboard["clics"] is None
    dashboard_with_real_data = ad_engine.tableau_de_bord({}, {"clics": 12})
    assert dashboard_with_real_data["clics"] == 12
    assert dashboard_with_real_data["impressions"] is None

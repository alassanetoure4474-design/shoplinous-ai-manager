"""Tests du moteur publicitaire et de l'internationalisation SHOPLINOUS."""
import pytest
import intl
import ad_engine


def test_marches_ouverts():
    ouverts = [c for c, p in intl.COUNTRIES.items() if p.open_for_sale]
    assert len(ouverts) == 29
    assert "MT" not in ouverts


def test_malte_fermee_sans_verification():
    st = intl.country_status("MT")
    assert st["ouvert_vente"] is False
    assert st["livrable"] is False


def test_pays_inconnu_rejete():
    with pytest.raises(KeyError):
        intl.country_status("ZZ")


def test_conversion_sans_taux_rejetee():
    with pytest.raises(ValueError):
        intl.convert(10.0, "USD", "EUR", {})
    assert intl.convert(10.0, "EUR", "EUR", {}) == 10.0
    assert round(intl.convert(2.82, "USD", "EUR", {"USD": 1.1181, "EUR": 1.0}), 2) == 2.52


def test_devises_et_langues():
    for cur in ("XOF", "XAF", "USD", "EUR", "GBP", "CAD", "CNY", "JPY", "NGN", "GHS", "MAD", "ZAR", "KES"):
        assert cur in intl.CURRENCIES
    for lang in ("fr", "en", "es", "pt", "ar"):
        assert intl.t("panier", lang)
    with pytest.raises(ValueError):
        intl.t("panier", "xx")


def test_score_produit():
    p = ad_engine.Produit("S1", "Deco murale", 24.9, 7.75, 100, 5, ["FR", "DE"])
    s = ad_engine.score_produit(p)
    assert s["eligible"] is True and s["score"] == 100
    rupture = ad_engine.Produit("S2", "Deco", 24.9, 7.75, 0, 5, ["FR"])
    assert ad_engine.score_produit(rupture)["eligible"] is False


def test_annonce_multilingue_et_marche_ferme():
    p = ad_engine.Produit("S1", "Tenture boheme", 24.9, 7.75, 100, 5, ["FR"])
    for lang in ("fr", "en", "es", "pt", "ar"):
        a = ad_engine.generer_annonce(p, lang, "FR")
        assert a["sku"] == "S1" and a["titre"] and a["cta"]
    with pytest.raises(ValueError):
        ad_engine.generer_annonce(p, "fr", "MT")
    with pytest.raises(ValueError):
        ad_engine.generer_annonce(p, "fr", "DE")


def test_campagne_payante_budget_zero():
    c = ad_engine.creer_campagne_payante("test", ["FR"])
    assert c.budget == 0.0 and c.statut == "brouillon"
    with pytest.raises(ValueError):
        ad_engine.creer_campagne_payante("test", ["FR"], budget=50.0)
    with pytest.raises(ValueError):
        ad_engine.creer_campagne_payante("test", ["MT"])


def test_calendrier_max_3_et_canal_non_autorise():
    cal = ad_engine.CalendrierOrganique()
    a = ad_engine.generer_annonce(ad_engine.Produit("S1", "Deco", 24.9, 7.75, 100, 5, ["FR"]), "fr", "FR")
    with pytest.raises(ValueError):
        cal.planifier("2026-11-04", a, "facebook")


def test_tableau_de_bord_sans_statistique_fictive():
    d = ad_engine.tableau_de_bord({"jour1": [1, 2]}, None)
    assert d["publications_planifiees"] == 2
    assert d["impressions"] is None and d["clics"] is None
    d2 = ad_engine.tableau_de_bord({}, {"clics": 12})
    assert d2["clics"] == 12 and d2["impressions"] is None

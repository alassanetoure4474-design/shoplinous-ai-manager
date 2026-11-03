"""Regression tests: logistical verification must not imply market readiness."""

import intl


def test_only_markets_with_payment_and_tax_evidence_are_open():
    assert intl.get_country("FR").open_for_sale is True
    for code in intl.VERIFIED_MARKETS:
        if code == "FR":
            continue
        country = intl.get_country(code)
        assert country.shippable is True
        assert country.payment_available is False
        assert country.taxes_configured is False
        assert country.open_for_sale is False


def test_non_european_markets_remain_closed_without_evidence():
    for code in ("CI", "US", "CA", "JP", "AE", "ZA"):
        country = intl.get_country(code)
        assert country.registered is True
        assert country.open_for_sale is False



def test_catalogue_mondial_affiche_les_pays_fermes_et_leurs_raisons():
    from shoplinous_global import market_manager

    countries = market_manager.catalogue_mondial()
    assert len(countries) == 249
    by_code = {country["code"]: country for country in countries}
    assert by_code["CI"]["ouvert_vente"] is False
    assert "paiement_non_verifie" in by_code["CI"]["raisons_fermeture"]
    assert by_code["FR"]["ouvert_vente"] is True
    open_only = market_manager.catalogue_mondial(inclure_fermes=False)
    assert [country["code"] for country in open_only] == ["FR"]


def test_catalogue_mondial_filtre_par_region():
    from shoplinous_global import market_manager

    african = market_manager.catalogue_mondial(region="Afrique")
    assert african
    assert all(country["region"] == "Afrique" for country in african)

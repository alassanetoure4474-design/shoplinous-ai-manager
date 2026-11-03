"""Régressions du registre ISO mondial, des devises et du statut commercial."""
import pycountry

import intl
from shoplinous_global import currency_manager
from shoplinous_global import market_manager


def test_catalogue_contient_les_pays_et_territoires_iso_3166_1():
    assert len(intl.COUNTRIES) == len(list(pycountry.countries))
    assert len(intl.COUNTRIES) >= 249
    assert all(len(code) == 2 for code in intl.COUNTRIES)
    assert intl.country_status("US")["nom"] == "États-Unis"


def test_pays_nouveau_repertorie_mais_ferme_par_defaut():
    status = intl.country_status("JP")
    assert status["enregistre"] is True
    assert status["ouvert_vente"] is False
    assert status["livrable"] is False
    assert status["paiement_disponible"] is False
    assert status["taxes_configurees"] is False


def test_statut_pays_ne_souvre_qu_avec_toutes_les_validations():
    country = intl.get_country("JP")
    old = (country.shippable, country.payment_available, country.taxes_configured)
    try:
        intl.set_country_verification("JP", shippable=True)
        assert country.open_for_sale is False
        intl.set_country_verification("JP", payment_available=True)
        assert country.open_for_sale is False
        intl.set_country_verification("JP", taxes_configured=True)
        assert country.open_for_sale is True
    finally:
        intl.set_country_verification(
            "JP", shippable=old[0],
            payment_available=old[1], taxes_configured=old[2])


def test_devise_locale_et_taux_non_invente():
    assert intl.get_country("CI").currency == "XOF"
    assert intl.get_country("JP").currency == "JPY"
    assert intl.get_country("US").currency == "USD"
    assert "JPY" in currency_manager.DEVISES
    assert "USD" in currency_manager.DEVISES
    assert intl.format_price(1250, "XOF", "fr")
    try:
        intl.convert(10, "EUR", "JPY", {})
    except ValueError as exc:
        assert "Taux de change manquant" in str(exc)
    else:
        raise AssertionError("Une conversion sans taux aurait dû échouer")


def test_currency_manager_couvre_les_codes_iso_4217():
    codes_iso = {
        item.alpha_3 for item in pycountry.currencies
        if getattr(item, "alpha_3", None) and item.alpha_3 != "XXX"
    }
    assert codes_iso.issubset(set(intl.CURRENCIES))
    assert codes_iso.issubset(set(currency_manager.DEVISES))


def test_selecteur_mondial_n_ouvre_pas_les_pays_non_verifies():
    countries = market_manager.catalogue_mondial()
    assert len(countries) == len(intl.COUNTRIES)
    by_code = {country["code"]: country for country in countries}
    assert by_code["JP"]["ouvert_vente"] is False
    open_only = market_manager.catalogue_mondial(inclure_fermes=False)
    assert all(country["ouvert_vente"] for country in open_only)
    assert len(open_only) == 29


def test_indicatifs_telephoniques_ou_absence_explicite():
    ci = intl.country_status("CI")
    assert ci["indicatif"] in (None, "+225")

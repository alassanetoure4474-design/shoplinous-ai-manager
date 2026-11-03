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

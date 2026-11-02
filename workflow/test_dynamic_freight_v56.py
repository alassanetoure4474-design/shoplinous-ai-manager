"""Tests for on-demand CJ freight quotes above the cached 1-5 quantities."""
from datetime import date

import freight_collector_v56 as fc

VID = fc.VID_BLANCHE
TODAY = date.today()


def _options(price=12.5, aging="5-12"):
    return [{"logisticPrice": price, "logisticName": "CJ live quote",
             "logisticAging": aging}]


def test_quantity_six_uses_live_cj_quote_and_calculates_price():
    calls = []

    def fetch(vid, country, quantity):
        calls.append((vid, country, quantity))
        return _options()

    result = fc.compute_pricing_v56(
        2.81, VID, "FR", 6, freight_fetch_fn=fetch, aujourdhui=TODAY
    )

    assert calls == [(VID, "FR", 6)]
    assert result["statut"] == "recommandation_ok"
    assert result["quantite"] == 6
    assert result["fret"]["usd"] == 12.5
    assert result["calcul"]["cout_produit_total_eur"] == round(
        round(2.81 * fc.p55.EXCHANGE_RATE_USD_EUR, 2) * 6, 2
    )


def test_large_quantity_is_not_capped_or_extrapolated():
    calls = []

    def fetch(vid, country, quantity):
        calls.append(quantity)
        return _options(price=70.0)

    result = fc.compute_pricing_v56(
        2.81, VID, "FR", 50, freight_fetch_fn=fetch, aujourdhui=TODAY
    )

    assert calls == [50]
    assert result["statut"] == "recommandation_ok"
    assert result["quantite"] == 50
    assert result["fret"]["usd"] == 70.0


def test_quantity_above_five_without_live_quote_fails_closed():
    result = fc.compute_pricing_v56(2.81, VID, "FR", 6, aujourdhui=TODAY)
    assert result["statut"] == "tarif_dynamique_requis"
    assert result["verification_manuelle"] is True
    assert "calcul" not in result


def test_live_quote_error_fails_closed():
    def fetch(*args):
        raise RuntimeError("CJ unavailable")

    result = fc.compute_pricing_v56(
        2.81, VID, "FR", 6, freight_fetch_fn=fetch, aujourdhui=TODAY
    )
    assert result["statut"] == "tarif_dynamique_indisponible"
    assert "calcul" not in result


def test_no_shipping_within_fifteen_days_fails_closed():
    result = fc.compute_pricing_v56(
        2.81, VID, "FR", 6,
        freight_fetch_fn=lambda *args: _options(price=8.0, aging="20-35"),
        aujourdhui=TODAY,
    )
    assert result["statut"] == "aucun_transporteur_15j"
    assert "calcul" not in result


def test_non_positive_or_non_integer_quantities_are_rejected():
    for quantity in (0, -1, True, 2.5, "6"):
        result = fc.compute_pricing_v56(
            2.81, VID, "FR", quantity,
            freight_fetch_fn=lambda *args: _options(),
            aujourdhui=TODAY,
        )
        assert result["statut"] == "quantite_invalide"
        assert "calcul" not in result

"""Tests GeniusPay EUR (v5.11) : aucun reseau, aucune vraie transaction.

Prouve la conversion sans ambiguite euros/centimes :
- 24.90 EUR saisis -> 2490 centimes envoyes a l'API ;
- XOF inchange : entier, 1 unite = 1 XOF, minimum 200 ;
- webhook EUR verifie au centime pres, euros/centimes jamais confondus.
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal

import httpx
import pytest

from shoplinous_global.geniuspay import (
    GeniusPayClient,
    GeniusPaySecurityError,
)
from shoplinous_global.geniuspay_eur import GeniusPayEurSandboxTester


def client(transport=None):
    return GeniusPayClient(
        api_key="pk_sandbox_test",
        api_secret="sk_sandbox_test",
        webhook_secret="whsec_test",
        environment="sandbox",
        transport=transport,
    )


def _reponse_eur(request):
    payload = json.loads(request.content)
    return httpx.Response(201, json={
        "success": True,
        "data": {
            "reference": "MTX-EUR-1",
            "status": "pending",
            "checkout_url": "https://geniuspay.ci/checkout/MTX-EUR-1",
            "environment": "sandbox",
            "amount": payload["amount"],
            "currency": payload["currency"],
            "metadata": payload["metadata"],
        },
    })


def test_24_90_eur_converti_en_2490_centimes():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["amount"] == 2490
        assert payload["currency"] == "EUR"
        return _reponse_eur(request)

    resultat = client(httpx.MockTransport(handler)).creer_checkout(
        Decimal("24.90"), "CMD-EUR-1", devise="EUR",
        client={"country": "FR"},
    )
    assert resultat["montant"] == 2490
    assert resultat["montant_saisi"] == "24.90"
    assert resultat["unite_api"] == "centimes"
    assert resultat["devise"] == "EUR"


def test_25_eur_converti_en_2500_centimes():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["amount"] == 2500
        return _reponse_eur(request)

    resultat = client(httpx.MockTransport(handler)).creer_checkout(
        25, "CMD-EUR-2", devise="EUR"
    )
    assert resultat["montant"] == 2500


def test_eur_trois_decimales_refusees():
    with pytest.raises(ValueError, match="decimales"):
        client().creer_checkout(Decimal("24.905"), "CMD", devise="EUR")


def test_eur_sous_deux_euros_refuse():
    with pytest.raises(ValueError, match="2.00"):
        client().creer_checkout(Decimal("1.99"), "CMD", devise="EUR")


def test_eur_deux_euros_exactement_accepte():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["amount"] == 200
        return _reponse_eur(request)

    resultat = client(httpx.MockTransport(handler)).creer_checkout(
        Decimal("2.00"), "CMD", devise="EUR"
    )
    assert resultat["montant"] == 200


def test_xof_decimales_refusees():
    with pytest.raises(ValueError, match="entier"):
        client().creer_checkout(Decimal("200.5"), "CMD")


def test_xof_sous_200_refuse():
    with pytest.raises(ValueError, match="200"):
        client().creer_checkout(199, "CMD")


def test_xof_inchange_en_unites():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["amount"] == 16300
        assert payload["currency"] == "XOF"
        return httpx.Response(201, json={
            "success": True,
            "data": {
                "reference": "MTX-XOF-1",
                "status": "pending",
                "checkout_url": "https://geniuspay.ci/checkout/MTX-XOF-1",
                "environment": "sandbox",
                "metadata": {"order_id": "CMD"},
            },
        })

    resultat = client(httpx.MockTransport(handler)).creer_checkout(
        16300, "CMD"
    )
    assert resultat["montant"] == 16300
    assert resultat["unite_api"] == "unites"


def test_wave_toujours_reserve_ci_xof():
    with pytest.raises(ValueError, match="CI/XOF"):
        client().creer_checkout(
            Decimal("24.90"), "CMD", devise="EUR",
            client={"country": "FR"}, methode_paiement="wave",
        )


def _signer(payload, secret="whsec_test", ts=None):
    ts = int(time.time()) if ts is None else ts
    payload["timestamp"] = ts
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    signature = hmac.new(
        secret.encode(), str(ts).encode() + b"." + raw.encode(),
        hashlib.sha256,
    ).hexdigest()
    return raw, str(ts), signature


def _succes_eur():
    return {
        "id": "evt-eur",
        "event": "payment.success",
        "environment": "sandbox",
        "data": {
            "reference": "MTX-EUR-1",
            "amount": 2490,
            "currency": "EUR",
            "status": "completed",
            "metadata": {"order_id": "CMD-EUR-1"},
        },
    }


def test_webhook_eur_montant_exact_confirme():
    payload = _succes_eur()
    raw, ts, signature = _signer(payload)
    resultat = client().webhook_paiement_reussi(
        raw, signature, ts, "payment.success", "sandbox",
        commande="CMD-EUR-1", montant=2490, devise="EUR",
        reference="MTX-EUR-1",
    )
    assert resultat["event"] == "payment.success"


def test_webhook_eur_confusion_euros_centimes_refusee():
    # 2490 (centimes API) compare a 24.90 (euros) : incoherence repoussee.
    payload = _succes_eur()
    raw, ts, signature = _signer(payload)
    with pytest.raises(GeniusPaySecurityError, match="Montant"):
        client().webhook_paiement_reussi(
            raw, signature, ts, "payment.success", "sandbox",
            commande="CMD-EUR-1", montant=Decimal("24.90"), devise="EUR",
            reference="MTX-EUR-1",
        )


def test_webhook_eur_montant_falsifie_refuse():
    payload = _succes_eur()
    payload["data"]["amount"] = 2400
    raw, ts, signature = _signer(payload)
    with pytest.raises(GeniusPaySecurityError):
        client().webhook_paiement_reussi(
            raw, signature, ts, "payment.success", "sandbox",
            commande="CMD-EUR-1", montant=2490, devise="EUR",
            reference="MTX-EUR-1",
        )


def test_webhook_eur_devise_falsifiee_refuse():
    payload = _succes_eur()
    payload["data"]["currency"] = "USD"
    raw, ts, signature = _signer(payload)
    with pytest.raises(GeniusPaySecurityError):
        client().webhook_paiement_reussi(
            raw, signature, ts, "payment.success", "sandbox",
            commande="CMD-EUR-1", montant=2490, devise="EUR",
            reference="MTX-EUR-1",
        )


def test_testeur_eur_sandbox_complet_via_mock():
    etat = {}

    def handler(request):
        if request.method == "POST":
            payload = json.loads(request.content)
            etat["order_id"] = payload["metadata"]["order_id"]
            assert payload["amount"] == 2490
            assert payload["currency"] == "EUR"
            return httpx.Response(201, json={
                "success": True,
                "data": {
                    "reference": "MTX-EUR-SB",
                    "status": "pending",
                    "checkout_url": "https://geniuspay.ci/checkout/MTX-EUR-SB",
                    "environment": "sandbox",
                    "metadata": payload["metadata"],
                },
            })
        return httpx.Response(200, json={
            "success": True,
            "data": {
                "reference": "MTX-EUR-SB",
                "status": "pending",
                "environment": "sandbox",
                "amount": 2490,
                "currency": "EUR",
                "gateway": "stripe",
                "metadata": {"order_id": etat.get("order_id", "")},
            },
        })

    testeur = GeniusPayEurSandboxTester(
        api_key="pk_sandbox_t",
        api_secret="sk_sandbox_t",
        webhook_secret="whsec_t",
        environment="sandbox",
        transport=httpx.MockTransport(handler),
    )
    resultat = testeur.tester_carte_eur_sandbox()
    assert resultat["montant_api"] == 2490
    assert resultat["montant_saisi"] == "24.90"
    assert resultat["webhook_verifie"] is True
    assert resultat["attaques_repoussees"] == 4
    assert "stripe" in resultat["gateways"]

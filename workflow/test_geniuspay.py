"""Tests GeniusPay : aucun reseau, aucune vraie transaction."""
import hashlib
import hmac
import json
import time

import httpx
import pytest

from shoplinous_global.geniuspay import (
    GeniusPayClient,
    GeniusPayConfigurationError,
    GeniusPayError,
    GeniusPaySecurityError,
)


def client(transport=None, webhook_secret="whsec_test"):
    return GeniusPayClient(
        api_key="pk_sandbox_test",
        api_secret="sk_sandbox_test",
        webhook_secret=webhook_secret,
        environment="sandbox",
        transport=transport,
    )


def test_sandbox_est_le_mode_par_defaut(monkeypatch):
    monkeypatch.delenv("GENIUSPAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("GENIUSPAY_ALLOW_LIVE", raising=False)
    c = GeniusPayClient(
        api_key="pk_sandbox_x",
        api_secret="sk_sandbox_y",
        webhook_secret="whsec_x",
    )
    assert c.environment == "sandbox"
    assert c.payment_ready is True


def test_cles_de_mauvais_environnement_refusees():
    c = GeniusPayClient(
        api_key="pk_live_test",
        api_secret="sk_live_test",
        webhook_secret="whsec_test",
        environment="sandbox",
    )
    assert c.api_configured is False
    with pytest.raises(GeniusPayConfigurationError):
        c.tester_connexion()


def test_mode_live_verrouille_par_defaut():
    with pytest.raises(GeniusPayConfigurationError, match="GENIUSPAY_ALLOW_LIVE"):
        GeniusPayClient(
            api_key="pk_live_test",
            api_secret="sk_live_test",
            webhook_secret="whsec_test",
            environment="live",
            allow_live=False,
        )


def test_tester_connexion_est_lecture_seule():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path.endswith("/account")
        assert request.headers["X-API-Key"] == "pk_sandbox_test"
        return httpx.Response(200, json={
            "success": True,
            "data": {
                "status": "active",
                "environment": "sandbox",
                "business_name": "SHOPLINOUS",
            },
        })

    result = client(httpx.MockTransport(handler)).tester_connexion()
    assert result["connecte"] is True
    assert result["environnement"] == "sandbox"


def test_compte_inactif_refuse():
    def handler(request):
        return httpx.Response(200, json={
            "success": True,
            "data": {"status": "pending", "environment": "sandbox"},
        })

    with pytest.raises(GeniusPayError, match="pas actif"):
        client(httpx.MockTransport(handler)).tester_connexion()


def test_decouverte_fournisseurs_mobile_money():
    def handler(request):
        assert request.method == "GET"
        assert request.url.params["country"] == "CI"
        return httpx.Response(200, json={
            "success": True,
            "data": {
                "country": "CI",
                "providers": [{"code": "WAVE_CIV", "name": "Wave"}],
            },
        })

    data = client(httpx.MockTransport(handler)).fournisseurs_mobile_money("ci")
    assert data["providers"][0]["code"] == "WAVE_CIV"


def test_checkout_sans_secret_webhook_est_bloque():
    c = client(webhook_secret="")
    assert c.api_configured is True
    assert c.payment_ready is False
    with pytest.raises(GeniusPayConfigurationError, match="secret webhook"):
        c.creer_checkout(1000, "CMD-1")


def test_checkout_heberge_sandbox_et_reference_commande():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path.endswith("/payments")
        payload = json.loads(request.content)
        assert payload["amount"] == 15000
        assert payload["currency"] == "XOF"
        assert payload["metadata"]["order_id"] == "CMD-42"
        assert "payment_method" not in payload
        return httpx.Response(201, json={
            "success": True,
            "data": {
                "reference": "MTX-ABC123",
                "status": "pending",
                "checkout_url": "https://geniuspay.ci/checkout/MTX-ABC123",
                "environment": "sandbox",
                "metadata": {"order_id": "CMD-42"},
            },
        })

    result = client(httpx.MockTransport(handler)).creer_checkout(
        15000, "CMD-42", client={"country": "CI"}
    )
    assert result["reference"] == "MTX-ABC123"
    assert result["checkout_url"].endswith("MTX-ABC123")


def test_checkout_refuse_un_domaine_de_redirection_inattendu():
    def handler(request):
        return httpx.Response(201, json={
            "success": True,
            "data": {
                "reference": "MTX-BAD",
                "status": "pending",
                "checkout_url": "https://phishing.example/pay",
                "environment": "sandbox",
            },
        })

    with pytest.raises(GeniusPayError, match="Domaine"):
        client(httpx.MockTransport(handler)).creer_checkout(500, "CMD-1")


def test_checkout_refuse_devise_non_documentee():
    with pytest.raises(ValueError, match="Devise non autorisee"):
        client().creer_checkout(1000, "CMD-1", devise="NGN")


def test_create_webhook_exige_https_et_retourne_un_secret():
    with pytest.raises(ValueError, match="https"):
        client().creer_webhook("http://example.com/hook")

    def handler(request):
        payload = json.loads(request.content)
        assert "payment.success" in payload["events"]
        return httpx.Response(201, json={
            "success": True,
            "data": {"id": 7, "secret": "whsec_created_once"},
        })

    data = client(httpx.MockTransport(handler)).creer_webhook(
        "https://shoplinous.example/webhooks/geniuspay"
    )
    assert data["secret"] == "whsec_created_once"


def _signed_payload(payload, secret="whsec_test", timestamp=None):
    ts = str(int(time.time()) if timestamp is None else timestamp)
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    sig = hmac.new(
        secret.encode(), ts.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return raw, ts, sig


def _success_payload():
    return {
        "id": "evt-1",
        "event": "payment.success",
        "timestamp": int(time.time()),
        "data": {
            "reference": "MTX-ABC123",
            "amount": 15000,
            "currency": "XOF",
            "status": "completed",
            "metadata": {"order_id": "CMD-42"},
        },
        "environment": "sandbox",
    }


def test_webhook_valide_lie_reference_montant_devise_et_commande():
    payload = _success_payload()
    raw, ts, sig = _signed_payload(payload)
    result = client().webhook_paiement_reussi(
        raw, sig, ts, "payment.success", "sandbox",
        commande="CMD-42", montant=15000, devise="XOF",
        reference="MTX-ABC123",
    )
    assert result["event"] == "payment.success"


def test_webhook_refuse_signature_invalide():
    payload = _success_payload()
    raw, ts, _ = _signed_payload(payload)
    with pytest.raises(GeniusPaySecurityError, match="Signature"):
        client().verifier_webhook(
            raw, "0" * 64, ts, "payment.success", "sandbox"
        )


def test_webhook_refuse_timestamp_trop_ancien():
    payload = _success_payload()
    raw, ts, sig = _signed_payload(payload, timestamp=int(time.time()) - 600)
    with pytest.raises(GeniusPaySecurityError, match="expire"):
        client().verifier_webhook(
            raw, sig, ts, "payment.success", "sandbox"
        )


@pytest.mark.parametrize("field,value", [
    ("reference", "MTX-OTHER"),
    ("amount", 1),
    ("currency", "EUR"),
])
def test_webhook_refuse_donnees_paiement_incoherentes(field, value):
    payload = _success_payload()
    payload["data"][field] = value
    raw, ts, sig = _signed_payload(payload)
    with pytest.raises(GeniusPaySecurityError):
        client().webhook_paiement_reussi(
            raw, sig, ts, "payment.success", "sandbox",
            commande="CMD-42", montant=15000, devise="XOF",
            reference="MTX-ABC123",
        )


def test_webhook_refuse_evenement_qui_n_est_pas_un_succes():
    payload = _success_payload()
    payload["event"] = "payment.failed"
    payload["data"]["status"] = "failed"
    raw, ts, sig = _signed_payload(payload)
    with pytest.raises(GeniusPaySecurityError):
        client().webhook_paiement_reussi(
            raw, sig, ts, "payment.failed", "sandbox",
            commande="CMD-42", montant=15000, devise="XOF",
            reference="MTX-ABC123",
        )

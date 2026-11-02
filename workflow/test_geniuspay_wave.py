"""Tests du diagnostic Wave Direct Sandbox : reseau entierement simule."""
import json

import httpx
import pytest

from shoplinous_global.geniuspay import (
    GeniusPayConfigurationError,
    GeniusPayError,
)
from shoplinous_global.geniuspay_wave import GeniusPayWaveSandboxTester


def make_client(transport=None, environment="sandbox", api_key="pk_sandbox_test",
                api_secret="sk_sandbox_test", allow_live=False):
    return GeniusPayWaveSandboxTester(
        api_key=api_key,
        api_secret=api_secret,
        environment=environment,
        allow_live=allow_live,
        transport=transport,
    )


def test_wave_direct_force_la_gateway_ci_et_verifie_la_transaction():
    seen = {}
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            payload = json.loads(request.content)
            seen["order_id"] = payload["metadata"]["order_id"]
            assert payload["amount"] == 200
            assert payload["currency"] == "XOF"
            assert payload["payment_method"] == "wave"
            assert payload["gateway"] == "wave"
            assert payload["customer"]["country"] == "CI"
            assert payload["metadata"]["purpose"] == "shoplinous_wave_direct_sandbox_test"
            assert "phone" not in payload["customer"]
            return httpx.Response(201, json={
                "success": True,
                "data": {
                    "reference": "MTX-WAVE-TEST",
                    "amount": 200,
                    "currency": "XOF",
                    "status": "pending",
                    "gateway": "wave",
                    "environment": "sandbox",
                    "metadata": {"order_id": seen["order_id"]},
                },
            })

        assert request.method == "GET"
        assert request.url.path.endswith("/payments/MTX-WAVE-TEST")
        return httpx.Response(200, json={
            "success": True,
            "data": {
                "reference": "MTX-WAVE-TEST",
                "amount": 200,
                "currency": "XOF",
                "status": "pending",
                "payment_method": "wave",
                "payment_provider": "wave",
                "environment": "sandbox",
                "metadata": {"order_id": seen["order_id"]},
            },
        })

    result = make_client(httpx.MockTransport(handler)).tester_wave_direct_sandbox()
    assert calls == ["POST", "GET"]
    assert result == {
        "reference": "MTX-WAVE-TEST",
        "environnement": "sandbox",
        "pays": "CI",
        "gateway": "wave",
        "montant": 200,
        "devise": "XOF",
        "statut": "pending",
    }


def test_wave_direct_refuse_toujours_le_mode_live_avant_reseau():
    called = []

    def handler(request):
        called.append(request.method)
        return httpx.Response(500)

    c = make_client(
        httpx.MockTransport(handler),
        environment="live",
        api_key="pk_live_test",
        api_secret="sk_live_test",
        allow_live=True,
    )
    with pytest.raises(GeniusPayConfigurationError, match="hors Sandbox"):
        c.tester_wave_direct_sandbox()
    assert called == []


def test_wave_direct_refuse_si_gateway_non_confirmee():
    seen = {}

    def handler(request):
        if request.method == "POST":
            payload = json.loads(request.content)
            seen["order_id"] = payload["metadata"]["order_id"]
            return httpx.Response(201, json={
                "success": True,
                "data": {
                    "reference": "MTX-WAVE-NOT-CONFIRMED",
                    "amount": 200,
                    "currency": "XOF",
                    "status": "pending",
                    "environment": "sandbox",
                    "metadata": {"order_id": seen["order_id"]},
                },
            })
        return httpx.Response(200, json={
            "success": True,
            "data": {
                "reference": "MTX-WAVE-NOT-CONFIRMED",
                "amount": 200,
                "currency": "XOF",
                "status": "pending",
                "environment": "sandbox",
                "metadata": {"order_id": seen["order_id"]},
            },
        })

    with pytest.raises(GeniusPayError, match="pas confirme le routage"):
        make_client(httpx.MockTransport(handler)).tester_wave_direct_sandbox()


def test_wave_direct_refuse_si_la_reponse_retourne_live():
    seen = {}

    def handler(request):
        if request.method == "POST":
            payload = json.loads(request.content)
            seen["order_id"] = payload["metadata"]["order_id"]
            return httpx.Response(201, json={
                "success": True,
                "data": {
                    "reference": "MTX-WAVE-ENV",
                    "amount": 200,
                    "currency": "XOF",
                    "status": "pending",
                    "gateway": "wave",
                    "environment": "sandbox",
                },
            })
        return httpx.Response(200, json={
            "success": True,
            "data": {
                "reference": "MTX-WAVE-ENV",
                "amount": 200,
                "currency": "XOF",
                "status": "pending",
                "payment_provider": "wave",
                "environment": "live",
                "metadata": {"order_id": seen["order_id"]},
            },
        })

    with pytest.raises(GeniusPayError, match="environnement"):
        make_client(httpx.MockTransport(handler)).tester_wave_direct_sandbox()

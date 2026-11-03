import json

import httpx
import pytest

from shoplinous_global import supabase_store as ss


def test_supabase_store_from_env_accepte_la_cle_secret_nommee(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.setenv(
        "SUPABASE_SECRET_KEYS",
        json.dumps({"default": "sb_secret_server_only"}),
    )

    store = ss.SupabaseStore.from_env()
    assert store.base_url == "https://project.supabase.co"
    assert store._service_key == "sb_secret_server_only"



def test_supabase_store_from_env_ne_choisit_pas_une_cle_secrete_non_default(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.setenv(
        "SUPABASE_SECRET_KEYS",
        json.dumps({"billing": "sb_secret_billing_only"}),
    )

    with pytest.raises(ss.SupabasePersistenceError, match="absente"):
        ss.SupabaseStore.from_env()


def test_rpc_legacy_service_role_jwt_conserve_authorization_bearer():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        return httpx.Response(200, json={"ok": True})

    legacy_jwt = "eyJhbGciOiJIUzI1NiJ9.legacy.signature"
    store = ss.SupabaseStore(
        "https://project.supabase.co",
        legacy_jwt,
        transport=httpx.MockTransport(handler),
    )
    assert store._rpc("shoplinous_reserve_wave_payment", {}) == {"ok": True}
    assert seen["headers"]["apikey"] == legacy_jwt
    assert seen["headers"]["authorization"] == "Bearer " + legacy_jwt

def test_supabase_store_refuse_http_et_cle_absente():
    with pytest.raises(ss.SupabasePersistenceError, match="HTTPS"):
        ss.SupabaseStore("http://project.supabase.co", "secret")
    with pytest.raises(ss.SupabasePersistenceError, match="absente"):
        ss.SupabaseStore("https://project.supabase.co", "")


def test_reservation_wave_envoie_une_rpc_serveur_sandbox():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "created": True,
            "payment_id": "6ea5210e-0bf0-4cbd-b102-1a2f01f5a010",
            "order_number": "FW-123",
            "status": "creating",
            "environment": "sandbox",
        })

    store = ss.SupabaseStore(
        "https://project.supabase.co",
        "sb_secret_server_only",
        transport=httpx.MockTransport(handler),
    )
    result = store.reserver_paiement_wave(
        "FW-123", 2500, "idem-key-123", environment="sandbox"
    )

    assert result["created"] is True
    assert seen["url"].endswith("/rest/v1/rpc/shoplinous_reserve_wave_payment")
    assert seen["headers"]["apikey"] == "sb_secret_server_only"
    assert "authorization" not in seen["headers"]
    assert seen["body"]["p_order_number"] == "FW-123"
    assert seen["body"]["p_country"] == "CI"
    assert seen["body"]["p_currency"] == "XOF"
    assert seen["body"]["p_amount"] == "2500"
    assert seen["body"]["p_method"] == "wave"
    assert seen["body"]["p_environment"] == "sandbox"


def test_reservation_refuse_montant_xof_non_entier_ou_inferieur():
    store = ss.SupabaseStore("https://project.supabase.co", "server-key")
    with pytest.raises(ValueError, match="minimum"):
        store.reserver_paiement_wave("FW-1", 150, "idem-key-123")
    with pytest.raises(ValueError, match="entier"):
        store.reserver_paiement_wave("FW-1", "2500.50", "idem-key-123")


def test_reservation_refuse_live_meme_si_demande():
    store = ss.SupabaseStore("https://project.supabase.co", "server-key")
    with pytest.raises(ss.SupabasePersistenceError, match="Live"):
        store.reserver_paiement_wave(
            "FW-1", 2500, "idem-key-123", environment="live"
        )


def test_erreur_http_supabase_ne_revele_pas_la_cle():
    secret = "sb_secret_do_not_log"

    def handler(request):
        return httpx.Response(401, text="invalid api key " + secret)

    store = ss.SupabaseStore(
        "https://project.supabase.co",
        secret,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ss.SupabasePersistenceError) as error:
        store._rpc("shoplinous_reserve_wave_payment", {})
    assert secret not in str(error.value)


def test_finalisation_refuse_domaine_wave_imitateur_avant_rpc():
    store = ss.SupabaseStore("https://project.supabase.co", "server-key")
    with pytest.raises(ValueError, match="domaine HTTPS Wave"):
        store.finaliser_checkout_wave(
            "6ea5210e-0bf0-4cbd-b102-1a2f01f5a010",
            "MTX-TEST",
            "https://wave.com.evil.example/pay",
        )


def test_finalisation_accepte_uniquement_wave_https_et_envoie_rpc():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "created": True,
            "payment_id": "6ea5210e-0bf0-4cbd-b102-1a2f01f5a010",
            "status": "pending",
            "provider_reference": "MTX-TEST",
            "checkout_url": "https://wave.com/pay/MTX-TEST",
            "environment": "sandbox",
        })

    store = ss.SupabaseStore(
        "https://project.supabase.co",
        "server-key",
        transport=httpx.MockTransport(handler),
    )
    result = store.finaliser_checkout_wave(
        "6ea5210e-0bf0-4cbd-b102-1a2f01f5a010",
        "MTX-TEST",
        "https://wave.com/pay/MTX-TEST",
        environment="sandbox",
    )
    assert result["status"] == "pending"
    assert seen["body"]["p_reference"] == "MTX-TEST"


class FakeStore:
    def __init__(self, reservation):
        self.reservation = dict(reservation)
        self.finalized = None

    def reserver_paiement_wave(self, **kwargs):
        self.reserve_args = kwargs
        return dict(self.reservation)

    def finaliser_checkout_wave(self, **kwargs):
        self.finalized = kwargs
        return {
            "created": True,
            "payment_id": kwargs["payment_id"],
            "status": "pending",
            "provider_reference": kwargs["reference"],
            "checkout_url": kwargs["checkout_url"],
            "environment": kwargs["environment"],
        }


class FakeGeniusPay:
    environment = "sandbox"

    def __init__(self):
        self.calls = []

    def creer_checkout_wave(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "reference": "MTX-WAVE-TEST",
            "checkout_url": "https://wave.com/pay/MTX-WAVE-TEST",
            "environnement": "sandbox",
        }


def test_service_persistant_cree_checkout_apres_reservation():
    store = FakeStore({
        "created": True,
        "payment_id": "6ea5210e-0bf0-4cbd-b102-1a2f01f5a010",
        "order_number": "FW-123",
        "status": "creating",
        "environment": "sandbox",
    })
    geniuspay = FakeGeniusPay()

    result = ss.WavePersistentPaymentService(store, geniuspay).initier(
        "FW-123", 3500, "idem-key-123"
    )

    assert result["status"] == "pending"
    assert len(geniuspay.calls) == 1
    assert geniuspay.calls[0]["montant"] == 3500
    assert geniuspay.calls[0]["commande"] == "FW-123"
    assert store.finalized["reference"] == "MTX-WAVE-TEST"


def test_service_persistant_reutilise_checkout_pending_sans_second_appel():
    existing = {
        "created": False,
        "payment_id": "6ea5210e-0bf0-4cbd-b102-1a2f01f5a010",
        "order_number": "FW-123",
        "status": "pending",
        "provider_reference": "MTX-OLD",
        "checkout_url": "https://wave.com/pay/MTX-OLD",
        "environment": "sandbox",
    }
    geniuspay = FakeGeniusPay()
    result = ss.WavePersistentPaymentService(
        FakeStore(existing), geniuspay
    ).initier("FW-123", 3500, "idem-key-123")

    assert result["provider_reference"] == "MTX-OLD"
    assert geniuspay.calls == []


def test_service_persistant_bloque_creation_ambigue_pour_eviter_doublon():
    reservation = {
        "created": False,
        "payment_id": "6ea5210e-0bf0-4cbd-b102-1a2f01f5a010",
        "order_number": "FW-123",
        "status": "creating",
        "environment": "sandbox",
    }
    geniuspay = FakeGeniusPay()
    with pytest.raises(ss.PaymentReconciliationRequired, match="aucun second checkout"):
        ss.WavePersistentPaymentService(
            FakeStore(reservation), geniuspay
        ).initier("FW-123", 3500, "idem-key-123")
    assert geniuspay.calls == []


def test_service_persistant_interdit_live_avant_reservation():
    class LiveGeniusPay(FakeGeniusPay):
        environment = "live"

    store = FakeStore({})
    with pytest.raises(ss.SupabasePersistenceError, match="Live"):
        ss.WavePersistentPaymentService(
            store, LiveGeniusPay()
        ).initier("FW-123", 3500, "idem-key-123")
    assert not hasattr(store, "reserve_args")

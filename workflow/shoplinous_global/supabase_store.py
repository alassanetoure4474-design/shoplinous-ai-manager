"""Persistance serveur Supabase pour les checkouts Wave Direct.

Ce module utilise uniquement la clé service_role/secret côté serveur.
Il ne journalise jamais les clés, signatures ou payloads de paiement.
"""
from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import httpx


class SupabasePersistenceError(RuntimeError):
    """Erreur Supabase sans divulgation de réponse ou de secret."""


class PaymentReconciliationRequired(SupabasePersistenceError):
    """Un checkout a pu être créé avant une panne : ne pas en créer un autre."""


def _amount_xof(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Montant XOF invalide") from None
    if not amount.is_finite() or amount < Decimal("200"):
        raise ValueError("Montant minimum Wave : 200 XOF")
    if amount != amount.to_integral_value():
        raise ValueError("Le montant XOF doit être un nombre entier")
    return amount


class SupabaseStore:
    """Client PostgREST minimal, réservé au backend SHOPLINOUS."""

    def __init__(
        self,
        supabase_url: str,
        service_key: str,
        timeout: float = 15.0,
        transport=None,
    ):
        parsed = urlparse(str(supabase_url or "").strip())
        if parsed.scheme != "https" or not parsed.hostname:
            raise SupabasePersistenceError(
                "SUPABASE_URL doit être une URL HTTPS valide"
            )
        if not isinstance(service_key, str) or not service_key.strip():
            raise SupabasePersistenceError(
                "Clé Supabase serveur absente (aucun accès effectué)"
            )
        self.base_url = supabase_url.rstrip("/")
        self._service_key = service_key
        self.timeout = timeout
        self.transport = transport

    @classmethod
    def from_env(cls, **kwargs) -> "SupabaseStore":
        return cls(
            supabase_url=os.getenv("SUPABASE_URL", ""),
            service_key=(
                os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
                or os.getenv("SUPABASE_SECRET_KEY", "")
            ),
            **kwargs,
        )

    def _rpc(self, function_name: str, payload: dict) -> dict:
        if not function_name.replace("_", "").isalnum():
            raise ValueError("Nom de fonction RPC invalide")
        headers = {
            "apikey": self._service_key,
            "Authorization": "Bearer " + self._service_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = client.post(
                    self.base_url + "/rest/v1/rpc/" + function_name,
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError:
            raise SupabasePersistenceError(
                "Supabase est injoignable (détails réseau masqués)"
            ) from None

        if response.status_code < 200 or response.status_code >= 300:
            raise SupabasePersistenceError(
                "Supabase a refusé l'opération (HTTP "
                + str(response.status_code) + ")"
            )
        try:
            data = response.json()
        except ValueError:
            raise SupabasePersistenceError(
                "Réponse RPC Supabase non JSON"
            ) from None
        if isinstance(data, list):
            if len(data) != 1 or not isinstance(data[0], dict):
                raise SupabasePersistenceError(
                    "Réponse RPC Supabase inattendue"
                )
            data = data[0]
        if not isinstance(data, dict):
            raise SupabasePersistenceError(
                "Réponse RPC Supabase inattendue"
            )
        return data

    def reserver_paiement_wave(
        self,
        order_number: str,
        amount,
        idempotency_key: str,
        environment: str = "sandbox",
    ) -> dict:
        order = str(order_number or "").strip()
        key = str(idempotency_key or "").strip()
        env = str(environment or "").strip().lower()
        montant = _amount_xof(amount)
        if not order or len(order) > 120:
            raise ValueError("Référence de commande invalide")
        if not 8 <= len(key) <= 128:
            raise ValueError("Clé d'idempotence invalide (8 à 128 caractères)")
        if env not in ("sandbox", "live"):
            raise ValueError("Environnement GeniusPay invalide")

        result = self._rpc(
            "shoplinous_reserve_wave_payment",
            {
                "p_order_number": order,
                "p_country": "CI",
                "p_currency": "XOF",
                "p_amount": str(montant),
                "p_method": "wave",
                "p_idempotency_key": key,
                "p_environment": env,
            },
        )
        required = ("payment_id", "order_number", "status", "environment")
        if any(not result.get(field) for field in required):
            raise SupabasePersistenceError(
                "Réservation Supabase incomplète"
            )
        if result["order_number"] != order:
            raise SupabasePersistenceError(
                "La référence de commande Supabase ne correspond pas"
            )
        return result

    def finaliser_checkout_wave(
        self,
        payment_id: str,
        reference: str,
        checkout_url: str,
        environment: str = "sandbox",
    ) -> dict:
        payment = str(payment_id or "").strip()
        ref = str(reference or "").strip()
        env = str(environment or "").strip().lower()
        parsed = urlparse(str(checkout_url or ""))
        if not payment or not ref or len(ref) > 120:
            raise ValueError("Identifiants du checkout invalides")
        if parsed.scheme != "https" or parsed.hostname not in (
            "wave.com", "www.wave.com"
        ):
            raise ValueError(
                "La redirection du checkout doit utiliser le domaine HTTPS Wave"
            )
        if env not in ("sandbox", "live"):
            raise ValueError("Environnement GeniusPay invalide")

        result = self._rpc(
            "shoplinous_finalize_wave_checkout",
            {
                "p_payment_id": payment,
                "p_reference": ref,
                "p_checkout_url": checkout_url,
                "p_environment": env,
            },
        )
        if str(result.get("payment_id")) != payment:
            raise SupabasePersistenceError(
                "La transaction finalisée ne correspond pas"
            )
        if result.get("provider_reference") != ref:
            raise SupabasePersistenceError(
                "La référence GeniusPay finalisée ne correspond pas"
            )
        return result


class WavePersistentPaymentService:
    """Orchestre réservation DB -> GeniusPay -> sauvegarde du checkout.

    Une réservation restée en état creating après une panne est bloquée :
    une tentative ambiguë doit être rapprochée manuellement avant tout retry.
    """

    def __init__(self, store: SupabaseStore, geniuspay_client):
        self.store = store
        self.geniuspay = geniuspay_client

    def initier(
        self,
        order_number: str,
        amount,
        idempotency_key: str,
    ) -> dict:
        environment = str(
            getattr(self.geniuspay, "environment", "sandbox")
        ).lower()
        reservation = self.store.reserver_paiement_wave(
            order_number=order_number,
            amount=amount,
            idempotency_key=idempotency_key,
            environment=environment,
        )

        # Une transaction pending déjà enregistrée est renvoyée telle quelle.
        # Aucun nouvel appel à POST /payments n'est effectué.
        if not reservation.get("created"):
            if (
                reservation.get("status") == "pending"
                and reservation.get("provider_reference")
                and reservation.get("checkout_url")
            ):
                return reservation
            if reservation.get("status") == "succeeded":
                return reservation
            if reservation.get("status") == "creating":
                raise PaymentReconciliationRequired(
                    "Une tentative de checkout existe sans résultat confirmé. "
                    "Rapprochement GeniusPay requis ; aucun second checkout créé."
                )
            raise SupabasePersistenceError(
                "La tentative existante doit être vérifiée avant un nouveau paiement"
            )

        # En cas de réponse réseau ambiguë, l'état DB reste creating.
        # Le service ne crée jamais automatiquement un checkout de remplacement.
        checkout = self.geniuspay.creer_checkout_wave(
            montant=int(_amount_xof(amount)),
            commande=order_number,
            devise="XOF",
            client={"country": "CI"},
        )
        reference = checkout.get("reference")
        url = checkout.get("checkout_url")
        checkout_environment = checkout.get("environnement", environment)
        return self.store.finaliser_checkout_wave(
            payment_id=reservation["payment_id"],
            reference=reference,
            checkout_url=url,
            environment=checkout_environment,
        )

"""Diagnostic Wave Direct pour GeniusPay, Sandbox uniquement.

Ce test cree une transaction technique simulee de 200 XOF puis la relit
par reference. Il ne doit jamais etre utilise avec des cles Live.
"""
from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from .geniuspay import (
    GeniusPayClient,
    GeniusPayConfigurationError,
    GeniusPayError,
)


class GeniusPayWaveSandboxTester(GeniusPayClient):
    """Diagnostic actif mais non financier : transaction Sandbox simulee."""

    MONTANT_TEST = 200
    DEVISE_TEST = "XOF"
    PAYS_TEST = "CI"

    def tester_wave_direct_sandbox(self) -> dict:
        """Force payment_method/gateway=wave, puis relit la transaction.

        La documentation GeniusPay indique que Sandbox simule les transactions.
        Le mode Live est explicitement refuse avant toute requete.
        """
        if self.environment != "sandbox":
            raise GeniusPayConfigurationError(
                "Test Wave refuse hors Sandbox : aucune requete envoyee"
            )
        if not self.api_configured:
            raise GeniusPayConfigurationError(
                "Cles GeniusPay Sandbox absentes ou incompatibles"
            )

        order_id = "SHOPLINOUS-WAVE-TEST-" + uuid.uuid4().hex[:16]
        payload = {
            "amount": self.MONTANT_TEST,
            "currency": self.DEVISE_TEST,
            "payment_method": "wave",
            "gateway": "wave",
            "description": "SHOPLINOUS - diagnostic Wave Direct Sandbox",
            "customer": {"country": self.PAYS_TEST},
            "metadata": {
                "order_id": order_id,
                "purpose": "shoplinous_wave_direct_sandbox_test",
            },
        }

        created = self._data(self._request("POST", "/payments", body=payload))
        reference = created.get("reference")
        if not isinstance(reference, str) or not reference.strip():
            raise GeniusPayError(
                "GeniusPay n'a pas retourne de reference pour le test Wave Sandbox"
            )

        created_environment = str(created.get("environment", "")).lower()
        if created_environment and created_environment != "sandbox":
            raise GeniusPaySecurityError(
                "GeniusPay a retourne un environnement autre que Sandbox"
            )

        detail = self.obtenir_paiement(reference)
        detail_environment = str(detail.get("environment", "sandbox")).lower()
        if detail_environment != "sandbox":
            raise GeniusPaySecurityError(
                "La transaction Wave retournee n'est pas en Sandbox"
            )

        candidates = []
        for source in (created, detail):
            for field in ("gateway", "payment_method", "payment_provider", "provider"):
                value = source.get(field)
                if value is not None:
                    candidates.append(str(value).strip().lower())
        if "wave" not in candidates:
            raise GeniusPayError(
                "La transaction Sandbox a ete creee, mais GeniusPay n'a pas confirme "
                "le routage vers Wave Direct (reference " + reference + ")"
            )

        try:
            amount_ok = Decimal(str(detail.get("amount"))) == Decimal(str(self.MONTANT_TEST))
        except (InvalidOperation, TypeError, ValueError):
            amount_ok = False
        if not amount_ok:
            raise GeniusPayError(
                "Le montant retourne pour le test Wave ne correspond pas "
                "(reference " + reference + ")"
            )
        if str(detail.get("currency", "")).upper() != self.DEVISE_TEST:
            raise GeniusPayError(
                "La devise retournee pour le test Wave ne correspond pas "
                "(reference " + reference + ")"
            )

        metadata = detail.get("metadata")
        if not isinstance(metadata, dict) or str(metadata.get("order_id", "")) != order_id:
            raise GeniusPayError(
                "Les metadata de la transaction Wave n'ont pas ete confirmees "
                "(reference " + reference + ")"
            )

        status = str(detail.get("status", "")).strip().lower()
        if status not in ("pending", "processing", "completed"):
            raise GeniusPayError(
                "Statut inattendu pour la transaction Wave Sandbox : "
                + (status or "absent")
                + " (reference " + reference + ")"
            )

        return {
            "reference": reference,
            "environnement": detail_environment,
            "pays": self.PAYS_TEST,
            "gateway": "wave",
            "montant": self.MONTANT_TEST,
            "devise": self.DEVISE_TEST,
            "statut": status,
        }


# Import local uniquement pour signaler une reponse d'environnement non sure.
from .geniuspay import GeniusPaySecurityError

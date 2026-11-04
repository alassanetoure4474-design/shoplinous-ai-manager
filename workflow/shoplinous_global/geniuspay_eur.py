"""Diagnostic carte/EUR GeniusPay, Sandbox uniquement.

Cree un checkout heberge EUR (saisie 24,90 -> API 2490 centimes), relit
la transaction par reference, puis valide un webhook payment.success
signe HMAC. Quatre attaques sont repoussees a chaque execution.
Il ne doit jamais etre utilise avec des cles Live : aucune requete n'est
emise hors Sandbox, aucun paiement reel n'est realise.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from decimal import Decimal, InvalidOperation

from .geniuspay import (
    GeniusPayClient,
    GeniusPayConfigurationError,
    GeniusPayError,
    GeniusPaySecurityError,
)


class GeniusPayEurSandboxTester(GeniusPayClient):
    """Diagnostic actif mais non financier : checkout EUR Sandbox simule."""

    MONTANT_TEST_EUR = Decimal("24.90")  # saisie en unites majeures
    MONTANT_TEST_CENTIMES = 2490         # unites mineures envoyees a l'API
    DEVISE_TEST = "EUR"
    PAYS_TEST = "FR"
    ATTAQUES_ATTENDUES = 4

    def _exiger_sandbox(self) -> None:
        if self.environment != "sandbox":
            raise GeniusPayConfigurationError(
                "Test EUR refuse hors Sandbox : aucune requete envoyee"
            )
        if not self.api_configured:
            raise GeniusPayConfigurationError(
                "Cles GeniusPay Sandbox absentes ou incompatibles"
            )

    def _secret_webhook_sandbox(self) -> str:
        """Recupere un secret webhook Sandbox si aucun n'est configure."""
        data = self._data(self._request(
            "POST",
            "/webhooks",
            body={
                "name": "SHOPLINOUS test sandbox EUR",
                "url": "https://example.com/shoplinous-eur-sandbox-test",
                "events": ["payment.success", "payment.failed"],
            },
        ))
        secret = data.get("secret")
        if not secret:
            raise GeniusPayError(
                "GeniusPay n'a pas retourne de secret webhook Sand
box"
            )
        return str(secret)

    def _signer(self, payload: dict, ts: int, secret: str) -> tuple:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        signature = hmac.new(
            secret.encode("utf-8"),
            str(ts).encode("ascii") + b"." + raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return raw, signature

    def tester_carte_eur_sandbox(self) -> dict:
        """Checkout EUR 24,90 + relecture + webhook signe + attaques."""
        self._exiger_sandbox()
        if not self.webhook_secret:
            self.webhook_secret = self._secret_webhook_sandbox()

        order_id = "SHOPLINOUS-EUR-TEST-" + uuid.uuid4().hex[:16]
        checkout = self.creer_checkout(
            montant=self.MONTANT_TEST_EUR,
            commande=order_id,
            devise=self.DEVISE_TEST,
            description="SHOPLINOUS - diagnostic carte EUR Sandbox",
            client={"country": self.PAYS_TEST},
        )
        if checkout["devise"] != self.DEVISE_TEST:
            raise GeniusPayError("Le checkout EUR n'a pas conserve la devise EUR")
        if checkout["montant"] != self.MONTANT_TEST_CENTIMES:
            raise GeniusPayError(
                "Montant API inattendu : " + str(checkout["montant"])
                + " au lieu de " + str(self.MONTANT_TEST_CENTIMES)
                + " centimes"
            )

        detail = self.obtenir_paiement(checkout["reference"])
        if str(detail.get("environment", "")).lower() != "sandbox":
            raise GeniusPaySecurityError(
                "La transaction EUR retournee n'est pas en Sandbox"
            )
        try:
            lu = Decimal(str(detail.get("amount")))
        except (InvalidOperation, TypeError, ValueError):
            lu = None
        if lu is None or lu != Decimal(self.MONTANT_TEST_CENTIMES):
            raise GeniusPayError(
                "Le montant EUR relu ne correspond pas (attendu "
                + 
str(self.MONTANT_TEST_CENTIMES) + " centimes)"
            )
        if str(detail.get("currency", "")).upper() != self.DEVISE_TEST:
            raise GeniusPayError("La devise EUR relue ne correspond pas")
        metadata = detail.get("metadata")
        if (not isinstance(metadata, dict)
                or str(metadata.get("order_id", "")) != order_id):
            raise GeniusPayError(
                "Les metadata EUR n'ont pas ete confirmees"
                + " (reference " + checkout["reference"] + ")"
            )
        statut = str(detail.get("status", "")).strip().lower()
        # "none" = transaction creee, aucun moyen de paiement encore choisi
        # (etat initial reel du checkout carte EUR en Sandbox GeniusPay).
        # Fail-closed : ce statut ne confirme jamais un paiement.
        if statut not in ("pending", "processing", "completed", "none"):
            raise GeniusPayError(
                "Statut inattendu pour la transaction EUR Sandbox : "
                + (statut or "absent")
            )

        gateways = set()
        for champ in ("gateway", "payment_method", "payment_provider", "provider"):
            valeur = detail.get(champ)
            if valeur:
                gateways.add(str(valeur).strip().lower())

        # ---- webhook payment.success signe (HMAC reel, calcul local) ----
        ts = int(time.time())
        payload = {
            "id": "evt-eur-test",
            "event": "payment.success",
            "timestamp": ts,
            "environment": "sandbox",
            "data": {
                "reference": checkout["reference"],
                "amount": self.MONTANT_TEST_CENTIMES,
                "currency": self.DEVISE_TEST,
                "status": "completed",
                "metadata": {"order_id": order_id},
            },
        }
        raw, signature = self._signer(payload, ts, self.webhook_secret)
        self.webhook_paiement_reussi(
            raw, signature, str(ts), "payment.success", "sandbox",
            commande=order_id,
            montant=self.MONTANT_TEST_CENTIMES,
            devise=self.DEVISE_TEST,
            reference=checkout["reference"],
        )
        webhook_verifie = True

        # ---- at
taques : chacune doit etre repoussee ----
        attaques = 0

        # 1. signature invalide
        try:
            self.verifier_webhook(
                raw, "0" * 64, str(ts), "payment.success", "sandbox"
            )
            raise GeniusPayError("Attaque signature invalide non repoussee")
        except GeniusPaySecurityError:
            attaques += 1

        # 2. montant falsifie (2400 centimes au lieu de 2490)
        faux = json.loads(raw)
        faux["data"]["amount"] = 2400
        raw_faux, sig_faux = self._signer(faux, ts, self.webhook_secret)
        try:
            self.webhook_paiement_reussi(
                raw_faux, sig_faux, str(ts), "payment.success", "sandbox",
                commande=order_id,
                montant=self.MONTANT_TEST_CENTIMES,
                devise=self.DEVISE_TEST,
                reference=checkout["reference"],
            )
            raise GeniusPayError("Attaque montant falsifie non repoussee")
        except GeniusPaySecurityError:
            attaques += 1

        # 3. payment.failed presente comme un succes
        rate = json.loads(raw)
        rate["event"] = "payment.failed"
        rate["data"]["status"] = "failed"
        raw_rate, sig_rate = self._signer(rate, ts, self.webhook_secret)
        try:
            self.webhook_paiement_reussi(
                raw_rate, sig_rate, str(ts), "payment.failed", "sandbox",
                commande=order_id,
                montant=self.MONTANT_TEST_CENTIMES,
                devise=self.DEVISE_TEST,
                reference=checkout["reference"],
            )
            raise GeniusPayError("Evenement failed accepte comme un succes")
        except GeniusPaySecurityError:
            attaques += 1

        # 4. webhook expire (hors fenetre anti-rejeu de 300 s)
        vieux_ts = ts - 400
        expire = json.loads(raw)
        expire["timestamp"] = vieux_ts
        raw_vieux, sig_vieux = self._signer(expire, vieux_ts, self.webhook_secret)
        try:
  
          self.verifier_webhook(
                raw_vieux, sig_vieux, str(vieux_ts),
                "payment.success", "sandbox"
            )
            raise GeniusPayError("Webhook expire non repousse")
        except GeniusPaySecurityError:
            attaques += 1

        if attaques != self.ATTAQUES_ATTENDUES:
            raise GeniusPayError(
                "Attaques repoussees : " + str(attaques)
                + "/" + str(self.ATTAQUES_ATTENDUES)
            )

        return {
            "reference": checkout["reference"],
            "environnement": "sandbox",
            "pays": self.PAYS_TEST,
            "devise": self.DEVISE_TEST,
            "montant_saisi": "24.90",
            "montant_api": self.MONTANT_TEST_CENTIMES,
            "gateways": sorted(gateways),
            "statut": statut,
            "webhook_verifie": webhook_verifie,
            "attaques_repoussees": attaques,
        }

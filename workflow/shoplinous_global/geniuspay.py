"""Client serveur GeniusPay pour SHOPLINOUS.

- API keys uniquement cote serveur.
- Sandbox par defaut ; le mode live exige une activation explicite.
- Checkout heberge : le client choisit son moyen de paiement.
- Les retours navigateur ne confirment jamais un paiement.
- Webhook HMAC-SHA256 + horodatage (fenetre de 5 minutes).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import httpx


BASE_URL = "https://geniuspay.ci/api/v1/merchant"
DELAI_WEBHOOK_SECONDES = 300
DEVISES_API = {"XOF", "EUR", "USD"}
EVENEMENTS_WEBHOOK = (
    "payment.success",
    "payment.failed",
    "payment.cancelled",
    "payment.refunded",
    "payment.expired",
)


class GeniusPayError(RuntimeError):
    """Erreur API GeniusPay sans divulgation des secrets."""


class GeniusPayConfigurationError(GeniusPayError):
    """Configuration GeniusPay absente ou incoherente."""


class GeniusPaySecurityError(GeniusPayError):
    """Signature, horodatage ou contenu de webhook invalide."""


def _url_https_valide(value: str) -> bool:
    try:
        parsed = urlparse(str(value))
        return parsed.scheme == "https" and bool(parsed.netloc)
    except (TypeError, ValueError):
        return False


class GeniusPayClient:
    """Client API marchand. Aucun secret n'est inclus dans ses representations."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        webhook_secret: str | None = None,
        environment: str | None = None,
        base_url: str = BASE_URL,
        timeout: float = 20.0,
        transport=None,
        allow_live: bool | None = None,
    ):
        self.api_key = api_key if api_key is not None else os.getenv("GENIUSPAY_API_KEY", "")
        self.api_secret = api_secret if api_secret is not None else os.getenv("GENIUSPAY_API_SECRET", "")
        self.webhook_secret = webhook_secret if webhook_secret is not None else os.getenv("GENIUSPAY_WEBHOOK_SECRET", "")
        self.environment = (environment or os.getenv("GENIUSPAY_ENVIRONMENT", "sandbox")).strip().lower()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport
        self.allow_live = (
            allow_live if allow_live is not None
            else os.getenv("GENIUSPAY_ALLOW_LIVE", "").strip().lower() == "true"
        )

        if self.environment not in ("sandbox", "live"):
            raise GeniusPayConfigurationError("GENIUSPAY_ENVIRONMENT doit etre sandbox ou live")
        if self.environment == "live" and not self.allow_live:
            raise GeniusPayConfigurationError(
                "Mode live bloque : GENIUSPAY_ALLOW_LIVE=true est requis explicitement"
            )

    @classmethod
    def from_env(cls) -> "GeniusPayClient":
        return cls()

    @property
    def api_configured(self) -> bool:
        prefix = "sandbox" if self.environment == "sandbox" else "live"
        return (
            bool(self.api_key and self.api_secret)
            and self.api_key.startswith("pk_" + prefix + "_")
            and self.api_secret.startswith("sk_" + prefix + "_")
        )

    @property
    def payment_ready(self) -> bool:
        return self.api_configured and bool(self.webhook_secret)

    def _headers(self) -> dict:
        if not self.api_configured:
            prefix = "sandbox" if self.environment == "sandbox" else "live"
            raise GeniusPayConfigurationError(
                "Cles GeniusPay absentes ou incompatibles avec l'environnement "
                + prefix + " (aucun paiement lance)"
            )
        return {
            "X-API-Key": self.api_key,
            "X-API-Secret": self.api_secret,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, *, params=None, body=None) -> dict:
        url = self.base_url + "/" + path.lstrip("/")
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=body,
                )
        except httpx.HTTPError:
            raise GeniusPayError("GeniusPay est injoignable (details reseau masques)") from None

        if response.status_code < 200 or response.status_code >= 300:
            raise GeniusPayError(
                "GeniusPay a refuse la requete (HTTP "
                + str(response.status_code) + ")"
            )
        try:
            result = response.json()
        except ValueError:
            raise GeniusPayError("Reponse GeniusPay non JSON") from None
        if not isinstance(result, dict) or result.get("success") is not True:
            raise GeniusPayError("Reponse GeniusPay invalide ou operation refusee")
        return result

    @staticmethod
    def _data(result: dict) -> dict:
        data = result.get("data")
        if not isinstance(data, dict):
            raise GeniusPayError("Reponse GeniusPay sans objet data valide")
        return data

    def tester_connexion(self) -> dict:
        """GET /account : lecture seule, ne cree aucune transaction."""
        data = self._data(self._request("GET", "/account"))
        status = str(data.get("status", "")).lower()
        env = str(data.get("environment", "")).lower()
        if status != "active":
            raise GeniusPayError("Le compte marchand GeniusPay n'est pas actif")
        if env and env != self.environment:
            raise GeniusPayError("L'environnement retourne par GeniusPay ne correspond pas")
        return {
            "connecte": True,
            "statut": status,
            "environnement": env or self.environment,
            "nom_marchand": data.get("business_name"),
        }

    def fournisseurs_mobile_money(self, pays: str | None = None) -> dict:
        """GET /pawapay/providers : decouverte dynamique, en lecture seule."""
        params = {}
        if pays:
            code = str(pays).strip().upper()
            if len(code) != 2 or not code.isalpha():
                raise ValueError("Code pays ISO2 invalide")
            params["country"] = code
        data = self._data(self._request("GET", "/pawapay/providers", params=params or None))
        return data

    def creer_webhook(self, url: str, nom: str = "SHOPLINOUS GeniusPay") -> dict:
        """Enregistre les evenements de paiement. Le secret retourne doit etre stocke."""
        if not _url_https_valide(url):
            raise ValueError("L'URL webhook doit etre publique et commencer par https://")
        data = self._data(self._request(
            "POST",
            "/webhooks",
            body={
                "name": str(nom)[:100],
                "url": url,
                "events": list(EVENEMENTS_WEBHOOK),
            },
        ))
        if not data.get("secret"):
            raise GeniusPayError(
                "GeniusPay n'a pas retourne de secret webhook ; configuration non terminee"
            )
        return data

    def creer_checkout(
        self,
        montant,
        commande,
        devise: str = "XOF",
        description: str | None = None,
        client: dict | None = None,
        success_url: str | None = None,
        error_url: str | None = None,
        methode_paiement: str | None = None,
    ) -> dict:
        """Cree un checkout GeniusPay, eventuellement force sur Wave Direct.

        Le routage Wave est strictement limite a CI/XOF et n'est accepte
        que si la reponse API confirme explicitement la passerelle Wave.
        """
        if not self.payment_ready:
            raise GeniusPayConfigurationError(
                "Paiements bloques : cles API et secret webhook sont requis"
            )
        if self.environment == "live" and not self.allow_live:
            raise GeniusPayConfigurationError("Paiements live non autorises")

        try:
            amount = Decimal(str(montant))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Montant invalide") from None
        if not amount.is_finite() or amount < Decimal("200"):
            raise ValueError("Montant minimum GeniusPay : 200")
        if amount != amount.to_integral_value():
            raise ValueError("Le montant GeniusPay doit etre un nombre entier")
        code_devise = str(devise).upper()
        if code_devise not in DEVISES_API:
            raise ValueError(
                "Devise non autorisee par le checkout standard GeniusPay : "
                + ", ".join(sorted(DEVISES_API))
            )
        methode = str(methode_paiement or "").strip().lower() or None
        if methode not in (None, "wave"):
            raise ValueError("Methode de paiement directe non prise en charge")
        pays_client = str((client or {}).get("country", "")).strip().upper()
        if methode == "wave" and (code_devise != "XOF" or pays_client != "CI"):
            raise ValueError("Wave Direct GeniusPay est reserve a CI/XOF")
        if commande is None or not str(commande).strip():
            raise ValueError("Reference de commande obligatoire")
        if success_url and not _url_https_valide(success_url):
            raise ValueError("success_url doit utiliser HTTPS")
        if error_url and not _url_https_valide(error_url):
            raise ValueError("error_url doit utiliser HTTPS")

        customer = {}
        if client:
            for key in ("name", "email", "phone", "country"):
                value = client.get(key)
                if isinstance(value, str) and value.strip():
                    customer[key] = value.strip()
        payload = {
            "amount": int(amount),
            "currency": code_devise,
            "description": (description or ("Commande " + str(commande)))[:500],
            "metadata": {"order_id": str(commande)},
        }
        if customer:
            payload["customer"] = customer
        if methode:
            # La selection explicite evite de renvoyer le client vers le
            # checkout multi-canaux lorsqu'il a choisi Wave Direct.
            payload["payment_method"] = methode
            payload["gateway"] = methode
        if success_url:
            payload["success_url"] = success_url
        if error_url:
            payload["error_url"] = error_url

        # payment_method volontairement omis : GeniusPay affiche son checkout
        # et choisit les canaux disponibles pour le client.
        data = self._data(self._request("POST", "/payments", body=payload))
        reference = data.get("reference")
        checkout_url = data.get("checkout_url") or data.get("payment_url")
        if not isinstance(reference, str) or not reference.strip():
            raise GeniusPayError("Reference de paiement absente de la reponse")
        if not _url_https_valide(checkout_url):
            raise GeniusPayError("URL de checkout GeniusPay absente ou invalide")
        host = urlparse(checkout_url).hostname
        if host not in ("geniuspay.ci", "www.geniuspay.ci"):
            raise GeniusPayError("Domaine de checkout inattendu : redirection refusee")
        if str(data.get("status", "")).lower() not in ("pending", "processing"):
            raise GeniusPayError("Statut initial inattendu pour le checkout")
        response_env = str(data.get("environment", self.environment)).lower()
        if response_env != self.environment:
            raise GeniusPayError("L'environnement du checkout ne correspond pas")

        if methode == "wave":
            routes = {
                str(data.get(field, "")).strip().lower()
                for field in ("gateway", "payment_method", "payment_provider", "provider")
                if data.get(field) is not None
            }
            if "wave" not in routes or routes - {"wave"}:
                raise GeniusPayError(
                    "GeniusPay n'a pas confirme le routage Wave Direct"
                )
            if Decimal(str(data.get("amount", amount))) != amount:
                raise GeniusPaySecurityError("Montant du checkout Wave incoherent")
            if str(data.get("currency", code_devise)).upper() != code_devise:
                raise GeniusPaySecurityError("Devise du checkout Wave incoherente")
            metadata = data.get("metadata")
            if (not isinstance(metadata, dict)
                    or str(metadata.get("order_id", "")) != str(commande)):
                raise GeniusPaySecurityError(
                    "Reference de commande du checkout Wave incoherente"
                )

        return {
            "reference": reference,
            "checkout_url": checkout_url,
            "statut": str(data["status"]).lower(),
            "montant": int(amount),
            "devise": code_devise,
            "environnement": response_env,
            "metadata": data.get("metadata") or {"order_id": str(commande)},
        }

    def creer_checkout_wave(
        self,
        montant,
        commande,
        devise: str = "XOF",
        description: str | None = None,
        client: dict | None = None,
        success_url: str | None = None,
        error_url: str | None = None,
    ) -> dict:
        """Cree un paiement Wave Direct pour une commande ivoirienne."""
        infos_client = dict(client or {})
        infos_client["country"] = "CI"
        return self.creer_checkout(
            montant=montant,
            commande=commande,
            devise=devise,
            description=description,
            client=infos_client,
            success_url=success_url,
            error_url=error_url,
            methode_paiement="wave",
        )

    def obtenir_paiement(self, reference: str) -> dict:
        """GET /payments/{reference} : verification serveur du statut."""
        ref = str(reference or "").strip()
        if not ref or len(ref) > 120 or "/" in ref or "\\" in ref:
            raise ValueError("Reference GeniusPay invalide")
        data = self._data(self._request("GET", "/payments/" + ref))
        if str(data.get("reference", "")) != ref:
            raise GeniusPayError("La reference retournee ne correspond pas")
        if str(data.get("environment", self.environment)).lower() != self.environment:
            raise GeniusPayError("L'environnement du paiement ne correspond pas")
        return data

    def verifier_webhook(
        self,
        raw_body: bytes | str,
        signature: str,
        timestamp: str,
        event_header: str,
        environment_header: str,
        *,
        maintenant: float | None = None,
    ) -> dict:
        """Verifie HMAC, fenetre anti-rejeu, evenement et environnement."""
        if not self.webhook_secret:
            raise GeniusPayConfigurationError("GENIUSPAY_WEBHOOK_SECRET absent")
        if isinstance(raw_body, str):
            raw = raw_body.encode("utf-8")
        elif isinstance(raw_body, bytes):
            raw = raw_body
        else:
            raise GeniusPaySecurityError("Corps webhook invalide")

        try:
            ts = int(str(timestamp))
        except (TypeError, ValueError):
            raise GeniusPaySecurityError("Timestamp webhook invalide") from None
        clock = time.time() if maintenant is None else maintenant
        if abs(clock - ts) > DELAI_WEBHOOK_SECONDES:
            raise GeniusPaySecurityError("Webhook expire (fenetre anti-rejeu depassee)")

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GeniusPaySecurityError("Payload webhook non JSON") from None
        if not isinstance(payload, dict):
            raise GeniusPaySecurityError("Payload webhook invalide")

        signature_value = str(signature or "").strip()
        if signature_value.startswith("sha256="):
            signature_value = signature_value[7:]
        messages = [str(timestamp).encode("ascii") + b"." + raw]

        # La documentation GeniusPay illustre json_encode($request->all()).
        # On accepte aussi cette forme compacte, en plus du corps HTTP brut.
        compact = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=True
        ).replace("/", "\\/")
        messages.append(str(timestamp).encode("ascii") + b"." + compact.encode("utf-8"))

        signatures_valides = [
            hmac.new(self.webhook_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
            for msg in messages
        ]
        if not any(hmac.compare_digest(expected, signature_value)
                   for expected in signatures_valides):
            raise GeniusPaySecurityError("Signature webhook invalide")

        payload_env = str(payload.get("environment", "")).lower()
        header_env = str(environment_header or "").lower()
        if payload_env != self.environment or header_env != self.environment:
            raise GeniusPaySecurityError("Environnement webhook inattendu")
        payload_timestamp = payload.get("timestamp")
        if payload_timestamp is not None:
            try:
                if int(payload_timestamp) != ts:
                    raise GeniusPaySecurityError(
                        "Timestamp du payload different de l'en-tete"
                    )
            except (TypeError, ValueError):
                raise GeniusPaySecurityError("Timestamp payload invalide") from None

        event = str(payload.get("event", ""))
        if not event or event != str(event_header or ""):
            raise GeniusPaySecurityError("Evenement webhook incoherent")
        return payload

    def webhook_paiement_reussi(
        self,
        raw_body: bytes | str,
        signature: str,
        timestamp: str,
        event_header: str,
        environment_header: str,
        *,
        commande,
        montant,
        devise: str,
        reference: str,
        maintenant: float | None = None,
    ) -> dict:
        """Valide un payment.success contre commande, reference, montant et devise."""
        payload = self.verifier_webhook(
            raw_body, signature, timestamp, event_header,
            environment_header, maintenant=maintenant,
        )
        if payload.get("event") != "payment.success":
            raise GeniusPaySecurityError("Evenement non assimilable a un paiement reussi")
        data = payload.get("data")
        if not isinstance(data, dict) or str(data.get("status", "")).lower() != "completed":
            raise GeniusPaySecurityError("Le statut du paiement n'est pas completed")
        if str(data.get("reference", "")) != str(reference):
            raise GeniusPaySecurityError("Reference de paiement incoherente")
        metadata = data.get("metadata")
        if not isinstance(metadata, dict) or str(metadata.get("order_id", "")) != str(commande):
            raise GeniusPaySecurityError("Reference de commande incoherente")
        try:
            amount_ok = Decimal(str(data.get("amount"))) == Decimal(str(montant))
        except (InvalidOperation, TypeError, ValueError):
            amount_ok = False
        if not amount_ok:
            raise GeniusPaySecurityError("Montant du webhook incoherent")
        if str(data.get("currency", "")).upper() != str(devise).upper():
            raise GeniusPaySecurityError("Devise du webhook incoherente")
        return payload

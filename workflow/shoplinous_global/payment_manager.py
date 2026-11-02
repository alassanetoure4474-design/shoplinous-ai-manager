"""Payment Manager : transactions, idempotence, webhooks.

Regles absolues (verifiees par tests) :
- Un paiement reussi n est JAMAIS declare a partir d une simple
  redirection navigateur : confirmer_redirection() refuse.
- Seul un webhook SIGNE (HMAC-SHA256, secret par prestataire) peut
  confirmer un paiement.
- Idempotence : une meme cle d idempotence retourne la MEME
  transaction, jamais un doublon.
- Aucun operateur non active sur le compte marchand n est affiche :
  seuls les prestataires connectes sont proposables.
"""
import hashlib
import hmac
import json
import re
import time
from decimal import Decimal, InvalidOperation


class Transaction:
    def __init__(self, identifiant, commande, montant, devise, pays,
                 moyen, prestataire, cle_idempotence):
        self.id = identifiant
        self.commande = commande
        self.montant = montant
        self.devise = devise
        self.pays = pays
        self.moyen = moyen
        self.prestataire = prestataire
        self.cle_idempotence = cle_idempotence
        self.reference_externe = None
        self.url_paiement = None
        self.statut = "creee"
        self.historique = [("creee", time.time())]

    def _passer(self, statut):
        self.statut = statut
        self.historique.append((statut, time.time()))


def _normaliser_moyen(value):
    """Normalise un moyen de paiement pour comparer les libelles."""
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _moyens_configures(prestataire):
    """Ne retourne que les moyens explicitement declares par l'adaptateur."""
    moyens = set(getattr(prestataire, "moyens_supportes", ()) or ())
    methode = getattr(prestataire, "methode", None)
    if methode:
        moyens.add(methode)
    return moyens


def _payload_webhook_coherent(tx, contenu):
    """Lie la notification signee a la transaction, son statut et son montant."""
    try:
        payload = json.loads(contenu)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False

    reference = payload.get("transaction_id", payload.get("transaction"))
    if str(reference or "") != str(tx.id):
        return False

    statut = payload.get("status", payload.get("statut"))
    if str(statut or "").strip().lower() not in {
            "ok", "success", "succeeded", "completed", "paid"}:
        return False

    montant = payload.get("amount", payload.get("montant"))
    if montant is not None:
        try:
            if Decimal(str(montant)) != Decimal(str(tx.montant)):
                return False
        except (InvalidOperation, TypeError, ValueError):
            return False

    devise = payload.get("currency", payload.get("devise"))
    if devise is not None and str(devise).upper() != str(tx.devise).upper():
        return False
    return True


class GestionnairePaiements:
    def __init__(self, registre, secrets_webhook=None):
        self.registre = registre
        self._secrets = secrets_webhook or {}
        self._transactions = []
        self._par_idempotence = {}

    def moyens_disponibles(self, code_pays, moyens_pays, devise):
        """Intersection pays/devise/moyens avec les adaptateurs connectes."""
        demandes = {_normaliser_moyen(m) for m in (moyens_pays or [])}
        proposables = []
        for p in self.registre.pour_pays(code_pays, devise):
            if p.nom == "geniuspay":
                # Checkout heberge : le client choisit parmi les canaux
                # que GeniusPay affiche pour ce compte marchand.
                proposables.append({
                    "moyen": "geniuspay_checkout",
                    "prestataire": p.nom, "devise": devise})
                # Option Wave Direct explicite, uniquement en CI/XOF,
                # et seulement si l'adaptateur sait creer ce checkout.
                if (code_pays == "CI" and devise == "XOF"
                        and demandes.intersection({"wave", "wave_direct"})
                        and callable(getattr(p.client, "creer_checkout_wave", None))):
                    proposables.append({
                        "moyen": "wave",
                        "prestataire": p.nom, "devise": devise})
                continue
            for moyen in sorted(_moyens_configures(p)):
                if _normaliser_moyen(moyen) in demandes:
                    proposables.append({
                        "moyen": moyen, "prestataire": p.nom,
                        "devise": devise})
        return proposables

    def creer_transaction(self, commande, montant, devise, pays, moyen,
                          cle_idempotence):
        if cle_idempotence in self._par_idempotence:
            return self._par_idempotence[cle_idempotence], False
        prestataires = self.registre.pour_pays(pays, devise)
        moyen_demande = _normaliser_moyen(moyen)
        compatibles = [
            p for p in prestataires
            if moyen_demande and any(
                _normaliser_moyen(m) == moyen_demande
                for m in _moyens_configures(p))
        ]
        if not compatibles:
            raise RuntimeError(
                "aucun prestataire connecte ne prend en charge le moyen "
                + repr(moyen) + " pour " + pays + "/" + devise
                + " : transaction refusee")
        prestataire = compatibles[0]
        identifiant = hashlib.sha256(
            (str(commande) + "|" + str(cle_idempotence)).encode()
        ).hexdigest()[:16]
        tx = Transaction(identifiant, commande, montant, devise, pays,
                         moyen, prestataire.nom, cle_idempotence)
        if prestataire.nom == "geniuspay":
            checkout = prestataire.creer_paiement(tx)
            tx.reference_externe = checkout["reference"]
            tx.url_paiement = checkout["checkout_url"]
        tx._passer("en_attente")
        self._transactions.append(tx)
        self._par_idempotence[cle_idempotence] = tx
        return tx, True

    def obtenir_transaction(self, transaction_id):
        """Retourne une transaction suivie sans modifier son statut."""
        return next(
            (tx for tx in self._transactions if tx.id == transaction_id),
            None,
        )

    def confirmer_redirection(self, transaction_id):
        """Une redirection navigateur ne prouve RIEN. Toujours refuse."""
        for tx in self._transactions:
            if tx.id == transaction_id:
                tx._passer("redirection_ignoree")
                return False
        raise KeyError("transaction inconnue")

    def verifier_signature(self, prestataire, contenu, signature):
        secret = self._secrets.get(prestataire)
        if not secret or not isinstance(contenu, str):
            return False
        attendu = hmac.new(secret.encode(), contenu.encode(),
                          hashlib.sha256).hexdigest()
        return hmac.compare_digest(attendu, str(signature))

    def confirmer_webhook(self, transaction_id, contenu, signature,
                          headers=None):
        """Confirme uniquement un webhook signe et lie au bon paiement."""
        for tx in self._transactions:
            if tx.id == transaction_id:
                if tx.statut in ("reussie", "remboursee"):
                    return True
                if tx.prestataire == "geniuspay":
                    fournisseur = next(
                        (p for p in self.registre.tous()
                         if p.nom == "geniuspay"), None)
                    if fournisseur is None:
                        tx._passer("webhook_refuse")
                        return False
                    try:
                        fournisseur.verifier_webhook(
                            tx, contenu, signature, headers=headers)
                    except Exception:
                        tx._passer("webhook_refuse")
                        return False
                    tx._passer("reussie")
                    return True
                if not self.verifier_signature(tx.prestataire, contenu,
                                              signature):
                    tx._passer("signature_refusee")
                    return False
                if not _payload_webhook_coherent(tx, contenu):
                    tx._passer("webhook_refuse")
                    return False
                tx._passer("reussie")
                return True
        raise KeyError("transaction inconnue")

    def annuler(self, transaction_id):
        for tx in self._transactions:
            if tx.id == transaction_id and tx.statut == "en_attente":
                tx._passer("annulee")
                return True
        return False

    def expirations(self, delai_secondes=3600):
        maintenant = time.time()
        for tx in self._transactions:
            if tx.statut == "en_attente" and (
                    maintenant - tx.historique[0][1]) > delai_secondes:
                tx._passer("expiree")

    def rapprochement(self):
        """Rapprochement comptable : totaux par prestataire et statut,
        dans la devise de la transaction."""
        tableau = {}
        for tx in self._transactions:
            cle = (tx.prestataire, tx.devise, tx.statut)
            tableau[cle] = tableau.get(cle, 0) + tx.montant
        return [{"prestataire": k[0], "devise": k[1], "statut": k[2],
                 "total": v} for k, v in sorted(tableau.items())]

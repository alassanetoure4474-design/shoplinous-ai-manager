"""Security & Audit Manager : secrets, signatures, journal, PII.

- Redaction : aucune valeur de secret (env) n apparaît jamais.
- Signatures webhook : HMAC-SHA256 (comparaison temps constant).
- Journal d audit : append-only avec chainage de hachage SHA-256
  (toute alteration casse la chaine, verifie par test).
- PII : liste blanche des champs clients autorises ; tout champ
  hors liste est rejete (minimisation des donnees).
"""
import hashlib
import hmac
import os
import time

CLES_SECRETS_ENV = ("CJ_API_KEY", "FREEWEBSTORE_API_KEY",
                    "FREE_LLM_API_KEY", "MISTRAL_API_KEY")

CHAMPS_CLIENT_AUTORISES = ("nom", "pays", "devise", "email",
                           "telephone")


def rediger(texte):
    """Retire toute valeur de secret d environnement du texte.
    La cle elle-meme n est JAMAIS journalisee."""
    resultat = str(texte)
    for nom in CLES_SECRETS_ENV:
        valeur = os.environ.get(nom)
        if valeur:
            resultat = resultat.replace(valeur, "[REDACTE]")
    return resultat[:1000]


def verifier_signature_webhook(contenu, signature, secret):
    """HMAC-SHA256 en comparaison temps constant (anti-timing)."""
    if not secret:
        return False
    attendu = hmac.new(secret.encode(), contenu.encode(),
                       hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendu, str(signature))


class JournalAudit:
    """Journal append-only : chaque entree contient le hachage de la
    precedente. verifier_chaine() detecte toute alteration."""

    def __init__(self):
        self._entrees = []
        self._precedent = "GENESIS"

    def ajouter(self, action, details=""):
        charge = (str(action) + "|" + rediger(details))
        empreinte = hashlib.sha256(
            (self._precedent + "|" + charge).encode()).hexdigest()
        entree = {"horodatage": time.time(), "action": action,
                  "details": rediger(details), "empreinte": empreinte,
                  "precedent": self._precedent}
        self._precedent = empreinte
        self._entrees.append(entree)
        return entree

    def entrees(self):
        return list(self._entrees)

    def verifier_chaine(self):
        precedent = "GENESIS"
        for e in self._entrees:
            charge = e["action"] + "|" + e["details"]
            attendu = hashlib.sha256(
                (precedent + "|" + charge).encode()).hexdigest()
            if attendu != e["empreinte"]:
                return False
            precedent = e["empreinte"]
        return True


def filtrer_donnees_client(donnees):
    """Minimisation PII : seuls les champs autorises passent."""
    if not isinstance(donnees, dict):
        return {}
    return {k: v for k, v in donnees.items()
            if k in CHAMPS_CLIENT_AUTORISES}

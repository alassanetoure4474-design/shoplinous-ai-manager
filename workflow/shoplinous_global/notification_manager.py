"""Notification Manager : canaux de notification.

Canaux : "journal" (interne, TOUJOURS actif) ; "email", "sms",
"webhook" (non connectes tant que les acces ne sont pas fournis).
Toute notification passe par la redaction des donnees sensibles.
"""
from shoplinous_global import security_audit


class GestionnaireNotifications:
    def __init__(self):
        self._canaux = {"journal": {"connecte": True}}
        for canal in ("email", "sms", "webhook"):
            self._canaux[canal] = {"connecte": False}
        self._envois = []

    def canaux(self):
        return {c: v["connecte"] for c, v in self._canaux.items()}

    def envoyer(self, canal, destinataire, message, donnees=None):
        if canal not in self._canaux:
            raise ValueError("canal inconnu: " + repr(canal))
        if not self._canaux[canal]["connecte"]:
            return {"statut": "canal_non_connecte", "canal": canal}
        contenu = security_audit.rediger(str(message))
        if donnees:
            contenu += " " + security_audit.rediger(str(donnees))
        envoi = {"canal": canal, "destinataire": destinataire,
                 "contenu": contenu, "statut": "envoye"}
        self._envois.append(envoi)
        return envoi

    def historique(self):
        return list(self._envois)

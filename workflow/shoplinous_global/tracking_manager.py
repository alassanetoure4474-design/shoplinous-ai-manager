"""Tracking Manager : suivi des expeditions.

Enregistre les evenements de suivi fournis par les transporteurs.
Aucun evenement n est devine : sans fournisseur connecte, l
historique reste vide (etat honnete).
"""
import time


class GestionnaireSuivi:
    def __init__(self):
        self._evenements = []

    def enregistrer(self, numero_commande, transporteur, statut,
                    source="api", horodatage=None):
        if not numero_commande or not statut:
            raise ValueError("evenement de suivi incomplet")
        evenement = {
            "commande": numero_commande, "transporteur": transporteur,
            "statut": statut, "source": source,
            "horodatage": horodatage or time.time()}
        self._evenements.append(evenement)
        return evenement

    def historique(self, numero_commande):
        return [e for e in self._evenements
                if e["commande"] == numero_commande]

    def dernier(self, numero_commande):
        h = self.historique(numero_commande)
        return h[-1] if h else None

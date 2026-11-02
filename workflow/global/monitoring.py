"""Monitoring Manager : compteurs et sante de la plateforme.

Compteurs atomiques par evenement ; sante() agrege le statut des 18
modules (via global.module_status), les compteurs et un resume des
connections REELLES (connecte ou non, jamais simule).
"""
import time


class Compteurs:
    def __init__(self):
        self._valeurs = {}

    def incrementer(self, nom, valeur=1):
        self._valeurs[nom] = self._valeurs.get(nom, 0) + valeur

    def valeur(self, nom):
        return self._valeurs.get(nom, 0)

    def instantane(self):
        return dict(self._valeurs)


class Monitoring:
    def __init__(self):
        self.compteurs = Compteurs()

    def evenement(self, nom, valeur=1):
        self.compteurs.incrementer(nom, valeur)

    def sante(self):
        import global as g
        statut_modules = g.module_status()
        return {
            "horodatage": time.time(),
            "modules": {m: s.get("charge") for m, s in
                        statut_modules.items()},
            "modules_defaillants": [m for m, s in statut_modules.items()
                                    if not s.get("charge")],
            "compteurs": self.compteurs.instantane(),
        }

    def connections_reelles(self):
        """Panorama honnete des connections : cj = reel, prestataires
        de paiement = aucun, autres fournisseurs = aucun."""
        import payment_providers, supplier_adapters
        return {
            "fournisseurs": supplier_adapters.RegistreFournisseurs().etat(),
            "paiement": payment_providers.RegistrePrestataires().etat(),
        }

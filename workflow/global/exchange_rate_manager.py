"""Exchange Rate Manager : taux horodates, cache, indisponibilite.

Regles :
- Tout taux porte un horodatage et une paire (source, cible).
- Cache avec TTL : un taux frais est reutilise, jamais devine.
- Si le fournisseur est indisponible et le cache perime :
  ErreurTauxIndisponible. AUCUN taux n'est invente ni extrapole.
- Historique des taux reellement utilises (audit).
"""
import time


class ErreurTauxIndisponible(RuntimeError):
    """Le service de change est indisponible : echec propre, aucune
    valeur par defaut inventee."""


class TauxHorodate:
    def __init__(self, paire, valeur, horodatage=None):
        if valeur <= 0:
            raise ValueError("taux non positif")
        self.paire = tuple(paire)
        self.valeur = float(valeur)
        self.horodatage = horodatage if horodatage is not None else time.time()

    def age(self, maintenant=None):
        return (maintenant or time.time()) - self.horodatage

    def __repr__(self):
        return ("TauxHorodate(%s->%s=%s @%.0f)" % (
            self.paire[0], self.paire[1], self.valeur, self.horodatage))


class FournisseurTaux:
    """Interface : un fournisseur de taux doit retourner un
    TauxHorodate ou lever une exception. Jamais de fallback cache
    interne : la politique de cache appartient au manager."""

    def taux(self, source, cible):
        raise NotImplementedError


class CacheTaux:
    def __init__(self, ttl_secondes=3600):
        self.ttl = ttl_secondes
        self._stock = {}

    def get(self, paire, maintenant=None):
        t = self._stock.get(tuple(paire))
        if t is not None and t.age(maintenant) <= self.ttl:
            return t
        return None

    def set(self, taux):
        self._stock[taux.paire] = taux


class ExchangeRateManager:
    def __init__(self, fournisseur, ttl_secondes=3600):
        self.fournisseur = fournisseur
        self.cache = CacheTaux(ttl_secondes)
        self.historique = []

    def taux(self, source, cible, maintenant=None):
        paire = (source, cible)
        frais = self.cache.get(paire, maintenant)
        if frais is not None:
            return frais
        try:
            brut = self.fournisseur.taux(source, cible)
        except ErreurTauxIndisponible:
            raise
        except Exception as exc:
            raise ErreurTauxIndisponible(
                "service de change indisponible: " + str(exc)[:120])
        if not isinstance(brut, TauxHorodate):
            raise ErreurTauxIndisponible(
                "reponse inattendue du service de change")
        self.cache.set(brut)
        self.historique.append({
            "paire": paire, "valeur": brut.valeur,
            "horodatage": brut.horodatage})
        return brut

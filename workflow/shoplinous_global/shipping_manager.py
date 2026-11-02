"""Shipping Manager : comparaison transporteurs par destination.

Compare des DEVIS REELS fournis (API fournisseur, ex : cj_freight de
daily.py a quantite exacte). Filtre par pays, quantite, poids,
dimensions, delai, restrictions douanieres. AUCUN devis absent n est
extrapole : pas de devis -> pas de resultat, echec explicite.
"""
from dataclasses import dataclass


@dataclass
class DevisTransport:
    fournisseur: str
    transporteur: str
    destination: str
    quantite: int
    cout: float
    devise: str
    delai_jours: int
    restrictions_ok: bool = True
    poids_kg: float = None
    dimensions_cm: tuple = None


def _devis_valide(d):
    return (isinstance(d, DevisTransport)
            and d.cout >= 0 and d.quantite >= 1
            and d.delai_jours >= 1 and d.destination)


def comparer_devis(devis, destination, quantite, delai_max_jours,
                   poids_max_kg=None):
    """Retourne les devis CONFORMES tries par cout croissant.
    Un devis non conforme n est ni corrige ni invente."""
    if quantite < 1:
        raise ValueError("quantite invalide: " + repr(quantite))
    conformes = []
    for d in (devis or []):
        if not _devis_valide(d):
            continue
        if d.destination != destination:
            continue
        if d.quantite != quantite:
            continue
        if d.delai_jours > delai_max_jours:
            continue
        if not d.restrictions_ok:
            continue
        if poids_max_kg is not None and d.poids_kg is not None and (
                d.poids_kg > poids_max_kg):
            continue
        conformes.append(d)
    return sorted(conformes, key=lambda x: x.cout)


def meilleur_devis(devis, destination, quantite, delai_max_jours,
                   poids_max_kg=None):
    """Le moins cher des devis conformes, ou None si AUCUN devis
    valable n existe (jamais d extrapolation)."""
    conformes = comparer_devis(devis, destination, quantite,
                               delai_max_jours, poids_max_kg)
    return conformes[0] if conformes else None


def verifier_contraintes_marche(devis, regles_livraison):
    """Verifie que le devis respecte les contraintes configurees du
    pays (delai maximal notamment)."""
    if devis is None:
        return False
    return devis.delai_jours <= regles_livraison.get(
        "delai_max_jours", 15)

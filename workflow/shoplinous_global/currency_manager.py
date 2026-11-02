"""Currency Manager : devises internationales, arrondis, coherence.

Devises : XOF, XAF, EUR, USD, GBP, CAD, GHS, NGN, MAD, KES, ZAR.
Exposants officiels (XOF/XAF sans decimale). Arrondi commercial
ROUND_HALF_UP. Un prix CONFIRME dans une commande n est jamais
modifie arbitrairement (verifie par test).
"""
import os
from decimal import Decimal, ROUND_HALF_UP

DEVISES = {
    "XOF": {"exposant": 0, "symbole": "FCFA"},
    "XAF": {"exposant": 0, "symbole": "FCFA"},
    "EUR": {"exposant": 2, "symbole": "EUR"},
    "USD": {"exposant": 2, "symbole": "$"},
    "GBP": {"exposant": 2, "symbole": "GBP"},
    "CAD": {"exposant": 2, "symbole": "CAD"},
    "GHS": {"exposant": 2, "symbole": "GHS"},
    "NGN": {"exposant": 2, "symbole": "NGN"},
    "MAD": {"exposant": 2, "symbole": "MAD"},
    "KES": {"exposant": 2, "symbole": "KES"},
    "ZAR": {"exposant": 2, "symbole": "ZAR"},
}


def devise_reference():
    """Devise de reference comptable, configurable par variable
    d environnement (defaut EUR)."""
    code = os.environ.get("ACCOUNTING_CURRENCY", "EUR")
    if code not in DEVISES:
        raise ValueError("devise de reference inconnue: " + repr(code))
    return code


def arrondir(montant, devise):
    """Arrondi commercial (ROUND_HALF_UP) selon l exposant de la devise.
    XOF : 1234.567 -> 1235 ; EUR : 10.455 -> 10.46."""
    if devise not in DEVISES:
        raise ValueError("devise non supportee: " + repr(devise))
    exp = DEVISES[devise]["exposant"]
    quantum = Decimal(1).scaleb(-exp)
    return Decimal(str(montant)).quantize(quantum, rounding=ROUND_HALF_UP)


def convertir(montant, devise_source, devise_cible, taux):
    """Convertit via un taux EXPLICITE (>0). Le taux vient toujours
    de ExchangeRateManager : aucun taux n est invente ici."""
    if devise_source not in DEVISES or devise_cible not in DEVISES:
        raise ValueError("devise non supportee")
    try:
        t = Decimal(str(taux))
    except Exception:
        raise ValueError("taux invalide: " + repr(taux))
    if t <= 0:
        raise ValueError("taux non positif: " + repr(taux))
    brut = Decimal(str(montant)) * t
    return arrondir(brut, devise_cible)


def coherent_prix_affiche_encaisse(prix_affiche, montant_encaisse,
                                   devise, tolerance=Decimal("0.01")):
    """Controle de coherence entre le prix affiche et le montant
    encaisse. Tolere l arrondi de la devise, rien de plus."""
    attendu = arrondir(prix_affiche, devise)
    encaisse = arrondir(montant_encaisse, devise)
    return abs(attendu - encaisse) <= tolerance

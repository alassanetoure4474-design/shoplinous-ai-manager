"""Currency Manager : devises internationales, arrondis, coherence.

v6.1 : s appuie sur world_currencies (referentiel ISO 4217 complet)
tout en conservant l API historique (DEVISES, arrondir, convertir,
devise_reference, coherent_prix_affiche_encaisse). Les devises
mondiales sont chargees depuis le referentiel pays ISO 3166-1 ;
un prix CONFIRME dans une commande n est jamais modifie.
"""
import os
from decimal import Decimal, ROUND_HALF_UP

from shoplinous_global import world_currencies
from shoplinous_global import world_countries

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


def charger_devises_mondiales() -> int:
    """Charge toutes les devises ISO 4217 utilisees par le referentiel
    pays mondial. Retourne le nombre de devises disponibles."""
    for p in world_countries.PAYS.values():
        for d in p.devises:
            if d and d not in DEVISES:
                DEVISES[d] = {
                    "exposant": world_currencies.exposant(d),
                    "symbole": world_currencies.symbole(d),
                }
    return len(DEVISES)


charger_devises_mondiales()


def devise_reference():
    """Devise de reference comptable, configurable par variable
    d environnement (defaut EUR)."""
    code = os.environ.get("ACCOUNTING_CURRENCY", "EUR")
    if code not in DEVISES:
        raise ValueError("devise de reference inconnue: " + repr(code))
    return code


def arrondir(montant, devise):
    """Arrondi commercial (ROUND_HALF_UP) selon l exposant ISO 4217.
    XOF : 1234.567 -> 1235 ; EUR : 10.455 -> 10.46 ; JPY -> 0 decimale."""
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


def convertir_trace(montant, devise_source, devise_cible, taux,
                    source_taux, date_taux):
    """Conversion avec historique complet (source + date du taux) :
    voir world_currencies.convertir_trace."""
    return world_currencies.convertir_trace(
        montant, devise_source, devise_cible, taux,
        source_taux, date_taux)


def coherent_prix_affiche_encaisse(prix_affiche, montant_encaisse,
                                   devise, tolerance=Decimal("0.01")):
    """Controle de coherence entre le prix affiche et le montant
    encaisse. Tolere l arrondi de la devise, rien de plus."""
    attendu = arrondir(prix_affiche, devise)
    encaisse = arrondir(montant_encaisse, devise)
    return abs(attendu - encaisse) <= tolerance

"""Gestion des devises ISO 4217, arrondis et cohérence des prix.
Les exposants et symboles proviennent du catalogue localisé de intl.py.
Les conversions exigent un taux explicite ; aucun taux n'est inventé.
"""
import os
from decimal import Decimal, ROUND_HALF_UP

from intl import CURRENCIES as ISO_CURRENCIES


DEVISES = {
    code: {
        "exposant": metadata["decimales"],
        "symbole": metadata["symbole"],
        "actif": metadata["actif"],
    }
    for code, metadata in ISO_CURRENCIES.items()
}


def devise_reference():
    code = os.environ.get("ACCOUNTING_CURRENCY", "EUR")
    if code not in DEVISES:
        raise ValueError("devise de reference inconnue: " + repr(code))
    return code


def arrondir(montant, devise):
    if devise not in DEVISES:
        raise ValueError("devise non supportee: " + repr(devise))
    exponent = DEVISES[devise]["exposant"]
    quantum = Decimal(1).scaleb(-exponent)
    return Decimal(str(montant)).quantize(quantum, rounding=ROUND_HALF_UP)


def convertir(montant, devise_source, devise_cible, taux):
    if devise_source not in DEVISES or devise_cible not in DEVISES:
        raise ValueError("devise non supportee")
    try:
        rate = Decimal(str(taux))
        value = Decimal(str(montant))
    except Exception as exc:
        raise ValueError("taux ou montant invalide: " + repr(taux)) from exc
    if rate <= 0:
        raise ValueError("taux non positif: " + repr(taux))
    return arrondir(value * rate, devise_cible)


def coherent_prix_affiche_encaisse(
    prix_affiche, montant_encaisse, devise,
    tolerance=Decimal("0.01"),
):
    expected = arrondir(prix_affiche, devise)
    received = arrondir(montant_encaisse, devise)
    return abs(expected - received) <= tolerance

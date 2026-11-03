"""Qualification mondiale des offres fournisseurs SHOPLINOUS.

L'origine du fournisseur ou de son entrepôt n'est jamais une liste blanche.
Toute origine ISO est recevable si l'offre prouve identité, conformité,
stock, images, coût, devise et devis réel vers la destination demandée.

Ce module ne contacte aucun fournisseur et n'invente aucune donnée :
il qualifie uniquement les preuves remontées par un adaptateur réel ou
une vérification humaine tracée.
"""
from decimal import Decimal, ROUND_FLOOR, InvalidOperation
import math
import re
import time
from typing import Mapping

from intl import CURRENCIES, get_country


# Règles commerciales conservées de workflow/daily.py, mais indépendantes
# de l'origine géographique du vendeur ou de l'entrepôt.
REGLES_BOUTIQUE = {
    "cout_achat_unitaire_max_eur": Decimal("8.00"),
    "transport_unitaire_max_eur": Decimal("6.00"),
    "delai_min_max_jours": 15,
    "stock_verifie_min": 1000,
    "images_validees_min": 2,
    "multiplicateur_marge_min": Decimal("3.0"),
    "fraicheur_stock_secondes": 3600,
    "fraicheur_devis_secondes": 3600,
    "fraicheur_taux_secondes": 3600,
    "fraicheur_images_secondes": 7 * 24 * 3600,
}

_PRODUITS_INTERDITS = re.compile(
    r"(?i)\b(battery|lithium|bluetooth|speaker|drone|camera|"
    r"cosmetic|cream|serum|supplement|cbd|vape|tattoo|knife|"
    r"gun|ammo|firearm|explosive|pesticide|weapon)\b"
)


def _decimal(value, field):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(field + " invalide")
    if not result.is_finite():
        raise ValueError(field + " non fini")
    return result


def _iso_country(code, field):
    if not isinstance(code, str) or not code.strip():
        raise ValueError(field + " manquant")
    normalized = code.strip().upper()
    try:
        get_country(normalized)
    except KeyError:
        raise ValueError(field + " doit être un code ISO 3166-1 valide")
    return normalized


def _taux_vers_eur(currency, rates, now):
    currency = str(currency or "").strip().upper()
    if currency not in CURRENCIES:
        raise ValueError("devise non prise en charge : " + currency)
    if currency == "EUR":
        return Decimal("1")
    rate = (rates or {}).get(currency)
    if rate is None:
        raise ValueError("taux réel " + currency + "->EUR manquant")
    pair = getattr(rate, "paire", None)
    value = getattr(rate, "valeur", None)
    timestamp = getattr(rate, "horodatage", None)
    if pair != (currency, "EUR") or value is None or timestamp is None:
        raise ValueError("objet de taux " + currency + "->EUR invalide")
    age = now - float(timestamp)
    if age < 0 or age > REGLES_BOUTIQUE["fraicheur_taux_secondes"]:
        raise ValueError("taux " + currency + "->EUR absent ou périmé")
    factor = _decimal(value, "taux " + currency + "->EUR")
    if factor <= 0:
        raise ValueError("taux " + currency + "->EUR non positif")
    return factor


def _prix_finissant_par_90(minimum_eur):
    """Arrondit au prochain prix x,90 sans jamais passer sous le plancher."""
    base = minimum_eur.quantize(Decimal("1"), rounding=ROUND_FLOOR)
    candidate = base + Decimal("0.90")
    if candidate < minimum_eur:
        candidate += Decimal("1.00")
    return candidate.quantize(Decimal("0.01"))


def evaluer_offre(offre: Mapping, destination: str, quantite: int,
                  taux_vers_eur: Mapping, maintenant: float = None) -> dict:
    """Évalue une offre pour UNE destination et UNE quantité exactes.

    Champs probants attendus :
      fournisseur, pays_fournisseur, pays_entrepot, sku, nom_produit,
      prix_achat, devise_achat, stock, stock_verifie, stock_verifie_le,
      images_validees, images_verifiees_le, preuve_images,
      fournisseur_verifie, preuve_fournisseur,
      conformite_verifiee, preuve_conformite,
      devis_livraison {reference, verifie, destination, quantite, cout,
        devise, delai_min_jours, delai_max_jours, restrictions_ok,
        verifie_le, expire_le}.

    L'origine est vérifiée comme code ISO uniquement. Elle n'est jamais
    comparée à une liste de pays autorisés : la route réelle vers la
    destination et les règles de la boutique décident.
    """
    maintenant = time.time() if maintenant is None else float(maintenant)
    refus = []
    resultat = {
        "eligible": False,
        "fournisseur": None,
        "pays_fournisseur": None,
        "pays_entrepot": None,
        "destination": None,
        "quantite": quantite,
        "cout_achat_eur": None,
        "transport_total_eur": None,
        "transport_unitaire_eur": None,
        "cout_rendu_eur": None,
        "prix_vente_min_eur": None,
        "delai_min_jours": None,
        "delai_max_jours": None,
        "refus": refus,
    }
    if not isinstance(offre, Mapping):
        return {**resultat, "refus": ["offre invalide"]}
    if not isinstance(quantite, int) or isinstance(quantite, bool) or quantite < 1:
        return {**resultat, "refus": ["quantité invalide"]}
    resultat["quantite"] = quantite

    try:
        destination = _iso_country(destination, "destination")
        country = get_country(destination)
        resultat["destination"] = destination
        if not country.open_for_sale:
            refus.append("destination non ouverte à la vente")
    except ValueError as exc:
        refus.append(str(exc))
        destination = None

    supplier_name = str(offre.get("fournisseur") or "").strip()
    sku = str(offre.get("sku") or "").strip()
    product_name = str(offre.get("nom_produit") or "").strip()
    resultat["fournisseur"] = supplier_name or None
    if not supplier_name:
        refus.append("nom du fournisseur manquant")
    if not sku:
        refus.append("SKU variante manquant")
    if not product_name:
        refus.append("nom du produit manquant")

    try:
        supplier_country = _iso_country(
            offre.get("pays_fournisseur"), "pays du fournisseur")
        warehouse_country = _iso_country(
            offre.get("pays_entrepot"), "pays de l'entrepôt")
        resultat["pays_fournisseur"] = supplier_country
        resultat["pays_entrepot"] = warehouse_country
    except ValueError as exc:
        refus.append(str(exc))

    if offre.get("fournisseur_verifie") is not True or not str(
            offre.get("preuve_fournisseur") or "").strip():
        refus.append("identité du fournisseur non vérifiée ou preuve absente")

    if offre.get("conformite_verifiee") is not True or not str(
            offre.get("preuve_conformite") or "").strip():
        refus.append("conformité produit non vérifiée ou preuve absente")

    if product_name and _PRODUITS_INTERDITS.search(product_name):
        refus.append("produit appartenant à une catégorie interdite")

    if offre.get("produit_interdit") is True:
        refus.append("produit interdit selon le contrôle réglementaire")

    stock = offre.get("stock")
    if not isinstance(stock, int) or isinstance(stock, bool) or stock < 0:
        refus.append("stock réel invalide")
    elif stock < REGLES_BOUTIQUE["stock_verifie_min"]:
        refus.append("stock inférieur au minimum de 1000 unités")
    if offre.get("stock_verifie") is not True:
        refus.append("stock non vérifié auprès de la source")
    stock_date = offre.get("stock_verifie_le")
    if not isinstance(stock_date, (int, float)):
        refus.append("date de vérification du stock absente")
    elif maintenant - float(stock_date) < 0 or (
            maintenant - float(stock_date)
            > REGLES_BOUTIQUE["fraicheur_stock_secondes"]):
        refus.append("mesure de stock périmée")

    images = offre.get("images_validees")
    if not isinstance(images, int) or isinstance(images, bool) or (
            images < REGLES_BOUTIQUE["images_validees_min"]):
        refus.append("moins de 2 images réellement validées")
    if not str(offre.get("preuve_images") or "").strip():
        refus.append("preuve de validation des images absente")
    images_date = offre.get("images_verifiees_le")
    if not isinstance(images_date, (int, float)):
        refus.append("date de validation des images absente")
    elif maintenant - float(images_date) < 0 or (
            maintenant - float(images_date)
            > REGLES_BOUTIQUE["fraicheur_images_secondes"]):
        refus.append("validation des images périmée")

    quote = offre.get("devis_livraison")
    if not isinstance(quote, Mapping):
        refus.append("devis transport réel manquant")
        quote = {}
    else:
        if quote.get("verifie") is not True:
            refus.append("devis transport non vérifié")
        if not str(quote.get("reference") or "").strip():
            refus.append("référence de devis transport absente")
        if quote.get("destination") != destination:
            refus.append("devis transport pour une autre destination")
        if quote.get("quantite") != quantite:
            refus.append("devis transport pour une autre quantité")
        verified_at = quote.get("verifie_le")
        expires_at = quote.get("expire_le")
        if not isinstance(verified_at, (int, float)):
            refus.append("date de vérification du devis absente")
        elif maintenant - float(verified_at) < 0 or (
                maintenant - float(verified_at)
                > REGLES_BOUTIQUE["fraicheur_devis_secondes"]):
            refus.append("devis transport périmé")
        if not isinstance(expires_at, (int, float)) or (
                float(expires_at) <= maintenant):
            refus.append("devis transport expiré")
        if quote.get("restrictions_ok") is not True:
            refus.append("restrictions douanières ou d'importation non levées")

    # Calcul des coûts uniquement quand données et taux sont vérifiables.
    achat_eur = transport_total_eur = transport_unit_eur = rendu_eur = None
    try:
        achat = _decimal(offre.get("prix_achat"), "prix fournisseur")
        if achat <= 0:
            raise ValueError("prix fournisseur non positif")
        achat_currency = str(offre.get("devise_achat") or "").upper()
        achat_eur = achat * _taux_vers_eur(achat_currency, taux_vers_eur, maintenant)
        resultat["cout_achat_eur"] = str(achat_eur.quantize(Decimal("0.01")))
        if achat_eur > REGLES_BOUTIQUE["cout_achat_unitaire_max_eur"]:
            refus.append("coût fournisseur supérieur à 8 EUR par unité")
    except ValueError as exc:
        refus.append(str(exc))

    try:
        shipping = _decimal(quote.get("cout"), "coût transport")
        if shipping < 0:
            raise ValueError("coût transport négatif")
        shipping_currency = str(quote.get("devise") or "").upper()
        transport_total_eur = shipping * _taux_vers_eur(
            shipping_currency, taux_vers_eur, maintenant)
        transport_unit_eur = transport_total_eur / Decimal(quantite)
        resultat["transport_total_eur"] = str(
            transport_total_eur.quantize(Decimal("0.01")))
        resultat["transport_unitaire_eur"] = str(
            transport_unit_eur.quantize(Decimal("0.01")))
        if transport_unit_eur > REGLES_BOUTIQUE["transport_unitaire_max_eur"]:
            refus.append("transport supérieur à 6 EUR par unité")
    except ValueError as exc:
        refus.append(str(exc))

    try:
        min_days = quote.get("delai_min_jours")
        max_days = quote.get("delai_max_jours")
        if not isinstance(min_days, int) or isinstance(min_days, bool) or (
                min_days < 1):
            raise ValueError("délai minimum invalide")
        if not isinstance(max_days, int) or isinstance(max_days, bool) or (
                max_days < min_days):
            raise ValueError("délai maximum invalide")
        resultat["delai_min_jours"] = min_days
        resultat["delai_max_jours"] = max_days
        if max_days > REGLES_BOUTIQUE["delai_min_max_jours"]:
            refus.append("délai de livraison supérieur à 15 jours")
    except ValueError as exc:
        refus.append(str(exc))

    if achat_eur is not None and transport_unit_eur is not None:
        rendu_eur = achat_eur + transport_unit_eur
        minimum = _prix_finissant_par_90(
            rendu_eur * REGLES_BOUTIQUE["multiplicateur_marge_min"])
        resultat["cout_rendu_eur"] = str(rendu_eur.quantize(Decimal("0.01")))
        resultat["prix_vente_min_eur"] = str(minimum)
        retail = offre.get("prix_vente_eur")
        if retail is not None:
            try:
                retail_price = _decimal(retail, "prix de vente proposé")
                if retail_price < minimum:
                    refus.append("prix de vente inférieur au minimum de marge x3")
            except ValueError as exc:
                refus.append(str(exc))

    resultat["eligible"] = not refus
    return resultat


def evaluer_offres(offres, destination, quantite, taux_vers_eur,
                   maintenant=None):
    """Évalue un ensemble d'offres mondiales et retourne le tri conforme.

    Une origine géographique ne donne aucun avantage ni pénalité : la
    comparaison repose sur le coût rendu, le délai vérifié et la conformité.
    """
    evaluations = [
        evaluer_offre(offre, destination, quantite, taux_vers_eur, maintenant)
        for offre in (offres or [])
    ]
    conformes = [item for item in evaluations if item["eligible"]]
    conformes.sort(key=lambda item: (
        Decimal(item["cout_rendu_eur"]),
        item["delai_max_jours"],
        str(item["fournisseur"]).casefold(),
    ))
    return {
        "destination": str(destination).upper(),
        "quantite": quantite,
        "nombre_offres": len(evaluations),
        "nombre_conformes": len(conformes),
        "meilleure_offre": conformes[0] if conformes else None,
        "offres_conformes": conformes,
        "offres_refusees": [item for item in evaluations if not item["eligible"]],
    }

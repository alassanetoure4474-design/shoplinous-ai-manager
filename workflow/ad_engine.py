"""SHOPLINOUS - Moteur publicitaire international.

Les annonces sont générées uniquement pour un marché ouvert et un produit
livrable. Les prix sont affichés dans la devise du pays après conversion
avec un taux fourni ; aucun taux ni canal social n'est simulé.
"""
from dataclasses import dataclass

from intl import (
    CURRENCIES,
    LANGUAGES,
    convert,
    format_price,
    get_country,
    is_rtl,
)


CANAL_AUTORISE = {  # publication réelle impossible sans connecteur vérifié
    "facebook": False,
    "instagram": False,
    "tiktok": False,
    "google": False,
    "pinterest": False,
}


@dataclass
class Produit:
    sku: str
    nom: str
    prix: float
    cout_total: float
    stock: int
    nb_images: int
    pays_livrables: list
    devise_base: str = "EUR"

    @property
    def marge(self) -> float:
        return round(self.prix - self.cout_total, 2)

    @property
    def rentable(self) -> bool:
        return self.cout_total > 0 and self.prix >= 3 * self.cout_total


def score_produit(p: Produit) -> dict:
    """Score 0-100 ; un produit non éligible n'est jamais promu."""
    score = 0
    if p.stock > 0:
        score += 25
    if p.stock >= 100:
        score += 15
    if p.rentable:
        score += 30
    if p.nb_images >= 2:
        score += 20
    if p.pays_livrables:
        score += 10
    eligible = bool(
        p.stock > 0 and p.rentable and p.nb_images >= 2 and p.pays_livrables
    )
    return {"sku": p.sku, "score": score, "eligible": eligible}


MODELES_ANNONCES = {
    "fr": {
        "titre": "Découverte : {nom}",
        "accroche": "{nom} — {prix}, livraison vers votre pays.",
        "cta": "Voir le produit",
        "hashtags": ["#deco", "#maison", "#shoplinous"],
    },
    "en": {
        "titre": "Discover: {nom}",
        "accroche": "{nom} — {prix}, shipping to your country.",
        "cta": "View product",
        "hashtags": ["#homedecor", "#shoplinous"],
    },
    "es": {
        "titre": "Descubre: {nom}",
        "accroche": "{nom} — {prix}, envío a tu país.",
        "cta": "Ver producto",
        "hashtags": ["#decoracion", "#shoplinous"],
    },
    "pt": {
        "titre": "Descubra: {nom}",
        "accroche": "{nom} — {prix}, entrega no seu país.",
        "cta": "Ver produto",
        "hashtags": ["#decoracao", "#shoplinous"],
    },
    "ar": {
        "titre": "اكتشف: {nom}",
        "accroche": "{nom} — {prix}، الشحن إلى بلدك.",
        "cta": "عرض المنتج",
        "hashtags": ["#تسوق", "#shoplinous"],
    },
}


def generer_annonce(
    p: Produit,
    lang: str,
    pays: str,
    devise: str = None,
    taux: dict = None,
) -> dict:
    """Génère une annonce seulement si marché, livraison et prix sont vérifiés.

    Le prix du produit est exprimé dans p.devise_base (EUR par défaut).
    Pour toute autre devise, taux doit contenir les taux réels du même
    référentiel. Une destination à plusieurs monnaies exige un choix explicite.
    """
    if lang not in LANGUAGES:
        raise ValueError("Langue non supportée : " + lang)

    code = str(pays).strip().upper()
    country = get_country(code)
    if not country.open_for_sale:
        raise ValueError("Marché non ouvert à la vente : " + code)
    shippable_codes = {str(item).strip().upper() for item in p.pays_livrables}
    if code not in shippable_codes:
        raise ValueError("Produit non livrable en " + code)

    base_currency = str(p.devise_base).upper()
    target_currency = str(devise or country.currency or "").upper()
    if not target_currency:
        raise ValueError("Destination avec plusieurs devises : choix explicite requis.")
    if target_currency not in country.currencies:
        raise ValueError("Devise non associée à la destination : " + target_currency)
    if base_currency not in CURRENCIES or target_currency not in CURRENCIES:
        raise ValueError("Devise non prise en charge pour le calcul du prix.")

    if target_currency == base_currency:
        local_price = float(p.prix)
    else:
        if taux is None:
            raise ValueError(
                "Taux de change réel requis pour "
                + base_currency + "->" + target_currency
            )
        local_price = convert(p.prix, base_currency, target_currency, taux)

    model = MODELES_ANNONCES[lang]
    price_text = format_price(local_price, target_currency, lang)
    return {
        "sku": p.sku,
        "lang": lang,
        "pays": code,
        "devise": target_currency,
        "direction": "rtl" if is_rtl(lang) else "ltr",
        "titre": model["titre"].format(nom=p.nom),
        "accroche": model["accroche"].format(nom=p.nom, prix=price_text),
        "cta": model["cta"],
        "hashtags": list(model["hashtags"]),
    }


@dataclass
class CampagnePayante:
    nom: str
    pays: list
    budget: float = 0.0
    statut: str = "brouillon"


def creer_campagne_payante(nom, pays, budget=0.0) -> CampagnePayante:
    if budget != 0:
        raise ValueError("Budget non autorisé : les campagnes restent à 0")
    for code in pays:
        if not get_country(code).open_for_sale:
            raise ValueError("Marché non ouvert : " + code)
    return CampagnePayante(nom=nom, pays=pays, budget=0.0, statut="brouillon")


class CalendrierOrganique:
    """Planifie max. 3 publications par jour, uniquement sur canaux autorisés."""

    def __init__(self):
        self.planning = {}

    def planifier(self, jour, annonce, canal) -> dict:
        if not CANAL_AUTORISE.get(canal, False):
            raise ValueError("Canal non autorisé : " + canal)
        items = self.planning.setdefault(jour, [])
        if len(items) >= 3:
            raise ValueError("Maximum 3 publications par jour")
        publication = {
            "jour": jour,
            "annonce": annonce,
            "canal": canal,
            "publie": False,
        }
        items.append(publication)
        return publication


def tableau_de_bord(planning, statistiques=None) -> dict:
    """N'invente jamais une statistique : les données absentes restent None."""
    nb = sum(len(items) for items in planning.values())
    stats = statistiques or {}
    return {
        "publications_planifiees": nb,
        "impressions": stats.get("impressions"),
        "clics": stats.get("clics"),
        "depenses": stats.get("depenses"),
        "conversions": stats.get("conversions"),
    }

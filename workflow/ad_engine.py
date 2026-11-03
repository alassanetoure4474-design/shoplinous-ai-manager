"""SHOPLINOUS - moteur publicitaire multilingue et multi-devises.

Aucune publication réelle sans connecteur autorisé. Les prix publicitaires
utilisent la devise du pays cible et exigent un taux explicite si nécessaire.
"""
from dataclasses import dataclass
from intl import (
    get_country, LANGUAGES, CURRENCIES, convert, format_price,
    text_direction,
)


CANAL_AUTORISE = {
    "facebook": False, "instagram": False, "tiktok": False,
    "google": False, "pinterest": False,
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
    devise_prix: str = "EUR"

    @property
    def marge(self) -> float:
        return round(self.prix - self.cout_total, 2)

    @property
    def rentable(self) -> bool:
        return self.prix >= 3 * self.cout_total


def score_produit(p: Produit) -> dict:
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
        "titre": "Découvrez : {nom}",
        "accroche": "{nom} — {prix}, livraison disponible dans votre pays.",
        "cta": "Voir le produit",
        "hashtags": ["#deco", "#maison", "#shoplinous"],
    },
    "en": {
        "titre": "Discover: {nom}",
        "accroche": "{nom} — {prix}, shipping availability checked for your country.",
        "cta": "View product",
        "hashtags": ["#homedecor", "#shoplinous"],
    },
    "es": {
        "titre": "Descubre: {nom}",
        "accroche": "{nom} — {prix}, envío disponible en tu país.",
        "cta": "Ver producto",
        "hashtags": ["#decoracion", "#shoplinous"],
    },
    "pt": {
        "titre": "Descubra: {nom}",
        "accroche": "{nom} — {prix}, entrega disponível no seu país.",
        "cta": "Ver produto",
        "hashtags": ["#decoracao", "#shoplinous"],
    },
    "ar": {
        "titre": "اكتشف: {nom}",
        "accroche": "{nom} — {prix}، الشحن متاح إلى بلدك.",
        "cta": "عرض المنتج",
        "hashtags": ["#تسوق", "#shoplinous"],
    },
}


def _prix_localise(p: Produit, devise_cible: str, taux: dict | None) -> str:
    if p.devise_prix not in CURRENCIES:
        raise ValueError("Devise source du produit inconnue : " + p.devise_prix)
    if devise_cible not in CURRENCIES:
        raise ValueError("Devise locale non identifiee pour ce pays")
    montant = p.prix
    if p.devise_prix != devise_cible:
        if taux is None:
            raise ValueError(
                "Taux de change horodate requis pour "
                + p.devise_prix + "->" + devise_cible
            )
        montant = convert(montant, p.devise_prix, devise_cible, taux)
    return format_price(montant, devise_cible)


def generer_annonce(
    p: Produit, lang: str, pays: str, taux: dict | None = None
) -> dict:
    """Génère une annonce uniquement pour un pays ouvert et un produit livrable.

    taux doit provenir d'un fournisseur de change horodaté ; sa forme est celle
    de intl.convert (valeurs relatives à une même devise de base).
    """
    if lang not in LANGUAGES:
        raise ValueError("Langue non supportee : " + lang)
    country = get_country(pays)
    if not country.open_for_sale:
        raise ValueError("Marche non ouvert a la vente : " + pays)
    if pays not in p.pays_livrables:
        raise ValueError("Produit non livrable en " + pays)
    if not country.currency:
        raise ValueError("Aucune devise locale commerciale identifiee : " + pays)

    model = MODELES_ANNONCES[lang]
    price = _prix_localise(p, country.currency, taux)
    return {
        "sku": p.sku,
        "lang": lang,
        "pays": country.code,
        "devise": country.currency,
        "direction": text_direction(lang),
        "titre": model["titre"].format(nom=p.nom),
        "accroche": model["accroche"].format(nom=p.nom, prix=price),
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
        raise ValueError("Budget non autorise : les campagnes restent a 0")
    for country_code in pays:
        if not get_country(country_code).open_for_sale:
            raise ValueError("Marche non ouvert : " + country_code)
    return CampagnePayante(nom=nom, pays=pays, budget=0.0, statut="brouillon")


class CalendrierOrganique:
    """Planifie au plus 3 publications par jour, sur des canaux autorisés."""
    def __init__(self):
        self.planning = {}

    def planifier(self, jour, annonce, canal) -> dict:
        if not CANAL_AUTORISE.get(canal, False):
            raise ValueError("Canal non autorise : " + canal)
        items = self.planning.setdefault(jour, [])
        if len(items) >= 3:
            raise ValueError("Maximum 3 publications par jour")
        publication = {
            "jour": jour, "annonce": annonce,
            "canal": canal, "publie": False,
        }
        items.append(publication)
        return publication


def tableau_de_bord(planning, statistiques=None) -> dict:
    count = sum(len(values) for values in planning.values())
    stats = statistiques or {}
    return {
        "publications_planifiees": count,
        "impressions": stats.get("impressions"),
        "clics": stats.get("clics"),
        "depenses": stats.get("depenses"),
        "conversions": stats.get("conversions"),
    }

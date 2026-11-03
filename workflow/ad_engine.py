"""SHOPLINOUS - Moteur publicitaire.
Scoring produits, annonces multilingues honnetes, calendrier organique,
campagnes payantes en brouillon budget 0 uniquement, tableau de bord sans
statistiques fictives. Aucune publication reelle sans canal autorise."""

from dataclasses import dataclass
from intl import get_country, LANGUAGES


CANAL_AUTORISE = {  # aucun connecteur actif : publication reelle impossible
    "facebook": False, "instagram": False, "tiktok": False,
    "google": False, "pinterest": False,
}


@dataclass
class Produit:
    sku: str
    nom: str
    prix: float
    cout_total: float  # cout produit + livraison
    stock: int
    nb_images: int
    pays_livrables: list

    @property
    def marge(self) -> float:
        return round(self.prix - self.cout_total, 2)

    @property
    def rentable(self) -> bool:
        return self.prix >= 3 * self.cout_total


def score_produit(p: Produit) -> dict:
    """Score 0-100 ; un produit non eligible n'est jamais promu."""
    s = 0
    if p.stock > 0: s += 25
    if p.stock >= 100: s += 15
    if p.rentable: s += 30
    if p.nb_images >= 2: s += 20
    if p.pays_livrables: s += 10
    eligible = bool(p.stock > 0 and p.rentable and p.nb_images >= 2 and p.pays_livrables)
    return {"sku": p.sku, "score": s, "eligible": eligible}


MODELES_ANNONCES = {
    "fr": {"titre": "Decouverte : {nom}",
           "accroche": "{nom} - {prix} EUR, livraison vers votre pays.",
           "cta": "Voir le produit",
           "hashtags": ["#deco", "#maison", "#shoplinous"]},
    "en": {"titre": "Discover: {nom}",
           "accroche": "{nom} - {prix} EUR, shipping to your country.",
           "cta": "View product",
           "hashtags": ["#homedecor", "#shoplinous"]},
    "es": {"titre": "Descubre: {nom}",
           "accroche": "{nom} - {prix} EUR, envio a tu pais.",
           "cta": "Ver producto",
           "hashtags": ["#decoracion", "#shoplinous"]},
    "pt": {"titre": "Descubra: {nom}",
           "accroche": "{nom} - {prix} EUR, entrega no seu pais.",
           "cta": "Ver produto",
           "hashtags": ["#decoracao", "#shoplinous"]},
    "ar": {"titre": "Discover: {nom}",
           "accroche": "{nom} - {prix} EUR, shipping to your country.",
           "cta": "View product",
           "hashtags": ["#homedecor", "#shoplinous"]},
}


def generer_annonce(p: Produit, lang: str, pays: str) -> dict:
    """Genere une annonce honnete : ni faux avis, ni fausse reduction,
    ni offre dans un pays non ouvert ou non livrable."""
    if lang not in LANGUAGES:
        raise ValueError("Langue non supportee : " + lang)
    c = get_country(pays)
    if not c.open_for_sale:
        raise ValueError("Marche non ouvert a la vente : " + pays)
    if pays not in p.pays_livrables:
        raise ValueError("Produit non livrable en " + pays)
    m = MODELES_ANNONCES[lang]
    return {
        "sku": p.sku, "lang": lang, "pays": pays,
        "titre": m["titre"].format(nom=p.nom),
        "accroche": m["accroche"].format(nom=p.nom, prix=("%.2f" % p.prix)),
        "cta": m["cta"], "hashtags": list(m["hashtags"]),
    }


@dataclass
class CampagnePayante:
    nom: str
    pays: list
    budget: float = 0.0
    statut: str = "brouillon"  # jamais "active" sans autorisation reelle


def creer_campagne_payante(nom, pays, budget=0.0) -> CampagnePayante:
    if budget != 0:
        raise ValueError("Budget non autorise : les campagnes restent a 0")
    for p in pays:
        if not get_country(p).open_for_sale:
            raise ValueError("Marche non ouvert : " + p)
    return CampagnePayante(nom=nom, pays=pays, budget=0.0, statut="brouillon")


class CalendrierOrganique:
    """Planifie max 3 publications par jour, sur des canaux autorises."""
    def __init__(self):
        self.planning = {}  # jour -> liste de publications

    def planifier(self, jour, annonce, canal) -> dict:
        if not CANAL_AUTORISE.get(canal, False):
            raise ValueError("Canal non autorise : " + canal)
        items = self.planning.setdefault(jour, [])
        if len(items) >= 3:
            raise ValueError("Maximum 3 publications par jour")
        pub = {"jour": jour, "annonce": annonce, "canal": canal, "publie": False}
        items.append(pub)
        return pub


def tableau_de_bord(planning, statistiques=None) -> dict:
    """N'invente jamais une statistique : seules les stats reelles passees
    apparaissent ; les autres champs valent None."""
    nb = sum(len(v) for v in planning.values())
    stats = statistiques or {}
    return {
        "publications_planifiees": nb,
        "impressions": stats.get("impressions"),
        "clics": stats.get("clics"),
        "depenses": stats.get("depenses"),
        "conversions": stats.get("conversions"),
    }

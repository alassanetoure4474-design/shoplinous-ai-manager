"""SHOPLINOUS - Moteur publicitaire mondial v2.

Scoring produits, annonces multilingues honnetes, prix en DEVISE LOCALE
(plus aucun prix EUR code en dur : le prix affiche depend du pays, de
la langue et de la devise reellement utilisee), calendrier organique,
campagnes payantes en brouillon budget 0 uniquement, tableau de bord
sans statistiques fictives.

Arabe : modeles REELLEMENT en arabe (+ indicateur RTL).
Connecteurs : facebook, instagram, tiktok, google, pinterest ;
tous non connectes par defaut. Le moteur PREPARE des publications,
il ne pretend jamais les avoir publiees.
"""

from dataclasses import dataclass, field

import intl


# --- Connecteurs extensors (aucun n est connecte sans contrat reel) ---
@dataclass
class CanalConnecteur:
    nom: str
    connecte: bool = False
    identifiant_compte: str = ""

    def peut_publier(self) -> bool:
        return self.connecte


CONNECTEURS = {
    "facebook": CanalConnecteur("facebook"),
    "instagram": CanalConnecteur("instagram"),
    "tiktok": CanalConnecteur("tiktok"),
    "google": CanalConnecteur("google"),
    "pinterest": CanalConnecteur("pinterest"),
}

# Compatibilite : reflet du registre (aucun canal autorise)
CANAL_AUTORISE = {k: c.connecte for k, c in CONNECTEURS.items()}


def connecter_canal(nom: str, identifiant_compte: str) -> None:
    """Active un canal UNIQUEMENT sur connexion reelle (credentials
    valides fournis par le proprietaire). Aucune depense n est engagee."""
    c = CONNECTEURS[nom]
    if not identifiant_compte:
        raise ValueError("identifiant de compte requis pour " + nom)
    c.connecte = True
    c.identifiant_compte = identifiant_compte
    CANAL_AUTORISE[nom] = True


@dataclass
class Produit:
    sku: str
    nom: str
    prix: float
    cout_total: float  # cout produit + livraison
    stock: int
    nb_images: int
    pays_livrables: list
    devise_reference: str = "EUR"  # devise de reference du prix catalogue

    @property
    def marge(self) -> float:
        return round(self.prix - self.cout_total, 2)

    @property
    def rentable(self) -> bool:
        return self.prix >= 3 * self.cout_total


def score_produit(p: Produit) -> dict:
    """Score 0-100 ; un produit non eligible n est jamais promu."""
    s = 0
    if p.stock > 0:
        s += 25
    if p.stock >= 100:
        s += 15
    if p.rentable:
        s += 30
    if p.nb_images >= 2:
        s += 20
    if p.pays_livrables:
        s += 10
    eligible = bool(p.stock > 0 and p.rentable
                    and p.nb_images >= 2 and p.pays_livrables)
    return {"sku": p.sku, "score": s, "eligible": eligible}


MODELES_ANNONCES = {
    "fr": {"titre": "Decouverte : {nom}",
           "accroche": "{nom} - {prix}, livraison vers votre pays.",
           "cta": "Voir le produit",
           "hashtags": ["#deco", "#maison", "#shoplinous"]},
    "en": {"titre": "Discover: {nom}",
           "accroche": "{nom} - {prix}, shipping to your country.",
           "cta": "View product",
           "hashtags": ["#homedecor", "#shoplinous"]},
    "es": {"titre": "Descubre: {nom}",
           "accroche": "{nom} - {prix}, envio a tu pais.",
           "cta": "Ver producto",
           "hashtags": ["#decoracion", "#shoplinous"]},
    "pt": {"titre": "Descubra: {nom}",
           "accroche": "{nom} - {prix}, entrega no seu pais.",
           "cta": "Ver produto",
           "hashtags": ["#decoracao", "#shoplinous"]},
    "ar": {"titre": "اكتشف: {nom}",
           "accroche": "{nom} - {prix}، الشحن إلى بلدك.",
           "cta": "شاهد المنتج",
           "hashtags": ["#ديكور_منزلي", "#شوبلينوس"]},
}


def _prix_local(p: Produit, devise: str, taux=None,
                source_taux=None, date_taux=None):
    """Prix affiche dans la devise du marche. Si la devise locale
    differe de la devise de reference, un taux EXPLICITE (avec source
    et date) est obligatoire : aucune conversion approximative cachee.
    Un prix converti est toujours marque indicatif, jamais garanti."""
    if devise == p.devise_reference:
        return p.prix, False, None
    if not taux or not source_taux or not date_taux:
        raise ValueError(
            "Taux requis (source + date) pour " + p.devise_reference
            + " -> " + devise)
    taux_dict = {p.devise_reference: 1.0, devise: taux}
    montant = intl.convert(p.prix, p.devise_reference, devise, taux_dict)
    trace = intl.taux_trace(p.prix, p.devise_reference, devise, taux,
                            source_taux, date_taux)
    return montant, True, trace


def generer_annonce(p: Produit, lang: str, pays: str,
                    taux=None, source_taux=None,
                    date_taux=None) -> dict:
    """Genere une annonce honnete : ni faux avis, ni fausse reduction,
    ni offre dans un pays non ouvert ou non livrable. Le prix affiche
    est dans la devise REELLE du marche, pas en EUR par defaut."""
    if lang not in intl.LANGUAGES:
        raise ValueError("Langue non supportee : " + lang)
    c = intl.get_country(pays)
    if not c.open_for_sale:
        raise ValueError("Marche non ouvert a la vente : " + pays)
    if pays not in p.pays_livrables:
        raise ValueError("Produit non livrable en " + pays)
    devise = c.devise or p.devise_reference
    montant, indicatif, trace = _prix_local(
        p, devise, taux, source_taux, date_taux)
    m = MODELES_ANNONCES[lang]
    prix_txt = intl.format_price(montant, devise, lang)
    return {
        "sku": p.sku, "lang": lang, "pays": pays,
        "devise": devise,
        "titre": m["titre"].format(nom=p.nom),
        "accroche": m["accroche"].format(nom=p.nom, prix=prix_txt),
        "cta": m["cta"], "hashtags": list(m["hashtags"]),
        "rtl": intl.rtl(lang),
        "prix_indicatif": indicatif,
        "trace_taux": trace,
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
        if not intl.get_country(p).open_for_sale:
            raise ValueError("Marche non ouvert : " + p)
    return CampagnePayante(nom=nom, pays=pays, budget=0.0,
                           statut="brouillon")


class CalendrierOrganique:
    """Planifie max 3 publications par jour, sur des canaux connectes
    en vrai. Prepare les publications sans jamais les publier."""
    def __init__(self):
        self.planning = {}  # jour -> liste de publications

    def planifier(self, jour, annonce, canal) -> dict:
        c = CONNECTEURS.get(canal)
        if c is None or not c.peut_publier():
            raise ValueError("Canal non connecte : " + canal)
        items = self.planning.setdefault(jour, [])
        if len(items) >= 3:
            raise ValueError("Maximum 3 publications par jour")
        pub = {"jour": jour, "annonce": annonce, "canal": canal,
               "publie": False, "note": "prepare, jamais publie"}
        items.append(pub)
        return pub


def tableau_de_bord(planning, statistiques=None) -> dict:
    """N invente jamais une statistique : seules les stats reelles
    passees apparaissent ; les autres champs valent None."""
    nb = sum(len(v) for v in planning.values())
    stats = statistiques or {}
    return {
        "publications_planifiees": nb,
        "impressions": stats.get("impressions"),
        "clics": stats.get("clics"),
        "depenses": stats.get("depenses"),
        "conversions": stats.get("conversions"),
        "canaux_connectes": [n for n, c in CONNECTEURS.items()
                             if c.connecte],
    }

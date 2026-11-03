"""Livraison mondiale CJdropshipping : produit par produit, destination
par destination. AUCUNE extrapolation : une option de livraison valide
pour un produit ne vaut JAMAIS pour un autre produit ni un autre pays.

Chaque evaluation exige des donnees REELLES fournies par l API CJ
(calculate_cj_shipping, get_cj_variant_stock) : canal, cout, delai,
stock, entrepot. Les regles metier SHOPLINOUS restent strictes :
stock CN >= 1000, cout <= 6 EUR, delai <= 15 jours.
"""
from shoplinous_global import world_countries

REGLES = {"stock_cn_min": 1000, "cout_eur_max": 6.0, "delai_jours_max": 15}


def stock_cn_eligible(stock_cn: int) -> bool:
    return isinstance(stock_cn, int) and stock_cn >= REGLES["stock_cn_min"]


def _delai_max(delai: str) -> int:
    """'7-15' -> 15 ; tout format inconnu est REJETE (jamais devine)."""
    try:
        return int(str(delai).split("-")[-1])
    except (ValueError, IndexError):
        raise ValueError("delai illisible : " + repr(delai))


def evaluer_devis(devis: dict) -> dict:
    """Evalue UN devis CJ pour UN couple (produit, destination).

    Champs attendus : vid, destination, canal, cout_eur, delai ("4-10"),
    stock_cn. Retourne l eligibilite avec la liste des refus motives.
    """
    refus = []
    if not devis.get("destination"):
        refus.append("destination_absente")
    if devis.get("destination") not in world_countries.PAYS:
        refus.append("destination_non_repertoriee")
    if not stock_cn_eligible(devis.get("stock_cn", 0)):
        refus.append("stock_cn_insuffisant")
    cout = devis.get("cout_eur")
    if not isinstance(cout, (int, float)) or cout is None:
        refus.append("cout_absent")
    elif cout > REGLES["cout_eur_max"]:
        refus.append("cout_trop_eleve")
    delai = devis.get("delai")
    if delai is None:
        refus.append("delai_absent")
    else:
        try:
            if _delai_max(delai) > REGLES["delai_jours_max"]:
                refus.append("delai_trop_long")
        except ValueError:
            refus.append("delai_illisible")
    return {
        "eligible": not refus,
        "refus": refus,
        "canal": devis.get("canal"),
        "destination": devis.get("destination"),
        "stock_cn": devis.get("stock_cn"),
        "cout_eur": cout,
        "delai": delai,
    }


def verifier_produit_destination(produit_sku: str, destination: str,
                                 devis: list) -> dict:
    """Verifie UN produit pour UNE destination a partir des devis CJ
    REELS fournis pour ce couple exact. Un devis d une autre destination
    est ignore : aucune extrapolation.

    Un produit n est vendable dans un pays que si :
    - le pays est ouvert a la commande (statut verifie) ;
    - au moins un devis CJ de CE pays pour CE produit est eligible.
    """
    statut = world_countries.statut(destination)
    if not statut["ouvert_commande"]:
        return {
            "sku": produit_sku, "destination": destination,
            "vendable": False,
            "raison": "marche_ferme:" + ",".join(statut["raisons_fermeture"]),
        }
    examines = [d for d in devis if d.get("destination") == destination]
    if not examines:
        return {
            "sku": produit_sku, "destination": destination,
            "vendable": False,
            "raison": "aucun_devis_pour_cette_destination",
        }
    evaluations = [evaluer_devis(d) for d in examines]
    eligibles = [e for e in evaluations if e["eligible"]]
    meilleur = min(
        (e for e in eligibles), key=lambda e: e["cout_eur"], default=None)
    return {
        "sku": produit_sku, "destination": destination,
        "vendable": bool(eligibles),
        "raison": None if eligibles else "aucun_devis_conforme",
        "nb_devis_examines": len(evaluations),
        "canal_retenu": meilleur["canal"] if meilleur else None,
        "cout_eur": meilleur["cout_eur"] if meilleur else None,
        "delai": meilleur["delai"] if meilleur else None,
    }

"""Pricing Manager : prix final transparent, echec si donnee manque.

Composition OBLIGATOIRE : prix fournisseur + transport + frais de
paiement (taux + fixe) + frais de plateforme + taxes - le tout en
devise de reference via le taux EXPLICITE fourni, puis marge
minimale verifiee. Si UNE donnee manque : DonneesPrixIncompletes
avec la liste EXACTE des champs manquants -> le prix est BLOQUE.
Le chiffre d'affaires n'est JAMAIS considere comme benefice.
"""
from decimal import Decimal

CHAMPS_REQUIS = (
    "prix_fournisseur", "transport", "taux_vers_reference",
    "frais_paiement_taux", "frais_paiement_fixe", "frais_plateforme",
    "taxe_taux", "marge_minimale", "devise_reference",
)


class DonneesPrixIncompletes(ValueError):
    def __init__(self, manquants):
        self.manquants = list(manquants)
        super().__init__(
            "donnees de prix manquantes: " + ", ".join(self.manquants))


def _d(v):
    return Decimal(str(v))


def calculer_prix_final(entree):
    """Retourne un dict de composition COMPLETE ou bloque le prix.

    Statuts : "ok" (prix valide), "marge_insuffisante" (prix bloque,
    raison precise), "donnees_incompletes" (leve en exception).
    """
    manquants = [c for c in CHAMPS_REQUIS if entree.get(c) is None]
    if manquants:
        raise DonneesPrixIncompletes(manquants)
    taux = _d(entree["taux_vers_reference"])
    if taux <= 0:
        raise ValueError("taux non positif")
    cout_fournisseur = _d(entree["prix_fournisseur"]) * taux
    cout_transport = _d(entree["transport"]) * taux
    cout_sous_jacent = cout_fournisseur + cout_transport
    frais_paiement = (cout_sous_jacent * _d(entree["frais_paiement_taux"])
                      + _d(entree["frais_paiement_fixe"]))
    frais_plateforme = _d(entree["frais_plateforme"])
    taxe_taux = _d(entree["taxe_taux"])
    marge_minimale = _d(entree["marge_minimale"])
    if marge_minimale < 0 or taxe_taux < 0:
        raise ValueError("taux negatif interdit (marge/taxe)")
    # benefice AVANT prix : on calcule le prix plancher qui garantit
    # la marge minimale apres frais et taxes.
    couts_avant_marge = cout_sous_jacent + frais_paiement + frais_plateforme
    # prix = (couts + marge) ; taxe prelevee sur le prix.
    denominateur = (Decimal(1) - taxe_taux)
    if denominateur <= 0:
        raise ValueError("taux de taxe >= 100 % : prix impossible")
    prix_plancher = (couts_avant_marge + marge_minimale) / denominateur
    prix_plancher = prix_plancher.quantize(Decimal("0.01"))
    return {
        "statut": "ok",
        "devise_reference": entree["devise_reference"],
        "composition": {
            "cout_fournisseur": str(cout_fournisseur.quantize(Decimal("0.01"))),
            "cout_transport": str(cout_transport.quantize(Decimal("0.01"))),
            "frais_paiement": str(frais_paiement.quantize(Decimal("0.01"))),
            "frais_plateforme": str(frais_plateforme.quantize(Decimal("0.01"))),
            "taxe_taux": str(taxe_taux),
        },
        "prix_plancher": str(prix_plancher),
        "cout_total": str(couts_avant_marge.quantize(Decimal("0.01"))),
        "note": "le chiffre d'affaires n'est pas le benefice",
    }


def verifier_prix_propose(prix_propose, entree):
    """Verifie qu'un prix propose couvre couts + taxes + marge minimale.
    Statut "marge_insuffisante" = prix BLOQUE, avec ecart exact."""
    base = calculer_prix_final(entree)
    prix = _d(prix_propose)
    taxe = prix * _d(entree["taxe_taux"])
    benefice_net = prix - _d(base["cout_total"]) - taxe
    if benefice_net < _d(entree["marge_minimale"]):
        return {"statut": "marge_insuffisante",
                "benefice_net": str(benefice_net.quantize(Decimal("0.01"))),
                "manque": str((_d(entree["marge_minimale"])
                               - benefice_net).quantize(Decimal("0.01"))),
                "prix_plancher": base["prix_plancher"]}
    return {"statut": "ok",
            "benefice_net": str(benefice_net.quantize(Decimal("0.01"))),
            "composition": base["composition"]}

"""SHOPLINOUS v5.5 - Moteur intelligent de calcul des prix de vente (branche workflow-v5-fix5b).

Objectif : recommander un prix de vente selon le cout d'achat CJ reel, le pays de
destination, la quantite commandee, le taux de change, les frais de paiement et la
marge beneficiaire minimale.

DONNEES REELLES embarquees (lecture seule CJ, aucune ecriture) :
- Produit de reference : attrape-reveves CJ pid 1797521453303214080, variante vid
  1797521453382905856 (80 g, 2.81 USD piece), mesure le 2026-11-02.
- Frets REAL_FREIGHT : options CJ les moins cheres relevees le 2026-11-02 via
  calculate_cj_shipping (lecture seule), pour les quantites 1 a 5 seulement.
  AUCUNE extrapolation : quantite > 5 ou destination non mesuree => verification
  manuelle requise, aucun prix n'est calcule.
- Taux de change : 1 USD = 0.89509 EUR (BCE / frankfurter.app, 2026-10-30).

SECURITE :
- Module PUR : aucun appel reseau, aucune ecriture Freewebstore/CJ.
- Aucun prix reel n'est modifie, aucun produit publie, aucune commande passee,
  aucun stock modifie, allow_publish=False, main jamais modifiee ni fusionnee.
- La livraison gratuite offerte au client est INTEGREE dans le prix de vente ;
  elle n'est PAS une livraison reellement gratuite pour SHOPLINOUS (le fret CJ
  reste un cout reel).

Frais de paiement : NON VERIFIES. Les parametres frais_paiement_taux et
frais_paiement_fixe_eur doivent etre fournis par l'appelant (valeurs reellement
negociees avec le prestataire de paiement). Aucune valeur n'est inventee ici.
"""

# --- Constantes de securite ---
ALLOW_PUBLISH = False
QTE_MAX_AUTOMATIQUE = 5
DATE_MESURE_FRETS = "2026-11-02"

# --- Taux de change reel (BCE / frankfurter.app) ---
EXCHANGE_RATE_USD_EUR = 0.89509
EXCHANGE_RATE_DATE = "2026-10-30"

# --- Cout d'achat reel du produit de reference (CJ, 2026-11-02) ---
PRODUCT_COST_USD = 2.81
PRODUCT_PID_CJ = "1797521453303214080"
PRODUCT_VID_CJ = "1797521453382905856"

# --- Regions ---
REGIONS = {
    "FR": "europe",
    "GB": "europe",
    "US": "amerique_du_nord",
    "CI": "afrique",
    "BR": "amerique_du_sud",
    "AU": "oceanie",
    "CN": "asie",
}

# --- Frets reels CJ par destination et quantite (USD, option la moins chere
# relevee le 2026-11-02, aucune extrapolation) ---
REAL_FREIGHT = {
    # France (Europe) : CJPacket Ordinary, 4-10 jours
    "FR": {
        1: {"usd": 4.69, "canal": "CJPacket Ordinary", "delai": "4-10"},
        2: {"usd": 5.65, "canal": "CJPacket Ordinary", "delai": "4-10"},
        3: {"usd": 6.62, "canal": "CJPacket Ordinary", "delai": "4-10"},
        4: {"usd": 7.58, "canal": "CJPacket Ordinary", "delai": "4-10"},
        5: {"usd": 8.54, "canal": "CJPacket Ordinary", "delai": "4-10"},
    },
    # Royaume-Uni (Europe)
    "GB": {
        1: {"usd": 3.68, "canal": "CJPacket Ordinary", "delai": "4-9"},
        2: {"usd": 4.40, "canal": "CJPacket Ordinary", "delai": "4-9"},
        3: {"usd": 5.08, "canal": "YunExpress Ordinary", "delai": "4-7"},
        4: {"usd": 5.82, "canal": "YunExpress Ordinary", "delai": "4-7"},
        5: {"usd": 6.47, "canal": "YunExpress Ordinary", "delai": "4-7"},
    },
    # Etats-Unis (Amerique du Nord)
    "US": {
        1: {"usd": 5.38, "canal": "CJPacket Super Pure Electricity", "delai": "5-11"},
        2: {"usd": 7.15, "canal": "YunExpress Ordinary", "delai": "4-7"},
        3: {"usd": 7.36, "canal": "LuWei Ordinary US", "delai": "5-11"},
        4: {"usd": 8.58, "canal": "LuWei Ordinary US", "delai": "5-11"},
        5: {"usd": 9.80, "canal": "LuWei Ordinary US", "delai": "5-11"},
    },
    # Cote d'Ivoire (Afrique) : CJPacket Eub, 12-50 jours
    "CI": {
        1: {"usd": 3.51, "canal": "CJPacket Eub", "delai": "12-50"},
        2: {"usd": 5.90, "canal": "CJPacket Eub", "delai": "12-50"},
        3: {"usd": 8.28, "canal": "CJPacket Eub", "delai": "12-50"},
        4: {"usd": 10.68, "canal": "CJPacket Eub", "delai": "12-50"},
        5: {"usd": 13.07, "canal": "CJPacket Eub", "delai": "12-50"},
    },
    # Bresil (Amerique du Sud) : CJPacket Eub, 12-50 jours
    "BR": {
        1: {"usd": 5.61, "canal": "CJPacket Eub", "delai": "12-50"},
        2: {"usd": 7.12, "canal": "CJPacket Eub", "delai": "12-50"},
        3: {"usd": 8.63, "canal": "CJPacket Eub", "delai": "12-50"},
        4: {"usd": 10.15, "canal": "CJPacket Eub", "delai": "12-50"},
        5: {"usd": 11.65, "canal": "CJPacket Eub", "delai": "12-50"},
    },
    # Australie (Oceanie) : CJPacket Eub, 6-10 jours
    "AU": {
        1: {"usd": 5.57, "canal": "CJPacket Eub", "delai": "6-10"},
        2: {"usd": 6.49, "canal": "CJPacket Eub", "delai": "6-10"},
        3: {"usd": 7.41, "canal": "CJPacket Eub", "delai": "6-10"},
        4: {"usd": 8.33, "canal": "CJPacket Eub", "delai": "6-10"},
        5: {"usd": 9.25, "canal": "CJPacket Eub", "delai": "6-10"},
    },
    # Chine (Asie) : YTO China Domestic, 2-3 jours (tarif plat releve)
    "CN": {
        1: {"usd": 1.43, "canal": "YTO China Domestic", "delai": "2-3"},
        2: {"usd": 1.43, "canal": "YTO China Domestic", "delai": "2-3"},
        3: {"usd": 1.43, "canal": "YTO China Domestic", "delai": "2-3"},
        4: {"usd": 1.43, "canal": "YTO China Domestic", "delai": "2-3"},
        5: {"usd": 1.43, "canal": "YTO China Domestic", "delai": "2-3"},
    },
}

# --- Messages d'alerte ---
MSG_QTE_SUPERIEURE = (
    "QUANTITE_SUPERIEURE_A_5 : verification manuelle requise, "
    "aucune extrapolation des tarifs de livraison."
)
MSG_TARIF_INDISPONIBLE = (
    "TARIF_INDISPONIBLE : aucun tarif CJ reel mesure pour cette "
    "destination/quantite, verification manuelle requise, aucune extrapolation."
)
MSG_FRAIS_PAIEMENT = (
    "Frais de paiement NON VERIFIES : les valeurs sont des parametres fournis "
    "par l'appelant, a confirmer avec le prestataire de paiement."
)


def validate_quantity(quantite):
    """Valide la quantite. Retourne un dict {statut, verification_manuelle, message}.

    1 a 5 : ok. Plus de 5 : depasse_plafond + alerte verification manuelle.
    Tout autre valeur (<=0, non entier, bool) : quantite_invalide.
    """
    if isinstance(quantite, bool) or not isinstance(quantite, int):
        return {
            "statut": "quantite_invalide",
            "verification_manuelle": True,
            "message": "Quantite invalide : un entier entre 1 et "
                       "%d est attendu." % QTE_MAX_AUTOMATIQUE,
        }
    if quantite < 1:
        return {
            "statut": "quantite_invalide",
            "verification_manuelle": True,
            "message": "Quantite invalide : un entier entre 1 et "
                       "%d est attendu." % QTE_MAX_AUTOMATIQUE,
        }
    if quantite > QTE_MAX_AUTOMATIQUE:
        return {
            "statut": "depasse_plafond",
            "verification_manuelle": True,
            "message": MSG_QTE_SUPERIEURE,
        }
    return {"statut": "ok", "verification_manuelle": False, "message": ""}


def get_freight_quote(pays, quantite, table=None):
    """Retourne le tarif reel mesure {usd, canal, delai} ou None si indisponible.

    Aucune extrapolation : si la destination ou la quantite n'a pas de tarif
    reellement mesure dans la table, retourne None (verification manuelle).
    """
    table = REAL_FREIGHT if table is None else table
    if not isinstance(pays, str):
        return None
    pays = pays.strip().upper()
    dest = table.get(pays)
    if not dest:
        return None
    q = dest.get(quantite)
    if not q:
        return None
    return {
        "pays": pays,
        "region": REGIONS.get(pays, "destination_non_mesuree"),
        "usd": q["usd"],
        "canal": q["canal"],
        "delai": q["delai"],
        "date_mesure": DATE_MESURE_FRETS,
    }


def _parametres_invalides(marge_min, frais_paiement_taux, frais_paiement_fixe_eur,
                          exchange_rate):
    if not isinstance(marge_min, (int, float)) or isinstance(marge_min, bool):
        return True
    if not isinstance(frais_paiement_taux, (int, float)) or isinstance(frais_paiement_taux, bool):
        return True
    if not isinstance(frais_paiement_fixe_eur, (int, float)) or isinstance(frais_paiement_fixe_eur, bool):
        return True
    if not isinstance(exchange_rate, (int, float)) or isinstance(exchange_rate, bool):
        return True
    if exchange_rate <= 0:
        return True
    if marge_min <= 0 or marge_min >= 1:
        return True
    if frais_paiement_taux < 0 or frais_paiement_taux >= 1:
        return True
    if frais_paiement_fixe_eur < 0:
        return True
    if (1 - frais_paiement_taux - marge_min) <= 0:
        return True
    return False


def compute_pricing(cout_achat_usd, pays, quantite,
                    exchange_rate=EXCHANGE_RATE_USD_EUR,
                    frais_paiement_taux=0.0,
                    frais_paiement_fixe_eur=0.0,
                    marge_min=0.20):
    """Moteur de calcul commercial. Retourne un dict de resultat.

    Statuts possibles :
    - "recommandation_ok" : prix de vente recommande calcule ;
    - "depasse_plafond" : quantite > 5, verification manuelle, aucun prix ;
    - "tarif_indisponible" : destination/quantite sans tarif reel mesure,
      verification manuelle, aucun prix (aucune extrapolation) ;
    - "quantite_invalide" : quantite absurde ;
    - "cout_invalide" : cout d'achat <= 0 ;
    - "parametres_invalides" : marge/taux de frais/taux de change incoherents.

    Livraison gratuite : le fret est INTEGRE au prix de vente recommande
    (fret facture au client = 0.00) mais reste un cout reel pour SHOPLINOUS.
    """
    base = {
        "produit": {
            "cout_achat_usd": cout_achat_usd,
            "pid_cj": PRODUCT_PID_CJ,
            "vid_cj": PRODUCT_VID_CJ,
        },
        "destination": pays,
        "quantite": quantite,
        "exchange_rate": exchange_rate,
        "exchange_rate_date": EXCHANGE_RATE_DATE,
        "frais_paiement_taux": frais_paiement_taux,
        "frais_paiement_fixe_eur": frais_paiement_fixe_eur,
        "marge_min": marge_min,
        "verification_manuelle": False,
        "message": "",
    }

    if _parametres_invalides(marge_min, frais_paiement_taux,
                             frais_paiement_fixe_eur, exchange_rate):
        base["statut"] = "parametres_invalides"
        base["verification_manuelle"] = True
        base["message"] = (
            "Parametres invalides : marge_min dans ]0,1[, frais_paiement_taux "
            "dans [0,1[, frais_paiement_fixe_eur >= 0, exchange_rate > 0 et "
            "frais_paiement_taux + marge_min < 1 sont attendus."
        )
        return base

    if not isinstance(cout_achat_usd, (int, float)) or isinstance(cout_achat_usd, bool) \
            or cout_achat_usd <= 0:
        base["statut"] = "cout_invalide"
        base["verification_manuelle"] = True
        base["message"] = "Cout d'achat invalide : une valeur strictement positive est attendue."
        return base

    vq = validate_quantity(quantite)
    if vq["statut"] != "ok":
        base["statut"] = vq["statut"]
        base["verification_manuelle"] = True
        base["message"] = vq["message"]
        return base

    quote = get_freight_quote(pays, quantite)
    if quote is None:
        base["statut"] = "tarif_indisponible"
        base["verification_manuelle"] = True
        base["message"] = MSG_TARIF_INDISPONIBLE
        return base

    # --- Calcul commercial (livraison gratuite integree au prix) ---
    cout_produit_eur = round(cout_achat_usd * exchange_rate, 2)
    fret_eur = round(quote["usd"] * exchange_rate, 2)
    denominateur = 1 - frais_paiement_taux - marge_min
    prix_vente = round(
        (cout_produit_eur + fret_eur + frais_paiement_fixe_eur) / denominateur, 2
    )
    frais_paiement_eur = round(prix_vente * frais_paiement_taux
                               + frais_paiement_fixe_eur, 2)
    cout_total_eur = round(cout_produit_eur + fret_eur + frais_paiement_eur, 2)
    benefice_estime_eur = round(prix_vente - cout_total_eur, 2)
    marge_pourcentage = round(benefice_estime_eur / prix_vente * 100, 2)

    # Verification defensive de la marge (tolerance d'arrondi 0.5 point).
    marge_verifiee = abs(marge_pourcentage - marge_min * 100) <= 0.5

    base.update({
        "statut": "recommandation_ok" if marge_verifiee else "incoherence_defensive",
        "region": quote["region"],
        "fret": {
            "usd": quote["usd"],
            "eur": fret_eur,
            "canal": quote["canal"],
            "delai": quote["delai"],
            "date_mesure": quote["date_mesure"],
        },
        "calcul": {
            "cout_produit_eur": cout_produit_eur,
            "frais_livraison_eur": fret_eur,
            "frais_paiement_eur": frais_paiement_eur,
            "cout_total_eur": cout_total_eur,
            "prix_vente_recommande_eur": prix_vente,
            "benefice_estime_eur": benefice_estime_eur,
            "marge_pourcentage": marge_pourcentage,
        },
        "livraison_gratuite": {
            "integree_au_prix": True,
            "fret_facture_au_client_eur": 0.00,
            "note": ("Livraison gratuite pour le client : le fret CJ reste un "
                     "cout reel pour SHOPLINOUS, integre dans le prix de vente."),
        },
        "avertissement_frais_paiement": MSG_FRAIS_PAIEMENT,
    })
    if not marge_verifiee:
        base["verification_manuelle"] = True
        base["message"] = "Incoherence defensive : marge calculee hors tolerance."
    return base


def build_pricing_table(marge_min=0.20, frais_paiement_taux=0.0,
                        frais_paiement_fixe_eur=0.0,
                        cout_achat_usd=PRODUCT_COST_USD):
    """Table complete par destination mesuree et quantite 1 a 5 (rapport)."""
    table = {}
    for pays in sorted(REAL_FREIGHT.keys()):
        rows = []
        for q in range(1, QTE_MAX_AUTOMATIQUE + 1):
            res = compute_pricing(
                cout_achat_usd, pays, q,
                frais_paiement_taux=frais_paiement_taux,
                frais_paiement_fixe_eur=frais_paiement_fixe_eur,
                marge_min=marge_min,
            )
            rows.append({
                "quantite": q,
                "statut": res["statut"],
                "fret_eur": res.get("fret", {}).get("eur"),
                "prix_vente_recommande_eur": res.get("calcul", {}).get(
                    "prix_vente_recommande_eur"),
                "marge_pourcentage": res.get("calcul", {}).get("marge_pourcentage"),
            })
        table[pays] = {"region": REGIONS.get(pays), "lignes": rows}
    return table

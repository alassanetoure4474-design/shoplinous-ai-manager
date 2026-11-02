"""Country & Region Manager : configuration independante par pays.

Chaque pays definit les 9 champs exiges : code ISO, langues, devise,
fuseau horaire, moyens de paiement, fournisseurs accessibles,
transporteurs, restrictions commerciales/fiscales, frais et regles
de livraison. La detection geographique est INDICATIVE : le client
peut toujours changer son pays (changer_pays).
"""
import copy

CHAMPS_REQUIS = ("code_iso", "langues", "devise", "fuseau",
                  "moyens_paiement", "fournisseurs", "transporteurs",
                  "restrictions", "regles_livraison")

PAYS = {
    "CI": {"code_iso": "CI", "langues": ["fr"], "devise": "XOF",
           "fuseau": "Africa/Abidjan",
           "moyens_paiement": ["Wave", "Orange Money", "MTN", "Moov"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": ["taxe_importation_electronique"],
           "regles_livraison": {"delai_max_jours": 15, "frais_base_eur": 6.0}},
    "SN": {"code_iso": "SN", "langues": ["fr"], "devise": "XOF",
           "fuseau": "Africa/Dakar",
           "moyens_paiement": ["Wave", "Orange Money", "Free Money"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": [],
           "regles_livraison": {"delai_max_jours": 15, "frais_base_eur": 6.0}},
    "BJ": {"code_iso": "BJ", "langues": ["fr"], "devise": "XOF",
           "fuseau": "Africa/Porto-Novo",
           "moyens_paiement": ["MTN", "Moov", "Celtiis"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": [],
           "regles_livraison": {"delai_max_jours": 15, "frais_base_eur": 6.5}},
    "BF": {"code_iso": "BF", "langues": ["fr"], "devise": "XOF",
           "fuseau": "Africa/Ouagadougou",
           "moyens_paiement": ["Orange Money", "Moov"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": ["enclavement_delai_majore"],
           "regles_livraison": {"delai_max_jours": 20, "frais_base_eur": 7.0}},
    "ML": {"code_iso": "ML", "langues": ["fr"], "devise": "XOF",
           "fuseau": "Africa/Bamako",
           "moyens_paiement": ["Orange Money", "Moov"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": ["enclavement_delai_majore"],
           "regles_livraison": {"delai_max_jours": 20, "frais_base_eur": 7.0}},
    "TG": {"code_iso": "TG", "langues": ["fr"], "devise": "XOF",
           "fuseau": "Africa/Lome",
           "moyens_paiement": ["TMoney", "Moov"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": [],
           "regles_livraison": {"delai_max_jours": 15, "frais_base_eur": 6.5}},
    "CM": {"code_iso": "CM", "langues": ["fr", "en"], "devise": "XAF",
           "fuseau": "Africa/Douala",
           "moyens_paiement": ["MTN", "Orange Money"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": [],
           "regles_livraison": {"delai_max_jours": 18, "frais_base_eur": 7.0}},
    "MA": {"code_iso": "MA", "langues": ["fr", "ar"], "devise": "MAD",
           "fuseau": "Africa/Casablanca",
           "moyens_paiement": ["Visa", "Mastercard"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": ["douane_marocaine_certificat"],
           "regles_livraison": {"delai_max_jours": 15, "frais_base_eur": 6.0}},
    "NG": {"code_iso": "NG", "langues": ["en"], "devise": "NGN",
           "fuseau": "Africa/Lagos",
           "moyens_paiement": ["Visa", "Mastercard"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": ["interdiction_importation_certains_articles"],
           "regles_livraison": {"delai_max_jours": 18, "frais_base_eur": 7.5}},
    "GH": {"code_iso": "GH", "langues": ["en"], "devise": "GHS",
           "fuseau": "Africa/Accra",
           "moyens_paiement": ["Visa", "Mastercard"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": [],
           "regles_livraison": {"delai_max_jours": 15, "frais_base_eur": 6.5}},
    "KE": {"code_iso": "KE", "langues": ["en", "sw"], "devise": "KES",
           "fuseau": "Africa/Nairobi",
           "moyens_paiement": ["Visa", "Mastercard"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": [],
           "regles_livraison": {"delai_max_jours": 18, "frais_base_eur": 7.0}},
    "ZA": {"code_iso": "ZA", "langues": ["en"], "devise": "ZAR",
           "fuseau": "Africa/Johannesburg",
           "moyens_paiement": ["Visa", "Mastercard"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": [],
           "regles_livraison": {"delai_max_jours": 15, "frais_base_eur": 6.5}},
    "FR": {"code_iso": "FR", "langues": ["fr"], "devise": "EUR",
           "fuseau": "Europe/Paris",
           "moyens_paiement": ["Visa", "Mastercard", "PayPal"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": ["tva_20_pourcent"],
           "regles_livraison": {"delai_max_jours": 15, "frais_base_eur": 5.0}},
    "GB": {"code_iso": "GB", "langues": ["en"], "devise": "GBP",
           "fuseau": "Europe/London",
           "moyens_paiement": ["Visa", "Mastercard", "PayPal"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": ["tva_20_pourcent"],
           "regles_livraison": {"delai_max_jours": 15, "frais_base_eur": 5.5}},
    "US": {"code_iso": "US", "langues": ["en"], "devise": "USD",
           "fuseau": "America/New_York",
           "moyens_paiement": ["Visa", "Mastercard", "PayPal"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": [],
           "regles_livraison": {"delai_max_jours": 15, "frais_base_eur": 5.5}},
    "CA": {"code_iso": "CA", "langues": ["en", "fr"], "devise": "CAD",
           "fuseau": "America/Toronto",
           "moyens_paiement": ["Visa", "Mastercard", "PayPal"],
           "fournisseurs": ["cj"], "transporteurs": ["CJ"],
           "restrictions": ["taxes_provinciales"],
           "regles_livraison": {"delai_max_jours": 15, "frais_base_eur": 5.5}},
}


def pays(code):
    """Configuration COMPLETE du pays (copie defensive). Code inconnu ->
    ValueError : aucune configuration n est inventee."""
    if code not in PAYS:
        raise ValueError("pays non configure: " + repr(code))
    return copy.deepcopy(PAYS[code])


def codes_pays():
    return sorted(PAYS)


def coherence_config():
    """Verifie que chaque pays possede les 9 champs requis."""
    problemes = []
    for code, conf in PAYS.items():
        for champ in CHAMPS_REQUIS:
            if champ not in conf:
                problemes.append(code + ":" + champ)
    return problemes


def suggest_country(indice_geo):
    """Detection geographique INDICATIVE (en-tete client, IP approx.).
    Retourne un simple indice ; le choix final appartient au client."""
    if isinstance(indice_geo, str) and indice_geo.strip().upper() in PAYS:
        return {"indicatif": indice_geo.strip().upper(),
                "nature": "indicative", "modifiable": True}
    return {"indicatif": None, "nature": "indicative",
            "modifiable": True}


def changer_pays(commande, nouveau_code):
    """Le client peut TOUJOURS changer son pays. Le pays initialement
    detecte est conserve pour audit, jamais impose."""
    conf = pays(nouveau_code)
    commande["pays"] = nouveau_code
    commande["devise"] = conf["devise"]
    commande["pays_detecte_initial"] = commande.get(
        "pays_detecte_initial", nouveau_code)
    return commande

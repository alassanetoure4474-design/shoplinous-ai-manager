"""Regroupements opérationnels et catalogue mondial.

MARCHES ne contient que les profils opérationnels déjà configurés. Le catalogue
ISO mondial est exposé séparément et ne transforme jamais un pays non vérifié
en destination commerciale.
"""
from shoplinous_global import country_manager


MARCHES = {
    "afrique_ouest": {"libelle": "Afrique de l'Ouest",
                      "pays": ["CI", "SN", "BJ", "BF", "ML", "TG", "GH", "NG"]},
    "afrique_centrale": {"libelle": "Afrique centrale", "pays": ["CM"]},
    "afrique_nord": {"libelle": "Afrique du Nord", "pays": ["MA"]},
    "afrique_autres": {"libelle": "Autres marches africains", "pays": ["KE", "ZA"]},
    "europe": {"libelle": "Europe", "pays": ["FR", "GB"]},
    "amerique_nord": {"libelle": "Amérique du Nord", "pays": ["US", "CA"]},
    "amerique_latine": {"libelle": "Amérique latine", "pays": []},
    "asie": {"libelle": "Asie", "pays": []},
    "oceanie": {"libelle": "Océanie", "pays": []},
}


def marches():
    return sorted(MARCHES)


def pays_du_marche(marche):
    if marche not in MARCHES:
        raise ValueError("marche inconnu: " + repr(marche))
    return list(MARCHES[marche]["pays"])


def marche_du_pays(code):
    for name, config in MARCHES.items():
        if code in config["pays"]:
            return name
    raise ValueError("pays hors marches configures: " + repr(code))


def coherence():
    appartenances = {}
    for code in country_manager.codes_pays():
        try:
            appartenances[code] = marche_du_pays(code)
        except ValueError:
            appartenances[code] = None
    seen = []
    duplicates = []
    for name, config in MARCHES.items():
        for code in config["pays"]:
            if code in seen:
                duplicates.append(code)
            seen.append(code)
    return {
        "pays_sans_marche": [code for code, market in appartenances.items()
                             if market is None],
        "pays_doubles": duplicates,
    }


def restriction_active(code_pays, sujet):
    config = country_manager.pays(code_pays)
    return sujet in config["restrictions"]


def catalogue_mondial(region=None, inclure_fermes=True):
    """Retourne le référentiel ISO complet avec statut commercial explicite."""
    from intl import list_countries
    return list_countries(region=region, include_closed=inclure_fermes)

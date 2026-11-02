"""Global Market Manager : regroupements de marches mondiaux.

Neuf marches couvrant Afrique de l'Ouest, centrale, du Nord, autres
marches africains, Europe, Amerique du Nord, Amerique latine, Asie,
Oceanie. Chaque marche liste ses pays configures ; un pays appartient
a exactement un marche.
"""
import country_manager

MARCHES = {
    "afrique_ouest": {"libelle": "Afrique de l'Ouest",
                      "pays": ["CI", "SN", "BJ", "BF", "ML", "TG", "GH", "NG"]},
    "afrique_centrale": {"libelle": "Afrique centrale", "pays": ["CM"]},
    "afrique_nord": {"libelle": "Afrique du Nord", "pays": ["MA"]},
    "afrique_autres": {"libelle": "Autres marches africains", "pays": ["KE", "ZA"]},
    "europe": {"libelle": "Europe", "pays": ["FR", "GB"]},
    "amerique_nord": {"libelle": "Amerique du Nord", "pays": ["US", "CA"]},
    "amerique_latine": {"libelle": "Amerique latine", "pays": []},
    "asie": {"libelle": "Asie", "pays": []},
    "oceanie": {"libelle": "Oceanie", "pays": []},
}


def marches():
    return sorted(MARCHES)


def pays_du_marche(marche):
    if marche not in MARCHES:
        raise ValueError("marche inconnu: " + repr(marche))
    return list(MARCHES[marche]["pays"])


def marche_du_pays(code):
    for nom, conf in MARCHES.items():
        if code in conf["pays"]:
            return nom
    raise ValueError("pays hors marches configures: " + repr(code))


def coherence():
    """Chaque pays configure appartient a exactement un marche."""
    appartenances = {}
    for code in country_manager.codes_pays():
        try:
            appartenances[code] = marche_du_pays(code)
        except ValueError:
            appartenances[code] = None
    doubles = [c for c in appartenances
               if list(appartenances.values()).count(appartenances[c]) > 1
               and appartenances[c] is not None]
    # un pays liste dans deux marches apparaitrait deux fois
    vus = []
    dup = []
    for nom, conf in MARCHES.items():
        for p in conf["pays"]:
            if p in vus:
                dup.append(p)
            vus.append(p)
    return {"pays_sans_marche": [c for c, m in appartenances.items()
                                 if m is None], "pays_doubles": dup}


def restriction_active(code_pays, sujet):
    """True si le sujet est restreint dans le pays (fiscal/douane)."""
    conf = country_manager.pays(code_pays)
    return sujet in conf["restrictions"]

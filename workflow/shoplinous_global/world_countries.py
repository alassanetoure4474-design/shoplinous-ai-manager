"""Referentiel mondial des pays (ISO 3166-1) a 5 statuts distincts.

Les cinq statuts ne sont JAMAIS confondus :
  1. REPERTORIE          : present au referentiel ISO 3166-1 ;
  2. SUPPORT_TECHNIQUE   : devise exploitable (ISO 4217) + formats locaux ;
  3. LIVRAISON_VERIFIEE  : livraison CJ verifiee pays par pays, avec date ;
  4. PAIEMENT_VERIFIE    : moyen de paiement teste avec succes, avec date ;
  5. OUVERT_COMMANDE     : intersection des 4 preuces ci-dessus.

REGLE ABSOLUE : un pays repertorie mais non verifie reste FERME a la
commande ; il apparait quand meme dans le selecteur mondial avec un
statut explicite et la raison de sa fermeture.
"""
from dataclasses import dataclass

from shoplinous_global import world_countries_data_1 as _p1
from shoplinous_global import world_countries_data_2 as _p2
from shoplinous_global import world_countries_data_3 as _p3
from shoplinous_global import world_countries_data_4 as _p4
from shoplinous_global import world_currencies

# Livraison CJ verifiee le 01/11/2026 : UE27 + GB/CH/NO, sauf Malte
LIVRAISON_VERIFIEE = frozenset([
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
    "GR", "HU", "IE", "IT", "LV", "LT", "LU", "NL", "PL", "PT", "RO",
    "SK", "SI", "ES", "SE", "GB", "CH", "NO",
])

# Paiements verifies : uniquement la France (checkout Freewebstore +
# webhook signe GeniusPay Sandbox, 02-03/11/2026). Tout ajout exige
# une preuve horodatee, jamais une supposition.
PAIEMENT_VERIFIE = frozenset(["FR"])

# Statut fiscal configure (TVA/registration) : France uniquement.
TAXES_CONFIGUREES = frozenset(["FR"])

DATE_VERIFICATION = "2026-11-01"

EVIDENCES = {
    "FR": {
        "livraison": "options CJ <=6 EUR et <=15 j verifiees le 01/11/2026",
        "paiement": "checkout Freewebstore + webhook GeniusPay sandbox le 02/11/2026",
        "taxes": "TVA FR active dans Freewebstore (vat.country=FR)",
    },
}


@dataclass(frozen=True)
class Pays:
    code: str
    iso3: str
    nom_fr: str
    nom_en: str
    indicatif: str
    devises: tuple
    langues: tuple
    region: str

    @property
    def devise_principale(self) -> str:
        return self.devises[0] if self.devises else ""


def _charger():
    table = {}
    for module, champ in ((_p1, "LIGNES_A_F"), (_p2, "LIGNES_G_L"),
                          (_p3, "LIGNES_M_R"), (_p4, "LIGNES_S_Z")):
        brut = getattr(module, champ).strip("\n")
        for ligne in brut.split("\n"):
            ligne = ligne.strip()
            if not ligne:
                continue
            f = ligne.split("|")
            if len(f) != 8:
                raise ValueError("ligne referentiel invalide : " + repr(ligne))
            code = f[0]
            if code in table:
                raise ValueError("code duplique : " + code)
            devises = tuple(d for d in f[5].split(",") if d)
            table[code] = Pays(
                code=code, iso3=f[1], nom_fr=f[2], nom_en=f[3],
                indicatif=f[4], devises=devises,
                langues=tuple(x for x in f[6].split(",") if x),
                region=f[7])
    return table


PAYS = _charger()


def pays(code: str) -> Pays:
    p = PAYS.get(code)
    if p is None:
        raise KeyError("pays non repertorie : " + repr(code))
    return p


def tous_codes():
    return sorted(PAYS)


def langues_boutique(code: str):
    """Langues de la boutique reellement disponibles dans le pays
    (fr/en/es/pt/ar) ; l anglais reste la langue de repli affichable."""
    p = pays(code)
    supportees = {"fr", "en", "es", "pt", "ar"}
    locales = tuple(l for l in p.langues if l in supportees)
    return locales or ("en",)


def formats_locaux(code: str) -> dict:
    """Formats de date, de prix et d adresse derives du pays et de la
    langue principale. Les conventions sont publiques et stables."""
    p = pays(code)
    langue = langues_boutique(code)[0]
    if langue == "en" and p.region == "AM_N":
        date_fmt = "%m/%d/%Y"
    else:
        date_fmt = "%d/%m/%Y"
    if code in ("US", "CA"):
        adresse = "{rue}\n{ville}, {province} {code_postal}\n{pays}"
    elif code == "JP":
        adresse = "{code_postal}\n{rue}, {ville}\n{pays}"
    elif code == "GB":
        adresse = "{rue}\n{ville}\n{code_postal}\n{pays}"
    else:
        adresse = "{rue}\n{code_postal} {ville}\n{pays}"
    return {
        "langue": langue,
        "date": date_fmt,
        "prix": "montant + code devise (exposant ISO 4217)",
        "adresse": adresse,
        "rtl": langue == "ar",
    }


def statut(code: str) -> dict:
    """Les 5 statuts, distincts et explicites, avec preuves et raisons."""
    p = pays(code)
    devise_ok = bool(p.devise_principale and
                     world_currencies.est_devise_valide(p.devise_principale))
    livraison = code in LIVRAISON_VERIFIEE
    paiement = code in PAIEMENT_VERIFIE
    taxes = code in TAXES_CONFIGUREES
    ouvert = bool(devise_ok and livraison and paiement and taxes)
    raisons = []
    if not devise_ok:
        raisons.append("devise_non_exploitable")
    if not livraison:
        raisons.append("livraison_non_verifiee")
    if not paiement:
        raisons.append("paiement_non_verifie")
    if not taxes:
        raisons.append("taxes_non_configurees")
    return {
        "code": code, "nom_fr": p.nom_fr, "nom_en": p.nom_en,
        "region": p.region, "indicatif": p.indicatif,
        "devise": p.devise_principale,
        "repertorie": True,
        "support_technique": devise_ok,
        "livraison_verifiee": livraison,
        "paiement_verifie": paiement,
        "taxes_configurees": taxes,
        "ouvert_commande": ouvert,
        "raisons_fermeture": raisons,
        "evidence": EVIDENCES.get(code),
    }


def ouvert_a_la_commande(code: str) -> bool:
    return statut(code)["ouvert_commande"]


def selecteur_mondial(langue: str = "fr") -> list:
    """Tous les pays repertories, avec statut EXPLICITE. Un pays ferme
    reste visible : le client sait pourquoi la commande y est bloquee."""
    out = []
    for code in tous_codes():
        s = statut(code)
        if langue == "en":
            nom = s["nom_en"]
        else:
            nom = s["nom_fr"]
        out.append({
            "code": code, "nom": nom,
            "devise": s["devise"],
            "ouvert_commande": s["ouvert_commande"],
            "raisons_fermeture": s["raisons_fermeture"],
        })
    return out


def stats() -> dict:
    ouverts = [c for c in PAYS if ouvert_a_la_commande(c)]
    livraisons = [c for c in PAYS if c in LIVRAISON_VERIFIEE]
    paiements = [c for c in PAYS if c in PAIEMENT_VERIFIE]
    return {
        "pays_repertories": len(PAYS),
        "livraison_verifiee": len(livraisons),
        "paiement_verifie": len(paiements),
        "ouverts_commande": len(ouverts),
        "ouverts": sorted(ouverts),
    }

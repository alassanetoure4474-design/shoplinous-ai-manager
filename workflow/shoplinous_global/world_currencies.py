"""Devises mondiales ISO 4217 : exposants, symboles, formatage, trace.

Exposants officiels ISO 4217 : la plupart des devises ont 2 decimales ;
les devises sans decimale (exposant 0) et a 3 decimales sont listees
explicitement. Aucun taux de change n est invente ici : toute
conversion exige un taux fourni avec sa SOURCE et sa DATE.

Protections anti-erreur d arrondi :
- calculs en Decimal (jamais en flottant) ;
- quantification unique a l exposant de la devise cible ;
- conservation de la devise de reference et du taux applique
  dans un historique rattachable a une commande.
"""
from decimal import Decimal, ROUND_HALF_UP

# Devises ISO 4217 sans decimale (exposant 0)
EXPOSANT_0 = {
    "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG",
    "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}

# Devises ISO 4217 a trois decimales (exposant 3)
EXPOSANT_3 = {"BHD", "IQD", "JOD", "KWD", "OMR", "TND"}


def exposant(devise: str) -> int:
    if not isinstance(devise, str) or len(devise) != 3 or devise != devise.upper():
        raise ValueError("code devise ISO 4217 invalide : " + repr(devise))
    if devise in EXPOSANT_0:
        return 0
    if devise in EXPOSANT_3:
        return 3
    return 2


def est_devise_valide(devise: str) -> bool:
    try:
        exposant(devise)
        return True
    except ValueError:
        return False


SYMBOLS = {
    "EUR": "EUR", "USD": "$", "GBP": "GBP", "XOF": "FCFA", "XAF": "FCFA",
    "XPF": "FCFP", "JPY": "JPY", "CNY": "CNY", "CAD": "CAD", "AUD": "AUD",
    "CHF": "CHF", "SEK": "kr", "DKK": "kr", "NOK": "kr", "ISK": "kr",
    "INR": "INR", "BRL": "R$", "MXN": "MXN", "ZAR": "R", "NGN": "NGN",
    "GHS": "GHS", "MAD": "MAD", "KES": "KES", "AED": "AED", "SAR": "SAR",
    "QAR": "QAR", "KWD": "KWD", "BHD": "BHD", "OMR": "OMR", "JOD": "JOD",
    "ILS": "ILS", "EGP": "EGP", "TND": "TND", "DZD": "DZD", "XCD": "XCD",
    "HTG": "G", "DOP": "DOP", "CUP": "CUP", "PAB": "B/.", "CRC": "CRC",
    "ARS": "ARS", "CLP": "CLP", "COP": "COP", "PEN": "PEN", "UYU": "UYU",
    "BOB": "BOB", "PYG": "PYG", "VES": "VES", "GTQ": "Q", "HNL": "L",
    "NIO": "NIO", "BZD": "BZD", "BBD": "BBD", "JMD": "JMD", "TTD": "TTD",
    "BSD": "B$", "KYD": "KYD", "BMD": "BMD", "CNY2": "CN",
}


def symbole(devise: str) -> str:
    if not est_devise_valide(devise):
        raise ValueError("devise inconnue : " + repr(devise))
    return SYMBOLS.get(devise, devise)


def arrondir(montant, devise: str) -> Decimal:
    """Arrondi commercial ROUND_HALF_UP a l exposant ISO 4217."""
    exp = exposant(devise)
    return Decimal(str(montant)).quantize(
        Decimal(1).scaleb(-exp), rounding=ROUND_HALF_UP)


def convertir_trace(montant, devise_source: str, devise_cible: str,
                    taux, source_taux: str, date_taux: str) -> dict:
    """Conversion DECIMALE avec trace complete (source + date du taux).

    Retourne un enregistrement d historique rattachable a une commande :
    montant source, taux, source, date, montant cible arrondi.
    Une conversion approximative n est JAMAIS un prix garanti : le prix
    de paiement reste dans la devise de reference de la commande.
    """
    if not source_taux or not date_taux:
        raise ValueError("source et date du taux obligatoires")
    t = Decimal(str(taux))
    if t <= 0:
        raise ValueError("taux non positif : " + repr(taux))
    source = Decimal(str(montant)) * t
    return {
        "montant_source": str(Decimal(str(montant))),
        "devise_source": devise_source,
        "taux": str(t),
        "source_taux": source_taux,
        "date_taux": date_taux,
        "devise_cible": devise_cible,
        "montant_converti": str(arrondir(source, devise_cible)),
        "prix_garanti": devise_source == devise_cible,
    }


def formater(montant, devise: str, langue: str = "fr") -> str:
    """Formate un montant selon la devise (exposant ISO) et la langue.

    Separateurs : espace (fr/en/eu) ; symbole place apres le montant,
    sauf USD/CAD/GBP en anglais (convention $x.xx).
    """
    m = arrondir(montant, devise)
    exp = exposant(devise)
    txt = format(m, "f")
    if exp == 0:
        parties = txt.split(".")[0]
    else:
        parties = txt
    entier, _, decimales = txt.partition(".")
    if exp > 0:
        # separateur de milliers espace
        signe = ""
        if entier.startswith("-"):
            signe, entier = "-", entier[1:]
        entier = "{:,}".format(int(entier)).replace(",", " ")
        corps = entier + "," + (decimales + "0" * exp)[:exp]
        texte = signe + corps
    else:
        signe = ""
        if entier.startswith("-"):
            signe, entier = "-", entier[1:]
        entier_fmt = "{:,}".format(int(entier)).replace(",", " ")
        texte = signe + entier_fmt
    s = symbole(devise)
    if langue == "en" and devise in ("USD", "CAD", "GBP"):
        return s + texte.replace(",", ".").lstrip()
    if langue == "en":
        return texte.replace(",", ",") + " " + s
    return texte + " " + s

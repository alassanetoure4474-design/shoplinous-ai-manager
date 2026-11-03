"""SHOPLINOUS — référentiel mondial ISO 3166/4217 et internationalisation.

Référentiel pays fourni par pycountry (ISO 3166-1), noms et devises
territoriales par Babel/CLDR. L'enregistrement d'un pays ne signifie jamais
qu'il est ouvert à la vente : les contrôles réels sont séparés.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite

import pycountry
from babel import Locale
from babel.numbers import (
    get_currency_name,
    get_currency_precision,
    get_currency_symbol,
    get_territory_currencies,
)


@dataclass
class Country:
    code: str
    name_fr: str
    region: str
    registered: bool = True
    shippable: bool = False
    payment_available: bool = False
    taxes_configured: bool = False
    alpha3: str = ""
    numeric: str = ""
    name_en: str = ""
    currencies: tuple = ()

    @property
    def currency(self):
        """Devise unique seulement si le territoire en possède une seule."""
        return self.currencies[0] if len(self.currencies) == 1 else None

    @property
    def open_for_sale(self) -> bool:
        return bool(
            self.registered
            and self.shippable
            and self.payment_available
            and self.taxes_configured
        )


# ISO 3166-1 : ensembles géographiques stables, avec territoires rattachés
# à leur région géographique. Ils servent uniquement au classement d'interface.
REGION_CODES = {
    "Afrique": set("""DZ AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ EG GQ ER SZ
ET GA GM GH GN GW KE LS LR LY MG MW ML MR MU MA MZ NA NE NG RE RW SH ST SN
SC SL SO ZA SS SD TZ TG TN UG EH ZM ZW""".split()),
    "Amériques": set("""AI AG AR AW BS BB BZ BM BQ BO BR CA KY CL CO CR CU CW DM
DO EC SV FK GF GL GD GP GT GY HT HN JM MQ MX MS NI PA PY PE PR BL KN LC MF
PM VC SX SR TT TC US UY VE VG VI""".split()),
    "Asie": set("""AF AM AZ BH BD BT BN KH CN CX CC IO GE HK IN ID IR IQ IL JP
JO KZ KW KG LA LB MO MY MV MN MM NP KP OM PK PS PH QA SA SG KR LK SY TW TJ
TH TL TR TM AE UZ VN YE""".split()),
    "Europe": set("""AX AL AD AT BY BE BA BG HR CY CZ DK EE FO FI FR DE GI GR GG
VA HU IS IE IM IT JE LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK
SI ES SJ SE CH UA GB""".split()),
    "Océanie": set("""AS AU CK FJ PF GU KI MH FM NR NC NZ NU NF MP PW PG PN WS
SB TK TO TV UM VU WF""".split()),
    "Antarctique": {"AQ", "BV", "GS", "HM", "TF"},
}
_REGION_BY_CODE = {
    code: region
    for region, codes in REGION_CODES.items()
    for code in codes
}


def _display_name(code: str, language: str) -> str:
    locale = Locale.parse(language)
    country = locale.territories.get(code)
    if country:
        return str(country)
    obj = pycountry.countries.get(alpha_2=code)
    return str(obj.name if obj else code)


# Construire les 249 codes pays/territoires à partir du paquet ISO validé.
COUNTRIES = {}
for _record in pycountry.countries:
    _code = _record.alpha_2
    if not _code:
        continue
    _currencies = tuple(get_territory_currencies(_code, tender=True))
    COUNTRIES[_code] = Country(
        code=_code,
        name_fr=_display_name(_code, "fr"),
        region=_REGION_BY_CODE.get(_code, "Autre"),
        registered=True,
        # Fermé par défaut ; seuls les marchés historiquement vérifiés sont ouverts.
        shippable=False,
        payment_available=False,
        taxes_configured=False,
        alpha3=getattr(_record, "alpha_3", ""),
        numeric=getattr(_record, "numeric", ""),
        name_en=_display_name(_code, "en"),
        currencies=_currencies,
    )

if len(COUNTRIES) != 249:
    raise RuntimeError(
        "Le référentiel ISO 3166-1 doit contenir 249 codes alpha-2 ; "
        f"obtenu : {len(COUNTRIES)}"
    )

UE27 = [
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
    "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
    "RO", "SK", "SI", "ES", "SE",
]
# Liste blanche historique conservée ; Malte reste fermée.
VERIFIED_MARKETS = sorted(set(UE27 + ["GB", "CH", "NO"]) - {"MT"})
for _code in VERIFIED_MARKETS:
    COUNTRIES[_code].shippable = True
    COUNTRIES[_code].payment_available = True
    COUNTRIES[_code].taxes_configured = True


def get_country(code: str) -> Country:
    normalized = str(code).strip().upper()
    country = COUNTRIES.get(normalized)
    if country is None:
        raise KeyError("Code pays ISO 3166-1 inconnu : " + normalized)
    return country


def list_countries(region: str = None) -> list:
    """Retourne tous les territoires ISO, sans présumer de leur ouverture."""
    values = sorted(COUNTRIES.values(), key=lambda item: item.name_fr.casefold())
    if region:
        values = [country for country in values if country.region == region]
    return [country_status(country.code) for country in values]


def country_currencies(code: str) -> list:
    """Codes ISO 4217 de monnaie ayant cours légal selon CLDR."""
    return list(get_country(code).currencies)


def country_status(code: str) -> dict:
    country = get_country(code)
    return {
        "code": country.code,
        "code_alpha3": country.alpha3,
        "code_numerique": country.numeric,
        "nom": country.name_fr,
        "name_en": country.name_en,
        "region": country.region,
        "devises": list(country.currencies),
        "devise_unique": country.currency,
        "enregistre": country.registered,
        "livrable": country.shippable,
        "paiement_disponible": country.payment_available,
        "taxes_configurees": country.taxes_configured,
        "ouvert_vente": country.open_for_sale,
    }


def register_country(code: str, name_fr: str = None, region: str = None, **flags) -> Country:
    """Met à jour les contrôles d'un territoire ISO existant ; fermé par défaut."""
    normalized = str(code).strip().upper()
    country = get_country(normalized)
    if name_fr:
        country.name_fr = name_fr
    if region:
        country.region = region
    country.registered = bool(flags.get("registered", country.registered))
    country.shippable = bool(flags.get("shippable", False))
    country.payment_available = bool(flags.get("payment_available", False))
    country.taxes_configured = bool(flags.get("taxes_configured", False))
    return country


# ISO 4217 : codes de monnaies courantes obtenus depuis les monnaies légales
# CLDR des territoires répertoriés, pas une liste de devises arbitraire.
CURRENCIES = {}
for _country in COUNTRIES.values():
    for _currency in _country.currencies:
        if _currency in CURRENCIES:
            continue
        CURRENCIES[_currency] = {
            "nom": get_currency_name(_currency, locale="fr"),
            "nom_en": get_currency_name(_currency, locale="en"),
            "symbole": get_currency_symbol(_currency, locale="fr") or _currency,
            "decimales": get_currency_precision(_currency),
        }


def register_currency(code: str, nom: str, symbole: str, decimales: int = 2) -> None:
    normalized = str(code).strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("Un code devise doit comporter 3 lettres ISO 4217.")
    if normalized in CURRENCIES:
        raise ValueError("Devise déjà présente : " + normalized)
    if not isinstance(decimales, int) or not 0 <= decimales <= 4:
        raise ValueError("Nombre de décimales invalide.")
    CURRENCIES[normalized] = {
        "nom": nom, "nom_en": nom, "symbole": symbole or normalized,
        "decimales": decimales,
    }


def convert(amount: float, source: str, cible: str, rates: dict) -> float:
    """Convertit avec des taux fournis dans une même unité de référence.

    rates[CODE] représente le nombre d'unités de la devise pour une unité
    de référence commune. Aucun taux n'est deviné ni récupéré implicitement.
    """
    source = str(source).upper()
    cible = str(cible).upper()
    if source not in CURRENCIES or cible not in CURRENCIES:
        raise ValueError("Devise inconnue")
    try:
        value = float(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("Montant invalide") from exc
    if not isfinite(value):
        raise ValueError("Montant non fini")
    if source == cible:
        return value
    if not isinstance(rates, dict) or source not in rates or cible not in rates:
        raise ValueError("Taux de change manquant pour " + source + "->" + cible)
    try:
        source_rate = float(rates[source])
        target_rate = float(rates[cible])
    except (TypeError, ValueError) as exc:
        raise ValueError("Taux de change invalide") from exc
    if (
        not isfinite(source_rate) or not isfinite(target_rate)
        or source_rate <= 0 or target_rate <= 0
    ):
        raise ValueError("Les taux de change doivent être finis et strictement positifs.")
    return value / source_rate * target_rate


def format_price(amount: float, currency: str, lang: str = "fr") -> str:
    currency = str(currency).upper()
    if currency not in CURRENCIES:
        raise ValueError("Devise inconnue : " + currency)
    try:
        value = Decimal(str(amount))
        if not value.is_finite():
            raise ValueError
        decimals = CURRENCIES[currency]["decimales"]
        quantum = Decimal(1).scaleb(-decimals)
        value = value.quantize(quantum, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Montant invalide") from exc
    txt = f"{value:,.{decimals}f}".replace(",", " ")
    return f"{txt} {CURRENCIES[currency]['symbole']}"


LANGUAGES = ["fr", "en", "es", "pt", "ar"]
TRANSLATIONS = {
    "fr": {
        "menu_accueil": "Accueil", "panier": "Panier", "checkout": "Paiement",
        "livraison": "Livraison", "retours": "Retours sous 14 jours",
        "ajouter": "Ajouter au panier",
    },
    "en": {
        "menu_accueil": "Home", "panier": "Cart", "checkout": "Checkout",
        "livraison": "Shipping", "retours": "14-day returns",
        "ajouter": "Add to cart",
    },
    "es": {
        "menu_accueil": "Inicio", "panier": "Carrito", "checkout": "Pago",
        "livraison": "Envío", "retours": "Devoluciones en 14 días",
        "ajouter": "Añadir al carrito",
    },
    "pt": {
        "menu_accueil": "Início", "panier": "Carrinho", "checkout": "Pagamento",
        "livraison": "Entrega", "retours": "Devoluções em 14 dias",
        "ajouter": "Adicionar ao carrinho",
    },
    "ar": {
        "menu_accueil": "الرئيسية", "panier": "سلة التسوق",
        "checkout": "إتمام الدفع", "livraison": "الشحن",
        "retours": "الإرجاع خلال 14 يومًا",
        "ajouter": "أضف إلى سلة التسوق",
    },
}


def is_rtl(lang: str) -> bool:
    return lang == "ar"


def t(key: str, lang: str) -> str:
    if lang not in TRANSLATIONS:
        raise ValueError("Langue non supportée : " + lang)
    if key not in TRANSLATIONS[lang]:
        raise KeyError("Traduction manquante : " + key)
    return TRANSLATIONS[lang][key]


def add_language(lang: str, entries: dict) -> None:
    if lang in TRANSLATIONS:
        raise ValueError("Langue déjà présente : " + lang)
    base = set(TRANSLATIONS["fr"].keys())
    if set(entries.keys()) != base:
        raise ValueError("Traductions incomplètes pour " + lang)
    TRANSLATIONS[lang] = dict(entries)

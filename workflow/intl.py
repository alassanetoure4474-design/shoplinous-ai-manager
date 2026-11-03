"""SHOPLINOUS — catalogue mondial ISO, devises, langues et statut commercial.
Le catalogue ISO est informatif : être répertorié ne signifie PAS être livrable,
payable ou ouvert à la vente. Les marchés historiques explicitement déclarés
vérifiés sont conservés ; tous les autres pays restent fermés par défaut.
Les conversions exigent des taux explicites fournis par une source horodatée.
"""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

import pycountry
from babel import Locale
from babel.core import get_global
from babel.numbers import (
    format_currency, get_currency_name, get_currency_precision,
    get_currency_symbol, get_territory_currencies,
)

try:
    import phonenumbers
except ImportError:
    phonenumbers = None


@dataclass
class Country:
    code: str
    name_fr: str
    region: str
    name_en: str = ""
    iso3: str = ""
    numeric: str = ""
    calling_code: str | None = None
    currency: str | None = None
    currencies: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    timezones: list[str] = field(default_factory=list)
    registered: bool = True
    shippable: bool = False
    payment_available: bool = False
    taxes_configured: bool = False

    @property
    def open_for_sale(self) -> bool:
        return bool(
            self.registered and self.shippable
            and self.payment_available and self.taxes_configured
        )


UE27 = [
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",
]
# Marchés existants déclarés ouverts avant l'extension mondiale.
# Ils ne sont pas propagés aux nouveaux pays ni aux autres produits.
VERIFIED_MARKETS = sorted(set(UE27 + ["GB", "CH", "NO"]) - {"MT"})


def _region_from_timezones(timezones: list[str]) -> str:
    if not timezones:
        return "Autres"
    prefix = timezones[0].split("/", 1)[0]
    return {
        "Africa": "Afrique", "Europe": "Europe",
        "Asia": "Asie", "America": "Amériques",
        "Australia": "Océanie", "Pacific": "Océanie",
        "Antarctica": "Antarctique",
    }.get(prefix, "Autres")


def _official_languages(code: str) -> list[str]:
    entries = get_global("territory_languages").get(code, {})
    official = [
        language for language, details in entries.items()
        if details.get("official_status") in ("official", "de_facto_official")
    ]
    return sorted(set(official)) if official else sorted(entries)[:8]


def _calling_code(code: str) -> str | None:
    if phonenumbers is None:
        return None
    value = phonenumbers.country_code_for_region(code)
    return "+" + str(value) if value else None


def _country_from_iso(item) -> Country:
    code = item.alpha_2
    zones = list(get_global("territory_zones").get(code, []))
    currencies = [
        value for value in get_territory_currencies(code, tender=True)
        if value != "XXX"
    ]
    legacy_market = code in VERIFIED_MARKETS
    localized_name = Locale.parse("fr").territories.get(code, item.name)
    return Country(
        code=code,
        name_fr=localized_name,
        name_en=item.name,
        region=_region_from_timezones(zones),
        iso3=getattr(item, "alpha_3", ""),
        numeric=getattr(item, "numeric", ""),
        calling_code=_calling_code(code),
        currency=currencies[0] if currencies else None,
        currencies=currencies,
        languages=_official_languages(code),
        timezones=zones,
        registered=True,
        shippable=legacy_market,
        payment_available=legacy_market,
        taxes_configured=legacy_market,
    )


# ISO 3166-1 : pays et territoires attribués, embarqués par pycountry.
# Aucun appel réseau n'est nécessaire au démarrage.
COUNTRIES: dict[str, Country] = {
    item.alpha_2: _country_from_iso(item) for item in pycountry.countries
}


def get_country(code: str) -> Country:
    normalized = code.strip().upper() if isinstance(code, str) else ""
    country = COUNTRIES.get(normalized)
    if country is None:
        raise KeyError("Pays ISO non enregistre : " + normalized)
    return country


def country_status(code: str) -> dict:
    country = get_country(code)
    return {
        "code": country.code,
        "iso3": country.iso3,
        "numeric": country.numeric,
        "nom": country.name_fr,
        "name_en": country.name_en,
        "region": country.region,
        "indicatif": country.calling_code,
        "langues": list(country.languages),
        "fuseaux": list(country.timezones),
        "devise": country.currency,
        "devises": list(country.currencies),
        "enregistre": country.registered,
        "livrable": country.shippable,
        "paiement_disponible": country.payment_available,
        "taxes_configurees": country.taxes_configured,
        "ouvert_vente": country.open_for_sale,
    }


def list_countries(region: str | None = None, include_closed: bool = True) -> list[dict]:
    """Catalogue du sélecteur mondial ; les statuts commerciaux restent explicites."""
    result = []
    for code in sorted(COUNTRIES):
        country = COUNTRIES[code]
        if region and country.region.casefold() != region.casefold():
            continue
        if not include_closed and not country.open_for_sale:
            continue
        result.append(country_status(code))
    return result


def set_country_verification(
    code: str, *, shippable: bool | None = None,
    payment_available: bool | None = None,
    taxes_configured: bool | None = None,
) -> Country:
    """Met à jour uniquement les validations explicitement fournies."""
    country = get_country(code)
    for key, value in (
        ("shippable", shippable),
        ("payment_available", payment_available),
        ("taxes_configured", taxes_configured),
    ):
        if value is not None:
            if not isinstance(value, bool):
                raise TypeError(key + " doit être un booléen")
            setattr(country, key, value)
    return country


def register_country(code: str, name_fr: str, region: str, **flags) -> Country:
    """Ajoute une entrée manuelle, fermée par défaut si elle n'est pas ISO."""
    normalized = code.strip().upper()
    existing = COUNTRIES.get(normalized)
    if existing is not None:
        existing.name_fr = name_fr
        existing.region = region
        for key in ("registered", "shippable", "payment_available", "taxes_configured"):
            if key in flags:
                setattr(existing, key, bool(flags[key]))
        return existing
    country = Country(
        code=normalized, name_fr=name_fr, region=region,
        registered=bool(flags.get("registered", True)),
        shippable=bool(flags.get("shippable", False)),
        payment_available=bool(flags.get("payment_available", False)),
        taxes_configured=bool(flags.get("taxes_configured", False)),
    )
    COUNTRIES[normalized] = country
    return country


# ISO 4217 : devises codifiées. Les codes historiques sont répertoriés,
# mais ne deviennent pas des moyens de paiement actifs automatiquement.
_ACTIVE_CURRENCY_CODES = {
    currency
    for item in pycountry.countries
    for currency in get_territory_currencies(item.alpha_2, tender=True)
}
CURRENCIES: dict[str, dict] = {}
for _item in pycountry.currencies:
    _code = getattr(_item, "alpha_3", None)
    if not _code or _code == "XXX":
        continue
    try:
        _digits = get_currency_precision(_code)
        _name_fr = get_currency_name(_code, locale="fr")
        _symbol = get_currency_symbol(_code, locale="fr")
    except Exception:
        _digits, _name_fr, _symbol = 2, _item.name, _code
    CURRENCIES[_code] = {
        "nom": _name_fr or _item.name,
        "symbole": _symbol or _code,
        "decimales": int(_digits),
        "actif": _code in _ACTIVE_CURRENCY_CODES,
        "iso4217": True,
    }


def register_currency(code: str, nom: str, symbole: str, decimales: int = 2) -> None:
    normalized = code.strip().upper()
    if normalized in CURRENCIES:
        raise ValueError("Devise deja presente : " + normalized)
    if not isinstance(decimales, int) or not 0 <= decimales <= 4:
        raise ValueError("Nombre de decimales invalide")
    CURRENCIES[normalized] = {
        "nom": nom, "symbole": symbole, "decimales": decimales,
        "actif": False, "iso4217": False,
    }


def convert(amount, source: str, cible: str, rates: dict) -> float:
    """Convertit avec des taux explicites exprimés par rapport à une base commune.

    Exemple : source EUR et taux EUR=1.0, USD=1.08 signifie 1 EUR = 1.08 USD.
    Aucun taux n'est téléchargé, extrapolé ou inventé par cette fonction.
    """
    if source not in CURRENCIES or cible not in CURRENCIES:
        raise ValueError("Devise inconnue")
    if source == cible:
        return float(amount)
    if not isinstance(rates, dict) or source not in rates or cible not in rates:
        raise ValueError("Taux de change manquant pour " + source + "->" + cible)
    try:
        source_rate = Decimal(str(rates[source]))
        target_rate = Decimal(str(rates[cible]))
        value = Decimal(str(amount))
    except Exception as exc:
        raise ValueError("Taux ou montant invalide") from exc
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("Les taux doivent être positifs")
    result = value / source_rate * target_rate
    digits = CURRENCIES[cible]["decimales"]
    quantum = Decimal(1).scaleb(-digits)
    return float(result.quantize(quantum, rounding=ROUND_HALF_UP))


_LANGUAGE_LOCALES = {
    "fr": "fr_FR", "en": "en_US", "es": "es_ES",
    "pt": "pt_BR", "ar": "ar",
}
LANGUAGES = list(_LANGUAGE_LOCALES)

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
        "menu_accueil": "Início", "panier": "Carrinho",
        "checkout": "Finalizar compra", "livraison": "Entrega",
        "retours": "Devoluções em 14 dias",
        "ajouter": "Adicionar ao carrinho",
    },
    "ar": {
        "menu_accueil": "الرئيسية", "panier": "سلة التسوق",
        "checkout": "إتمام الشراء", "livraison": "الشحن",
        "retours": "إرجاع خلال 14 يومًا",
        "ajouter": "أضف إلى السلة",
    },
}


def t(key: str, lang: str) -> str:
    if lang not in TRANSLATIONS:
        raise ValueError("Langue non supportee : " + lang)
    if key not in TRANSLATIONS[lang]:
        raise KeyError("Traduction manquante : " + key)
    return TRANSLATIONS[lang][key]


def add_language(lang: str, entries: dict) -> None:
    if lang in TRANSLATIONS:
        raise ValueError("Langue deja presente : " + lang)
    base = set(TRANSLATIONS["fr"].keys())
    if set(entries.keys()) != base:
        raise ValueError("Traductions incompletes pour " + lang)
    TRANSLATIONS[lang] = entries
    if lang not in LANGUAGES:
        LANGUAGES.append(lang)


def is_rtl(lang: str) -> bool:
    return lang.split("-", 1)[0].lower() in {"ar", "fa", "he", "ur"}


def text_direction(lang: str) -> str:
    return "rtl" if is_rtl(lang) else "ltr"


def format_price(amount, currency: str, lang: str = "fr") -> str:
    if currency not in CURRENCIES:
        raise ValueError("Devise inconnue : " + currency)
    locale = _LANGUAGE_LOCALES.get(lang)
    if locale is None:
        raise ValueError("Langue non supportee pour le formatage : " + lang)
    return format_currency(
        Decimal(str(amount)), currency, locale=locale,
        currency_digits=True, decimal_quantization=True,
    )

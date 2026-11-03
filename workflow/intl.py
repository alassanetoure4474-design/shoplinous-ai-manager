"""SHOPLINOUS — référentiels internationaux, devises et langues.

Le référentiel ISO est embarqué en local. Être répertorié ne signifie jamais
qu'un marché est ouvert : livraison, paiement et fiscalité sont validés
séparément. Aucun taux de change n'est inventé.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite

from iso_countries_data import DATA


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


COUNTRY_FIELDS = DATA["country_fields"]
COUNTRY_RECORDS = {
    row[0]: dict(zip(COUNTRY_FIELDS, row))
    for row in DATA["countries"]
}
if len(COUNTRY_RECORDS) != 249:
    raise RuntimeError("Le référentiel ISO 3166-1 doit contenir 249 codes alpha-2.")

UE27 = [
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
    "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
    "RO", "SK", "SI", "ES", "SE",
]
# Liste blanche conservée : uniquement les marchés historiquement vérifiés.
VERIFIED_MARKETS = sorted(set(UE27 + ["GB", "CH", "NO"]) - {"MT"})

NAMES_FR = {code: record["name_fr"] for code, record in COUNTRY_RECORDS.items()}
REGIONS = {code: record["region"] for code, record in COUNTRY_RECORDS.items()}
for _code in UE27:
    REGIONS[_code] = "Europe"
for _code, _region in {
    "BM": "Amériques", "BV": "Antarctique", "CV": "Afrique",
    "FK": "Amériques", "FO": "Europe", "GS": "Antarctique",
    "HM": "Océanie", "IS": "Europe", "KM": "Afrique",
    "MG": "Afrique", "MU": "Afrique", "SC": "Afrique",
    "IO": "Asie", "CC": "Asie", "CX": "Asie",
}.items():
    if _code in REGIONS:
        REGIONS[_code] = _region

COUNTRIES = {}
for _code, _record in COUNTRY_RECORDS.items():
    _verified = _code in VERIFIED_MARKETS
    COUNTRIES[_code] = Country(
        code=_code,
        name_fr=_record["name_fr"],
        region=REGIONS.get(_code, "Autre"),
        registered=True,
        shippable=_verified,
        payment_available=_verified,
        taxes_configured=_verified,
        alpha3=_record["alpha3"],
        numeric=_record["numeric"],
        name_en=_record["name_en"],
        currencies=tuple(_record["currencies"]),
    )


def get_country(code: str) -> Country:
    normalized = str(code).strip().upper()
    country = COUNTRIES.get(normalized)
    if country is None:
        raise KeyError("Code pays ISO 3166-1 inconnu : " + normalized)
    return country


def list_countries(region: str = None) -> list:
    """Retourne les 249 territoires ISO, sans présumer de leur ouverture."""
    values = sorted(COUNTRIES.values(), key=lambda item: item.name_fr.casefold())
    if region:
        values = [country for country in values if country.region == region]
    return [country_status(country.code) for country in values]


def country_currencies(code: str) -> list:
    """Devises ayant cours légal selon le snapshot CLDR de ce territoire."""
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
    """Met à jour les contrôles d'un pays ISO existant ; fermé par défaut."""
    normalized = str(code).strip().upper()
    if normalized not in COUNTRY_RECORDS:
        raise KeyError("Code pays ISO 3166-1 inconnu : " + normalized)
    country = COUNTRIES[normalized]
    if name_fr:
        country.name_fr = name_fr
    if region:
        country.region = region
    country.registered = bool(flags.get("registered", country.registered))
    country.shippable = bool(flags.get("shippable", False))
    country.payment_available = bool(flags.get("payment_available", False))
    country.taxes_configured = bool(flags.get("taxes_configured", False))
    return country


# ISO 4217 : codes de devises actuellement associés à au moins un territoire
# comme monnaie ayant cours légal dans le snapshot CLDR du 03/11/2026.
CURRENCY_FIELDS = DATA["currency_fields"]
_ALL_CURRENCY_META = {
    row[0]: dict(zip(CURRENCY_FIELDS, row))
    for row in DATA["currencies"]
}
_ACTIVE_TENDER_CODES = {
    currency
    for record in COUNTRY_RECORDS.values()
    for currency in record["currencies"]
}
CURRENCIES = {
    code: {
        "nom": meta["name_fr"],
        "nom_en": meta["name_en"],
        "symbole": meta["symbol"] or code,
        "decimales": meta["decimals"],
    }
    for code, meta in _ALL_CURRENCY_META.items()
    if code in _ACTIVE_TENDER_CODES
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
    """Convertit via des taux fournis, jamais via un taux inventé.

    Convention : rates[CODE] représente le nombre d'unités de cette devise
    pour une unité de référence commune.
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
    if not isfinite(source_rate) or not isfinite(target_rate) or source_rate <= 0 or target_rate <= 0:
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


# --- Langues : les traductions marquées disponibles sont réellement remplies.
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

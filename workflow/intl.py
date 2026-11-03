"""SHOPLINOUS — Internationalisation : pays, devises, langues.
Aucun pays n'est declare ouvert a la vente sans verification reelle.
Aucun taux de change n'est invente : toute conversion exige un taux fourni."""

from dataclasses import dataclass, field


@dataclass
class Country:
    code: str
    name_fr: str
    region: str
    registered: bool = True
    shippable: bool = False
    payment_available: bool = False
    taxes_configured: bool = False

    @property
    def open_for_sale(self) -> bool:
        """Ouvert a la vente uniquement si toutes les verifications sont faites."""
        return self.registered and self.shippable and self.payment_available and self.taxes_configured


UE27 = ["AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IT",
        "LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE"]
# Marches verifies le 01/11/2026 : UE27 + GB/CH/NO, sauf Malte
VERIFIED_MARKETS = sorted(set(UE27 + ["GB","CH","NO"]) - {"MT"})

NAMES_FR = {
    "AT":"Autriche","BE":"Belgique","BG":"Bulgarie","HR":"Croatie","CY":"Chypre",
    "CZ":"Tchequie","DK":"Danemark","EE":"Estonie","FI":"Finlande","FR":"France",
    "DE":"Allemagne","GR":"Grece","HU":"Hongrie","IE":"Irlande","IT":"Italie",
    "LV":"Lettonie","LT":"Lituanie","LU":"Luxembourg","MT":"Malte","NL":"Pays-Bas",
    "PL":"Pologne","PT":"Portugal","RO":"Roumanie","SK":"Slovaquie","SI":"Slovenie",
    "ES":"Espagne","SE":"Suede","GB":"Royaume-Uni","CH":"Suisse","NO":"Norvege",
}
REGIONS = {c: "UE" for c in UE27}
REGIONS.update({"GB": "Europe", "CH": "Europe", "NO": "Europe"})

COUNTRIES = {}
for _c in set(UE27 + ["GB","CH","NO"]):
    _open = _c in VERIFIED_MARKETS
    COUNTRIES[_c] = Country(
        code=_c, name_fr=NAMES_FR.get(_c, _c), region=REGIONS.get(_c, "?"),
        registered=True, shippable=_open, payment_available=_open,
        taxes_configured=_open,
    )


def get_country(code: str) -> Country:
    c = COUNTRIES.get(code)
    if c is None:
        raise KeyError("Pays non enregistre : " + code)
    return c


def country_status(code: str) -> dict:
    c = get_country(code)
    return {
        "code": c.code, "nom": c.name_fr, "region": c.region,
        "enregistre": c.registered, "livrable": c.shippable,
        "paiement_disponible": c.payment_available,
        "taxes_configurees": c.taxes_configured,
        "ouvert_vente": c.open_for_sale,
    }


def register_country(code: str, name_fr: str, region: str, **flags) -> Country:
    """Ajoute un pays ; il reste ferme tant que chaque verification n'est pas faite."""
    c = Country(code=code, name_fr=name_fr, region=region,
                 registered=bool(flags.get("registered", True)),
                 shippable=bool(flags.get("shippable", False)),
                 payment_available=bool(flags.get("payment_available", False)),
                 taxes_configured=bool(flags.get("taxes_configured", False)))
    COUNTRIES[code] = c
    return c


# --- Devises (extensible) ---
CURRENCIES = {
    "EUR": {"nom": "Euro", "symbole": "EUR", "decimales": 2},
    "USD": {"nom": "Dollar americain", "symbole": "$", "decimales": 2},
    "XOF": {"nom": "Franc CFA (UEMOA)", "symbole": "FCFA", "decimales": 0},
    "XAF": {"nom": "Franc CFA (CEMAC)", "symbole": "FCFA", "decimales": 0},
    "GBP": {"nom": "Livre sterling", "symbole": "GBP", "decimales": 2},
    "CAD": {"nom": "Dollar canadien", "symbole": "CAD", "decimales": 2},
    "CNY": {"nom": "Yuan", "symbole": "CNY", "decimales": 2},
    "JPY": {"nom": "Yen", "symbole": "JPY", "decimales": 0},
    "NGN": {"nom": "Naira", "symbole": "NGN", "decimales": 2},
    "GHS": {"nom": "Cedi", "symbole": "GHS", "decimales": 2},
    "MAD": {"nom": "Dirham", "symbole": "MAD", "decimales": 2},
    "ZAR": {"nom": "Rand", "symbole": "ZAR", "decimales": 2},
    "KES": {"nom": "Shilling kenyen", "symbole": "KES", "decimales": 2},
}


def register_currency(code: str, nom: str, symbole: str, decimales: int = 2) -> None:
    if code in CURRENCIES:
        raise ValueError("Devise deja presente : " + code)
    CURRENCIES[code] = {"nom": nom, "symbole": symbole, "decimales": decimales}


def convert(amount: float, source: str, cible: str, rates: dict) -> float:
    """Convertit via des taux fournis (ex. BCE/Frankfurter). Ne invente jamais un taux."""
    if source not in CURRENCIES or cible not in CURRENCIES:
        raise ValueError("Devise inconnue")
    if source == cible:
        return amount
    if not rates or source not in rates or cible not in rates:
        raise ValueError("Taux de change manquant pour " + source + "->" + cible)
    return amount / rates[source] * rates[cible]


def format_price(amount: float, currency: str, lang: str = "fr") -> str:
    d = CURRENCIES[currency]["decimales"]
    txt = ("{:,.%df}" % d).format(amount).replace(",", " ")
    return txt + " " + CURRENCIES[currency]["symbole"]


# --- Langues (extensible) ---
LANGUAGES = ["fr", "en", "es", "pt", "ar"]

TRANSLATIONS = {
    "fr": {"menu_accueil": "Accueil", "panier": "Panier", "checkout": "Paiement",
           "livraison": "Livraison", "retours": "Retours 14 jours",
           "ajouter": "Ajouter au panier"},
    "en": {"menu_accueil": "Home", "panier": "Cart", "checkout": "Checkout",
           "livraison": "Shipping", "retours": "14-day returns",
           "ajouter": "Add to cart"},
    "es": {"menu_accueil": "Inicio", "panier": "Carrito", "checkout": "Pago",
           "livraison": "Envio", "retours": "Devoluciones 14 dias",
           "ajouter": "Anadir al carrito"},
    "pt": {"menu_accueil": "Inicio", "panier": "Carrinho", "checkout": "Pagamento",
           "livraison": "Entrega", "retours": "Devolucoes 14 dias",
           "ajouter": "Adicionar ao carrinho"},
    "ar": {"menu_accueil": "Home", "panier": "Cart", "checkout": "Checkout",
           "livraison": "Shipping", "retours": "Returns 14 days",
           "ajouter": "Add to cart"},
}


def t(key: str, lang: str) -> str:
    if lang not in TRANSLATIONS:
        raise ValueError("Langue non supportee : " + lang)
    return TRANSLATIONS[lang][key]


def add_language(lang: str, entries: dict) -> None:
    if lang in TRANSLATIONS:
        raise ValueError("Langue deja presente : " + lang)
    base = set(TRANSLATIONS["fr"].keys())
    if set(entries.keys()) != base:
        raise ValueError("Traductions incompletes pour " + lang)
    TRANSLATIONS[lang] = entries

"""SHOPLINOUS - Internationalisation mondiale v2.

Referentiel ISO 3166-1 complet (voir world_countries) : chaque pays
repond aux 5 statuts distincts. Aucun pays n est declare ouvert a la
vente sans preuve ; les marches non verifies restent visibles dans le
selecteur mondial avec la raison de leur fermeture.

Traductions : fr, en, es, pt, ar (arabe REEL, non une copie de
l anglais) + gestion RTL pour l arabe. Une langue n est declaree
disponible que si ses traductions sont completes.

Compatibilite ascendante : Country, get_country, country_status,
register_country, CURRENCIES, convert, format_price, t, add_language
conservent leurs signatures.
"""
from dataclasses import dataclass, field

from shoplinous_global import world_countries as _wc
from shoplinous_global import world_currencies as _cur


@dataclass
class Country:
    code: str
    name_fr: str
    region: str
    registered: bool = True
    shippable: bool = False
    payment_available: bool = False
    taxes_configured: bool = False
    name_en: str = ""
    indicatif: str = ""
    devise: str = ""
    langues: tuple = ()

    @property
    def open_for_sale(self) -> bool:
        """Ouvert a la vente uniquement si toutes les verifications
        sont faites : repertorie, devise exploitable, livraison
        verifiee, paiement verifie, taxes configurees."""
        return (self.registered and self.shippable
                and self.payment_available and self.taxes_configured)


UE27 = ["AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
        "GR", "HU", "IE", "IT", "LV", "LT", "LU", "NL", "PL", "PT", "RO",
        "SK", "SI", "ES", "SE"]
# Livraison verifiee le 01/11/2026 : UE27 + GB/CH/NO, sauf Malte.
VERIFIED_MARKETS = sorted(set(UE27 + ["GB", "CH", "NO"]) - {"MT"})
LIVRAISON_VERIFIEE = _wc.LIVRAISON_VERIFIEE
PAIEMENT_VERIFIE = _wc.PAIEMENT_VERIFIE
TAXES_CONFIGUREES = _wc.TAXES_CONFIGUREES


def _construire():
    table = {}
    for code in _wc.tous_codes():
        p = _wc.pays(code)
        table[code] = Country(
            code=code, name_fr=p.nom_fr, region=p.region,
            registered=True,
            shippable=code in LIVRAISON_VERIFIEE,
            payment_available=code in PAIEMENT_VERIFIE,
            taxes_configured=code in TAXES_CONFIGUREES,
            name_en=p.nom_en, indicatif=p.indicatif,
            devise=p.devise_principale, langues=p.langues)
    return table


COUNTRIES = _construire()
NAMES_FR = {c: p.name_fr for c, p in COUNTRIES.items()}
REGIONS = {c: p.region for c, p in COUNTRIES.items()}


def get_country(code: str) -> Country:
    c = COUNTRIES.get(code)
    if c is None:
        raise KeyError("Pays non enregistre : " + str(code))
    return c


def country_status(code: str) -> dict:
    s = _wc.statut(code)
    return {
        "code": s["code"], "nom": s["nom_fr"], "region": s["region"],
        "indicatif": s["indicatif"], "devise": s["devise"],
        "enregistre": s["repertorie"],
        "support_technique": s["support_technique"],
        "livrable": s["livraison_verifiee"],
        "paiement_disponible": s["paiement_verifie"],
        "taxes_configurees": s["taxes_configurees"],
        "ouvert_vente": s["ouvert_commande"],
        "raisons_fermeture": s["raisons_fermeture"],
    }


def register_country(code: str, name_fr: str, region: str, **flags) -> Country:
    """Ajoute un pays ; il reste ferme tant que chaque verification
    n est pas apportee (aucun flag n est suppose vrai par defaut)."""
    c = Country(code=code, name_fr=name_fr, region=region,
                registered=bool(flags.get("registered", True)),
                shippable=bool(flags.get("shippable", False)),
                payment_available=bool(flags.get("payment_available", False)),
                taxes_configured=bool(flags.get("taxes_configured", False)))
    COUNTRIES[code] = c
    return c


def selecteur_mondial(langue: str = "fr") -> list:
    return _wc.selecteur_mondial(langue)


# --- Devises : derivees du referentiel ISO 4217 (world_currencies) ---
CURRENCIES = {}
for _p in COUNTRIES.values():
    for _d in (_p.devise,):
        if _d and _d not in CURRENCIES:
            CURRENCIES[_d] = {
                "nom": _d,
                "symbole": _cur.symbole(_d),
                "decimales": _cur.exposant(_d),
            }


def register_currency(code: str, nom: str, symbole: str,
                      decimales: int = 2) -> None:
    if code in CURRENCIES:
        raise ValueError("Devise deja presente : " + code)
    CURRENCIES[code] = {"nom": nom, "symbole": symbole,
                        "decimales": decimales}


def convert(amount: float, source: str, cible: str, rates: dict) -> float:
    """Convertit via des taux fournis (source + date a conserver via
    world_currencies.convertir_trace). Aucun taux n est invente."""
    if source not in CURRENCIES or cible not in CURRENCIES:
        raise ValueError("Devise inconnue")
    if source == cible:
        return amount
    if not rates or source not in rates or cible not in rates:
        raise ValueError(
            "Taux de change manquant pour " + source + "->" + cible)
    return amount / rates[source] * rates[cible]


def format_price(amount: float, currency: str, lang: str = "fr") -> str:
    return _cur.formater(amount, currency, lang)


# --- Langues : traductions completes, arabe reel, RTL ---
LANGUAGES = ["fr", "en", "es", "pt", "ar"]
RTL = {"ar": True}

TRANSLATIONS = {
    "fr": {
        "menu_accueil": "Accueil", "panier": "Panier",
        "checkout": "Paiement", "livraison": "Livraison",
        "retours": "Retours 14 jours", "ajouter": "Ajouter au panier",
        "catalogue": "Catalogue", "compte_client": "Compte client",
        "notifications": "Notifications",
        "erreur_generique": "Une erreur est survenue, merci de reessayer.",
        "paiement_refuse": "Le paiement a ete refuse.",
        "commande_confirmee": "Votre commande est confirmee.",
        "delai_livraison_estime": "Delai de livraison estime :",
        "rupture_stock": "Rupture de stock",
        "recherche": "Rechercher", "suivi_commande": "Suivi de commande",
    },
    "en": {
        "menu_accueil": "Home", "panier": "Cart",
        "checkout": "Checkout", "livraison": "Shipping",
        "retours": "14-day returns", "ajouter": "Add to cart",
        "catalogue": "Catalog", "compte_client": "Customer account",
        "notifications": "Notifications",
        "erreur_generique": "An error occurred, please try again.",
        "paiement_refuse": "The payment was declined.",
        "commande_confirmee": "Your order is confirmed.",
        "delai_livraison_estime": "Estimated delivery time:",
        "rupture_stock": "Out of stock",
        "recherche": "Search", "suivi_commande": "Order tracking",
    },
    "es": {
        "menu_accueil": "Inicio", "panier": "Carrito",
        "checkout": "Pago", "livraison": "Envio",
        "retours": "Devoluciones 14 dias", "ajouter": "Anadir al carrito",
        "catalogue": "Catalogo", "compte_client": "Cuenta del cliente",
        "notifications": "Notificaciones",
        "erreur_generique": "Se produjo un error, intentalo de nuevo.",
        "paiement_refuse": "El pago fue rechazado.",
        "commande_confirmee": "Tu pedido esta confirmado.",
        "delai_livraison_estime": "Tiempo de envio estimado:",
        "rupture_stock": "Agotado",
        "recherche": "Buscar", "suivi_commande": "Seguimiento del pedido",
    },
    "pt": {
        "menu_accueil": "Inicio", "panier": "Carrinho",
        "checkout": "Pagamento", "livraison": "Entrega",
        "retours": "Devolucoes 14 dias", "ajouter": "Adicionar ao carrinho",
        "catalogue": "Catalogo", "compte_client": "Conta do cliente",
        "notifications": "Notificacoes",
        "erreur_generique": "Ocorreu um erro, tente novamente.",
        "paiement_refuse": "O pagamento foi recusado.",
        "commande_confirmee": "O seu pedido esta confirmado.",
        "delai_livraison_estime": "Prazo de entrega estimado:",
        "rupture_stock": "Esgotado",
        "recherche": "Pesquisar", "suivi_commande": "Acompanhamento do pedido",
    },
    "ar": {
        "menu_accueil": "الرئيسية", "panier": "السلة",
        "checkout": "إتمام الشراء", "livraison": "الشحن",
        "retours": "الإرجاع خلال 14 يومًا",
        "ajouter": "أضف إلى السلة",
        "catalogue": "دليل المنتجات",
        "compte_client": "حساب العميل",
        "notifications": "الإشعارات",
        "erreur_generique": "حدث خطأ، يرجى المحاولة مرة أخرى.",
        "paiement_refuse": "تم رفض عملية الدفع.",
        "commande_confirmee": "تم تأكيد طلبك.",
        "delai_livraison_estime": "مدة التوصيل المتوقعة:",
        "rupture_stock": "نفدت الكمية",
        "recherche": "بحث",
        "suivi_commande": "تتبع الطلب",
    },
}

_CLES_BASE = set(TRANSLATIONS["fr"].keys())


def t(key: str, lang: str) -> str:
    if lang not in TRANSLATIONS:
        raise ValueError("Langue non supportee : " + lang)
    return TRANSLATIONS[lang][key]


def rtl(lang: str) -> bool:
    return bool(RTL.get(lang))


def langues_disponibles() -> list:
    """Langues reellement disponibles : traductions COMPLETES uniquement."""
    return [l for l in LANGUAGES
            if l in TRANSLATIONS
            and set(TRANSLATIONS[l].keys()) == _CLES_BASE]


def add_language(lang: str, entries: dict) -> None:
    if lang in TRANSLATIONS:
        raise ValueError("Langue deja presente : " + lang)
    if set(entries.keys()) != _CLES_BASE:
        raise ValueError("Traductions incompletes pour " + lang)
    TRANSLATIONS[lang] = entries
    LANGUAGES.append(lang)

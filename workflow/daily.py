"""SHOPLINOUS - Workflow quotidien v5 (marche : UE27 + GB/CH/NO, Malte ecarte).

Corrections v5 (branche workflow-v5-review, 01/11/2026) :
A. cn_stock_of() CORRIGE : la reponse reelle du stock CJ montre
   stock[0].inventory = 0 alors que l'inventaire reel est dans
   storageNum / totalInventoryNum (mesure reelle : storageNum 11347,
   stock[0].inventory 0). Priorite corrigee : storageNum >
   totalInventoryNum > stock[0].inventory.
B. cj_freight() accepte la quantite REELLE (parametre quantity,
   plafond MAX_ORDER_QTY = 5, donnees fret CJ mesurees de 1 a 5 unites).
C. NOUVELLE activite process_order(order) : analyse de commande en
   LECTURE SEULE - recalcule le fret CJ avec la quantite reelle,
   verifie la couverture du tarif facture, alerte si ecart > 10 %.
   NE MODIFIE AUCUNE COMMANDE, NE CREE NI NE PAIE AUCUNE COMMANDE CJ.
D. v5.1 : process_order est APPELEE par le workflow pour CHAQUE commande
   recue (analyse reelle, lecture seule). Repartition multi-lignes
   securisee : par ligne si chaque ligne porte son tarif, sinon UNE SEULE
   comparaison au total commande (jamais de repartition inventee).
   Commandes > 5 unites : statut depasse_plafond, AUCUN appel CJ,
   verification manuelle obligatoire. AUCUNE creation, modification,
   paiement ni annulation de commande fournisseur, par construction.
E. v5.2 : compatibilite REELLE Freewebstore confirmee (GET /orders et
   GET /orders/abandoned, 01/11/2026) : en-tete x-api-key (doc
   officielle), URI /orders, pagination limit/offset, adaptateur
   fw_normalize_order (id, delivery_address.country_iso_2, postage,
   order_details[].quantity/productSKU). AUCUNE donnee personnelle
   copiee. Le vid CJ n'est pas transporte par Freewebstore : lignes en
   verification manuelle (sans_vid + SKU) jusqu'a correspondance.
F. v5.3 : TABLE SKU->vid (correspondance Freewebstore -> CJ) :
   fw_variant_records() collecte en LECTURE SEULE, pour CHAQUE produit
   FW, son productId, son productSKU et ses variantId (champ 'uvid'
   reel du detail produit) ; build_vid_table() consulte le produit CJ
   correspondant (recherche par SKU variante - methode confirmee en
   lecture seule le 02/11/2026 - puis variantes: vid, variantSku) et
   n'associe JAMAIS d'approximation : uniquement SKU EXACT et UNIVOQUE.
   Absent ou ambigu -> sans_vid CONSERVE + alerte manuelle. Amorce
   VID_TABLE_SEED verifiee (lecture seule, 02/11/2026). Aucune ecriture
   boutique ni CJ ; allow_publish=False inchange.

Regles de reference (base de connaissances SHOPLINOUS, 01/11/2026) :
1. Stock China Warehouse >= 1000 pour CHAQUE variante conservee
2. Prix fournisseur <= 8 EUR pour CHAQUE variante conservee
3. Livraison <= 6 EUR, delai min ET max <= 15 jours, verifies pour CHAQUE
   couple (variante, pays) ; seuls les delais reellement verifies sont
   annonces, par pays. NOTE v5 : le seuil de 6 EUR s'applique au fret
   UNITAIRE (1 unite de reference) ; les colis multi-unites sont
   couverts par les bandes de quantite au checkout (+1,00 EUR/unite).
4. >= 2 images reellement accessibles ET valides (GET + lecture du contenu,
   octets magiques + MIME), sources : champ productImage du detail produit
   CJ + images des variantes + bigImage
5. Anti-doublon : SKU ET similarite de nom sur le catalogue COMPLET pagine
6. Produits interdits (electronique risquee, contrefacons, reglementes)
7. Categories prioritaires : maison, decoration, rangement, cuisine, accessoires
8. Prix STRICTEMENT >= 3 x (cout variante + livraison pays) pour CHAQUE
   combinaison, arrondi au X,90
9. Stock affiche = min(100, stock CJ - 100) ; 0 si rupture

BENEFICE NET ESTIME (formule corrigee v4, conservee) :
    benefice = prix_produit                        # encaisse sur le produit
             + livraison_facturee_au_client        # RECETTE, jamais depense
             - cout_produit_CJ                     # depense fournisseur
             - livraison_reelle_CJ                 # depense transport
             - frais_paiement                      # % + fixe
             - autres_charges_connues              # ex: TVA collectee si applicable

Securite : allow_publish=False par defaut (mode veille : RIEN n'est cree
ni modifie) ; taux de change OBLIGATOIRE en direct (aucun repli) ; toute
reponse HTTP ou metier invalide bloque et signale ; QPS CJ respecte
(1 req/s, throttle 1,1 s) ; AUCUN achat fournisseur automatique.

STRUCTURES CONFIRMEES via appels reels au serveur MCP SHOPLINOUS (01/11/2026)
(ces formes de donnees sont observees ; l'authentification REST DIRECTE
reste NON TESTEE) :
- CJ search      -> data.content[0].productList[] (id, sku, nameEn, bigImage,
                   sellPrice, warehouseInventoryNum)
- CJ variantes  -> data[] (vid, variantSku, variantNameEn, variantSellPrice,
                   variantImage, variantKey)
- CJ stock vid  -> data[] : countryCode "CN", storageNum (INVENTAIRE REEL),
                   totalInventoryNum, stock[0].inventory (OBSERVE A 0 - bug v4)
- CJ fret       -> data[] (logisticName, logisticPrice USD, logisticAging "n-m")
                   ; le parametre quantity est accepte et le fret croit
                   d'environ +0,96 USD par unite supplementaire (mesure 1 a 5)
- CJ detail     -> productImage = chaine JSON = tableau d'URLs (7 observees)
ENDPOINTS REST DIRECTS : NON VALIDES (auth CJ-API-KEY et POST/PUT/GET
Freewebstore non prouves hors MCP) - toute erreur suspend le run.
"""
import os
import json
import math
import re
import time
import asyncio
from datetime import timedelta
from pydantic import BaseModel, ConfigDict

import httpx
import mistralai.workflows as workflows

# ---------------------------------------------------------------- regles ----
MIN_STOCK_CN = 1000
MAX_COST_EUR = 8.0
MAX_SHIP_EUR = 6.0
MAX_SHIP_DAYS = 15
MIN_IMAGES = 2
MARGIN_MULTIPLE = 3.0
MAX_PUBLISH_PER_RUN = 3
SAFETY_STOCK = 100
DISPLAY_STOCK_CAP = 100
MAX_ORDER_QTY = 5            # v5 : fret CJ mesure de 1 a 5 unites
FREIGHT_ALERT_TOLERANCE = 0.10   # v5 : alerte si tarif facture < fret reel -10%
PAYMENT_FEE_RATE = float(os.environ.get("PAYMENT_FEE_RATE", "0.029"))
PAYMENT_FEE_FIXED_EUR = float(os.environ.get("PAYMENT_FEE_FIXED_EUR", "0.30"))
CJ_BASE = os.environ.get("CJ_API_BASE", "https://developers.cjdropshipping.com/api2.0/v1")
FW_BASE = os.environ.get("FREEWEBSTORE_API_BASE", "https://api.freewebstore.com")
FW_PER_PAGE = 100
FW_ORDERS_PAGE = 50    # v5.2 : pagination GET /orders (limit/offset)

# v5.3 : AMORCE de table SKU -> vid, verifiee en LECTURE SEULE le
# 02/11/2026 (boutique storeid 1107499, produit Attrape-reves 18809643,
# produit CJ pid 1797521453303214080). Cette amorce est un filet de
# securite : build_vid_table() reconstruit la table COMPLETE depuis les
# donnees vivantes a chaque execution (lecture seule FW + CJ) ; les
# entrees reconstruites prevaleulent toujours sur l'amorce.
VID_TABLE_SEED = {
    "CJJT205244501AZ": {"vid": "1797521453382905856",
                        "fw_product_id": "18809643",
                        "fw_variant_id": "ZsKQFt",
                        "cj_pid": "1797521453303214080"},
    "CJJT205244502BY": {"vid": "1797521453454209024",
                        "fw_product_id": "18809643",
                        "fw_variant_id": "WPPmLB",
                        "cj_pid": "1797521453303214080"},
}
CJ_QPS_SECONDS = 1.1   # QPS CJ 1 req/s, confirme par erreur reelle 1600200
MIN_IMAGE_BYTES = 4096

# Formats reels autorises, verifies par OCTETS MAGIQUES puis par Content-Type.
# JPEG, PNG et WebP uniquement (le GIF est ecarte : rendu produit mediocre).
ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")

# UE27 + GB/CH/NO. Malte EXCLU le 01/11/2026 : aucune option CJ <= 15 jours.
DEST_COUNTRIES = ["FR", "DE", "ES", "IT", "NL", "BE", "LU", "IE", "PT", "AT",
                  "PL", "CZ", "SK", "HU", "SI", "HR", "RO", "BG", "GR", "EE",
                  "LV", "LT", "FI", "SE", "DK", "CY", "GB", "CH", "NO"]

BANNED_PATTERNS = re.compile(
    r"(?i)\b(battery|electric|electricity|lithium|bluetooth|speaker|camera|drone|"
    r"cosmetic|cream|serum|supplement|food|candy|cbd|vape|tattoo|knife|gun|ammo)\b"
)


class EvaluationSuspended(RuntimeError):
    """Emis quand une condition prealable indispensable echoue (taux, secret)."""


class CjThrottle:
    """Limite les appels CJ a 1 req/s (QPS documente, confirme par test).
    VERROU GLOBAL : respecte strictement la limite CJ 1 requete/seconde,
    quel que soit le nombre d'appels concurrents."""
    def __init__(self):
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self):
        async with self._lock:
            delta = time.monotonic() - self._last
            if delta < CJ_QPS_SECONDS:
                await asyncio.sleep(CJ_QPS_SECONDS - delta)
            self._last = time.monotonic()


_THROTTLE = CjThrottle()


def _cj_headers():
    key = os.environ.get("CJ_API_KEY")
    if not key:
        raise EvaluationSuspended(
            "CJ_API_KEY manquant : evaluation suspendue (secret absent).")
    return {"CJ-API-KEY": key, "Content-Type": "application/json"}


def _fw_headers():
    key = os.environ.get("FREEWEBSTORE_API_KEY")
    if not key:
        raise EvaluationSuspended(
            "FREEWEBSTORE_API_KEY manquant : evaluation suspendue (secret absent).")
    # v5.2 : en-tete x-api-key CONFIRME par la doc officielle Freewebstore
    # (https://api.freewebstore.com - Authorization). L'en-tete Bearer
    # n'est PAS la methode documentee.
    return {"x-api-key": key, "Content-Type": "application/json"}


def cj_check(data: dict, what: str) -> dict:
    """Verifie le code metier et la structure CJ. Jamais de reponse vide = succes."""
    if not isinstance(data, dict):
        raise RuntimeError(f"CJ {what}: reponse non-dict")
    code = data.get("code")
    if code not in (200, "200") or data.get("result") is False or data.get("success") is False:
        raise RuntimeError(f"CJ {what}: code metier {code} - {data.get('message')}")
    if "data" not in data:
        raise RuntimeError(f"CJ {what}: champ data absent")
    return data


def validate_quantity(qty) -> int:
    """v5 : valide la quantite d'une ligne de commande.
    Plafond MAX_ORDER_QTY = 5 (donnees fret CJ mesurees de 1 a 5 unites ;
    au-dela, fret non mesure -> verification manuelle)."""
    if not isinstance(qty, int) or isinstance(qty, bool):
        raise RuntimeError(f"quantite invalide: {qty!r}")
    if qty < 1:
        raise RuntimeError(f"quantite invalide: {qty!r}")
    if qty > MAX_ORDER_QTY:
        raise RuntimeError(
            f"quantite {qty} > plafond {MAX_ORDER_QTY} : fret CJ non mesure, "
            "verification manuelle requise")
    return qty


def freight_coverage_alert(charged_eur, actual_eur,
                           tolerance: float = FREIGHT_ALERT_TOLERANCE):
    """v5 : compare le tarif de livraison facture au fret CJ reel.
    Retourne None si couvert, sinon un message d'alerte.
    Ne bloque JAMAIS la commande : alerte uniquement (lecture seule)."""
    if charged_eur is None:
        return "tarif de livraison facture inconnu : verification manuelle"
    if actual_eur is None or actual_eur <= 0:
        return "fret CJ reel indisponible : verification manuelle"
    if charged_eur < actual_eur * (1 - tolerance):
        return (f"tarif facture {charged_eur:.2f} EUR < fret reel "
                f"{actual_eur:.2f} EUR (tolerance {tolerance:.0%}) : "
                "marge livraison non couverte")
    return None


def parse_cj_images(detail_payload: dict) -> list:
    """Extrait les URLs du champ productImage du detail produit CJ
    (chaine JSON contenant un tableau d'URLs - structure confirmee par MCP)."""
    raw = None
    data = detail_payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        raw = data[0].get("productImage")
    elif isinstance(data, dict):
        raw = data.get("productImage")
    if isinstance(raw, list):        # tolerance si l'API renvoie deja une liste
        return [u for u in raw if isinstance(u, str)]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return [u for u in parsed if isinstance(u, str)]
        except (json.JSONDecodeError, TypeError):
            return []
    return []


# ------------------------------------------------------------- activites ----
@workflows.activity(start_to_close_timeout=timedelta(seconds=30), retry_policy_max_attempts=2)
async def usd_eur_rate() -> float:
    """Taux USD/EUR OBLIGATOIRE en direct (BCE via Frankfurter).
    Aucun repli : indisponible, invalide, nul, negatif ou NaN -> suspension."""
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://api.frankfurter.app/latest",
                        params={"from": "USD", "to": "EUR"})
        r.raise_for_status()
        body = r.json()
        rate = ((body.get("rates") or {}).get("EUR"))
        if not isinstance(rate, (int, float)) or math.isnan(rate) or rate <= 0:
            raise RuntimeError("Taux USD/EUR invalide (NaN, nul ou negatif)")
        return float(rate)


@workflows.activity(start_to_close_timeout=timedelta(minutes=2), retry_policy_max_attempts=3)
async def cj_search(keyword: str, page_size: int = 10) -> dict:
    await _THROTTLE.wait()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{CJ_BASE}/product/search", headers=_cj_headers(),
                         json={"keyword": keyword, "pageSize": page_size, "pageNumber": 1})
        r.raise_for_status()
        data = cj_check(r.json(), "search")
        content = data["data"].get("content")
        if not isinstance(content, list) or not content or not isinstance(content[0].get("productList"), list):
            raise RuntimeError("CJ search: structure productList inattendue")
        return data


@workflows.activity(start_to_close_timeout=timedelta(minutes=3), retry_policy_max_attempts=3)
async def cj_variants(pid: str) -> dict:
    """TOUTES les variantes (aucune coupure, aucune limite)."""
    await _THROTTLE.wait()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{CJ_BASE}/product/variant/query",
                         headers=_cj_headers(), json={"productId": pid})
        r.raise_for_status()
        data = cj_check(r.json(), "variantes")
        if not isinstance(data["data"], list):
            raise RuntimeError(f"CJ variantes {pid}: structure inattendue")
        return data


@workflows.activity(start_to_close_timeout=timedelta(minutes=2), retry_policy_max_attempts=3)
async def cj_product_detail(pid: str) -> dict:
    """Detail produit CJ - source du champ productImage (galerie complete)."""
    await _THROTTLE.wait()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{CJ_BASE}/product/query",
                         headers=_cj_headers(), json={"pid": pid})
        r.raise_for_status()
        return cj_check(r.json(), f"detail {pid}")


@workflows.activity(start_to_close_timeout=timedelta(minutes=2), retry_policy_max_attempts=3)
async def cj_stock(vid: str) -> dict:
    await _THROTTLE.wait()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{CJ_BASE}/product/stock/queryById",
                         headers=_cj_headers(), json={"vid": vid})
        r.raise_for_status()
        data = cj_check(r.json(), f"stock {vid}")
        if not isinstance(data["data"], list):
            raise RuntimeError(f"CJ stock {vid}: structure inattendue")
        return data


@workflows.activity(start_to_close_timeout=timedelta(minutes=2), retry_policy_max_attempts=3)
async def cj_freight(vid: str, country: str, quantity: int = 1) -> dict:
    """v5 : fret CJ avec la QUANTITE REELLE de la commande.
    Fret mesure reellement (01/11/2026) : le fret croit d'environ
    +0,96 USD par unite supplementaire. Quantite validee par
    validate_quantity() : 1 a 5 unites, plafond garde-fou."""
    qty = validate_quantity(quantity)
    await _THROTTLE.wait()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{CJ_BASE}/logistic/freight/calculate", headers=_cj_headers(),
                         json={"vid": vid, "quantity": qty,
                               "countryCode": country, "startCountryCode": "CN"})
        r.raise_for_status()
        data = cj_check(r.json(), f"fret {vid}->{country} x{qty}")
        if not isinstance(data["data"], list):
            raise RuntimeError(f"CJ fret {country}: structure inattendue")
        return data


@workflows.activity(start_to_close_timeout=timedelta(seconds=45), retry_policy_max_attempts=2)
async def check_image(url: str) -> dict:
    """Verifie REELLEMENT une image : GET (jamais HEAD seul), lecture du
    contenu, octets magiques (JPEG/PNG/WebP), MIME declare, taille reelle,
    erreurs HTTP. Retourne le verdict ou leve une exception."""
    if not url or not url.startswith("https://"):
        raise RuntimeError("URL image invalide")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(url)          # GET : on lit le contenu, pas seulement l'en-tete
        r.raise_for_status()           # toute erreur HTTP (404, 500...) leve
        content_type = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise RuntimeError(f"type MIME non autorise: {content_type!r}")
        content = r.content           # lecture reelle du contenu
        if not content:
            raise RuntimeError("image vide")
        if len(content) < MIN_IMAGE_BYTES:
            raise RuntimeError(f"image trop petite ({len(content)} octets)")
        # Octets magiques : verituable nature du fichier, pas la declaration.
        detected = None
        if content.startswith(b"\xff\xd8\xff"):
            detected = "image/jpeg"
        elif content.startswith(b"\x89PNG\r\n\x1a\n"):
            detected = "image/png"
        elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            detected = "image/webp"
        if detected is None or detected != content_type:
            raise RuntimeError(f"contenu reel ({detected}) != MIME declare ({content_type})")
        return {"url": url, "bytes": len(content), "mime": content_type}


@workflows.activity(start_to_close_timeout=timedelta(minutes=3), retry_policy_max_attempts=3)
async def fw_list_all_products() -> list:
    """Catalogue COMPLET Freewebstore avec pagination verifiee."""
    products, page = [], 1
    async with httpx.AsyncClient(timeout=60) as c:
        while True:
            r = await c.get(f"{FW_BASE}/product",
                            params={"per_page": FW_PER_PAGE, "page": page},
                            headers=_fw_headers())
            r.raise_for_status()
            body = r.json()
            if not isinstance(body, dict) or not isinstance(body.get("list"), list):
                raise RuntimeError("Freewebstore: structure catalogue inattendue")
            batch = [p for p in body["list"]
                     if isinstance(p, dict) and p.get("id") and p.get("name")]
            if len(batch) != len(body["list"]):
                raise RuntimeError("Freewebstore: produits mal formes dans le catalogue")
            products.extend(batch)
            if len(body["list"]) < FW_PER_PAGE:
                break
            page += 1
    return products


@workflows.activity(start_to_close_timeout=timedelta(minutes=2), retry_policy_max_attempts=3)
async def fw_get_product(pid: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{FW_BASE}/product/{pid}", headers=_fw_headers())
        r.raise_for_status()
        return r.json()


@workflows.activity(start_to_close_timeout=timedelta(minutes=2), retry_policy_max_attempts=3)
async def fw_orders() -> dict:
    """v5.2 : commandes Freewebstore - LECTURE SEULE, pagination verifiee.
    URI REELLE confirmee : GET /orders (doc officielle + reponse reelle
    {"orders": {"found": N, "orders": [...]}}). Boucle limit/offset
    jusqu'a recuperation de toutes les commandes (criteres d'arret :
    'found' atteint OU page plus courte que la taille demandee).
    Aucune ecriture."""
    collected, offset, found = [], 0, None
    async with httpx.AsyncClient(timeout=60) as c:
        while True:
            r = await c.get(f"{FW_BASE}/orders",
                            params={"limit": FW_ORDERS_PAGE, "offset": offset},
                            headers=_fw_headers())
            r.raise_for_status()
            body = r.json()
            if not isinstance(body, dict):
                raise RuntimeError("Freewebstore /orders: reponse non-dict")
            inner = body.get("orders")
            if isinstance(inner, dict):
                batch = inner.get("orders")
                if found is None:
                    found = inner.get("found")
            elif isinstance(inner, list):
                batch = inner
                if found is None:
                    found = len(inner)
            else:
                raise RuntimeError("Freewebstore /orders: champ orders inattendu")
            if not isinstance(batch, list):
                raise RuntimeError("Freewebstore /orders: liste commandes inattendue")
            collected.extend(o for o in batch if isinstance(o, dict))
            if not batch:
                break
            if isinstance(found, int):
                # 'found' connu : paginer jusqu'a recuperation complete
                if len(collected) >= found:
                    break
            elif len(batch) < FW_ORDERS_PAGE:
                # 'found' inconnu : une page courte signale la fin
                break
            offset += len(batch)
    return {"found": found if isinstance(found, int) else len(collected),
            "orders": collected}


def fw_normalize_order(raw) -> dict:
    """v5.2 : ADAPTATEUR SECURISE commande Freewebstore -> process_order.

    Structure REELLE confirmee par GET /orders et GET /orders/abandoned
    (01/11/2026, storeid 1107499) :
    - identifiant commande : raw["id"]
    - pays : raw["delivery_address"]["country_iso_2"] (ISO-2, ex. "FR")
    - lignes produits : raw["order_details"][] avec "quantity",
      "productSKU" (SKU variante CJ, ex. CJJT205244502BY), "productId",
      "variantId" (identifiant variante FREWEBSTORE, pas le vid CJ),
      "net" (prix ligne EUR)
    - frais de livraison factures : raw["postage"] (niveau commande, EUR,
      avec postage_tax)

    SECURITE : n'extrait QUE les champs metier. AUCUNE donnee personnelle
    (nom, email, telephone, adresse, IP, session) n'est copiee.
    Le vid CJ n'est JAMAIS transporte par Freewebstore : il est resolu a
    None et process_order demandera une verification manuelle (sans_vid)
    jusqu'a ce qu'une correspondance SKU -> vid soit disponible."""
    if not isinstance(raw, dict):
        return {"id": None, "country": None, "shipping_charged": None,
                "items": [], "source": "freewebstore"}
    addr = raw.get("delivery_address") or {}
    country = None
    if isinstance(addr, dict):
        iso = addr.get("country_iso_2")
        if isinstance(iso, str) and len(iso.strip()) == 2:
            country = iso.strip().upper()
    postage = raw.get("postage")
    if not isinstance(postage, (int, float)) or isinstance(postage, bool):
        postage = None
    items = []
    for d in raw.get("order_details") or []:
        if not isinstance(d, dict):
            continue
        items.append({
            "vid": None,   # vid CJ non transporte par Freewebstore
            "sku": d.get("productSKU") or "",
            "product_id": d.get("productId"),
            "quantity": d.get("quantity"),
            "prix_ligne_eur": d.get("net"),
        })
    return {"id": raw.get("id"), "country": country,
            "shipping_charged": postage, "items": items,
            "source": "freewebstore"}


async def fw_variant_records(catalogue: list | None = None) -> list:
    """v5.3 : variantes Freewebstore en LECTURE SEULE.

    Pour CHAQUE produit Freewebstore : productId, productSKU et
    variantId. Structure REELLE confirmee par GET /product et
    GET /product/{id} (02/11/2026) : le detail produit porte
    core.id, core.sku et variants[] avec 'uvid' (= le variantId
    present dans les commandes) et 'sku' (= le SKU variante CJ
    saisi a la creation). Aucune ecriture."""
    if catalogue is None:
        catalogue = await fw_list_all_products()
    records = []
    for p in catalogue or []:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        detail = await fw_get_product(str(p["id"]))
        for v in detail.get("variants") or []:
            if isinstance(v, dict) and v.get("uvid") and v.get("sku"):
                records.append({
                    "fw_product_id": str(p["id"]),
                    "fw_product_sku": p.get("sku") or "",
                    "fw_variant_id": v["uvid"],
                    "variant_sku": v["sku"],
                })
    return records


async def build_vid_table(variant_records: list,
                           cj_search_fn=None, cj_variants_fn=None) -> dict:
    """v5.3 : table SKU -> vid CJ, correspondances EXACTES UNIQUEMENT.

    Pour chaque SKU variante Freewebstore :
    1. recherche du produit CJ candidat par le SKU variante lui-meme
       (methode CONFIRMEE en lecture seule le 02/11/2026 : la recherche
       CJ par SKU de variante retourne le produit porteur ; la
       recherche par SKU de produit retourne 0) ;
    2. consultation des variantes du produit CJ (vid, variantSku) ;
    3. association UNIQUEMENT si le SKU correspond EXACTEMENT
       (egalite stricte de chaine) et de facon UNIVOQUE (un seul vid).
    AUCUNE approximation tolernee : casse differente, SKU tronque,
    vid multiple ou produit candidat multiple -> pas d'association :
    la ligne reste sans_vid et une alerte manuelle est emise
    (listes 'absents' et 'ambigus'). Aucune ecriture CJ ni FW.

    Retour : {"table": {sku: {vid, fw_product_id, fw_variant_id,
    cj_pid}}, "absents": [...], "ambigus": [...],
    "nb_variantes_fw": N}. Contient uniquement des identifiants
    metier - AUCUNE donnee personnelle."""
    search = cj_search_fn or cj_search
    variants = cj_variants_fn or cj_variants
    table: dict = {}
    absents: list = []
    ambigus: list = []
    deja_traite: set = set()
    variants_cache: dict = {}
    for rec in variant_records or []:
        sku = rec.get("variant_sku") or ""
        if not sku or sku in deja_traite:
            continue
        deja_traite.add(sku)
        try:
            sres = await search(sku)
        except Exception as exc:
            absents.append({"variant_sku": sku,
                            "fw_variant_id": rec.get("fw_variant_id"),
                            "motif": f"recherche CJ indisponible: {exc}"})
            continue
        products = []
        try:
            for block in sres["data"]["content"]:
                for p in block.get("productList") or []:
                    if isinstance(p, dict) and p.get("id"):
                        products.append(str(p["id"]))
        except (TypeError, KeyError, AttributeError):
            absents.append({"variant_sku": sku,
                            "fw_variant_id": rec.get("fw_variant_id"),
                            "motif": "structure recherche CJ inattendue"})
            continue
        if not products:
            absents.append({"variant_sku": sku,
                            "fw_variant_id": rec.get("fw_variant_id"),
                            "motif": "aucun produit CJ candidat"})
            continue
        matches = []          # [(pid, vid)] pour correspondance exacte
        for pid in sorted(set(products)):
            if pid not in variants_cache:
                try:
                    vres = await variants(pid)
                    data = vres.get("data")
                    variants_cache[pid] = (data if isinstance(data, list)
                                           else None)
                except Exception:
                    variants_cache[pid] = None
            vlist = variants_cache[pid]
            if not vlist:
                continue
            hits = [v.get("vid") for v in vlist
                    if isinstance(v, dict)
                    and v.get("variantSku") == sku          # EXACT
                    and v.get("vid")]
            for vid in hits:
                matches.append((pid, vid))
        vids = sorted({vid for _, vid in matches})
        if len(vids) == 1:
            pid = next(p for p, v in matches if v == vids[0])
            table[sku] = {"vid": vids[0],
                          "fw_product_id": rec.get("fw_product_id"),
                          "fw_variant_id": rec.get("fw_variant_id"),
                          "cj_pid": pid}
        elif not matches:
            absents.append({"variant_sku": sku,
                            "fw_variant_id": rec.get("fw_variant_id"),
                            "motif": "aucune variante CJ a SKU exact "
                                     "(aucune approximation toleree)"})
        else:
            ambigus.append({"variant_sku": sku,
                            "fw_variant_id": rec.get("fw_variant_id"),
                            "candidats_vid": vids,
                            "motif": "SKU correspond a plusieurs vids CJ"})
    return {"table": table, "absents": absents, "ambigus": ambigus,
            "nb_variantes_fw": len(variant_records or [])}


@workflows.activity(start_to_close_timeout=timedelta(minutes=5), retry_policy_max_attempts=2)
async def process_order(order: dict, vid_table: dict | None = None) -> dict:
    """v5.1 : analyse de commande en LECTURE SEULE STRICTE.

    Pour chaque ligne de commande :
    - recalcule le fret CJ avec la QUANTITE REELLE (cj_freight quantity),
    - convertit au taux USD/EUR du jour,
    - compare au tarif de livraison facture au client,
    - emet une ALERTE si la marge livraison n'est pas couverte (>10 %).

    v5.1 - REPARTITION MULTI-LIGNES SECURISEE :
    - si CHAQUE ligne porte son propre 'shipping_charged' -> comparaison
      ligne par ligne ;
    - sinon, si la commande porte un 'shipping_charged' global -> UNE SEULE
      comparaison au niveau commande (somme des frets reels vs total
      facture). AUCUNE repartition n'est inventee entre les lignes ;
    - sinon -> alerte 'tarif inconnu', verification manuelle.
      Si au moins une ligne n'a pas pu etre verifiee, la comparaison au
      niveau commande est ANNULEE (jamais de conclusion sur un total de
      fret incomplet).

    v5.1 - COMMANDES DEPASSANT MAX_ORDER_QTY (5) UNITES :
    la ligne est marquee statut 'depasse_plafond', AUCUN appel fret CJ
    n'est emis (fret non mesure au-dela de 5 unites), alerte explicite
    de verification manuelle OBLIGATOIRE.

    v5.1 - PROTECTION FOURNISSEUR (par construction) :
    cette activite n'emet QUE des calculs de fret CJ
    (/logistic/freight/calculate, endpoint de calcul sans effet de bord).
    Elle ne cree, ne paie, ne modifie et n'annule AUCUNE commande CJ,
    et n'ecrit rien chez CJ ni Freewebstore. Les lignes invalides
    (quantite, vid, pays) ne declenchent AUCUN appel CJ.
    """
    report = {"order_id": order.get("id"), "pays": None, "lignes": [],
              "alertes": [], "mode": "lecture_seule", "statut": "analyse"}
    country = ((order.get("deliveryAddress") or {}).get("country")
               or order.get("country"))
    report["pays"] = country
    if not country or country not in DEST_COUNTRIES:
        report["statut"] = "hors_marche"
        report["alertes"].append(f"pays hors marche ou inconnu: {country!r}")
        return report
    items = order.get("items") or []
    if not isinstance(items, list) or not items:
        report["statut"] = "sans_lignes"
        report["alertes"].append("commande sans lignes")
        return report
    try:
        rate = await usd_eur_rate()
    except Exception as exc:
        report["statut"] = "taux_indisponible"
        report["alertes"].append(f"taux USD/EUR indisponible: {exc}")
        return report
    report["usd_eur"] = rate

    # --- repartition securisee du tarif de livraison facture ---
    line_charged = [it.get("shipping_charged") for it in items
                    if isinstance(it, dict)]
    order_charged = order.get("shipping_charged")
    per_line = (len(line_charged) == len(items)
                and all(isinstance(c, (int, float))
                        and not isinstance(c, bool) for c in line_charged))
    if per_line:
        report["repartition_livraison"] = "par_ligne"
    elif isinstance(order_charged, (int, float)) and not isinstance(order_charged, bool):
        report["repartition_livraison"] = "total_commande"
    else:
        report["repartition_livraison"] = "inconnue"
        report["alertes"].append(
            "tarif de livraison facture inconnu (ni par ligne ni total) : "
            "verification manuelle")

    total_actual_eur = 0.0
    all_lines_checked = True
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            report["alertes"].append(f"ligne {idx + 1} mal formee")
            all_lines_checked = False
            continue
        vid = it.get("vid") or it.get("cj_vid")
        sku = it.get("sku") or ""
        vid_resolu_table = False
        # v5.3 : resolution du vid par la table SKU->vid (EXACT uniquement)
        if not vid and isinstance(vid_table, dict):
            entry = (vid_table.get("table") or {}).get(sku)
            if isinstance(entry, dict) and entry.get("vid"):
                vid = entry["vid"]
                vid_resolu_table = True
        qty_raw = it.get("quantity", it.get("qty", 1))
        line = {"vid": vid, "quantite": qty_raw}
        if vid_resolu_table:
            line["vid_source"] = "table_sku_vid"
        try:
            qty = validate_quantity(qty_raw)
        except RuntimeError as exc:
            if (isinstance(qty_raw, int) and not isinstance(qty_raw, bool)
                    and qty_raw > MAX_ORDER_QTY):
                line["statut"] = "depasse_plafond"
                line["alerte"] = (
                    f"quantite {qty_raw} > plafond {MAX_ORDER_QTY} : fret CJ "
                    "non mesure au-dela de 5 unites, verification manuelle "
                    "OBLIGATOIRE (aucun appel CJ emis)")
            else:
                line["statut"] = "quantite_invalide"
                line["alerte"] = (f"quantite invalide: {qty_raw!r} : "
                                  "verification manuelle")
            report["alertes"].append(f"ligne {idx + 1} ({vid}): {line['alerte']}")
            report["lignes"].append(line)
            all_lines_checked = False
            continue
        if not vid:
            # v5.3 : sans_vid CONSERVE si absent ou ambigu (jamais
            # d'association approximative) + alerte manuelle.
            line["statut"] = "sans_vid"
            line["sku"] = sku
            motif = ("correspondance SKU->vid requise, "
                     "verification manuelle")
            if isinstance(vid_table, dict):
                sku_ambigus = {a.get("variant_sku")
                               for a in vid_table.get("ambigus") or []
                               if isinstance(a, dict)}
                if sku in sku_ambigus:
                    motif = ("correspondance SKU->vid AMBIGUE : "
                             "aucune association approximative, "
                             "verification manuelle OBLIGATOIRE")
            line["alerte"] = (f"ligne sans vid CJ (sku {sku or 'inconnu'}) : "
                              + motif)
            report["alertes"].append(f"ligne {idx + 1}: {line['alerte']}")
            report["lignes"].append(line)
            all_lines_checked = False
            continue
        try:
            fres = await cj_freight(vid, country, quantity=qty)
        except Exception as exc:
            line["statut"] = "fret_indisponible"
            line["alerte"] = f"fret non verifiable: {exc}"
            report["alertes"].append(f"ligne {idx + 1} ({vid}): {line['alerte']}")
            report["lignes"].append(line)
            all_lines_checked = False
            continue
        prices = []
        for o in fres["data"]:
            try:
                if o.get("logisticPrice") is not None:
                    prices.append(float(o["logisticPrice"]))
            except (TypeError, ValueError):
                continue
        if not prices:
            line["statut"] = "fret_indisponible"
            line["alerte"] = "aucune option de fret CJ disponible"
            report["alertes"].append(f"ligne {idx + 1} ({vid}): {line['alerte']}")
            report["lignes"].append(line)
            all_lines_checked = False
            continue
        actual_eur = min(prices) * rate
        line["statut"] = "verifie"
        line["fret_cj_eur"] = round(actual_eur, 2)
        total_actual_eur += actual_eur
        if report["repartition_livraison"] == "par_ligne":
            charged = line_charged[idx]
            line["tarif_facture_eur"] = charged
            alert = freight_coverage_alert(charged, actual_eur)
            if alert:
                line["alerte"] = alert
                report["alertes"].append(
                    f"ligne {idx + 1} ({vid}) x{qty}: {alert}")
        report["lignes"].append(line)

    if report["repartition_livraison"] == "total_commande":
        report["fret_total_eur"] = round(total_actual_eur, 2)
        if not all_lines_checked:
            report["alertes"].append(
                "comparaison au niveau commande ANNULEE : au moins une ligne "
                "n'a pas pu etre verifiee (total fret incomplet)")
        else:
            alert = freight_coverage_alert(order_charged, total_actual_eur
                                            if total_actual_eur > 0 else None)
            if alert:
                report["alertes"].append(
                    f"commande {order.get('id')}: {alert}")
    if not all_lines_checked:
        report["statut"] = "lignes_non_verifiees"
    elif report["alertes"]:
        report["statut"] = "alertes"
    else:
        report["statut"] = "verifie"
    return report


@workflows.activity(start_to_close_timeout=timedelta(minutes=2), retry_policy_max_attempts=2)
async def fw_create_product(core: dict, variants: list) -> dict:
    """Creation d'un produit Freewebstore. APPELEE UNIQUEMENT si
    allow_publish=True (mode publication). En mode veille (defaut),
    cette activite n'est JAMAIS executee (branche de code inatteignable).
    La reponse est RELUE par fw_get_product avant tout succes affiche."""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{FW_BASE}/product", headers=_fw_headers(),
                         json={"core": core, "variants": variants})
        r.raise_for_status()
        return r.json()


# ------------------------------------------------------------ logique pure ----
def sale_price(minimum_eur: float) -> float:
    """Prix STRICTEMENT >= minimum_eur, arrondi au X,90 superieur."""
    candidate = math.floor(minimum_eur) + 0.90
    if candidate < minimum_eur - 1e-9:
        candidate += 1.0
    return round(candidate, 2)


def display_stock(cj_stock: int) -> int:
    """Regle 9 : min(100, stock - 100), 0 si rupture."""
    return max(0, min(DISPLAY_STOCK_CAP, cj_stock - SAFETY_STOCK))


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9\s-]", "", name.lower())
    s = re.sub(r"\s+", "-", s.strip())
    return s[:60].strip("-")


def _name_tokens(name: str) -> set:
    return {t for t in re.sub(r"[^a-z0-9\s]", "", name.lower()).split() if len(t) > 3}


def similar_name(new_name: str, existing_names: list) -> bool:
    """Doublon si >= 60% des mots significatifs du nouveau nom deja presents."""
    new_tokens = _name_tokens(new_name)
    if not new_tokens:
        return False
    for existing in existing_names:
        common = new_tokens & _name_tokens(existing)
        if common and len(common) / len(new_tokens) >= 0.6:
            return True
    return False


def cn_stock_of(stock_payload: dict) -> int:
    """Extrait le stock China Warehouse d'une reponse stock validee.

    CORRECTION v5 : la reponse REELLE observee (01/11/2026) montre
    storageNum = 11347, totalInventoryNum = 11347, mais
    stock[0].inventory = 0. La v4 lisait stock[0]["inventory"] en
    priorite et retournait donc 0 a tort (rejet errone du produit).
    Priorite corrigee : storageNum > totalInventoryNum > stock[0].inventory.
    Valeurs non-entiieres ou negatives ignorees (jamais 0 accepte d'une
    source douteuse si une source fiable existe)."""
    for entry in stock_payload.get("data", []) or []:
        if not isinstance(entry, dict) or entry.get("countryCode") != "CN":
            continue
        for field in ("storageNum", "totalInventoryNum"):
            value = entry.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
        stocks = entry.get("stock") or []
        if stocks and isinstance(stocks[0], dict):
            inventory = stocks[0].get("inventory")
            if (isinstance(inventory, int)
                    and not isinstance(inventory, bool)
                    and inventory > 0):
                return inventory
    return 0


def conforming_freight_options(options: list, rate: float) -> list:
    """Options CJ conformes : <= MAX_SHIP_EUR et delai max <= MAX_SHIP_DAYS.
    Conserve le delai MINIMAL et MAXIMAL reellement annonce par CJ.
    NOTE v5 : a utiliser pour le fret UNITAIRE (quantity=1) uniquement ;
    les colis multi-unites sont couverts par les bandes de quantite."""
    ok = []
    for o in options or []:
        try:
            price = float(o.get("logisticPrice"))
            aging = (o.get("logisticAging") or "").split("-")
            aging_min, aging_max = int(aging[0]), int(aging[-1])
        except (TypeError, ValueError, IndexError):
            continue
        if price * rate <= MAX_SHIP_EUR and aging_max <= MAX_SHIP_DAYS:
            ok.append({"price_eur": round(price * rate, 2),
                       "aging_min": aging_min, "aging_max": aging_max})
    return ok


def merge_destinations(per_variant: dict) -> tuple:
    """Un pays est retenu seulement s'il est conforme pour TOUTES les
    variantes. Retourne (destinations, delais_min, delais_max) par pays :
    uniquement des delais reellement verifies."""
    countries = set()
    for mapping in per_variant.values():
        countries |= set(mapping.keys())
    kept, delays_min, delays_max = {}, {}, {}
    for country in sorted(countries):
        if all(country in mapping for mapping in per_variant.values()):
            kept[country] = round(max(m[country]["price_eur"]
                                      for m in per_variant.values()), 2)
            delays_min[country] = min(m[country]["aging_min"]
                                       for m in per_variant.values())
            delays_max[country] = max(m[country]["aging_max"]
                                       for m in per_variant.values())
    return kept, delays_min, delays_max


def estimated_net_profit(price: float, checkout_shipping_eur: float | None,
                         worst_cost_eur: float, worst_ship_cj_eur: float,
                         other_costs_eur: float = 0.0) -> float:
    """FORMULE CORRIGEE v4 (conservee en v5) :
    benefice = prix_produit (encaisse)
             + livraison_facturee_au_client   <-- RECETTE, jamais soustraite
             - cout_produit_CJ
             - livraison_reelle_CJ
             - frais_paiement (calcules par l'appelant, inclus via other_costs
               pour garder cette fonction pure)
             - autres_charges_connues (frais paiement + taxes connues)
    Si le tarif checkout est inconnu (None), on calcule en dessous de la
    realite : scenario 0 EUR facture au client (jamais de benefice surestime)."""
    shipping_revenue = checkout_shipping_eur if checkout_shipping_eur is not None else 0.0
    return round(price + shipping_revenue - worst_cost_eur - worst_ship_cj_eur
                 - other_costs_eur, 2)


# ------------------------------------------------------------- workflow ----
class DailyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keywords: list[str] = ["home decoration", "kitchen organizer",
                           "storage basket", "wall art", "practical accessories"]
    # MODE VEILLE par defaut : aucune creation ni modification.
    allow_publish: bool = False
    # Tarif de livraison reellement facture au client au checkout.
    # Sans lui : publication bloquee ; benefice estime en scenario pessimiste.
    checkout_shipping_eur: float | None = None


@workflows.workflow.define(name="shoplinous_daily", execution_timeout=timedelta(hours=8))
class ShoplinousDailyWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, params: DailyParams) -> dict:
        report = {"published": [], "valides_en_veille": [], "rejected": [],
                  "alerts": [], "errors": [],
                  "mode": "veille" if not params.allow_publish else "publication"}

        # Taux de change : OBLIGATOIRE en direct. Aucun repli.
        try:
            rate = await usd_eur_rate()
        except Exception as exc:
            report["errors"].append(f"EVALUATION SUSPENDUE - taux USD/EUR indisponible: {exc}")
            return report
        report["usd_eur"] = rate

        if params.allow_publish and params.checkout_shipping_eur is None:
            report["errors"].append(
                "PUBLICATION BLOQUEE : tarif de livraison checkout non fourni.")
            return report

        try:
            catalogue = await fw_list_all_products()
        except Exception as exc:
            report["errors"].append(f"EVALUATION SUSPENDUE - catalogue: {exc}")
            return report
        existing_skus = {(p.get("sku") or "").upper() for p in catalogue}
        existing_names = [p.get("name") or "" for p in catalogue]

        validated_count = 0
        for kw in params.keywords:
            if validated_count >= MAX_PUBLISH_PER_RUN:
                break
            try:
                res = await cj_search(kw)
            except Exception as exc:
                report["errors"].append(f"search '{kw}': {exc}")
                continue
            for cand in res["data"]["content"][0]["productList"]:
                if validated_count >= MAX_PUBLISH_PER_RUN:
                    break
                pid = cand.get("id")
                if not pid:
                    continue
                try:
                    sku = (cand.get("sku") or "")
                    cj_name = cand.get("nameEn") or ""
                    # Regle 5 : anti-doublon SKU ET nom, catalogue complet.
                    if f"SHP-{sku[:20]}".upper() in existing_skus:
                        report["rejected"].append({"id": pid, "reason": "doublon SKU"})
                        continue
                    if similar_name(cj_name, existing_names):
                        report["rejected"].append({"id": pid, "reason": "doublon nom similaire"})
                        continue
                    if BANNED_PATTERNS.search(cj_name):
                        report["rejected"].append({"id": pid, "reason": "produit interdit"})
                        continue
                    # Regles 1-2 : TOUTES les variantes.
                    vres = await cj_variants(pid)
                    variants = vres["data"]
                    if not variants:
                        report["rejected"].append({"id": pid, "reason": "aucune variante"})
                        continue
                    retained, excluded_variants, sku_seen = [], [], set()
                    for v in variants:
                        vid, vsku = v.get("vid"), (v.get("variantSku") or "")
                        if not vid or not vsku:
                            excluded_variants.append({"vid": vid, "reason": "champs manquants"})
                            continue
                        if vsku.upper() in sku_seen or vsku.upper() in existing_skus:
                            excluded_variants.append({"vid": vid, "reason": "SKU duplique"})
                            continue
                        sku_seen.add(vsku.upper())
                        try:
                            stock_payload = await cj_stock(vid)
                        except Exception as exc:
                            excluded_variants.append({"vid": vid,
                                "reason": f"stock non verifiable: {exc}"})
                            continue
                        cn_stock = cn_stock_of(stock_payload)
                        if cn_stock < MIN_STOCK_CN:
                            excluded_variants.append({"vid": vid,
                                "reason": f"stock CN {cn_stock} < {MIN_STOCK_CN}"})
                            continue
                        cost_eur = float(v.get("variantSellPrice") or 0) * rate
                        if cost_eur > MAX_COST_EUR or cost_eur <= 0:
                            excluded_variants.append({"vid": vid,
                                "reason": f"cout {cost_eur:.2f} EUR hors regle"})
                            continue
                        retained.append({"vid": vid, "sku": vsku, "cost_eur": cost_eur,
                                         "cn_stock": cn_stock,
                                         "image": v.get("variantImage") or ""})
                    if excluded_variants:
                        report["alerts"].append({"id": pid,
                                                 "variantes_exclues": excluded_variants})
                    if not retained:
                        report["rejected"].append({"id": pid,
                            "reason": "aucune variante conforme"})
                        continue
                    # Regle 3 : fret pour CHAQUE variante x CHAQUE pays.
                    per_variant, freight_error = {}, False
                    for v in retained:
                        mapping = {}
                        for country in DEST_COUNTRIES:
                            try:
                                fres = await cj_freight(v["vid"], country, quantity=1)
                            except Exception as exc:
                                report["errors"].append(
                                    f"fret {v['vid']}->{country}: {exc}")
                                freight_error = True
                                break
                            ok = conforming_freight_options(fres["data"], rate)
                            if ok:
                                mapping[country] = min(ok, key=lambda o: o["price_eur"])
                        if freight_error:
                            break
                        per_variant[v["vid"]] = mapping
                    if freight_error:
                        continue
                    kept, delays_min, delays_max = merge_destinations(per_variant)
                    if not kept:
                        report["rejected"].append({"id": pid,
                            "reason": "aucune destination conforme pour toutes les variantes"})
                        continue
                    # Regle 4 : images - champ productImage DU DETAIL PRODUIT
                    # + images des variantes + bigImage, verifiees par GET.
                    urls = set()
                    for v in retained:
                        if v["image"]:
                            urls.add(v["image"])
                    if cand.get("bigImage"):
                        urls.add(cand["bigImage"])
                    try:
                        detail = await cj_product_detail(pid)
                    except Exception as exc:
                        report["errors"].append(f"detail {pid}: {exc}")
                        continue
                    for u in parse_cj_images(detail):
                        urls.add(u)
                    accessible = []
                    for url in sorted(urls):
                        try:
                            verdict = await check_image(url)
                            accessible.append(verdict)
                        except Exception as exc:
                            report["alerts"].append({"id": pid, "image_refusee": url,
                                                     "raison": str(exc)})
                    if len(accessible) < MIN_IMAGES:
                        report["rejected"].append({"id": pid,
                            "reason": f"images valides {len(accessible)} < {MIN_IMAGES}"})
                        continue
                    # Regle 8 : marge pour CHAQUE combinaison variante/pays.
                    worst_minimum = max((v["cost_eur"] + kept[c]) * MARGIN_MULTIPLE
                                         for v in retained for c in kept)
                    price = sale_price(worst_minimum)
                    worst_cost = max(v["cost_eur"] for v in retained)
                    worst_ship_cj = max(kept.values())
                    payment_fee = round(price * PAYMENT_FEE_RATE
                                        + PAYMENT_FEE_FIXED_EUR, 2)
                    net = estimated_net_profit(price, params.checkout_shipping_eur,
                                                worst_cost, worst_ship_cj,
                                                other_costs_eur=payment_fee)
                    entry = {"id": pid, "name": cj_name, "price": price,
                             "variantes": len(retained),
                             "images_valides": len(accessible),
                             "destinations": kept,
                             "delais_par_pays": {c: [delays_min[c], delays_max[c]]
                                                  for c in kept},
                             "marge_brute_min_eur": round(price - worst_cost
                                                          - worst_ship_cj, 2),
                             "frais_paiement_estimes_eur": payment_fee,
                             "benefice_net_estime_eur": net,
                             "hypothese_livraison_client": params.checkout_shipping_eur
                             if params.checkout_shipping_eur is not None
                             else "inconnue (scenario pessimiste 0 EUR)"}
                    if not params.allow_publish:
                        report["valides_en_veille"].append(entry)
                        validated_count += 1
                        continue
                    # --- Publication (seulement si autorisee) ---
                    dmin = min(delays_min[c] for c in kept)
                    dmax = max(delays_max[c] for c in kept)
                    fw_variants = [{
                        "key": f"Standard {i+1}" if len(retained) > 1 else "Standard",
                        "sku": v["sku"],
                        "image": {"filename": v["image"] or cand.get("bigImage", "")},
                        "stock": display_stock(v["cn_stock"]),
                        "condition": "New",
                        "sequence": i + 1,
                    } for i, v in enumerate(retained)]
                    core = {
                        "name": f"{cj_name} - SHOPLINOUS",
                        "abstract": (f"{cj_name}. Produit selectionne par SHOPLINOUS. "
                                     f"Livraison verifiee en {dmin} a {dmax} jours ouvres "
                                     "selon le pays de destination (Union europeenne, "
                                     "Royaume-Uni, Suisse, Norvege)."),
                        "price": price,
                        "brand": "SHOPLINOUS",
                        "sku": f"SHP-{sku[:20]}",
                        "condition": "new",
                        "published": True,
                        "url": _slug(cj_name),
                        "image": {"filename": accessible[0]["url"]},
                        "seo": {
                            "title": f"{cj_name} | SHOPLINOUS",
                            "desc": (f"{cj_name} selectionne par SHOPLINOUS. "
                                     f"Livraison {dmin}-{dmax} jours selon le pays, "
                                     "delais verifies par destination."),
                            "keywords": cj_name.lower().split()[:5],
                        },
                    }
                    created = await fw_create_product(core, fw_variants)
                    # Verification OBLIGATOIRE : identifiant + relecture.
                    new_id = None
                    if isinstance(created, dict):
                        new_id = created.get("productId") or created.get("id") \
                            or (created.get("core") or {}).get("id")
                    if not new_id:
                        report["errors"].append({"id": pid,
                            "reason": f"creation non confirmee: {str(created)[:200]}"})
                        continue
                    check = await fw_get_product(new_id)
                    c_core = check.get("core") or {}
                    if not c_core.get("id") or c_core.get("published") is not True \
                            or c_core.get("price") != price:
                        report["errors"].append({"id": pid, "freewebstore_id": new_id,
                            "reason": "verification post-creation echouee (publie/prix)"})
                        continue
                    report["published"].append({**entry, "freewebstore_id": new_id})
                    existing_skus.add(f"SHP-{sku[:20]}".upper())
                    existing_names.append(cj_name)
                    validated_count += 1
                except Exception as exc:
                    report["errors"].append(f"produit {pid}: {exc}")

        # v5.3 : table SKU->vid, correspondances EXACTES uniquement.
        # Reconstruite a chaque execution depuis les donnees vivantes
        # (LECTURE SEULE FW + CJ) ; l'amorce VID_TABLE_SEED sert de
        # filet de securite si la reconstruction echoue. Les entrees
        # reconstruites prevaleulent sur l'amorce.
        try:
            fw_records = await fw_variant_records(catalogue)
            vid_table = await build_vid_table(fw_records)
            for seed_sku, seed_entry in VID_TABLE_SEED.items():
                if seed_sku not in vid_table["table"]:
                    vid_table["table"][seed_sku] = dict(seed_entry)
        except Exception as exc:
            vid_table = {"table": {k: dict(v)
                                   for k, v in VID_TABLE_SEED.items()},
                         "absents": [], "ambigus": [],
                         "nb_variantes_fw": 0}
            report["errors"].append(
                f"vid_table: reconstruction impossible ({exc}) : "
                "amorce verifiee utilisee")
        report["vid_table"] = {
            "entrees": sorted(vid_table["table"]),
            "absents": vid_table["absents"],
            "ambigus": vid_table["ambigus"],
            "nb_variantes_fw": vid_table.get("nb_variantes_fw", 0)}
        report["alerts"].extend(
            {"vid_table": a.get("variant_sku"), "alerte": a.get("motif")}
            for a in vid_table["absents"] + vid_table["ambigus"])

        # Surveillance commandes : lecture seule, AUCUN paiement fournisseur.
        # v5.2 : GET /orders pagine (limit/offset, en-tete x-api-key),
        # adaptateur securise fw_normalize_order (AUCUNE donnee personnelle
        # copiee), PUIS process_order en lecture seule stricte.
        # PROTECTION FOURNISSEUR : aucune creation, modification,
        # paiement ni annulation de commande CJ, jamais, par construction.
        try:
            orders_body = await fw_orders()
            order_list = orders_body.get("orders") or []
            if not isinstance(order_list, list):
                raise RuntimeError("structure commandes inattendue")
            report["orders_found"] = orders_body.get("found", len(order_list))
            report["orders_analyzed"] = []
            for o in order_list:
                if not isinstance(o, dict):
                    report["errors"].append("commande mal formee ignoree")
                    continue
                try:
                    oreport = await process_order(
                        fw_normalize_order(o), vid_table=vid_table)
                except Exception as exc:
                    report["errors"].append(
                        f"process_order {o.get('id')}: {exc}")
                    continue
                report["orders_analyzed"].append(oreport)
                for a in oreport.get("alertes", []):
                    report["alerts"].append(
                        {"order": oreport.get("order_id"), "alerte": a})
        except Exception as exc:
            report["errors"].append(f"orders: {exc}")

        return report

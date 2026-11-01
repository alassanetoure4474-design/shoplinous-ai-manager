"""SHOPLINOUS - Workflow quotidien v4 (marche : UE27 + GB/CH/NO, Malte ecarte).

Regles de reference (base de connaissances SHOPLINOUS, 01/11/2026) :
1. Stock China Warehouse >= 1000 pour CHAQUE variante conservee
2. Prix fournisseur <= 8 EUR pour CHAQUE variante conservee
3. Livraison <= 6 EUR, delai min ET max <= 15 jours, verifies pour CHAQUE
   couple (variante, pays) ; seuls les delais reellement verifies sont
   annonces, par pays
4. >= 2 images reellement accessibles ET valides (GET + lecture du contenu,
   octets magiques + MIME), sources : champ productImage du detail produit
   CJ + images des variantes + bigImage
5. Anti-doublon : SKU ET similarite de nom sur le catalogue COMPLET pagine
6. Produits interdits (electronique risquee, contrefacons, reglementes)
7. Categories prioritaires : maison, decoration, rangement, cuisine, accessoires
8. Prix STRICTEMENT >= 3 x (cout variante + livraison pays) pour CHAQUE
   combinaison, arrondi au X,90
9. Stock affiche = min(100, stock CJ - 100) ; 0 si rupture

BENEFICE NET ESTIME (formule corrigee v4) :
    benefice = prix_produit                        # encaisse sur le produit
             + livraison_facturee_au_client        # RECETTE, jamais depense
             - cout_produit_CJ                     # depense fournisseur
             - livraison_reelle_CJ                 # depense transport
             - frais_paiement                      # % + fixe
             - autres_charges_connues              # ex: TVA collectee si applicable

Securite : allow_publish=False par defaut (mode veille : RIEN n'est cree
ni modifie) ; taux de change OBLIGATOIRE en direct (aucun repli) ; toute
reponse HTTP ou metier invalide bloque et signale.

STRUCTURES CONFIRMEES via appels reels au serveur MCP SHOPLINOUS (01/11/2026)
(ces formes de donnees sont observees ; l'authentification REST DIRECTE
reste NON TESTEE) :
- CJ search      -> data.content[0].productList[] (id, sku, nameEn, bigImage,
                   sellPrice, warehouseInventoryNum)
- CJ variantes  -> data[] (vid, variantSku, variantNameEn, variantSellPrice,
                   variantImage, variantKey)
- CJ stock vid  -> data[] (stock[].inventory, storageNum, countryCode "CN")
- CJ fret       -> data[] (logisticName, logisticPrice USD, logisticAging "n-m")
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
PAYMENT_FEE_RATE = float(os.environ.get("PAYMENT_FEE_RATE", "0.029"))
PAYMENT_FEE_FIXED_EUR = float(os.environ.get("PAYMENT_FEE_FIXED_EUR", "0.30"))
CJ_BASE = os.environ.get("CJ_API_BASE", "https://developers.cjdropshipping.com/api2.0/v1")
FW_BASE = os.environ.get("FREEWEBSTORE_API_BASE", "https://api.freewebstore.com")
FW_PER_PAGE = 100
CJ_QPS_SECONDS = 1.1   # QPS CJ 1 req/s, confirme par erreur reelle 1600200
MIN_IMAGE_BYTES = 4096

# Formats reels autorises, verifies par OCTETS MAGIQUES puis par Content-Type.
# JPEG, PNG et WebP uniquement (le GIF est ecarte : rendu produit mediocre).
MAGIC_SIGNATURES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}
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
    """Limite les appels CJ a 1 req/s (QPS documente, confirme par test)."""
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
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


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
async def cj_freight(vid: str, country: str) -> dict:
    await _THROTTLE.wait()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{CJ_BASE}/logistic/freight/calculate", headers=_cj_headers(),
                         json={"vid": vid, "quantity": 1,
                               "countryCode": country, "startCountryCode": "CN"})
        r.raise_for_status()
        data = cj_check(r.json(), f"fret {vid}->{country}")
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
async def fw_create_product(core: dict, variants: list) -> dict:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{FW_BASE}/product", headers=_fw_headers(),
                         json={"core": core, "variants": variants})
        r.raise_for_status()
        return r.json()


@workflows.activity(start_to_close_timeout=timedelta(minutes=2), retry_policy_max_attempts=3)
async def fw_get_product(pid: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{FW_BASE}/product/{pid}", headers=_fw_headers())
        r.raise_for_status()
        return r.json()


@workflows.activity(start_to_close_timeout=timedelta(minutes=2), retry_policy_max_attempts=3)
async def fw_orders() -> dict:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{FW_BASE}/order", params={"limit": 50}, headers=_fw_headers())
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
    """Extrait le stock China Warehouse d'une reponse stock validee."""
    for entry in stock_payload.get("data", []) or []:
        if entry.get("countryCode") == "CN":
            stocks = entry.get("stock") or []
            if stocks and isinstance(stocks[0].get("inventory"), int):
                return stocks[0]["inventory"]
            return int(entry.get("storageNum") or entry.get("totalInventoryNum") or 0)
    return 0


def conforming_freight_options(options: list, rate: float) -> list:
    """Options CJ conformes : <= MAX_SHIP_EUR et delai max <= MAX_SHIP_DAYS.
    Conserve le delai MINIMAL et MAXIMAL reellement annonce par CJ."""
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
    """FORMULE CORRIGEE v4 :
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
                                fres = await cj_freight(v["vid"], country)
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

        # Surveillance commandes : lecture seule, AUCUN paiement fournisseur.
        try:
            orders = await fw_orders()
            report["orders_found"] = orders.get("found", 0)
        except Exception as exc:
            report["errors"].append(f"orders: {exc}")

        return report

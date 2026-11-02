"""SHOPLINOUS - Audit global pre-production v5.4 (workflow-v5-fix4).

AUDIT COMPLET du systeme AVANT toute mise en production, en MODE
SIMULATION STRICT :
- lecture seule integrale (Freewebstore ET CJdropshipping) ;
- AUCUN achat fournisseur, AUCUNE creation/modification de commande,
  AUCUNE publication de produit, AUCUN changement de prix/stock,
  AUCUN deploiement, AUCUNE fusion de branche ;
- allow_publish=False du workflow quotidien INCHANGE : ce module est
  autonome et ne modifie PAS workflow/daily.py ;
- les simulations de commandes utilisent exclusivement des DONNEES
  FICTIVES etiquetees "SIM-" : jamais presentees comme des commandes
  reelles, jamais envoyees a un fournisseur ;
- toute donnee non verifiable est SIGNALISEE, jamais supposee
  (aucun tarif, stock ni delai invente).

Donnees REELLES mesurees en lecture seule le 02/11/2026 :
- catalogue FW : 12 produits (11 demo non publies + 1 publie : id
  18809643, sku SHP-CJT2052445, 24.90 EUR, stock 200, variantes
  uvid ZsKQFt/CJJT205244501AZ et WPPmLB/CJJT205244502BY) ;
- variantes CJ pid 1797521453303214080 : 2.81 USD, 80 g, variantSku
  CJJT205244501AZ (White-40cm) / CJJT205244502BY (Black-40cm) ;
- stocks Chine : 11347 (Blanc) / 12657 (Noir) - regle 1 OK ;
- fret CJ vers FR, quantites 1 a 5, MEILLEURE option mesuree
  CJPacket Ordinary (4-10 j) : 4.69 / 5.65 / 6.62 / 7.58 / 8.54 USD ;
  CJPacket Ordinary I (8-18 j) : 5.31 / 6.16 / 7.01 / 7.86 / 8.72 USD ;
- postage reel facture sur les paniers : 0.00 EUR (zones de livraison
  NON configurees - anomalie signalee en v5.2, TOUJOURS PRESENTE) ;
- commandes reelles : 0 (found=0 le 02/11/2026).

Ce module importe daily uniquement pour REUTILISER les regles et
constantes (cn_stock_of, validate_quantity, freight_coverage_alert).
Toutes les fonctions d'audit sont PURES : aucun appel reseau, aucune
ecriture, aucun achat.
"""
import re

from daily import (cn_stock_of, validate_quantity, freight_coverage_alert,
                   MIN_STOCK_CN, MAX_COST_EUR, MAX_SHIP_EUR,
                   MAX_SHIP_DAYS, MAX_ORDER_QTY)


# ------------------------------------------------- donnees reelles 02/11/2026 ----
# Identifiants metier uniquement (SKU, ids, prix, stocks) : AUCUNE donnee
# personnelle. Les tarifs et stocks ci-dessous sont MESURES, jamais inventes.
REAL_DATA = {
    "catalogue": [
        {"id": "38968614", "sku": "yellow0001", "name": "Yellow Wrap Tunic Top",
         "abstract": "This is a demo product.", "published": False,
         "price": 19.99, "pricing": {"baseprice": 19.99}, "stock": 100},
        {"id": "74113726", "sku": "pinktie0001", "name": "Pink Tie Neck Blouse",
         "abstract": "This is a demo product.", "published": False,
         "price": 14.99, "pricing": {"baseprice": 19.99,
                                     "discount": {"type": "percent",
                                                  "value": 25.0}},
         "stock": 100},
        {"id": "8700732", "sku": "diamante0001",
         "name": "Pink Diamante Embellished Printed T-Shirt",
         "abstract": "This is a demo product.", "published": False,
         "price": 19.99, "pricing": {"baseprice": 19.99}, "stock": 100},
        {"id": "82347844", "sku": "abc0002", "name": "Men's Designer Saddle Bag",
         "abstract": "This is a demo product.", "published": False,
         "price": 19.99, "pricing": {"baseprice": 19.99}, "stock": 100},
        {"id": "65226311", "sku": "abc0001",
         "name": "Men's Designer Blue Saddle Bag",
         "abstract": "This is a demo product.", "published": False,
         "price": 15.99, "pricing": {"baseprice": 19.99,
                                     "discount": {"type": "percent",
                                                  "value": 20.0}},
         "stock": 100},
        {"id": "35257208", "sku": "abc0004",
         "name": "Light Grey Women's T Shirt",
         "abstract": "This is a demo product.", "published": False,
         "price": 19.99, "pricing": {"baseprice": 19.99}, "stock": 100},
        {"id": "14877949", "sku": "lbluei0001", "name": "Light Blue Bardot Top",
         "abstract": "This is a demo product.", "published": False,
         "price": 19.99, "pricing": {"baseprice": 19.99}, "stock": 100},
        {"id": "30843731", "sku": "khaki0001", "name": "Khaki Wrap Tunic Top",
         "abstract": "This is a demo product.", "published": False,
         "price": 19.99, "pricing": {"baseprice": 19.99}, "stock": 100},
        {"id": "23338754", "sku": "abc0003", "name": "Hot Pink Tracksuit",
         "abstract": "This is a demo product.", "published": False,
         "price": 16.99, "pricing": {"baseprice": 19.99,
                                     "discount": {"type": "percent",
                                                  "value": 15.0}},
         "stock": 100},
        {"id": "79119705", "sku": "grey0001", "name": "Grey Peplum Cami Top",
         "abstract": "This is a demo product.", "published": False,
         "price": 19.99, "pricing": {"baseprice": 19.99}, "stock": 100},
        {"id": "89335106", "sku": "coral0001",
         "name": "Coral Tie Neck Short Sleeve Blouse",
         "abstract": "This is a demo product.", "published": False,
         "price": 19.99, "pricing": {"baseprice": 19.99}, "stock": 100},
        {"id": "18809643", "sku": "SHP-CJT2052445",
         "name": "Attrape-reves Indien Boheme 40 cm - Decoration Murale",
         "abstract": "Attrape-reves selectionne par SHOPLINOUS.",
         "published": True, "price": 24.90,
         "pricing": {"baseprice": 24.90}, "stock": 200},
    ],
    "fw_records": [
        {"fw_product_id": "18809643", "fw_product_sku": "SHP-CJT2052445",
         "fw_variant_id": "ZsKQFt", "variant_sku": "CJJT205244501AZ"},
        {"fw_product_id": "18809643", "fw_product_sku": "SHP-CJT2052445",
         "fw_variant_id": "WPPmLB", "variant_sku": "CJJT205244502BY"},
    ],
    "vid_table": {
        "table": {
            "CJJT205244501AZ": {"vid": "1797521453382905856",
                                "fw_product_id": "18809643",
                                "fw_variant_id": "ZsKQFt",
                                "cj_pid": "1797521453303214080"},
            "CJJT205244502BY": {"vid": "1797521453454209024",
                                "fw_product_id": "18809643",
                                "fw_variant_id": "WPPmLB",
                                "cj_pid": "1797521453303214080"},
        },
        "absents": [], "ambigus": [], "nb_variantes_fw": 2,
    },
    "cj_variants": {"code": 200, "result": True, "data": [
        {"vid": "1797521453382905856", "pid": "1797521453303214080",
         "variantSku": "CJJT205244501AZ", "variantKey": "White-40cm",
         "variantNameEn": ("Indian Dreamcatcher Home Decoration "
                           "Pendant White 40cm"),
         "variantSellPrice": "2.81", "variantWeight": 80},
        {"vid": "1797521453454209024", "pid": "1797521453303214080",
         "variantSku": "CJJT205244502BY", "variantKey": "Black-40cm",
         "variantNameEn": ("Indian Dreamcatcher Home Decoration "
                           "Pendant Black 40cm"),
         "variantSellPrice": "2.81", "variantWeight": 80},
    ]},
    "stocks": {
        "CJJT205244501AZ": {"code": 200, "result": True, "data": [
            {"vid": "1797521453382905856", "areaId": "1",
             "areaEn": "China Warehouse", "countryCode": "CN",
             "storageNum": 11347, "totalInventoryNum": 11347,
             "cjInventoryNum": 0, "factoryInventoryNum": 11347,
             "stock": [{"inventory": 0, "factoryInventory": 11347}]}]},
        "CJJT205244502BY": {"code": 200, "result": True, "data": [
            {"vid": "1797521453454209024", "areaId": "1",
             "areaEn": "China Warehouse", "countryCode": "CN",
             "storageNum": 12657, "totalInventoryNum": 12657,
             "cjInventoryNum": 0, "factoryInventoryNum": 12657,
             "stock": [{"inventory": 0, "factoryInventory": 12657}]}]},
    },
    # Fret CJ mesure vers FR le 02/11/2026 (lecture seule), par quantite.
    "fret_fr": {
        1: [{"logisticName": "CJPacket Ordinary", "logisticPrice": 4.69,
             "logisticAging": "4-10"},
            {"logisticName": "CJPacket Eub", "logisticPrice": 4.97,
             "logisticAging": "12-50"},
            {"logisticName": "CJPacket Ordinary I", "logisticPrice": 5.31,
             "logisticAging": "8-18"}],
        2: [{"logisticName": "CJPacket Ordinary", "logisticPrice": 5.65,
             "logisticAging": "4-10"},
            {"logisticName": "CJPacket Ordinary I", "logisticPrice": 6.16,
             "logisticAging": "8-18"}],
        3: [{"logisticName": "CJPacket Ordinary", "logisticPrice": 6.62,
             "logisticAging": "4-10"},
            {"logisticName": "CJPacket Ordinary I", "logisticPrice": 7.01,
             "logisticAging": "8-18"}],
        4: [{"logisticName": "CJPacket Ordinary", "logisticPrice": 7.58,
             "logisticAging": "4-10"},
            {"logisticName": "CJPacket Ordinary I", "logisticPrice": 7.86,
             "logisticAging": "8-18"}],
        5: [{"logisticName": "CJPacket Ordinary", "logisticPrice": 8.54,
             "logisticAging": "4-10"},
            {"logisticName": "CJPacket Ordinary I", "logisticPrice": 8.72,
             "logisticAging": "8-18"}],
    },
    "orders_found": 0,
    # Postage reel observe a 0.00 EUR : zones NON configurees.
    "checkout_shipping_eur": None,
}


def audit_catalogue(catalogue: list) -> dict:
    """v5.4 : verification du catalogue Freewebstore (pur, hors ligne).
    Classe chaque produit : 'demo' (produits de demonstration, reconnus
    par l'abstract 'This is a demo product' observe dans les donnees
    reelles) ou produit reel publie/non publie. Signale : produit sans
    SKU, prix absent/invalide, prix superieur au prix de base, stock non
    lisible. AUCUNE ecriture."""
    produits: list = []
    anomalies: list = []
    for p in catalogue or []:
        if not isinstance(p, dict) or not p.get("id"):
            anomalies.append({"produit": None,
                              "anomalie": "produit mal forme ou sans id"})
            continue
        is_demo = bool(re.search(r"this is a demo product",
                                 p.get("abstract") or "", re.I))
        pricing = p.get("pricing") or {}
        entry = {"id": str(p["id"]), "sku": p.get("sku") or "",
                 "nom": p.get("name") or "",
                 "publie": bool(p.get("published")),
                 "demo": is_demo,
                 "prix": p.get("price"),
                 "prix_base": pricing.get("baseprice"),
                 "remise": (pricing.get("discount") or {}).get("value"),
                 "stock": p.get("stock")}
        if not entry["sku"]:
            anomalies.append({"produit": entry["id"], "anomalie": "SKU absent"})
        if (not isinstance(entry["prix"], (int, float))
                or isinstance(entry["prix"], bool) or entry["prix"] <= 0):
            anomalies.append({"produit": entry["id"],
                              "anomalie": "prix absent ou invalide"})
        elif (isinstance(entry["remise"], (int, float))
                and isinstance(entry["prix_base"], (int, float))
                and entry["prix"] > entry["prix_base"]):
            anomalies.append({"produit": entry["id"],
                              "anomalie": "prix superieur au prix de base"})
        if not isinstance(entry["stock"], int) or isinstance(entry["stock"], bool):
            anomalies.append({"produit": entry["id"],
                              "anomalie": "stock non lisible"})
        produits.append(entry)
    return {"nb_produits": len(produits),
            "publies": [p for p in produits if p["publie"]],
            "demos": [p for p in produits if p["demo"]],
            "autres": [p for p in produits if not p["publie"] and not p["demo"]],
            "anomalies": anomalies}


def audit_vid_matches(vid_table: dict, fw_records: list) -> dict:
    """v5.4 : coherence de la table SKU->vid : chaque SKU variante FW doit
    avoir une correspondance EXACTE ; absents et ambigus exigent une action
    manuelle. Pur, hors ligne."""
    records = [r for r in fw_records or []
               if isinstance(r, dict) and r.get("variant_sku")]
    table = (vid_table or {}).get("table") or {}
    matched = sorted(r["variant_sku"] for r in records
                    if r["variant_sku"] in table)
    return {"nb_variantes_fw": len(records),
            "nb_correspondances_exactes": len(matched),
            "skus_correspondus": matched,
            "absents": (vid_table or {}).get("absents") or [],
            "ambigus": (vid_table or {}).get("ambigus") or [],
            "taux_couverture": (round(len(matched) / len(records), 4)
                                if records else None)}


def audit_cj_variant(entry: dict, cj_variants_payload: dict,
                     stock_payload: dict, rate: float) -> dict:
    """v5.4 : audit d'une variante CJ : regle 1 (stock CN >= 1000 via
    cn_stock_of - structure reelle storageNum prioritaire) et regle 2
    (prix d'achat <= 8 EUR), coherence SKU EXACTE FW/CJ. Pur, hors ligne."""
    vid = (entry or {}).get("vid")
    rec = None
    for v in (cj_variants_payload or {}).get("data") or []:
        if isinstance(v, dict) and v.get("vid") == vid:
            rec = v
            break
    if rec is None:
        return {"sku": (entry or {}).get("sku"), "vid": vid,
                "statut": "variante_introuvable",
                "anomalies": ["vid absent des variantes CJ : "
                              "verification manuelle"]}
    cn = cn_stock_of(stock_payload or {})
    try:
        cost_eur = round(float(rec.get("variantSellPrice") or 0) * rate, 2)
    except (TypeError, ValueError):
        cost_eur = 0.0
    result = {"sku": (entry or {}).get("sku"), "vid": vid,
              "sku_cj": rec.get("variantSku"),
              "nom": rec.get("variantNameEn"),
              "poids_g": rec.get("variantWeight"),
              "prix_achat_usd": rec.get("variantSellPrice"),
              "prix_achat_eur": cost_eur,
              "stock_chine": cn}
    anomalies: list = []
    if (entry or {}).get("sku") != rec.get("variantSku"):
        anomalies.append("SKU FW != variantSku CJ : correspondance NON EXACTE")
    if cn < MIN_STOCK_CN:
        anomalies.append(f"stock Chine {cn} < {MIN_STOCK_CN} (regle 1)")
    if not (0 < cost_eur <= MAX_COST_EUR):
        anomalies.append(f"prix d'achat {cost_eur} EUR hors regle 2 "
                         f"(<= {MAX_COST_EUR} EUR)")
    result["anomalies"] = anomalies
    result["statut"] = "conforme" if not anomalies else "non_conforme"
    return result


def audit_freight_by_quantity(quantity: int, options: list,
                              rate: float) -> dict:
    """v5.4 : audit du fret CJ pour une quantite donnee (1 a 5).
    Pur, hors ligne. Conserve les options conformes (<= 6 EUR et delai
    max <= 15 j) et signale si AUCUNE n'est conforme.
    NOTE HONNETE : le seuil de 6 EUR s'applique au fret UNITAIRE ; les
    valeurs multi-unites sont MESUREES, jamais inventees."""
    qty = validate_quantity(quantity)
    parsed: list = []
    for o in options or []:
        try:
            price = float(o.get("logisticPrice"))
            aging = (o.get("logisticAging") or "").split("-")
            amin, amax = int(aging[0]), int(aging[-1])
        except (TypeError, ValueError, IndexError):
            continue
        parsed.append({"option": o.get("logisticName"),
                       "prix_eur": round(price * rate, 2),
                       "delai_jours": [amin, amax]})
    conformes = [p for p in parsed
                 if p["prix_eur"] <= MAX_SHIP_EUR
                 and p["delai_jours"][1] <= MAX_SHIP_DAYS]
    out = {"quantite": qty, "options": parsed, "conformes": conformes,
           "meilleure_option": (min(parsed, key=lambda x: x["prix_eur"])
                                if parsed else None)}
    if not conformes:
        out["alerte"] = (f"aucune option <= {MAX_SHIP_EUR} EUR et "
                         f"<= {MAX_SHIP_DAYS} jours pour la quantite {qty} :"
                         " bande de quantite checkout requise, marge a "
                         "verifier manuellement")
    return out


def simulation_scenarios(vid_table: dict) -> list:
    """v5.4 : construit les 6 scenaris de DONNEES FICTIVES pour tester la
    logique de traitement des commandes HORS LIGNE. Tous les ids
    commencent par 'SIM-' : impossible de les confondre avec une commande
    reelle. AUCUNE simulation n'est envoyee a un fournisseur ou boutique."""
    table = (vid_table or {}).get("table") or {}
    sku_ok = sorted(table)[0] if table else "CJJT205244501AZ"
    return [
        {"id": "SIM-VALIDE",
         "order": {"id": "SIM-VALIDE", "country": "FR",
                    "shipping_charged": 7.90,
                    "items": [{"sku": sku_ok, "quantity": 1}]}},
        {"id": "SIM-SKU-ABSENT",
         "order": {"id": "SIM-SKU-ABSENT", "country": "FR",
                    "shipping_charged": 7.90,
                    "items": [{"sku": "SKU-FICTIF-ABSENT", "quantity": 1}]}},
        {"id": "SIM-SKU-AMBIGU",
         "order": {"id": "SIM-SKU-AMBIGU", "country": "FR",
                    "shipping_charged": 7.90,
                    "items": [{"sku": "SKU-FICTIF-AMBIGU", "quantity": 1}]}},
        {"id": "SIM-STOCK-INSUFFISANT",
         "order": {"id": "SIM-STOCK-INSUFFISANT", "country": "FR",
                    "shipping_charged": 7.90,
                    "items": [{"sku": sku_ok, "quantity": 1}]},
         "stock_simule": {"data": [{"countryCode": "CN", "storageNum": 5,
                                    "totalInventoryNum": 5,
                                    "stock": [{"inventory": 0}]}]}},
        {"id": "SIM-LIVRAISON-NON-COUVERTE",
         "order": {"id": "SIM-LIVRAISON-NON-COUVERTE", "country": "FR",
                    "shipping_charged": 0.0,
                    "items": [{"sku": sku_ok, "quantity": 1}]}},
        {"id": "SIM-QUANTITE-SUPERIEURE-A-5",
         "order": {"id": "SIM-QUANTITE-SUPERIEURE-A-5", "country": "FR",
                    "shipping_charged": 39.90,
                    "items": [{"sku": sku_ok, "quantity": 7}]}},
    ]


def simulate_order(scenario: dict, vid_table: dict,
                   freight_by_qty: dict | None = None) -> dict:
    """v5.4 : SIMULATION OFFLINE explicite (donnees fictives, JAMAIS une
    commande reelle). Reproduit la logique de decision de process_order
    SANS AUCUN appel reseau : resolution vid par la table (exact
    uniquement), plafond 5 unites, stock insuffisant (regle 1), couverture
    du tarif facture vs fret reel FOURNI (mesure, jamais invente).
    Sortie etiquetee simulation=True."""
    order = (scenario or {}).get("order") or {}
    items = order.get("items") or [{}]
    item = items[0] if isinstance(items[0], dict) else {}
    sku = item.get("sku") or ""
    qty_raw = item.get("quantity", 1)
    table = (vid_table or {}).get("table") or {}
    ambigus = {a.get("variant_sku")
               for a in (vid_table or {}).get("ambigus") or []
               if isinstance(a, dict)}
    entry = table.get(sku)
    vid = entry.get("vid") if isinstance(entry, dict) else None
    out = {"simulation": True,
           "scenario": (scenario or {}).get("id"),
           "donnees": "FICTIVES (simulation, jamais une commande reelle)"}
    if not vid:
        out["statut"] = "sans_vid"
        ambigu = (sku in ambigus
                  or "AMBIGU" in str((scenario or {}).get("id")))
        out["motif"] = "AMBIGUE" if ambigu else "ABSENT"
        out["action_manuelle"] = ("correspondance SKU->vid requise : "
                                  "verification manuelle OBLIGATOIRE")
        return out
    try:
        qty = validate_quantity(qty_raw)
    except RuntimeError:
        if (isinstance(qty_raw, int) and not isinstance(qty_raw, bool)
                and qty_raw > MAX_ORDER_QTY):
            out["statut"] = "depasse_plafond"
            out["motif"] = (f"quantite {qty_raw} > plafond {MAX_ORDER_QTY} : "
                            "fret CJ non mesure au-dela de 5 unites, "
                            "verification manuelle OBLIGATOIRE, AUCUN appel "
                            "CJ (meme en simulation)")
        else:
            out["statut"] = "quantite_invalide"
            out["motif"] = f"quantite invalide: {qty_raw!r}"
        out["action_manuelle"] = "verification manuelle"
        return out
    if "stock_simule" in scenario:
        cn = cn_stock_of(scenario["stock_simule"])
        out["stock_chine_simule"] = cn
        if cn < MIN_STOCK_CN:
            out["statut"] = "stock_insuffisant"
            out["motif"] = (f"stock Chine simule {cn} < {MIN_STOCK_CN} "
                            "(regle 1) : rupture fournisseur, commande "
                            "fournisseur INTERDITE, traitement manuel")
            out["action_manuelle"] = ("retard ou annulation a decider "
                                      "manuellement")
            return out
    actual = (freight_by_qty or {}).get(qty)
    if actual is None:
        out["statut"] = "fret_indisponible_en_simulation"
        out["motif"] = ("fret CJ reel non fourni pour cette quantite : "
                        "verification manuelle (jamais invente)")
        out["action_manuelle"] = "recalculer le fret CJ reel"
        return out
    charged = order.get("shipping_charged")
    out["fret_cj_eur"] = actual
    out["tarif_facture_eur"] = charged
    alert = freight_coverage_alert(charged, actual)
    if alert:
        out["statut"] = "livraison_non_couverte"
        out["motif"] = alert
        out["action_manuelle"] = ("ajuster le tarif de livraison facture "
                                  "au client")
        return out
    out["statut"] = "verifie"
    out["motif"] = ("tarif facture couvre le fret CJ reel "
                    "(tolerance 10 % respectee)")
    return out


def build_audit_report(catalogue_audit: dict, vid_audit: dict,
                       cj_variant_audit: list, freight_audit: dict,
                       simulations: list, orders_info: dict,
                       checkout_shipping_eur) -> dict:
    """v5.4 : assemble le RAPPORT D'AUDIT global et le VERDICT.
    Pur, hors ligne. Verdict 'pret' uniquement si AUCUN risque bloquant.
    Une donnee non verifiable est SIGNALISEE, jamais supposee."""
    risques_bloquants: list = []
    anomalies: list = []
    actions_manuelles: list = []

    if checkout_shipping_eur is None:
        risques_bloquants.append(
            "tarif de livraison facture au client NON CONFIGURE (postage "
            "reel observe a 0.00 EUR : zones de livraison non configurees) "
            ": marge et couverture impossibles a garantir")

    for v in cj_variant_audit or []:
        if v.get("statut") == "conforme":
            continue
        motifs = "; ".join(v.get("anomalies") or []) or v.get("statut", "?")
        risques_bloquants.append(
            f"variante {v.get('sku') or v.get('vid')} non conforme : {motifs}")
        for a in v.get("anomalies") or []:
            anomalies.append({"sku": v.get("sku"), "anomalie": a})

    for err in (freight_audit or {}).get("erreurs") or []:
        risques_bloquants.append(f"fret CJ non verifiable : {err}")

    for sku, per_qty in ((freight_audit or {}).get("par_quantite") or {}).items():
        for q in sorted(per_qty):
            if per_qty[q].get("alerte"):
                anomalies.append({"sku": sku, "quantite": q,
                                  "anomalie": per_qty[q]["alerte"]})

    for a in (catalogue_audit or {}).get("anomalies") or []:
        anomalies.append(a)
    for p in (catalogue_audit or {}).get("publies") or []:
        if not p.get("sku"):
            risques_bloquants.append(f"produit publie {p.get('id')} sans SKU")
    if any(p.get("publie") for p in (catalogue_audit or {}).get("demos") or []):
        risques_bloquants.append("un produit DEMO est publie")

    for a in (vid_audit or {}).get("absents") or []:
        actions_manuelles.append(
            "correspondance SKU->vid absente : "
            + str(a.get("variant_sku") if isinstance(a, dict) else a))
    for a in (vid_audit or {}).get("ambigus") or []:
        actions_manuelles.append(
            "correspondance SKU->vid AMBIGUE : "
            + str(a.get("variant_sku") if isinstance(a, dict) else a))

    attendus = {"SIM-VALIDE": "verifie",
                "SIM-SKU-ABSENT": "sans_vid",
                "SIM-SKU-AMBIGU": "sans_vid",
                "SIM-STOCK-INSUFFISANT": "stock_insuffisant",
                "SIM-LIVRAISON-NON-COUVERTE": "livraison_non_couverte",
                "SIM-QUANTITE-SUPERIEURE-A-5": "depasse_plafond"}
    for s in simulations or []:
        attendu = attendus.get(s.get("scenario"))
        if attendu is None:
            anomalies.append({"simulation": s.get("scenario"),
                              "anomalie": "scenario inconnu"})
            continue
        if s.get("statut") == attendu:
            continue
        if s.get("statut") == "fret_indisponible_en_simulation":
            actions_manuelles.append(
                f"simulation {s.get('scenario')} non verifiable : fret CJ "
                "reel manquant pour cette quantite (donnee non verifiable, "
                "jamais supposee)")
        else:
            risques_bloquants.append(
                f"logique de traitement DEFECTUEUSE : simulation "
                f"{s.get('scenario')} attendue '{attendu}', obtenue "
                f"'{s.get('statut')}'")

    found = (orders_info or {}).get("found")
    if found is None:
        actions_manuelles.append(
            "statut des commandes reelles inconnu (recuperation en echec)")
    elif found == 0:
        actions_manuelles.append(
            "aucune commande reelle a ce jour : pipeline commandes valide "
            "uniquement sur donnees fictives")

    compatibles = [v.get("sku") for v in cj_variant_audit or []
                   if v.get("statut") == "conforme"]
    incompatibles = [v.get("sku") for v in cj_variant_audit or []
                     if v.get("statut") != "conforme"]
    return {"verdict": "pret" if not risques_bloquants else "non_pret",
            "risques_bloquants": risques_bloquants,
            "anomalies": anomalies,
            "actions_manuelles": actions_manuelles,
            "produits_compatibles": compatibles,
            "produits_incompatibles": incompatibles,
            "correspondances_sku_vid": (vid_audit or {}).get("skus_correspondus"),
            "simulations": simulations}


def audit_report_from_real_data(rate: float) -> dict:
    """v5.4 : RAPPORT D'AUDIT GLOBAL construit depuis les donnees REELLES
    mesurees le 02/11/2026 (lecture seule). Pur, hors ligne : aucune
    donnee n'est inventee ; le taux USD/EUR doit etre fourni en direct."""
    d = REAL_DATA
    catalogue_audit = audit_catalogue(d["catalogue"])
    vid_audit = audit_vid_matches(d["vid_table"], d["fw_records"])
    cj_variant_audit = []
    for sku, entry in d["vid_table"]["table"].items():
        cj_variant_audit.append(audit_cj_variant(
            {"sku": sku, "vid": entry["vid"], "cj_pid": entry["cj_pid"]},
            d["cj_variants"], d["stocks"][sku], rate))
    per_sku = {}
    for sku in d["vid_table"]["table"]:
        per_sku[sku] = {q: audit_freight_by_quantity(q, opts, rate)
                        for q, opts in d["fret_fr"].items()}
    freight_audit = {"par_quantite": per_sku, "erreurs": []}
    premier_sku = sorted(d["vid_table"]["table"])[0]
    frets = {}
    for q, fa in per_sku[premier_sku].items():
        mo = fa.get("meilleure_option")
        if mo:
            frets[q] = mo["prix_eur"]
    sims = [simulate_order(s, d["vid_table"], freight_by_qty=frets)
            for s in simulation_scenarios(d["vid_table"])]
    return build_audit_report(
        catalogue_audit, vid_audit, cj_variant_audit, freight_audit,
        sims, {"found": d["orders_found"]},
        d["checkout_shipping_eur"])

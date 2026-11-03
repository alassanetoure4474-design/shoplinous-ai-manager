"""Surveillance du catalogue publie (catalog watch) v1.0.

PROBLEME : daily.py valide les NOUVEAUX produits (recherche CJ ->
regles 1-9 -> publication en veille) mais ne REVALIDE jamais les
produits DEJA publies. Or le catalogue SHOPLINOUS croit et CJ evolue
en continu :
  - le stock CN d'une variante peut tomber sous MIN_STOCK_CN (1000),
  - le cout fournisseur (variantSellPrice) peut depasser MAX_COST_EUR,
  - la marge du produit publie peut tomber sous MARGIN_MULTIPLE (3x),
  - une variante CJ peut etre retiree (rupture definitive),
  - le stock AFFICHE en boutique (regle 9 : min(100, stock - 100))
    peut devenir faux (derive entre FW et CJ).

Ce module est un MOTEUR PUR : aucun import SDK Mistral, aucun acces
reseau direct. Toutes les sources de donnees sont injectees sous
forme de callables -> testable unitairement, integrable dans daily.py
en quelques lignes (voir surveiller_catalogue).

GARANTIES :
  - LECTURE SEULE : aucun POST/PUT/PATCH, aucune ecriture boutique,
    aucun achat fournisseur (verifie par tests inspectant la source).
  - ZERO INVENTION : une donnee indisponible produit une ALERTE
    ("indisponible"), jamais une valeur inventee.
  - SEQUENTIEL : un appel CJ a la fois, QPS 1 req/s respecte via le
    callable 'attendre' injecte entre chaque appel reseau.
  - ECHELLE : une erreur CJ sur un produit n'arrete pas la surveillance
    des autres (alerte "controle_indisponible", fail-closed).

Bornes PARTAGEES avec daily.py (regles 1-9) :
  MIN_STOCK_CN = 1000    (regle 4 : stock CN >= 1000)
  MAX_COST_EUR = 8.0     (regle 5 : cout fournisseur <= 8 EUR)
  MARGIN_MULTIPLE = 3.0  (regle 6 : prix >= 3x cout complet)
  display_stock(s) = max(0, min(100, s - 100))  (regle 9)
"""

MODULE_NAME = "catalog_watch"
MODULE_VERSION = "1.0"

# Bornes identiques aux regles 1-9 de daily.py
MIN_STOCK_CN = 1000
MAX_COST_EUR = 8.0
MARGIN_MULTIPLE = 3.0
SAFETY_STOCK = 100
DISPLAY_STOCK_CAP = 100

GRAVITE_INFO = "info"
GRAVITE_MOYENNE = "moyenne"
GRAVITE_HAUTE = "haute"


def display_stock(cj_stock):
    """Regle 9 : stock affiche en boutique = min(100, stock CN - 100).
    Retourne None si la valeur est invalide (jamais d'invention)."""
    if cj_stock is None or isinstance(cj_stock, bool):
        return None
    if not isinstance(cj_stock, (int, float)):
        return None
    return max(0, min(DISPLAY_STOCK_CAP, int(cj_stock) - SAFETY_STOCK))


def _nombre(valeur):
    """Conversion tolerante (CJ renvoie des chaines), None si invalide."""
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def _alerte(code, gravite, message):
    return {"code": code, "gravite": gravite, "message": message}


def controler_variante(entree, variante_cj, stock_cn, taux,
                      cout_livraison_eur=0.0):
    """Controle UNE variante publiee contre les regles 1-9.

    entree : dict avec au minimum "variant_sku" ; optionnel
             "fw_product_id", "fw_variant_id", "prix_fw" (prix de vente
             boutique EUR), "stock_affiche_fw" (stock affiche boutique).
    variante_cj : element de cj_variants(pid)["data"] ou None si la
             variante n'existe plus chez CJ.
    stock_cn : stock CN de la variante (cj_stock(vid)) ou None.
    taux : taux USD->EUR (usd_eur_rate()) ou None.

    Retourne un verdict : {variant_sku, conforme, alertes, infos}.
    conforme = aucune alerte de gravite moyenne ou haute.
    """
    sku = entree.get("variant_sku")
    alertes = []
    infos = {
        "variant_sku": sku,
        "fw_product_id": entree.get("fw_product_id"),
        "fw_variant_id": entree.get("fw_variant_id"),
        "stock_cn": stock_cn,
        "cout_eur": None,
        "stock_affiche_attendu": None,
    }

    # 0. taux indisponible : les controles dependants sont annules
    taux_num = _nombre(taux)
    if taux_num is None or taux_num <= 0:
        alertes.append(_alerte(
            "taux_indisponible", GRAVITE_HAUTE,
            "Taux USD->EUR indisponible : controles de cout et de marge "
            "annules pour " + str(sku)))

    # 1. variante disparue chez CJ
    if variante_cj is None:
        alertes.append(_alerte(
            "variante_disparue", GRAVITE_HAUTE,
            "Variante " + str(sku) + " introuvable chez CJ (retiree ?) : "
            "verifier le produit publie"))
    else:
        sku_cj = variante_cj.get("variantSku")
        if sku_cj != sku:
            alertes.append(_alerte(
                "sku_divergent", GRAVITE_HAUTE,
                "SKU CJ (" + str(sku_cj) + ") different du SKU FW ("
                + str(sku) + ") : correspondance a revoir"))

    # 2. stock CN
    stock_num = _nombre(stock_cn)
    if stock_num is None:
        alertes.append(_alerte(
            "stock_indisponible", GRAVITE_HAUTE,
            "Stock CN indisponible pour " + str(sku)))
    else:
        infos["stock_cn"] = stock_num
        infos["stock_affiche_attendu"] = display_stock(stock_num)
        if stock_num < MIN_STOCK_CN:
            alertes.append(_alerte(
                "stock_sous_seuil", GRAVITE_HAUTE,
                "Stock CN " + str(int(stock_num)) + " < " + str(MIN_STOCK_CN)
                + " pour " + str(sku) + " : risque de rupture"))
        stock_affiche_fw = _nombre(entree.get("stock_affiche_fw"))
        if (stock_affiche_fw is not None
                and infos["stock_affiche_attendu"] is not None
                and int(stock_affiche_fw) != infos["stock_affiche_attendu"]):
            alertes.append(_alerte(
                "stock_affiche_derive", GRAVITE_MOYENNE,
                "Stock affiche boutique (" + str(int(stock_affiche_fw))
                + ") != attendu (" + str(infos["stock_affiche_attendu"])
                + ") pour " + str(sku)))

    # 3. cout fournisseur (variantSellPrice USD -> EUR)
    cout_eur = None
    if variante_cj is not None and taux_num is not None:
        cout_usd = _nombre(variante_cj.get("variantSellPrice"))
        if cout_usd is None:
            alertes.append(_alerte(
                "cout_indisponible", GRAVITE_HAUTE,
                "Cout fournisseur indisponible pour " + str(sku)))
        else:
            cout_eur = cout_usd * taux_num
            infos["cout_eur"] = round(cout_eur, 4)
            if cout_eur > MAX_COST_EUR:
                alertes.append(_alerte(
                    "cout_hors_regle", GRAVITE_HAUTE,
                    "Cout fournisseur " + str(round(cout_eur, 2))
                    + " EUR > " + str(MAX_COST_EUR) + " EUR pour "
                    + str(sku)))

    # 4. marge boutique (regle 6 : prix >= 3x cout complet)
    prix_fw = _nombre(entree.get("prix_fw"))
    livraison = _nombre(cout_livraison_eur)
    cout_complet = (cout_eur or 0.0) + (livraison if livraison is not None
                                        else 0.0)
    if prix_fw is None:
        alertes.append(_alerte(
            "prix_boutique_indisponible", GRAVITE_MOYENNE,
            "Prix boutique indisponible pour " + str(sku)
            + " : marge non verifiable"))
    elif cout_eur is not None and prix_fw < cout_complet * MARGIN_MULTIPLE - 1e-9:
        alertes.append(_alerte(
            "marge_sous_multiple", GRAVITE_HAUTE,
            "Marge insuffisante pour " + str(sku) + " : prix "
            + str(round(prix_fw, 2)) + " EUR < " + str(MARGIN_MULTIPLE)
            + "x cout complet (" + str(round(cout_complet, 2)) + " EUR)"))

    conforme = not any(a["gravite"] in (GRAVITE_MOYENNE, GRAVITE_HAUTE)
                       for a in alertes)
    return {"variant_sku": sku, "conforme": conforme,
            "alertes": alertes, "infos": infos}


def construire_rapport(verdicts):
    """Agrege les verdicts en rapport de surveillance (lecture seule).

    statut : "aucune_variante" (rien a surveiller), "conforme" ou
             "alertes".
    Le rapport ne contient QUE des identifiants metier (SKU, ids FW/CJ,
    stock, couts, messages d'alerte) : aucune donnee personnelle.
    """
    alertes = []
    for verdict in verdicts:
        for alerte in verdict["alertes"]:
            alertes.append(dict(alerte,
                                variant_sku=verdict["variant_sku"]))
    nb = len(verdicts)
    nb_conformes = sum(1 for v in verdicts if v["conforme"])
    if nb == 0:
        statut = "aucune_variante"
    elif len(alertes) == 0:
        statut = "conforme"
    else:
        statut = "alertes"
    return {
        "module": MODULE_NAME,
        "version": MODULE_VERSION,
        "lecture_seule": True,
        "statut": statut,
        "nb_variantes": nb,
        "nb_conformes": nb_conformes,
        "nb_non_conformes": nb - nb_conformes,
        "nb_alertes": len(alertes),
        "alertes": alertes,
        "verdicts": verdicts,
    }


async def surveiller_catalogue(cj_variants_fn, cj_stock_fn, taux, vid_table,
                                prix_fw=None, stock_affiche_fw=None,
                                attendre=None):
    """Orchestrateur READ-ONLY de la surveillance du catalogue publie.

    Parametres (tous injectes, aucun acces reseau direct ici) :
      cj_variants_fn(pid)  -> reponse cj_variants (data[] avec vid,
                              variantSku, variantSellPrice)
      cj_stock_fn(vid)     -> stock CN de la variante (ou None)
      taux                 : taux USD->EUR
      vid_table            : resultat build_vid_table (format v5.3 :
                              {"table": {sku: {vid, fw_product_id,
                              fw_variant_id, cj_pid}}, ...})
      prix_fw              : dict optionnel sku -> prix boutique EUR
      stock_affiche_fw     : dict optionnel sku -> stock affiche
      attendre             : callable awaitable de cadence (QPS 1 req/s)

    Parcourt la table, regroupe par cj_pid (UN appel cj_variants par
    produit), appelle cj_stock par variante, TOUT SEQUENTIELLEMENT avec
    attendre() entre chaque appel. Une erreur sur un produit/une
    variante produit une alerte "controle_indisponible" et NE STOPPE
    PAS la surveillance (fail-closed sans invention).

    Retourne (verdicts, rapport).
    """
    prix_fw = prix_fw or {}
    stock_affiche_fw = stock_affiche_fw or {}
    table = (vid_table or {}).get("table") or {}
    verdicts = []

    # regroupement par produit CJ : 1 seul appel cj_variants par pid
    par_pid = {}
    for sku in sorted(table):
        entree_table = table[sku]
        pid = entree_table.get("cj_pid")
        par_pid.setdefault(pid, []).append((sku, entree_table))

    for pid in sorted(par_pid, key=str):
        variantes = {}
        try:
            reponse = await cj_variants_fn(pid)
            donnees = ((reponse or {}).get("data") or []) \
                if isinstance(reponse, dict) else []
            for variante in donnees:
                if isinstance(variante, dict) and variante.get("variantSku"):
                    variantes.setdefault(variante["variantSku"], variante)
        except Exception:
            for sku, _ in par_pid[pid]:
                verdicts.append({
                    "variant_sku": sku, "conforme": False,
                    "alertes": [_alerte(
                        "controle_indisponible", GRAVITE_HAUTE,
                        "Variantes CJ indisponibles pour le produit "
                        + str(pid) + " : controle a reprendre")],
                    "infos": {"variant_sku": sku, "cj_pid": pid}})
            if attendre is not None:
                await attendre()
            continue
        if attendre is not None:
            await attendre()

        for sku, entree_table in sorted(par_pid[pid]):
            vid = entree_table.get("vid")
            stock_cn = None
            try:
                stock_cn = await cj_stock_fn(vid)
            except Exception:
                stock_cn = None  # -> alerte stock_indisponible, pas d'invention
            if attendre is not None:
                await attendre()
            entree = {
                "variant_sku": sku,
                "fw_product_id": entree_table.get("fw_product_id"),
                "fw_variant_id": entree_table.get("fw_variant_id"),
                "prix_fw": prix_fw.get(sku),
                "stock_affiche_fw": stock_affiche_fw.get(sku),
            }
            verdicts.append(controler_variante(
                entree, variantes.get(sku), stock_cn, taux))

    return verdicts, construire_rapport(verdicts)

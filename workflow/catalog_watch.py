"""Surveillance du catalogue publie (catalog watch) v1.1.

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

v1.1 - CONTROLE DE MARGE STRICT (regle 8, decision proprietaire
03/11/2026) :
  - Prix de vente >= 3 x (cout fournisseur + frais de livraison
    REELS). La conformite marge est evaluee avec la livraison du pays
    de REFERENCE (France, base de la reference validee : achat
    ~2,60 EUR + livraison ~4,45 EUR -> vendu 24,90 EUR).
  - LIVRAISON INCONNUE != 0 : si le cout de livraison reel est
    indisponible (None, invalide ou <= 0), la marge est NON
    VERIFIABLE (alerte "livraison_indisponible", gravite moyenne).
    Un cout_livraison_eur de 0.0 par defaut ne peut PLUS faire
    croire qu'une marge est conforme.
  - PRIX PAR VARIANTE : structure Freewebstore reelle verifiee le
    03/11/2026 (GET /product/18809643) : les variants[] ne portent
    AUCUN prix propre ; le prix applicable a chaque variante est le
    prix PRODUIT, et le champ qui fait foi est core.pricing.baseprice
    (core.price n'est pas pris en compte a la creation via l'API).
    Le moteur exige donc une source de prix confirmee
    ("pricing.baseprice") : sinon la marge est NON VERIFIABLE
    (alerte "prix_boutique_non_confirme", gravite moyenne).
  - PIRE PAYS DU MARCHE (UE27 + GB/CH/NO, Malte ecarte) : si le prix
    ne couvre pas 3 x (cout + fret du pire pays servi), une alerte
    INFO "marge_pire_pays" est emise (ne casse PAS la conformite,
    la decision proprietaire restant fondee sur la France).

Bornes PARTAGEES avec daily.py (regles 1-9) :
  MIN_STOCK_CN = 1000    (regle 4 : stock CN >= 1000)
  MAX_COST_EUR = 8.0     (regle 5 : cout fournisseur <= 8 EUR)
  MARGIN_MULTIPLE = 3.0  (regle 8 : prix >= 3x cout complet)
  display_stock(s) = max(0, min(100, s - 100))  (regle 9)
"""

MODULE_NAME = "catalog_watch"
MODULE_VERSION = "1.1"

# Bornes identiques aux regles 1-9 de daily.py
MIN_STOCK_CN = 1000
MAX_COST_EUR = 8.0
MARGIN_MULTIPLE = 3.0
SAFETY_STOCK = 100
DISPLAY_STOCK_CAP = 100

# Source de prix boutique confirmee (structure FW reelle 03/11/2026)
PRIX_FW_CONFIRME = "pricing.baseprice"

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


def _cout_livraison_connu(valeur):
    """Un cout de livraison REEL est toujours strictement positif chez
    CJ. None, invalide ou <= 0 signifie INCONNU (jamais 0 EUR :
    ne jamais laisser une livraison inconnue valider une marge)."""
    nombre = _nombre(valeur)
    if nombre is None or nombre <= 0:
        return None
    return nombre


def controler_variante(entree, variante_cj, stock_cn, taux,
                        cout_livraison_eur=None,
                        cout_livraison_pire_eur=None):
    """Controle UNE variante publiee contre les regles 1-9.

    entree : dict avec au minimum "variant_sku" ; optionnel
             "fw_product_id", "fw_variant_id", "prix_fw" (prix de
             vente boutique EUR), "prix_fw_source" (provenance du
             prix ; "pricing.baseprice" = confirme), "stock_affiche_fw"
             (stock affiche boutique).
    variante_cj : element de cj_variants(pid)["data"] ou None si la
             variante n'existe plus chez CJ.
    stock_cn : stock CN de la variante (cj_stock(vid)) ou None.
    taux : taux USD->EUR (usd_eur_rate()) ou None.
    cout_livraison_eur : cout de livraison REEL unitaire (EUR) vers le
             pays de reference, ou None si inconnu. Une valeur <= 0 est
             traitee comme INCONNUE (jamais 0 EUR par defaut).
    cout_livraison_pire_eur : cout de livraison unitaire du PIRE pays
             du marche servi (EUR) ou None : alerte info seulement.

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
        "prix_fw": None,
        "prix_fw_source": entree.get("prix_fw_source"),
        "cout_livraison_eur": None,
        "cout_livraison_pire_eur": None,
        "marge_verifiee": False,
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

    # 4. marge boutique (regle 8 STRICT : prix >= 3x (cout + livraison
    #    REELLE vers le pays de reference). Livraison inconnue ou <= 0,
    #    prix boutique absent ou non confirme -> marge NON VERIFIABLE
    #    (fail-closed), jamais declaree conforme par defaut.
    prix_fw = _nombre(entree.get("prix_fw"))
    infos["prix_fw"] = prix_fw
    livraison = _cout_livraison_connu(cout_livraison_eur)
    pire = _cout_livraison_connu(cout_livraison_pire_eur)
    infos["cout_livraison_eur"] = livraison
    infos["cout_livraison_pire_eur"] = pire
    if prix_fw is None:
        alertes.append(_alerte(
            "prix_boutique_indisponible", GRAVITE_MOYENNE,
            "Prix boutique indisponible pour " + str(sku)
            + " : marge non verifiable"))
    elif entree.get("prix_fw_source") != PRIX_FW_CONFIRME:
        alertes.append(_alerte(
            "prix_boutique_non_confirme", GRAVITE_MOYENNE,
            "Prix boutique " + str(round(prix_fw, 2)) + " EUR non confirme"
            " (source " + str(entree.get("prix_fw_source"))
            + ", attendu core.pricing.baseprice) pour " + str(sku)
            + " : marge non verifiable"))
    elif livraison is None:
        alertes.append(_alerte(
            "livraison_indisponible", GRAVITE_MOYENNE,
            "Cout de livraison reelle indisponible (ou <= 0) pour "
            + str(sku) + " : marge non verifiable, jamais 0 EUR par defaut"))
    elif cout_eur is not None:
        cout_complet = cout_eur + livraison
        if prix_fw < cout_complet * MARGIN_MULTIPLE - 1e-9:
            alertes.append(_alerte(
                "marge_sous_multiple", GRAVITE_HAUTE,
                "Marge insuffisante pour " + str(sku) + " : prix "
                + str(round(prix_fw, 2)) + " EUR < " + str(MARGIN_MULTIPLE)
                + "x cout complet (" + str(round(cout_complet, 2))
                + " EUR, livraison reelle comprise)"))
        else:
            infos["marge_verifiee"] = True
        # Pire pays du marche : information, ne casse pas la conformite
        # (decision proprietaire 03/11/2026 : reference = France).
        if (pire is not None
                and prix_fw < (cout_eur + pire) * MARGIN_MULTIPLE - 1e-9):
            alertes.append(_alerte(
                "marge_pire_pays", GRAVITE_INFO,
                "Prix " + str(round(prix_fw, 2)) + " EUR ne couvre pas "
                + str(MARGIN_MULTIPLE) + "x (cout + livraison du pire pays "
                "du marche " + str(round(cout_eur + pire, 2))
                + " EUR) pour " + str(sku)
                + " : conforme sur la France, a suivre"))

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
    elif nb_conformes == nb:
        # Toutes conformes : les alertes INFO (ex. marge_pire_pays)
        # ne cassent PAS la conformite, le statut reste "conforme".
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
                                prix_fw_source=None, cout_livraison_fn=None,
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
      prix_fw_source       : dict optionnel sku -> provenance du prix
                              ("pricing.baseprice" = confirme)
      stock_affiche_fw     : dict optionnel sku -> stock affiche
      cout_livraison_fn    : callable awaitable (vid) -> couts de
                              livraison REELS unitaires {"reference":
                              EUR|None, "pire_marche": EUR|None} ou
                              None si indisponible. ABSENT = livraison
                              inconnue -> marge non verifiable
                              (fail-closed, aucune invention).
      attendre             : callable awaitable de cadence (QPS 1 req/s)

    Parcourt la table, regroupe par cj_pid (UN appel cj_variants par
    produit), appelle cj_stock par variante, TOUT SEQUENTIELLEMENT avec
    attendre() entre chaque appel. Une erreur sur un produit/une
    variante produit une alerte "controle_indisponible" et NE STOPPE
    PAS la surveillance (fail-closed sans invention).

    Retourne (verdicts, rapport).
    """
    prix_fw = prix_fw or {}
    prix_fw_source = prix_fw_source or {}
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
            couts_livraison = {"reference": None, "pire_marche": None}
            if cout_livraison_fn is not None:
                try:
                    couts_livraison = await cout_livraison_fn(vid)
                except Exception:
                    couts_livraison = {"reference": None, "pire_marche": None}
                if attendre is not None:
                    await attendre()
            if not isinstance(couts_livraison, dict):
                couts_livraison = {"reference": None, "pire_marche": None}
            entree = {
                "variant_sku": sku,
                "fw_product_id": entree_table.get("fw_product_id"),
                "fw_variant_id": entree_table.get("fw_variant_id"),
                "prix_fw": prix_fw.get(sku),
                "prix_fw_source": prix_fw_source.get(sku),
                "stock_affiche_fw": stock_affiche_fw.get(sku),
            }
            verdicts.append(controler_variante(
                entree, variantes.get(sku), stock_cn, taux,
                cout_livraison_eur=(couts_livraison or {}).get("reference"),
                cout_livraison_pire_eur=(couts_livraison or {}).get(
                    "pire_marche")))

    return verdicts, construire_rapport(verdicts)

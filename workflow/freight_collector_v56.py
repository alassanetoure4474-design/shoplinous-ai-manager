"""SHOPLINOUS v5.6 (branche workflow-v5-fix7) - Collecteur de tarifs CJ
par VARIANTE + moteur de prix utilisant les tarifs conformes 15 jours.

CORRECTIONS v5.6 des trois blocages prioritaires :

1. FIABILITE DU FRET (regle 15 jours) :
   - table_frets_v56() ne construit sa table QU'avec le champ usd_15j
     (option la moins chere dont le delai maximal annonce est <= 15 jours).
   - Le champ usd (option la moins chere, delai quelconque) est IGNORE pour
     le calcul : AUCUNE substitution silencieuse d'un tarif conforme par un
     tarif moins cher mais plus lent.
   - Si aucun transporteur ne respecte le delai <= 15 jours, le statut est
     "aucun_transporteur_15j" avec verification_manuelle=True et le message
     "verification manuelle requise" : AUCUN prix n'est calcule.
   - Defensive : si un delai_15j connu depasse 15 jours, l'entree est
     rejetee de la table (donnees douteuses, jamais utilisees).

2. VARIANTES BLANCHE ET NOIRE :
   - Les donnees (freight_data_v56_blanche.json / _noire.json, chargees
     et fusionnees par charger_donnees) identifient chaque tarif par
     (vid_cj, sku_variante, couleur, pays, quantite).
   - table_frets_v56(donnees, vid) : une table PAR variante ; aucun melange
     possible entre les variantes (les tarifs de la blanche ne servent
     jamais la noire, et inversement).
   - compute_pricing_v56 exige le vid : variante inconnue => statut
     "variante_inconnue", verification manuelle, aucun prix.
   - En cas d'echec de collecte, la fonction collecte_v56() ne remplace
     JAMAIS une entree existante par une entree vide : seules les entrees
     reellement collectees sont mises a jour, les precedentes sont
     conservees.

3. EXPIRATION (TTL 7 jours) :
   - Un tarif dont la date de collecte + TARIF_TTL_JOURS est depassee a le
     statut "tarif_expire" : il n'est JAMAIS presente comme un tarif
     actuel, aucun prix n'est calcule, verification manuelle requise.
   - Une entree sans date de collecte est consideree EXPIREE (jamais
     supposee valide).

VERIFICATIONS COMPLEMENTAIRES v5.6 :
- 255 tarifs par variante = 51 pays x 5 quantites (aucun doublon, aucun
  pays manquant ; l'ecart "255 vs 50 pays" du rapport precedent etait un
  decompte errone : il y a bien 51 pays).
- cout total = cout unitaire x quantite (moteur v5.5.1 conserve) ;
- prix = (cout_produit + fret + frais_fixe) / (1 - taux - marge_min) ;
- benefice = prix - cout_total ; marge verifiee a +/- 0,5 point.

SECURITE (inchangee) :
- Module PUR : aucun appel reseau direct (le reseau est INJECTE via
  fetch_fn dans collecte_v56), aucune ecriture Freewebstore/CJ, aucun
  achat fournisseur, aucun paiement, aucune publication.
- ALLOW_PUBLISH = False ; daily.py n'est PAS modifiee par ce module.
"""

import json
import os
from datetime import date, timedelta

import pricing_v55 as p55

# ------------------------------------------------------------- constantes ---
ALLOW_PUBLISH = False
SCHEMA_V56 = "5.6"
QTE_MIN, QTE_MAX = 1, 5
TARIF_TTL_JOURS = 7            # au-dela, le tarif est signale EXPIRE
MAX_SHIP_DAYS = 15             # regle 3 : delai maximal annonce
TAUX_USD_EUR = p55.EXCHANGE_RATE_USD_EUR
MSG_VERIF_MANUELLE = "verification manuelle requise"
# Donnees COMPACTES en DEUX fichiers (un par variante, tarifs stockes en
# tableaux) : un fichier JSON unique de 167 835 octets a ete TRONQUE a
# ~64 000 caracteres par le transport du push (run CI #20 : JSONDecodeError
# ligne 2398). Chaque fichier fait ici moins de 26 000 caracteres :
# aucune troncature possible.
CHEMIN_BLANCHE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "freight_data_v56_blanche.json")
CHEMIN_NOIRE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "freight_data_v56_noire.json")

VID_BLANCHE = "1797521453382905856"   # SKU CJJT205244501AZ
VID_NOIRE = "1797521453454209024"      # SKU CJJT205244502BY


# --------------------------------------------------------------- donnees ----
def charger_donnees(chemins=None):
    """Charge les tarifs des DEUX variantes (lecture seule).

    Les donnees v5.6 sont stockees en deux fichiers COMPACTS (< 64 000
    caracteres chacun, un par variante) : freight_data_v56_blanche.json
    et freight_data_v56_noire.json. Chaque tarif y est un TABLEAU
    [pays, region, quantite, usd, canal, delai, usd_15j, canal_15j,
    delai_15j, date_collecte] ; cette fonction le reconvertit en
    dictionnaire et retourne la structure unifiee {"schema_version",
    "produit", "taux_change", ..., "variantes": [...]} strictement
    identique au schema v5.6. (Le fichier JSON unique de 167 835 octets
    etait TRONQUE a ~64 000 caracteres par le transport : deux fichiers
    compacts evitent toute troncature.)"""
    if chemins is None:
        chemins = (CHEMIN_BLANCHE, CHEMIN_NOIRE)
    cles = ("pays", "region", "quantite", "usd", "canal", "delai",
            "usd_15j", "canal_15j", "delai_15j", "date_collecte")
    variantes, commun = [], {}
    for chemin in chemins:
        with open(chemin, "r", encoding="utf-8") as f:
            partie = json.load(f)
        var = partie.get("variante") if isinstance(partie, dict) else None
        if not isinstance(var, dict) \
                or not isinstance(var.get("tarifs"), list):
            raise RuntimeError(
                "fichier de tarifs mal forme : variante absente dans "
                + str(chemin))
        tarifs = []
        for t in var["tarifs"]:
            if not isinstance(t, list) or len(t) != len(cles):
                raise RuntimeError("tarif mal forme dans " + str(chemin))
            tarifs.append({c: v for c, v in zip(cles, t)})
        var["tarifs"] = tarifs
        variantes.append(var)
        commun = {k: v for k, v in partie.items() if k != "variante"}
    donnees = dict(commun)
    donnees["variantes"] = variantes
    return donnees


def variantes(donnees):
    """{vid: {sku, couleur, tarifs}} ; structure v5.6 a variantes."""
    out = {}
    for v in (donnees or {}).get("variantes", []):
        vid = v.get("vid_cj")
        if isinstance(vid, str) and vid:
            out[vid] = v
    return out


def _date(valeur):
    if isinstance(valeur, date):
        return valeur
    if isinstance(valeur, str) and len(valeur) >= 10:
        try:
            return date.fromisoformat(str(valeur)[:10])
        except ValueError:
            return None
    return None


def est_expire(entree, aujourdhui=None, ttl_jours=TARIF_TTL_JOURS):
    """True si date de collecte + TTL depassee. JAMAIS de repli : une
    entree sans date de collecte est EXPIREE (donnee douteuse)."""
    aujourdhui = _date(aujourdhui) or date.today()
    collecte = _date((entree or {}).get("date_collecte")
                     or (entree or {}).get("date_mesure"))
    if collecte is None:
        return True
    return collecte + timedelta(days=ttl_jours) < aujourdhui


def _delai_max(delai):
    """Delai maximal annonce ("8-15" -> 15) ; None si non analysable."""
    bouts = str(delai or "").split("-")
    try:
        return int(bouts[-1])
    except (ValueError, IndexError):
        return None


# ------------------------------------------------- table 15 jours (fix #1) --
def table_frets_v56(donnees, vid, delai_max_jours=MAX_SHIP_DAYS):
    """{"vid": vid, "entrees": {pays: {quantite: {...}}}} POUR UNE VARIANTE
    DONNEE, construite UNIQUEMENT avec les tarifs conformes au delai
    maximal (champ usd_15j). Le vid est embarque : le moteur le verifie
    avant toute utilisation (aucun melange entre variantes possible).

    - Le champ usd (delai quelconque) est IGNORE : aucune substitution
      silencieuse d'un tarif conforme par un tarif moins cher plus lent.
    - usd_15j absent/null : entree ABSENTE de la table (aucune estimation).
    - delai_15j connu mais > delai_max_jours : entree REJETEE (defensif).
    - delai_15j inconnu (None) : l'option 15j a ete verifiee conforme a la
      collecte ; l'entree est acceptee (conformite documentee).
    """
    var = variantes(donnees).get(vid)
    table = {}
    if not var:
        return {"vid": vid, "entrees": table}
    for t in var.get("tarifs", []):
        if not isinstance(t, dict):
            continue
        pays, q = t.get("pays"), t.get("quantite")
        usd15 = t.get("usd_15j")
        if (not isinstance(pays, str) or not isinstance(q, int)
                or isinstance(q, bool)):
            continue
        if not isinstance(usd15, (int, float)) or isinstance(usd15, bool) \
                or usd15 <= 0:
            continue
        dmax = _delai_max(t.get("delai_15j"))
        if dmax is not None and dmax > delai_max_jours:
            continue                      # donnee douteuse : jamais utilisee
        table.setdefault(pays, {})[q] = {
            "usd": usd15,
            "canal": t.get("canal_15j") or "(canal non releve)",
            "delai": t.get("delai_15j") or "(delai <= 15 j verifie a la collecte)",
            "date_collecte": t.get("date_collecte") or "",
            "region": t.get("region") or "region_inconnue",
        }
    return {"vid": vid, "entrees": table}


def _entree_v56(donnees, vid, pays, quantite):
    """Entree brute d'une variante, SANS melange entre variantes."""
    var = variantes(donnees).get(vid)
    if not var:
        # les tarifs des AUTRES variantes ne sont jamais lus ici
        return None
    for t in var.get("tarifs", []):
        if isinstance(t, dict) and t.get("pays") == pays \
                and t.get("quantite") == quantite:
            return t
    return None


def statut_tarif(donnees, vid, pays, quantite, aujourdhui=None,
                 delai_max_jours=MAX_SHIP_DAYS):
    """Statut d'un tarif : actif / expire / aucun_transporteur_15j /
    destination_inconnue / variante_inconnue. JAMAIS d'estimation."""
    if vid not in variantes(donnees):
        return "variante_inconnue"
    entree = _entree_v56(donnees, vid, pays, quantite)
    if entree is None:
        return "destination_inconnue"
    if est_expire(entree, aujourdhui):
        return "expire"
    usd15 = entree.get("usd_15j")
    if not isinstance(usd15, (int, float)) or isinstance(usd15, bool) \
            or usd15 <= 0:
        return "aucun_transporteur_15j"
    dmax = _delai_max(entree.get("delai_15j"))
    if dmax is not None and dmax > delai_max_jours:
        return "aucun_transporteur_15j"
    return "actif"


# ----------------------------------------------------- moteur v5.6 (fix #1) -
def compute_pricing_v56(cout_achat_usd, vid, pays, quantite,
                        donnees=None, table=None,
                        exchange_rate=p55.EXCHANGE_RATE_USD_EUR,
                        frais_paiement_taux=0.0,
                        frais_paiement_fixe_eur=0.0,
                        marge_min=0.20,
                        delai_max_jours=MAX_SHIP_DAYS,
                        aujourdhui=None,
                        freight_fetch_fn=None):
    """Moteur v5.6 : prix fonde UNIQUEMENT sur un tarif reel conforme
    15 jours de LA variante demandee.

    Statuts :
    - "recommandation_ok" : prix calcule, marge verifiee ;
    - "incoherence_defensive" : marge hors tolerance, verification manuelle ;
    - "depasse_plafond" : quantite > 5, aucun prix ;
    - "quantite_invalide" / "cout_invalide" / "parametres_invalides" ;
    - "variante_inconnue" : vid absent des donnees (aucun melange) ;
    - "destination_inconnue" : pays/quantite sans tarif mesure ;
    - "expire" : tarif perime (TTL 7 jours), jamais present comme actuel ;
    - "aucun_transporteur_15j" : aucun transporteur <= 15 jours,
      message "verification manuelle requise", AUCUN prix calcule.
    """
    base = {
        "produit": {"cout_achat_usd": cout_achat_usd,
                    "pid_cj": p55.PRODUCT_PID_CJ, "vid_cj": vid},
        "destination": pays,
        "quantite": quantite,
        "moteur": "v5.6 (tarifs 15 jours par variante)",
        "delai_max_jours": delai_max_jours,
        "exchange_rate": exchange_rate,
        "exchange_rate_date": p55.EXCHANGE_RATE_DATE,
        "frais_paiement_taux": frais_paiement_taux,
        "frais_paiement_fixe_eur": frais_paiement_fixe_eur,
        "marge_min": marge_min,
        "verification_manuelle": False,
        "message": "",
    }

    if p55._parametres_invalides(marge_min, frais_paiement_taux,
                                 frais_paiement_fixe_eur, exchange_rate):
        base.update({"statut": "parametres_invalides",
                     "verification_manuelle": True,
                     "message": "Parametres invalides (marge, frais, taux)."})
        return base
    if not isinstance(cout_achat_usd, (int, float)) \
            or isinstance(cout_achat_usd, bool) or cout_achat_usd <= 0:
        base.update({"statut": "cout_invalide",
                     "verification_manuelle": True,
                     "message": "Cout d'achat invalide."})
        return base
    # Toute quantite entiere positive est acceptee. Les tarifs 1-5
    # restent servis par le cache ; au-dela, CJ doit fournir un devis live.
    if isinstance(quantite, bool) or not isinstance(quantite, int) or quantite < 1:
        base.update({"statut": "quantite_invalide",
                     "verification_manuelle": True,
                     "message": "Quantite invalide : un entier positif est attendu."})
        return base

    # Devis a la demande pour les quantites hors du cache historique.
    # Le callback injecte appelle CJ calculate_cj_shipping en lecture seule.
    if quantite > QTE_MAX:
        if not callable(freight_fetch_fn):
            base.update({"statut": "tarif_dynamique_requis",
                         "verification_manuelle": True,
                         "message": "Devis CJ dynamique requis ; aucune extrapolation."})
            return base
        try:
            options = freight_fetch_fn(vid, pays, quantite)
            mini, mini15 = choisir_option_v56(options or [])
        except Exception as exc:
            base.update({"statut": "tarif_dynamique_indisponible",
                         "verification_manuelle": True,
                         "message": "Devis CJ impossible : " + str(exc)[:180]})
            return base
        if mini15 is None:
            base.update({"statut": "aucun_transporteur_15j",
                         "verification_manuelle": True,
                         "message": "Aucun transporteur conforme au delai maximal : " + MSG_VERIF_MANUELLE})
            return base
        quote = {"usd": mini15["usd"], "canal": mini15.get("canal") or "",
                 "delai": mini15.get("delai") or "",
                 "date_collecte": (_date(aujourdhui) or date.today()).isoformat(),
                 "region": p55.REGIONS.get(pays, "region_inconnue")}
        table = {"vid": vid, "entrees": {pays: {quantite: quote}}}

    # --- table : par variante, conformite 15 jours, jamais de melange ---
    if table is None:
        if donnees is None:
            donnees = charger_donnees()
        st = statut_tarif(donnees, vid, pays, quantite, aujourdhui,
                          delai_max_jours)
        if st == "variante_inconnue":
            base.update({"statut": "variante_inconnue",
                         "verification_manuelle": True,
                         "message": "Variante absente des donnees : "
                                  + MSG_VERIF_MANUELLE + "."})
            return base
        if st == "destination_inconnue":
            base.update({"statut": "destination_inconnue",
                         "verification_manuelle": True,
                         "message": "Destination/quantite sans tarif mesure : "
                                  + MSG_VERIF_MANUELLE + "."})
            return base
        if st == "expire":
            base.update({"statut": "expire",
                         "verification_manuelle": True,
                         "message": "Tarif expire (TTL "
                                  + str(TARIF_TTL_JOURS)
                                  + " jours), jamais present comme actuel : "
                                  + MSG_VERIF_MANUELLE + "."})
            return base
        if st == "aucun_transporteur_15j":
            base.update({"statut": "aucun_transporteur_15j",
                         "verification_manuelle": True,
                         "message": "Aucun transporteur ne respecte le delai "
                                  "maximal de " + str(delai_max_jours)
                                  + " jours : " + MSG_VERIF_MANUELLE + "."})
            return base
        table = table_frets_v56(donnees, vid, delai_max_jours)
    if not isinstance(table, dict) or table.get("vid") != vid:
        # Table d'une autre variante (ou mal formee) : AUCUN melange.
        base.update({"statut": "variante_inconnue",
                     "verification_manuelle": True,
                     "message": "Table de tarifs d'une autre variante : "
                              + MSG_VERIF_MANUELLE + "."})
        return base
    entrees = table.get("entrees") or {}
    quote = (entrees.get(pays) or {}).get(quantite)
    if quote is None:
        base.update({"statut": "aucun_transporteur_15j",
                     "verification_manuelle": True,
                     "message": "Aucun tarif conforme " + str(delai_max_jours)
                              + " jours dans la table : "
                              + MSG_VERIF_MANUELLE + "."})
        return base
    # AUDIT FINALISATION : le controle TTL s'applique AUSSI lorsque
    # table= est fournie directement (avant, une table construite
    # ailleurs contournait l'expiration : un tarif perime pouvait etre
    # utilise). Une entree de table sans date de collecte est EXPIREE
    # (est_expire ne suppose jamais une donnee valide).
    if est_expire(quote, aujourdhui):
        base.update({"statut": "expire",
                     "verification_manuelle": True,
                     "message": "Tarif expire (TTL "
                              + str(TARIF_TTL_JOURS)
                              + " jours), jamais present comme actuel : "
                              + MSG_VERIF_MANUELLE + "."})
        return base
    dmax = _delai_max(quote.get("delai"))
    if dmax is not None and dmax > delai_max_jours:
        base.update({"statut": "aucun_transporteur_15j",
                     "verification_manuelle": True,
                     "message": "Delai reel (" + str(dmax) + " jours) > "
                              + str(delai_max_jours) + " jours : "
                              + MSG_VERIF_MANUELLE + "."})
        return base

    # --- calcul commercial (v5.5.1 conserve : cout x quantite) ---
    cout_unitaire_eur = round(cout_achat_usd * exchange_rate, 2)
    cout_produit_eur = round(cout_unitaire_eur * quantite, 2)
    fret_eur = round(quote["usd"] * exchange_rate, 2)
    denominateur = 1 - frais_paiement_taux - marge_min
    prix_vente = round((cout_produit_eur + fret_eur
                       + frais_paiement_fixe_eur) / denominateur, 2)
    frais_paiement_eur = round(prix_vente * frais_paiement_taux
                               + frais_paiement_fixe_eur, 2)
    cout_total_eur = round(cout_produit_eur + fret_eur
                           + frais_paiement_eur, 2)
    benefice_estime_eur = round(prix_vente - cout_total_eur, 2)
    marge_pourcentage = round(benefice_estime_eur / prix_vente * 100, 2)
    marge_verifiee = abs(marge_pourcentage - marge_min * 100) <= 0.5

    base.update({
        "statut": "recommandation_ok" if marge_verifiee
                  else "incoherence_defensive",
        "region": quote.get("region"),
        "fret": {"usd": quote["usd"], "eur": fret_eur,
                 "canal": quote.get("canal"), "delai": quote.get("delai"),
                 "date_mesure": quote.get("date_collecte")},
        "calcul": {
            "cout_produit_unitaire_eur": cout_unitaire_eur,
            "cout_produit_total_eur": cout_produit_eur,
            "frais_livraison_eur": fret_eur,
            "frais_paiement_eur": frais_paiement_eur,
            "cout_total_eur": cout_total_eur,
            "prix_vente_recommande_eur": prix_vente,
            "benefice_estime_eur": benefice_estime_eur,
            "marge_pourcentage": marge_pourcentage,
        },
        "livraison_gratuite": {
            "integree_au_prix": True,
            "fret_facture_au_client_eur": 0.00,
            "note": ("Livraison gratuite pour le client : le fret CJ reste "
                     "un cout reel pour SHOPLINOUS, integre dans le prix."),
        },
        "avertissement_frais_paiement": p55.MSG_FRAIS_PAIEMENT,
    })
    if not marge_verifiee:
        base["verification_manuelle"] = True
        base["message"] = ("Incoherence defensive : marge hors tolerance : "
                           + MSG_VERIF_MANUELLE + ".")
    return base


# ----------------------------------------------------------- collecte v5.6 --
def choisir_option_v56(options):
    """(option la moins chere, option la moins chere avec delai max
    <= 15 jours) ; (None, ...) si aucune. Reutilise la logique v5.5."""
    import freight_collector_v55 as fc55
    return fc55.choisir_option(options)


def collecte_v56(fetch_fn, pays_liste, donnees, vid, sku, couleur,
                 aujourdhui=None, ttl_jours=TARIF_TTL_JOURS):
    """Collecte UNE variante (vid) sur pays_liste x quantites 1-5.

    ECHEC : les entrees precedentes sont CONSERVEES (jamais remplacees
    par une entree vide) ; seules les entrees collectees avec succes sont
    mises a jour. Retourne un rapport honnete :
    {"collectes": N, "conserves": M, "echecs": [...], "cache_hits": K}.
    """
    aujourdhui = _date(aujourdhui) or date.today()
    # mutation DIRECTE de donnees (variantes() renvoie une copie) :
    # on retrouve la variante dans la liste, on la cree si absente.
    liste_var = donnees.setdefault("variantes", [])
    var = None
    for v in liste_var:
        if isinstance(v, dict) and v.get("vid_cj") == vid:
            var = v
            break
    if var is None:
        var = {"vid_cj": vid, "sku_variante": sku, "couleur": couleur,
               "tarifs": []}
        liste_var.append(var)
    par_cle = {}
    for t in var.get("tarifs", []):
        if isinstance(t, dict) and "pays" in t and "quantite" in t:
            par_cle[(t["pays"], t["quantite"])] = t
    collectes, conserves, echecs, cache = 0, 0, [], 0
    for pays in pays_liste:
        for q in range(QTE_MIN, QTE_MAX + 1):
            try:
                options = fetch_fn(vid, pays, q)
            except Exception as exc:            # echec : on CONSERVE
                anciennete = par_cle.get((pays, q))
                if anciennete is not None and not est_expire(
                        anciennete, aujourdhui, ttl_jours):
                    conserves += 1
                echecs.append({"pays": pays, "quantite": q,
                               "motif": str(exc)[:200]})
                continue
            mini, mini15 = choisir_option_v56(options or [])
            if mini is None and mini15 is None:
                anciennete = par_cle.get((pays, q))
                if anciennete is not None and not est_expire(
                        anciennete, aujourdhui, ttl_jours):
                    conserves += 1
                echecs.append({"pays": pays, "quantite": q,
                               "motif": "aucune option CJ retournee"})
                continue
            par_cle[(pays, q)] = {
                "pays": pays, "quantite": q,
                "usd": (mini or {}).get("usd"),
                "canal": (mini or {}).get("canal", ""),
                "delai": (mini or {}).get("delai", ""),
                "usd_15j": (mini15 or {}).get("usd"),
                "canal_15j": (mini15 or {}).get("canal", ""),
                "delai_15j": (mini15 or {}).get("delai", ""),
                "date_collecte": aujourdhui.isoformat(),
            }
            collectes += 1
    var["tarifs"] = [par_cle[(p, q)] for (p, q) in sorted(par_cle)]
    return {"collectes": collectes, "conserves": conserves,
            "cache_hits": cache, "echecs": echecs}


# ------------------------------------------------------------- rapports ----
def rapport_variantes(donnees, aujourdhui=None):
    """Verification d'integrite : par variante, nombre de tarifs, pays,
    entrees expirees et tarifs conformes 15 jours. Rien n'est invente."""
    out = {}
    for vid, var in variantes(donnees).items():
        tarifs = var.get("tarifs", [])
        pays = sorted({t.get("pays") for t in tarifs if isinstance(t, dict)})
        expires = [t for t in tarifs if isinstance(t, dict)
                   and est_expire(t, aujourdhui)]
        conformes_15j = [t for t in tarifs if isinstance(t, dict)
                         and isinstance(t.get("usd_15j"), (int, float))
                         and not isinstance(t.get("usd_15j"), bool)
                         and t["usd_15j"] > 0]
        out[vid] = {
            "sku_variante": var.get("sku_variante"),
            "couleur": var.get("couleur"),
            "nb_tarifs": len(tarifs),
            "nb_pays": len(pays),
            "pays": pays,
            "nb_expires": len(expires),
            "nb_conformes_15j": len(conformes_15j),
        }
    return out

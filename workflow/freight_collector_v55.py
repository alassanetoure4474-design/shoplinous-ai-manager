"""SHOPLINOUS v5.5 (chantier complementaire, branche workflow-v5-fix6) -
Collecteur de tarifs CJ + moteur de prix CORRIGE par quantite.

PRIORITES TRAITEES :
1. CORRECTION du calcul du cout total selon la quantite : compute_pricing_v551
   multiplie le cout d'achat UNITAIRE par la quantite. Le module pricing_v55
   (v5.5, branche fix5b) calcule le prix avec le cout UNITAIRE seulement ;
   il n'a PAS ete modifie ici (risque de transcription d'octets) : la version
   corrigee est compute_pricing_v551, qui REUTILISE validate_quantity,
   _parametres_invalides et les constantes de pricing_v55.
2. Tarifs CJ reels collectes pour la REGLE EUROPE ACTUELLE :
   UE27 + GB/CH/NO = 30 pays (Malte inclus POUR DOCUMENTATION ; la regle 3
   l'exclut : aucune option <= 6 EUR ; la regle active daily.DEST_COUNTRIES
   liste 29 destinations, Malte ecart). NOTE d'honnetete : l'enonce parlait de
   "31 pays" ; la regle reelle en compte 30 (dont 29 actifs).
3. Destinations mondiales prises en charge par CJ : 21 pays collectes.
4. Limitation de debit (QPS CJ 1 req/s, confirme par erreur reelle 1600200),
   CACHE (une entree fraiche n'est JAMAIS re-collectee) et REPRISE sur erreur
   (jusqu'a 3 tentatives). Aucune methode GROUPEE n'existe cote CJ :
   l'endpoint /logistic/freight/calculate traite UN couple (variante, pays,
   quantite) par appel - verifie via l'inventaire du connecteur.
5. Stockage par produit, variante, pays, quantite, transporteur (canal),
   delai et date de collecte : fichier freight_data_v55.json (255 tarifs,
   51 pays, collecte en lecture seule le 2026-11-02).
6. JAMAIS d'estimation : un tarif manquant reste manquant (statut
   tarif_indisponible + verification manuelle).
7. ACTUALISATION automatique : une entree de plus de TARIF_TTL_JOURS (7)
   jours est signaler EXPIREE et re-collectee par collecte().

SECURITE : lecture seule stricte (aucune commande CJ, aucun changement de
prix ou de stock Freewebstore, aucun deploiement, aucune fusion,
allow_publish=False, main intacte). Module PUR : le reseau est INJECTE
via fetch_fn (en production : calculate_cj_shipping du serveur MCP
SHOPLINOUS, en lecture seule).
"""

import json
import os
from datetime import date, timedelta

import pricing_v55 as p55

# ---------------------------------------------------------------- regles ---
ALLOW_PUBLISH = False
QTE_MIN = 1
QTE_MAX = 5
TARIF_TTL_JOURS = 7          # au-dela, le tarif est signale EXPIRE
MAX_SHIP_EUR = 6.0           # regle 3 (marche Europe)
MAX_SHIP_DAYS = 15           # regle 3
TAUX_USD_EUR = p55.EXCHANGE_RATE_USD_EUR
PRODUCT_VID_CJ = p55.PRODUCT_VID_CJ
PRODUCT_PID_CJ = p55.PRODUCT_PID_CJ
CHEMIN_DONNEES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "freight_data_v55.json")

# Regle Europe actuelle : UE27 + GB/CH/NO (30 pays, Malte documente).
EUROPE_30 = sorted([
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE", "GB", "CH", "NO",
])

# Destinations mondiales collectees hors Europe (21 pays, par region).
MONDE_21 = sorted([
    "US", "CA", "MX",                 # Amerique du Nord
    "BR", "AR",                       # Amerique du Sud
    "AU", "NZ",                       # Oceanie
    "CN", "JP", "KR", "IN", "TR", "AE",  # Asie / Moyen-Orient
    "ZA", "MA", "DZ", "TN", "SN", "NG", "EG", "CI",  # Afrique
])


def _date(valeur):
    """Accepte une date ou une chaine ISO ; None -> date du jour."""
    if valeur is None:
        return date.today()
    if isinstance(valeur, date):
        return valeur
    return date.fromisoformat(str(valeur)[:10])


# ------------------------------------------------------------ donnees ------
def charger_donnees(chemin=CHEMIN_DONNEES):
    """Charge le fichier de tarifs collectes. Erreur explicite si absent."""
    with open(chemin, "r", encoding="utf-8") as f:
        donnees = json.load(f)
    if not isinstance(donnees, dict) or not isinstance(donnees.get("tarifs"), list):
        raise RuntimeError("fichier de tarifs mal forme : champ tarifs absent")
    return donnees


def _index_tarifs(donnees):
    """Index (pays, quantite) -> entree. Derniere entree gagnante."""
    index = {}
    for t in donnees.get("tarifs", []) or []:
        if not isinstance(t, dict):
            continue
        pays = t.get("pays")
        q = t.get("quantite")
        if isinstance(pays, str) and isinstance(q, int) and not isinstance(q, bool):
            index[(pays, q)] = t
    return index


def table_frets(donnees):
    """Table {pays: {quantite: {usd, canal, delai, date_mesure, region}}}.

    Aucune estimation : les entrees sans prix valide sont ignorees."""
    table = {}
    for (pays, q), t in _index_tarifs(donnees).items():
        usd = t.get("usd")
        if not isinstance(usd, (int, float)) or isinstance(usd, bool) or usd <= 0:
            continue
        table.setdefault(pays, {})[q] = {
            "usd": usd,
            "canal": t.get("canal") or "",
            "delai": t.get("delai") or "",
            "date_mesure": t.get("date_collecte") or "",
            "region": t.get("region") or "region_inconnue",
        }
    return table


# --------------------------------------------------------- expiration -----
def est_expire(entree, aujourdhui=None, ttl_jours=TARIF_TTL_JOURS):
    """True si la date de collecte + TTL depassee. JAMAIS de repli : une
    entree sans date de collecte est consideree EXPIREE (donnee douteuse)."""
    aujourdhui = _date(aujourdhui)
    brut = (entree or {}).get("date_collecte") or (entree or {}).get("date_mesure")
    if not brut:
        return True
    collecte = date.fromisoformat(str(brut)[:10])
    return collecte + timedelta(days=ttl_jours) < aujourdhui


class MagasinTarifs:
    """Cache de tarifs avec statut par entree : frais / expire / absent."""

    def __init__(self, donnees, aujourdhui=None):
        self.donnees = donnees
        self.aujourdhui = _date(aujourdhui)
        self._index = _index_tarifs(donnees)

    def entree(self, pays, quantite):
        return self._index.get((str(pays).strip().upper(), quantite))

    def statut(self, pays, quantite):
        e = self.entree(pays, quantite)
        if e is None:
            return "absent"
        if est_expire(e, self.aujourdhui):
            return "expire"
        return "frais"


# ------------------------------------------------------- regle 3 ----------
def est_conforme_regle3(entree, taux=TAUX_USD_EUR):
    """Regle 3 (marche Europe) : option <= 6 EUR ET delai max <= 15 jours.

    Se base sur l'option la moins chere AYANT un delai max <= 15 jours
    (champ usd_15j releve a la collecte). JAMAIS d'estimation : si
    usd_15j est absent, la conformite est FAUSSE (a verifier manuellement)."""
    if not isinstance(entree, dict):
        return False
    usd15 = entree.get("usd_15j")
    if not isinstance(usd15, (int, float)) or isinstance(usd15, bool) or usd15 <= 0:
        return False
    return usd15 * taux <= MAX_SHIP_EUR


def rapport_couverture(donnees, aujourdhui=None):
    """Rapport : pays reellement couverts / non desservis, regle 3, monde.

    Un pays est COUVERT s'il possede les 5 quantites (1 a 5) avec un prix
    reel. Les entrees expirees sont listees separement (a actualiser).
    Regle 3 : conformite a la quantite 1 (reference) ET sur les 5
    quantites (champs separes, aucune confusion)."""
    aujourdhui = _date(aujourdhui)
    index = _index_tarifs(donnees)
    quantites_par_pays = {}
    for (pays, q), t in index.items():
        if isinstance(t.get("usd"), (int, float)) and not isinstance(t.get("usd"), bool) \
                and t.get("usd") > 0:
            quantites_par_pays.setdefault(pays, set()).add(q)

    couverts = sorted(p for p, qs in quantites_par_pays.items()
                      if qs >= {1, 2, 3, 4, 5})
    partiels = sorted(p for p, qs in quantites_par_pays.items()
                      if qs < {1, 2, 3, 4, 5})
    tous_demandes = sorted(set(EUROPE_30) | set(MONDE_21))
    non_desservis = sorted(p for p in tous_demandes if p not in couverts
                           and p not in partiels)
    expires = sorted({p for (p, q), t in index.items()
                      if est_expire(t, aujourdhui)})

    # Regle 3 verifiee a la QUANTITE DE REFERENCE 1 (validation historique
    # pays par pays du 01/11/2026) PUIS sur TOUTES les quantites : avec les
    # tarifs reels, seuls GB et PL restent <= 6 EUR pour q1 a q5 (limite
    # honnete, aucun arrondi cache).
    europe_conformes_q1 = sorted(
        p for p in EUROPE_30 if est_conforme_regle3(index.get((p, 1))))
    europe_non_conformes_q1 = sorted(p for p in EUROPE_30
                                      if p not in europe_conformes_q1)
    europe_conformes_q1_a_5 = sorted(
        p for p in EUROPE_30
        if all(est_conforme_regle3(index.get((p, q)))
               for q in range(QTE_MIN, QTE_MAX + 1)))
    monde = sorted(p for p in couverts if p not in EUROPE_30)
    return {
        "date_rapport": aujourdhui.isoformat(),
        "pays_couverts_q1_a_5": couverts,
        "pays_partiels": partiels,
        "non_desservis": non_desservis,
        "tarifs_expires": expires,
        "europe_30_regle3_conformes_q1": europe_conformes_q1,
        "europe_30_regle3_non_conformes_q1": europe_non_conformes_q1,
        "europe_30_regle3_conformes_q1_a_5": europe_conformes_q1_a_5,
        "destinations_mondiales_couvertes": monde,
    }


# ----------------------------------------------------------- collecte -----
def choisir_option(options):
    """Extrait de la reponse CJ : (option la moins chere, option la moins
    chere avec delai max <= 15 jours). Retourne (None, ...) si aucune."""
    mini, mini15 = None, None
    for o in options or []:
        if not isinstance(o, dict):
            continue
        prix = o.get("logisticPrice")
        if not isinstance(prix, (int, float)) or isinstance(prix, bool) or prix <= 0:
            continue
        if mini is None or prix < mini["usd"]:
            mini = {"usd": prix, "canal": o.get("logisticName") or "",
                     "delai": o.get("logisticAging") or ""}
        bouts = str(o.get("logisticAging") or "").split("-")
        try:
            delai_max = int(bouts[-1])
        except (ValueError, IndexError):
            continue
        if delai_max <= MAX_SHIP_DAYS and (mini15 is None or prix < mini15["usd"]):
            mini15 = {"usd": prix, "canal": o.get("logisticName") or "",
                      "delai": o.get("logisticAging") or ""}
    return mini, mini15


def collecte(fetch_fn, pays_liste, donnees, aujourdhui=None,
             quantites=None, sleep_fn=None, tentatives=3):
    """Collecte/actualise les tarifs CJ en LECTURE SEULE.

    fetch_fn(pays, quantite) -> liste d'options CJ
    [{logisticPrice, logisticName, logisticAging}] (reseau INJECTE ;
    en production : calculate_cj_shipping, QPS 1 req/s).
    sleep_fn() : limite de debit, appele AVANT CHAQUE appel reseau.
    - CACHE : une entree FRAICHE (date + TTL non depasses) est reutilisee,
      AUCUN appel reseau n'est emis pour elle ;
    - ACTUALISATION : une entree ABSENTE ou EXPIREE est (re)collectee ;
    - REPRISE : en cas d'erreur, jusqu'a ``tentatives`` essais (avec
      sleep_fn entre chaque) ; en cas d'echec definitif, l'entree est
      enregistree avec usd null et motif d'echec - JAMAIS estimee.

    Retour : {"donnees": donnees_mises_a_jour, "appels_reseau": N,
    "cache_hits": N, "echecs": [{"pays", "quantite", "motif"}]}
    """
    aujourdhui = _date(aujourdhui)
    if quantites is None:
        quantites = list(range(QTE_MIN, QTE_MAX + 1))
    index = _index_tarifs(donnees)
    aujourdhui_iso = aujourdhui.isoformat()
    appels, echecs, cache = 0, [], 0
    for pays in pays_liste:
        pays = str(pays).strip().upper()
        region = "europe" if pays in EUROPE_30 else (
            (index.get((pays, 1)) or {}).get("region") or "region_inconnue")
        for q in quantites:
            existante = index.get((pays, q))
            if existante is not None and not est_expire(existante, aujourdhui):
                cache += 1
                continue
            options, erreur = None, None
            for essai in range(tentatives):
                if sleep_fn is not None:
                    sleep_fn()
                appels += 1
                try:
                    options = fetch_fn(pays, q)
                    break
                except Exception as exc:          # reprise sur erreur
                    erreur = str(exc)
                    options = None
            if options:
                mini, mini15 = choisir_option(options)
                if mini:
                    entree = {
                        "pays": pays, "region": region, "quantite": q,
                        "usd": mini["usd"], "canal": mini["canal"],
                        "delai": mini["delai"],
                        "usd_15j": mini15["usd"] if mini15 else None,
                        "date_collecte": aujourdhui_iso,
                    }
                    index[(pays, q)] = entree
                else:
                    echecs.append({"pays": pays, "quantite": q,
                                   "motif": "aucune option avec prix valide"})
            else:
                echecs.append({"pays": pays, "quantite": q,
                               "motif": erreur or "aucune option CJ"})
    nouvelles = [index[k] for k in sorted(index.keys())]
    donnees["tarifs"] = nouvelles
    return {"donnees": donnees, "appels_reseau": appels,
            "cache_hits": cache, "echecs": echecs}


# --------------------------------- moteur de prix CORRIGE (v5.5.1) --------
def compute_pricing_v551(cout_achat_usd, pays, quantite,
                         donnees=None, table=None,
                         exchange_rate=p55.EXCHANGE_RATE_USD_EUR,
                         frais_paiement_taux=0.0,
                         frais_paiement_fixe_eur=0.0,
                         marge_min=0.20):
    """Moteur v5.5.1 CORRIGE : cout du produit = UNITAIRE x QUANTITE.

    Reutilise validate_quantity / _parametres_invalides de pricing_v55.
    ``table`` : table issue de table_frets(donnees) ; par defaut, la table
    embarquee p55.REAL_FREIGHT (7 pays). Statuts identiques a v5.5
    (recommandation_ok, depasse_plafond, tarif_indisponible,
    quantite_invalide, cout_invalide, parametres_invalides)."""
    if table is None and donnees is not None:
        table = table_frets(donnees)
    base = {
        "produit": {"cout_achat_usd": cout_achat_usd,
                    "pid_cj": PRODUCT_PID_CJ, "vid_cj": PRODUCT_VID_CJ},
        "destination": pays,
        "quantite": quantite,
        "moteur": "v5.5.1 (cout x quantite)",
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
        base["statut"] = "parametres_invalides"
        base["verification_manuelle"] = True
        base["message"] = "Parametres invalides (marge, frais, taux)."
        return base
    if not isinstance(cout_achat_usd, (int, float)) or isinstance(cout_achat_usd, bool) \
            or cout_achat_usd <= 0:
        base["statut"] = "cout_invalide"
        base["verification_manuelle"] = True
        base["message"] = "Cout d'achat invalide."
        return base
    vq = p55.validate_quantity(quantite)
    if vq["statut"] != "ok":
        base.update({"statut": vq["statut"], "verification_manuelle": True,
                     "message": vq["message"]})
        return base
    quote = p55.get_freight_quote(pays, quantite, table=table)
    if quote is None:
        base["statut"] = "tarif_indisponible"
        base["verification_manuelle"] = True
        base["message"] = p55.MSG_TARIF_INDISPONIBLE
        return base

    # --- CORRECTION v5.5.1 : cout total = unitaire x quantite ---
    cout_unitaire_eur = round(cout_achat_usd * exchange_rate, 2)
    cout_produit_eur = round(cout_unitaire_eur * quantite, 2)
    fret_eur = round(quote["usd"] * exchange_rate, 2)
    denominateur = 1 - frais_paiement_taux - marge_min
    prix_vente = round((cout_produit_eur + fret_eur
                        + frais_paiement_fixe_eur) / denominateur, 2)
    frais_paiement_eur = round(prix_vente * frais_paiement_taux
                               + frais_paiement_fixe_eur, 2)
    cout_total_eur = round(cout_produit_eur + fret_eur + frais_paiement_eur, 2)
    benefice_estime_eur = round(prix_vente - cout_total_eur, 2)
    marge_pourcentage = round(benefice_estime_eur / prix_vente * 100, 2)
    marge_verifiee = abs(marge_pourcentage - marge_min * 100) <= 0.5

    base.update({
        "statut": "recommandation_ok" if marge_verifiee else "incoherence_defensive",
        "region": quote["region"],
        "fret": {"usd": quote["usd"], "eur": fret_eur, "canal": quote["canal"],
                 "delai": quote["delai"], "date_mesure": quote["date_mesure"]},
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
            "note": ("Livraison gratuite pour le client : le fret CJ reste un "
                     "cout reel pour SHOPLINOUS, integre dans le prix de vente."),
        },
        "avertissement_frais_paiement": p55.MSG_FRAIS_PAIEMENT,
    })
    if not marge_verifiee:
        base["verification_manuelle"] = True
        base["message"] = "Incoherence defensive : marge calculee hors tolerance."
    return base

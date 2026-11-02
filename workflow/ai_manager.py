"""SHOPLINOUS - Gestionnaire multi-IA centralise (FreeLLMAPI).

Finalisation (02/11/2026) : SHOPLINOUS accede aux modeles IA UNIQUEMENT
via FreeLLMAPI, la passerelle qui centralise les cles Mistral, Gemini et
Groq. CE MODULE NE CONTIENT AUCUNE CLE : la cle de la passerelle est
lue dans FREE_LLM_API_KEY et n'est JAMAIS affichee, journalisee ni
copiee (le journal passe par un filtre de redaction).

Regles :
- Choix du fournisseur parmi mistral, gemini, groq ; ordre configurable
  via AI_PROVIDER_ORDER (defaut mistral, gemini, groq).
- BASCULE AUTOMATIQUE vers le fournisseur suivant en cas de quota
  depasse (HTTP 429), erreur serveur (5xx), indisponibilite reseau ou
  delai depasse.
- MODELES PAYANTS INTERDITS : seul le modele declare par fournisseur
  (variables AI_MODEL_MISTRAL / AI_MODEL_GEMINI / AI_MODEL_GROQ) est
  autorise ; tout autre nom de modele est refuse par ValueError.
- CACHE des reponses (cle = empreinte messages + modele), TTL
  AI_CACHE_TTL_SECONDS (defaut 3600 s ; 0 desactive le cache).
- JOURNALISATION et SUIVI DES QUOTAS par fournisseur (requetes,
  bascules, erreurs, acces cache, restant lu dans usage.remaining si
  la passerelle le fournit).
- SEPARATION DES RESPONSABILITES INVIOLABLE : l'IA ne sert qu'a des
  taches textuelles (redaction, resume, formulation). Les calculs
  financiers, prix, marges, benefices, stocks et commandes restent
  EXCLUSIVEMENT en code Python deterministe (daily.py, pricing_v55.py,
  freight_collector_v56.py). Ce module n'importe AUCUN de ces modules,
  n'ecrit jamais chez Freewebstore, CJ ou Supabase, et ne declenche
  aucune operation commerciale.
"""

import os
import time
import json
import hashlib
import logging

import httpx

logger = logging.getLogger("shoplinous.ai_manager")

FOURNISSEURS_PAR_DEFAUT = ("mistral", "gemini", "groq")
MODELES_LIBRES_PAR_DEFAUT = {
    "mistral": "mistral-small-latest",
    "gemini": "gemini-flash-latest",
    "groq": "llama-3.3-70b-versatile",
}
DELAI_DEFAUT = 30.0
CACHE_TTL_DEFAUT = 3600

_journal = []
_cache = {}
_quotas = {}


class AiIndisponible(RuntimeError):
    """Aucun fournisseur IA n'a repondu (apres bascules)."""


def _fournisseurs():
    brut = os.environ.get("AI_PROVIDER_ORDER", "")
    if not brut.strip():
        return list(FOURNISSEURS_PAR_DEFAUT)
    ordre = [p.strip() for p in brut.split(",") if p.strip()]
    valides = [p for p in ordre if p in MODELES_LIBRES_PAR_DEFAUT]
    return valides or list(FOURNISSEURS_PAR_DEFAUT)


def _modeles():
    return {
        "mistral": os.environ.get("AI_MODEL_MISTRAL",
                                  MODELES_LIBRES_PAR_DEFAUT["mistral"]),
        "gemini": os.environ.get("AI_MODEL_GEMINI",
                                 MODELES_LIBRES_PAR_DEFAUT["gemini"]),
        "groq": os.environ.get("AI_MODEL_GROQ",
                               MODELES_LIBRES_PAR_DEFAUT["groq"]),
    }


def _cle_api():
    return os.environ.get("FREE_LLM_API_KEY", "")


def _base_url():
    return os.environ.get("FREE_LLM_API_BASE", "").rstrip("/")


def _sans_secret(texte):
    """Redaction : la cle API n'apparait JAMAIS dans un message."""
    cle = _cle_api()
    if cle:
        texte = str(texte).replace(cle, "[REDACTE]")
    return str(texte)[:300]


def _journaliser(evenement, fournisseur, detail=""):
    entree = {"horodatage": time.time(), "evenement": evenement,
              "fournisseur": fournisseur, "detail": _sans_secret(detail)}
    _journal.append(entree)
    logger.info("%s (%s): %s", evenement, fournisseur, entree["detail"])


def journal():
    """Copie du journal (aucun secret, verifie par les tests)."""
    return [dict(e) for e in _journal]


def quotas():
    """Compteurs par fournisseur : requetes, bascules, erreurs, cache."""
    return {f: dict(v) for f, v in _quotas.items()}


def reinitialiser_etat():
    """Tests / debug : vide cache, journal et quotas."""
    _cache.clear()
    _journal.clear()
    _quotas.clear()


def _compter(fournisseur, cle, n=1):
    s = _quotas.setdefault(fournisseur,
                           {"requetes": 0, "bascules": 0, "erreurs": 0,
                            "cache_hits": 0, "restant": None})
    s[cle] += n


def _cle_cache(messages, modele):
    blob = json.dumps([messages, modele], sort_keys=True,
                      ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _extraire_texte(reponse):
    """Extrait le contenu d'une reponse FreeLLMAPI (format compatible
    OpenAI attendu). JAMAIS d'invention : structure inattendue -> None."""
    if not isinstance(reponse, dict):
        return None
    choix = reponse.get("choices")
    if isinstance(choix, list) and choix and isinstance(choix[0], dict):
        message = choix[0].get("message")
        if (isinstance(message, dict)
                and isinstance(message.get("content"), str)):
            return message["content"]
        if isinstance(choix[0].get("text"), str):
            return choix[0]["text"]
    if isinstance(reponse.get("content"), str):
        return reponse["content"]
    return None


async def appeler_ia(messages, fournisseurs=None, modele=None,
                     delai=None, ignorer_cache=False):
    """Appel IA multi-fournisseurs avec bascule automatique.

    messages : liste [{"role": ..., "content": ...}].
    fournisseurs : ordre a essayer (defaut AI_PROVIDER_ORDER, sinon
    mistral, gemini, groq).
    modele : modele IMPOSE ; il doit etre l'un des modeles libres
    declares (AI_MODEL_*), sinon ValueError (modeles payants INTERDITS).
    delai : timeout par fournisseur (defaut AI_TIMEOUT_SECONDS, 30 s).
    ignorer_cache : contourne le cache en lecture.

    Retourne {"fournisseur", "modele", "contenu", "depuis_cache"}.
    Leve AiIndisponible si tous les fournisseurs echouent, ValueError
    si FREE_LLM_API_KEY ou FREE_LLM_API_BASE est absent, si les
    messages sont invalides ou si un modele non autorise est demande.
    """
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages IA invalides")
    cle = _cle_api()
    base = _base_url()
    if not cle or not base:
        raise ValueError("FREE_LLM_API_KEY ou FREE_LLM_API_BASE absent : "
                         "acces IA refuse (aucune valeur par defaut "
                         "inventee, aucune cle en dur)")
    modeles = _modeles()
    if modele is not None and modele not in modeles.values():
        raise ValueError("modele non autorise : seuls les modeles libres "
                         "declares (AI_MODEL_*) sont permis ; tout modele "
                         "payant est INTERDIT")
    ordre = fournisseurs or _fournisseurs()
    ordre = [f for f in ordre if f in MODELES_LIBRES_PAR_DEFAUT]
    if not ordre:
        raise ValueError("aucun fournisseur IA valide configure")
    delai = delai or float(os.environ.get("AI_TIMEOUT_SECONDS",
                                          DELAI_DEFAUT))
    ttl_cache = int(os.environ.get("AI_CACHE_TTL_SECONDS", CACHE_TTL_DEFAUT))

    empreinte = None
    if ttl_cache > 0:
        modele_ref = modele or ",".join(modeles.get(f, "")
                                        for f in ordre)
        empreinte = _cle_cache(messages, modele_ref)
        if not ignorer_cache:
            frappe = _cache.get(empreinte)
            if frappe and frappe["expire"] > time.time():
                _compter(frappe["fournisseur"], "cache_hits")
                _journaliser("cache", frappe["fournisseur"],
                             "reponse servie depuis le cache")
                return {**frappe["reponse"], "depuis_cache": True}

    erreurs = []
    for fournisseur in ordre:
        modele_f = modeles.get(fournisseur)
        if not modele_f or (modele is not None and modele != modele_f):
            continue
        try:
            async with httpx.AsyncClient(timeout=delai) as client:
                r = await client.post(
                    base + "/chat/completions",
                    headers={"Authorization": "Bearer " + cle,
                             "Content-Type": "application/json"},
                    json={"model": modele_f, "messages": messages})
            if r.status_code == 429:
                _compter(fournisseur, "bascules")
                # le corps de la reponse est journalise VIA le filtre de
                # redaction (_sans_secret) : la cle n'y apparaît JAMAIS
                _journaliser("quota_depasse", fournisseur,
                             "HTTP 429 : bascule vers le fournisseur "
                             "suivant ; corps: " + (r.text or ""))
                erreurs.append((fournisseur, "429"))
                continue
            if r.status_code >= 500:
                _compter(fournisseur, "bascules")
                _journaliser("indisponible", fournisseur,
                             "HTTP " + str(r.status_code) + " : bascule ; "
                             "corps: " + (r.text or ""))
                erreurs.append((fournisseur, str(r.status_code)))
                continue
            r.raise_for_status()
            corps = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            _compter(fournisseur, "bascules")
            _journaliser("erreur", fournisseur,
                         type(exc).__name__ + " : bascule")
            erreurs.append((fournisseur, type(exc).__name__))
            continue
        contenu = _extraire_texte(corps)
        if contenu is None:
            _compter(fournisseur, "erreurs")
            _journaliser("reponse_invalide", fournisseur,
                         "structure de reponse inattendue : bascule")
            erreurs.append((fournisseur, "reponse_invalide"))
            continue
        _compter(fournisseur, "requetes")
        usage = corps.get("usage") if isinstance(corps, dict) else None
        if isinstance(usage, dict) and isinstance(
                usage.get("remaining"), (int, float)):
            _quotas[fournisseur]["restant"] = usage["remaining"]
        _journaliser("succes", fournisseur, "reponse recue")
        reponse = {"fournisseur": fournisseur, "modele": modele_f,
                   "contenu": contenu, "depuis_cache": False}
        if empreinte and ttl_cache > 0:
            _cache[empreinte] = {"reponse": dict(reponse),
                                 "expire": time.time() + ttl_cache,
                                 "fournisseur": fournisseur}
        return reponse
    detail = ("; ".join(f + "=" + e for f, e in erreurs)
              if erreurs else "aucun fournisseur joignable")
    raise AiIndisponible("aucun fournisseur IA disponible : " + detail)


def appeler_ia_sync(*args, **kwargs):
    """Enveloppe synchrone d'appeler_ia (usage scripts / tests)."""
    import asyncio
    return asyncio.run(appeler_ia(*args, **kwargs))

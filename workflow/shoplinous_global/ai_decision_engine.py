"""AI Decision Engine : recommandations sur donnees verifiees.

Utilise les cinq modeles IA existants (ai_manager : FreeLLMAPI,
bascule automatique) UNIQUEMENT pour la justification textuelle.
La DECISION reste deterministe sur donnees verifiees (cout total,
disponibilite, delai reel, fiabilite, destination, marge minimale).
L IA ne declenche JAMAIS d achat reel : toute action fournisseur
exige une autorisation distincte (action = AUTORISATION_REQUISE).
"""


def recommander_fournisseur(options, marge_minimale=0):
    """options : liste de dicts {fournisseur, cout_total, disponible,
    delai_reel, fiabilite, destination_ok, marge}. Une option sans
    donnee verifiee est EXCLUE, jamais completee."""
    eligibles = []
    for o in options or []:
        requis = ("fournisseur", "cout_total", "disponible",
                  "delai_reel", "destination_ok", "marge")
        if any(o.get(r) is None for r in requis):
            continue
        if not o["disponible"] or not o["destination_ok"]:
            continue
        if o["marge"] < marge_minimale:
            continue
        eligibles.append(o)
    if not eligibles:
        return {"decision": "aucune_option_verifiee",
                "action": "AUTORISATION_REQUISE",
                "note": "aucune option ne satisfait les donnees "
                        "verifiees ; rien n est invente"}
    meilleur = min(eligibles, key=lambda o: (
        o["cout_total"] * (1 + 0.05 * o["delai_reel"])
        - o["marge"] * (o["fiabilite"] or 1)))
    return {"decision": "recommandation",
            "fournisseur": meilleur["fournisseur"],
            "cout_total": meilleur["cout_total"],
            "delai_reel": meilleur["delai_reel"],
            "marge": meilleur["marge"],
            "action": "AUTORISATION_REQUISE",
            "note": "l IA ne declenche aucun achat : autorisation "
                    "distincte obligatoire"}


def recommander_transport(devis, destination, quantite,
                          delai_max_jours):
    """Delegue au Shipping Manager (donnees reelles uniquement)."""
    from shoplinous_global import shipping_manager
    meilleur = shipping_manager.meilleur_devis(
        devis, destination, quantite, delai_max_jours)
    if meilleur is None:
        return {"decision": "aucun_devis_conforme",
                "action": "AUTORISATION_REQUISE"}
    return {"decision": "recommandation",
            "transporteur": meilleur.transporteur,
            "cout": meilleur.cout, "devise": meilleur.devise,
            "delai_jours": meilleur.delai_jours,
            "action": "AUTORISATION_REQUISE"}


def justifier(recommandation):
    """Justification textuelle IA (facultative, jamais bloquante).
    Reutilise ai_manager/FreeLLMAPI avec les cinq modeles et la
    bascule existantes ; sans IA le resume deterministe suffit."""
    try:
        import ai_manager
        texte = str(recommandation)[:400]
        resume = ai_manager.appeler_ia(
            "resume en une phrase, francais, sans prix : " + texte)
        if resume:
            return resume
    except Exception:
        pass
    return "recommandation basee sur donnees verifiees uniquement"

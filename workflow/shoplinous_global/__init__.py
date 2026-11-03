"""SHOPLINOUS GLOBAL - architecture modulaire v6.

19 modules independants, interfaces claires, aucun ne casse les
32 outils existants (workflow/daily.py) ni les cinq modeles IA
(workflow/ai_manager.py). Les modules sont volontairement
hors-ligne par defaut : une integration est "connectee" uniquement
si un contrat/utilisateur reel existe, jamais simulee.

Modules (1 a 19) :
 1. market_manager        - marches mondiaux et regroupements
 2. country_manager       - configuration independante par pays
 3. currency_manager      - devises, arrondis, coherence affiche/encaisse
 4. exchange_rate_manager - taux horodates, cache, indisponibilite
 5. pricing_manager        - prix final transparent, blocage si donnee manque
 6. payment_manager       - transactions, idempotence, webhooks
 7. payment_providers     - adaptateurs prestataires de paiement
 8. supplier_manager      - fournisseurs, CSV, saisie manuelle
 9. supplier_adapters     - registre d'adaptateurs fournisseurs
10. product_catalog       - catalogue produits multi-fournisseurs
11. inventory             - stocks agreges et alertes
12. shipping_manager     - comparaison transporteurs, sans extrapolation
13. order_manager         - machine a etats des commandes mondiales
14. tracking_manager      - suivi des expeditions
15. ai_decision_engine    - recommandations sur donnees verifiees
16. notification_manager  - notifications multi-canaux
17. security_audit        - secrets, signatures, journal d'audit, PII
18. monitoring            - compteurs et sante de la plateforme
19. supplier_qualification - controle mondial des offres et devis réels
"""
import importlib

VERSION = "6.3"

MODULES = [
    "market_manager", "country_manager", "currency_manager",
    "exchange_rate_manager", "pricing_manager", "payment_manager",
    "payment_providers", "supplier_manager", "supplier_adapters", "supplier_qualification",
    "product_catalog", "inventory", "shipping_manager",
    "order_manager", "tracking_manager", "ai_decision_engine",
    "notification_manager", "security_audit", "monitoring",
]


def module_status():
    """Retourne l'etat de chaque module : charge True/False.
    Ne simule jamais un module absent."""
    statut = {}
    for nom in MODULES:
        try:
            importlib.import_module("shoplinous_global." + nom)
            statut[nom] = {"charge": True, "version": VERSION}
        except Exception as exc:
            statut[nom] = {"charge": False, "erreur": str(exc)[:120]}
    return statut

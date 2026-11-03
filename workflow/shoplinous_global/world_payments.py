"""Paiements internationaux : registre extensible de prestataires.

Deux niveaux STRICTEMENT distincts :
- CAPACITE DECLAREE par un prestataire (a verifier par pays/devis) ;
- PREUVE SHOPLINOUS : un moyen de paiement n est operationnel que si
  un test concluant horodate existe (webhook signe, paiement sandbox).

Aucune simulation : un prestataire non teste reste non_verifie et
n apparait jamais comme operationnel dans un pays.
"""

PRESTATAIRES = {
    "geniuspay": {
        "nom": "GeniusPay",
        "statut": "verifie_sandbox",
        "pays_testes": {"FR": "webhook signe sandbox OK 02/11/2026"},
        "note": "capacites Live non testees : KYC requis",
    },
    "freewebstore_checkout": {
        "nom": "Checkout Freewebstore (Paddle)",
        "statut": "verifie_sandbox",
        "pays_testes": {"FR": "checkout invité actif, TVA FR 02/11/2026"},
        "note": "paiements par carte via la plateforme Freewebstore",
    },
    "stripe": {"nom": "Stripe", "statut": "non_verifie",
               "pays_testes": {}, "note": "aucun contrat"},
    "paypal": {"nom": "PayPal", "statut": "non_verifie",
               "pays_testes": {}, "note": "aucun contrat"},
    "wave": {"nom": "Wave", "statut": "non_verifie",
             "pays_testes": {}, "note": "Wave Direct sandbox seulement"},
}

MOBILE_MONEY_DECLARE = {
    # Capacites DECLAREES (sources publiques prestataires) : a tester
    # une par une avant toute activation. Jamais presentees comme
    # operationnelles tant qu aucune preuve n existe.
    "CI": ["Wave", "Orange Money", "MTN MoMo", "Moov"],
    "SN": ["Wave", "Orange Money", "Free Money"],
    "BJ": ["MTN MoMo", "Moov"],
    "BF": ["Orange Money", "Moov"],
    "ML": ["Orange Money", "Moov"],
    "TG": ["TMoney", "Moov"],
    "CM": ["MTN MoMo", "Orange Money"],
    "GH": ["MTN MoMo", "Telecel Cash", "AT Money"],
    "KE": ["M-Pesa", "Airtel Money"],
    "NG": ["Paystack", "Flutterwave"],
}


def registre() -> dict:
    return {
        nom: {"statut": conf["statut"], "pays_testes": dict(conf["pays_testes"])}
        for nom, conf in PRESTATAIRES.items()
    }


def prestataires_verifies(pays: str) -> list:
    """Prestataires avec une PREUVE reelle pour CE pays uniquement."""
    return sorted(
        nom for nom, conf in PRESTATAIRES.items()
        if pays in conf["pays_testes"])


def moyens_declares(pays: str) -> list:
    """Capacites declarees pour le pays : information indicative,
    jamais un statut operationnel."""
    return list(MOBILE_MONEY_DECLARE.get(pays, []))


def operationnel(prestataire: str, pays: str) -> bool:
    conf = PRESTATAIRES.get(prestataire)
    if conf is None:
        raise ValueError("prestataire inconnu : " + repr(prestataire))
    return pays in conf["pays_testes"]


def activer_prestataire(nom: str, pays: str, preuve: str, date: str) -> None:
    """Activation UNIQUEMENT sur preuve horodatee documentee."""
    if not preuve or not date:
        raise ValueError("preuve et date obligatoires")
    PRESTATAIRES[nom]["pays_testes"][pays] = preuve + " (" + date + ")"

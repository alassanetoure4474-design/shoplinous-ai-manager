"""Parcours de paiement GeniusPay de bout en bout (reseau simule).

Teste le CHAINAGE COMPLET avec le VRAI GeniusPayClient et le VRAI
GestionnairePaiements, sur un transport httpx simule (MockTransport) :
aucun reseau reel, aucun debit, aucun secret affiche. Represente le
parcours de production prevu pour la Cote d'Ivoire (Wave Direct, XOF) :

1. decouverte des moyens (Wave propose en CI/XOF uniquement),
2. creation de transaction -> checkout heberge GeniusPay routage wave,
3. redirection navigateur : ne confirme JAMAIS le paiement,
4. webhook payment.success SIGNE (HMAC-SHA256 reel, fenetre 300 s,
   reference + commande + montant + devise verifies) -> paiement reussi,
5. rapprochement comptable.
""";
import hashlib
import hmac
import json
import time

import httpx
import pytest

from shoplinous_global import payment_manager as pay
from shoplinous_global import payment_providers as prv
from shoplinous_global.geniuspay import GeniusPayClient

WEBHOOK_SECRET = "whsec_parcours_test"
MONTANT_XOF = 16300  # ~24,90 EUR au taux XOF usuel ; entier, >= 200


def _reponse_checkout(request):
    payload = json.loads(request.content)
    assert payload["payment_method"] == "wave"
    assert payload["gateway"] == "wave"
    assert payload["amount"] == MONTANT_XOF
    assert payload["currency"] == "XOF"
    assert payload["customer"]["country"] == "CI"
    assert payload["metadata"]["order_id"] == "CMD-CI-1"
    return httpx.Response(201, json={
        "success": True,
        "data": {
            "reference": "MTX-PARCOURS-1",
            "status": "pending",
            "payment_url": "https://wave.com/pay/MTX-PARCOURS-1",
            "environment": "sandbox",
            "gateway": "wave",
            "amount": MONTANT_XOF,
            "currency": "XOF",
            "metadata": {"order_id": "CMD-CI-1"},
        },
    })


def _reponse_get(request):
    return httpx.Response(200, json={
        "success": True,
        "data": {
            "reference": "MTX-PARCOURS-1",
            "status": "pending",
            "payment_method": "wave",
            "payment_provider": "wave",
            "environment": "sandbox",
            "amount": MONTANT_XOF,
            "currency": "XOF",
            "metadata": {"order_id": "CMD-CI-1"},
        },
    })


def client_parcours():
    def handler(request):
        if request.method == "POST":
            return _reponse_checkout(request)
        return _reponse_get(request)
    return GeniusPayClient(
        api_key="pk_sandbox_test",
        api_secret="sk_sandbox_test",
        webhook_secret=WEBHOOK_SECRET,
        environment="sandbox",
        transport=httpx.MockTransport(handler),
    )


def gestionnaire(client=None):
    reg = prv.RegistrePrestataires(geniuspay_client=client or client_parcours())
    return pay.GestionnairePaiements(reg)


def _webhook_succes(reference, commande, montant, ts):
    payload = {
        "id": "evt-parcours",
        "event": "payment.success",
        "timestamp": int(ts),
        "environment": "sandbox",
        "data": {
            "reference": reference,
            "amount": montant,
            "currency": "XOF",
            "status": "completed",
            "metadata": {"order_id": commande},
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(
        WEBHOOK_SECRET.encode(), str(ts).encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    return raw.decode(), signature, {
        "X-Webhook-Timestamp": str(ts),
        "X-Webhook-Event": "payment.success",
        "X-Webhook-Environment": "sandbox",
    }


def test_geniuspay_est_connecte_avec_cles_et_secret():
    reg = prv.RegistrePrestataires(geniuspay_client=client_parcours())
    etat = reg.etat()["geniuspay"]
    assert etat["connecte"] is True
    assert etat["api_configuree"] is True
    assert etat["webhook_configure"] is True


def test_parcours_complet_wave_direct_ci():
    mgr = gestionnaire()
    # 1. moyens : Wave Direct propose uniquement en CI/XOF
    moyens = mgr.moyens_disponibles("CI", ["Wave"], "XOF")
    assert {"moyen": "wave", "prestataire": "geniuspay",
            "devise": "XOF"} in moyens
    # 2. transaction + checkout heberge
    tx, neuve = mgr.creer_transaction(
        "CMD-CI-1", MONTANT_XOF, "XOF", "CI", "wave", "cle-parcours-1")
    assert neuve is True
    assert tx.statut == "en_attente"
    assert tx.prestataire == "geniuspay"
    assert tx.reference_externe == "MTX-PARCOURS-1"
    assert tx.url_paiement == "https://wave.com/pay/MTX-PARCOURS-1"
    # 3. la redirection navigateur ne prouve jamais le paiement
    assert mgr.confirmer_redirection(tx.id) is False
    assert tx.statut != "reussie"
    # 4. webhook signe et coherent -> paiement confirme
    ts = str(int(time.time()))
    raw, signature, headers = _webhook_succes(
        "MTX-PARCOURS-1", "CMD-CI-1", MONTANT_XOF, ts)
    assert mgr.confirmer_webhook(tx.id, raw, signature,
                                 headers=headers) is True
    assert tx.statut == "reussie"
    # rejeu du meme webhook : idempotent, pas de doublon d'effet
    assert mgr.confirmer_webhook(tx.id, raw, signature,
                                 headers=headers) is True
    assert tx.statut == "reussie"
    # 5. rapprochement comptable
    assert mgr.rapprochement() == [
        {"prestataire": "geniuspay", "devise": "XOF",
         "statut": "reussie", "total": MONTANT_XOF},
    ]


def test_webhook_signe_avec_mauvaise_cle_refuse():
    mgr = gestionnaire()
    tx, _ = mgr.creer_transaction(
        "CMD-CI-1", MONTANT_XOF, "XOF", "CI", "wave", "cle-mauvaise-cle")
    ts = str(int(time.time()))
    raw, _, headers = _webhook_succes(
        "MTX-PARCOURS-1", "CMD-CI-1", MONTANT_XOF, ts)
    mauvaise = hmac.new(
        b"whsec_ATTAQUANT", str(ts).encode() + raw.encode(),
        hashlib.sha256).hexdigest()
    assert mgr.confirmer_webhook(tx.id, raw, mauvaise,
                                 headers=headers) is False
    assert tx.statut == "webhook_refuse"


def test_webhook_expire_refuse():
    mgr = gestionnaire()
    tx, _ = mgr.creer_transaction(
        "CMD-CI-1", MONTANT_XOF, "XOF", "CI", "wave", "cle-expire")
    ts = str(int(time.time()) - 400)  # fenetre anti-rejeu : 300 s
    raw, signature, headers = _webhook_succes(
        "MTX-PARCOURS-1", "CMD-CI-1", MONTANT_XOF, ts)
    assert mgr.confirmer_webhook(tx.id, raw, signature,
                                 headers=headers) is False
    assert tx.statut == "webhook_refuse"


def test_webhook_montant_falsifie_refuse():
    mgr = gestionnaire()
    tx, _ = mgr.creer_transaction(
        "CMD-CI-1", MONTANT_XOF, "XOF", "CI", "wave", "cle-montant")
    ts = str(int(time.time()))
    raw, signature, headers = _webhook_succes(
        "MTX-PARCOURS-1", "CMD-CI-1", 1, ts)  # montant falsifie
    assert mgr.confirmer_webhook(tx.id, raw, signature,
                                 headers=headers) is False
    assert tx.statut == "webhook_refuse"


def test_idempotence_ne_cree_pas_de_doublon():
    mgr = gestionnaire()
    tx1, n1 = mgr.creer_transaction(
        "CMD-CI-2", MONTANT_XOF, "XOF", "CI", "wave", "cle-idem")
    tx2, n2 = mgr.creer_transaction(
        "CMD-CI-2", MONTANT_XOF, "XOF", "CI", "wave", "cle-idem")
    assert n1 is True and n2 is False and tx1 is tx2
    with pytest.raises(ValueError, match="autre demande"):
        mgr.creer_transaction(
            "CMD-AUTRE", MONTANT_XOF, "XOF", "CI", "wave", "cle-idem")


def test_wave_direct_hors_ci_xof_refuse():
    mgr = gestionnaire()
    assert not any(
        m["moyen"] == "wave"
        for m in mgr.moyens_disponibles("SN", ["Wave"], "XOF"))
    assert not any(
        m["moyen"] == "wave"
        for m in mgr.moyens_disponibles("CI", ["Wave"], "EUR"))

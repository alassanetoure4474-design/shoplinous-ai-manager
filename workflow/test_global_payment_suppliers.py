"""Tests paiement + fournisseurs SHOPLINOUS GLOBAL v6. Aucun reseau,
aucun vrai prestataire : la NON-connexion est testee elle-meme."""
import pytest

from shoplinous_global import payment_manager as pay
from shoplinous_global import payment_providers as prv
from shoplinous_global import supplier_manager as sup
from shoplinous_global import supplier_adapters as sad
from shoplinous_global import product_catalog as cat
from shoplinous_global import inventory as inv


class TestPrestataires:
    def test_aucun_prestataire_connecte_par_defaut(self):
        reg = prv.RegistrePrestataires()
        assert reg.actifs() == []
        assert set(reg.etat()) == {"cinetpay", "paydunya", "korapay",
                                   "stripe", "paypal", "geniuspay"}
        assert all(not v["connecte"] for v in reg.etat().values())

    def test_prestataire_non_connecte_ne_cree_rien(self):
        p = prv.CinetPay()
        with pytest.raises(RuntimeError, match="contrat marchand"):
            p.creer_paiement({"x": 1})

    def test_pays_supportes_documentes(self):
        assert "CI" in prv.CinetPay().pays_supportes
        assert "FR" in prv.Stripe().pays_supportes


class TestGestionnairePaiements:
    def _mgr(self, secrets=None):
        return pay.GestionnairePaiements(prv.RegistrePrestataires(),
                                        secrets or {})

    def test_aucun_prestataire_actif_refuse(self):
        with pytest.raises(RuntimeError, match="refusee"):
            self._mgr().creer_transaction("C1", 100, "XOF", "CI",
                                         "Wave", "cle-1")

    def test_idempotence_meme_cle_meme_transaction(self):
        reg = prv.RegistrePrestataires()
        reg.tous()[0].connected = True
        reg.tous()[0].methode = "wave"
        mgr = pay.GestionnairePaiements(reg, {})
        tx1, neuve1 = mgr.creer_transaction("C1", 100, "XOF", "CI",
                                           "wave", "cle-abc")
        tx2, neuve2 = mgr.creer_transaction("C1", 100, "XOF", "CI",
                                            "wave", "cle-abc")
        assert tx1 is tx2 and neuve1 and not neuve2

    def test_redirection_ne_confirme_jamais(self):
        reg = prv.RegistrePrestataires()
        reg.tous()[0].connected = True
        reg.tous()[0].methode = "wave"
        mgr = pay.GestionnairePaiements(reg, {"cinetpay": "secret"})
        tx, _ = mgr.creer_transaction("C1", 100, "XOF", "CI", "wave",
                                      "cle-r")
        assert mgr.confirmer_redirection(tx.id) is False
        assert tx.statut == "redirection_ignoree"
        assert tx.statut != "reussie"

    def test_webhook_bien_signe_confirme(self):
        import hashlib, hmac as h
        reg = prv.RegistrePrestataires()
        reg.tous()[0].connected = True
        reg.tous()[0].methode = "wave"
        mgr = pay.GestionnairePaiements(reg, {"cinetpay": "secret"})
        tx, _ = mgr.creer_transaction("C1", 100, "XOF", "CI", "wave",
                                      "cle-w")
        contenu = '{"transaction": "' + tx.id + '", "statut": "ok"}'
        signature = h.new(b"secret", contenu.encode(),
                          hashlib.sha256).hexdigest()
        assert mgr.confirmer_webhook(tx.id, contenu, signature) is True
        assert tx.statut == "reussie"

    def test_webhook_mauvaise_signature_refuse(self):
        reg = prv.RegistrePrestataires()
        reg.tous()[0].connected = True
        reg.tous()[0].methode = "wave"
        mgr = pay.GestionnairePaiements(reg, {"cinetpay": "secret"})
        tx, _ = mgr.creer_transaction("C1", 100, "XOF", "CI", "wave",
                                      "cle-b")
        assert mgr.confirmer_webhook(tx.id, "{}", "deadbeef") is False
        assert tx.statut == "signature_refusee"


    def test_le_moyen_demande_selectionne_le_bon_prestataire(self):
        reg = prv.RegistrePrestataires()
        reg.tous()[0].connected = True
        reg.tous()[0].methode = "wave"
        reg.tous()[1].connected = True
        reg.tous()[1].methode = "orange_money"
        tx, _ = pay.GestionnairePaiements(reg, {}).creer_transaction(
            "C1", 100, "XOF", "CI", "Orange Money", "cle-orange")
        assert tx.prestataire == "paydunya"

    def test_moyens_disponibles_respecte_les_moyens_du_pays(self):
        reg = prv.RegistrePrestataires()
        reg.tous()[0].connected = True
        reg.tous()[0].moyens_supportes = ("wave", "orange_money")
        mgr = pay.GestionnairePaiements(reg, {})
        disponibles = mgr.moyens_disponibles(
            "CI", ["Wave", "Visa"], "XOF")
        assert disponibles == [
            {"moyen": "wave", "prestataire": "cinetpay", "devise": "XOF"}]

    def test_moyen_non_pris_en_charge_refuse(self):
        reg = prv.RegistrePrestataires()
        reg.tous()[0].connected = True
        reg.tous()[0].methode = "wave"
        with pytest.raises(RuntimeError) as exc:
            pay.GestionnairePaiements(reg, {}).creer_transaction(
                "C1", 100, "XOF", "CI", "paypal", "cle-wrong-method")
        assert "aucun prestataire connecte" in str(exc.value)

    def test_webhook_signe_d_une_autre_transaction_refuse(self):
        import hashlib, hmac as h
        reg = prv.RegistrePrestataires()
        reg.tous()[0].connected = True
        reg.tous()[0].methode = "wave"
        mgr = pay.GestionnairePaiements(reg, {"cinetpay": "secret"})
        tx, _ = mgr.creer_transaction("C1", 100, "XOF", "CI", "wave",
                                      "cle-other-tx")
        contenu = '{"transaction": "AUTRE-TX", "statut": "ok"}'
        signature = h.new(b"secret", contenu.encode(),
                          hashlib.sha256).hexdigest()
        assert mgr.confirmer_webhook(tx.id, contenu, signature) is False
        assert tx.statut == "webhook_refuse"

    def test_webhook_montant_ou_devise_incorrects_refuses(self):
        import hashlib, hmac as h
        reg = prv.RegistrePrestataires()
        reg.tous()[0].connected = True
        reg.tous()[0].methode = "wave"
        mgr = pay.GestionnairePaiements(reg, {"cinetpay": "secret"})
        tx, _ = mgr.creer_transaction("C1", 100, "XOF", "CI", "wave",
                                      "cle-wrong-amount")
        contenu = ('{"transaction": "' + tx.id
                   + '", "statut": "ok", "amount": 999, "currency": "XOF"}')
        signature = h.new(b"secret", contenu.encode(),
                          hashlib.sha256).hexdigest()
        assert mgr.confirmer_webhook(tx.id, contenu, signature) is False
        assert tx.statut == "webhook_refuse"


    def test_geniuspay_est_inactif_sans_cles_et_secret_webhook(self):
        reg = prv.RegistrePrestataires()
        etat = reg.etat()["geniuspay"]
        assert etat["connecte"] is False

    def test_geniuspay_checkout_retourne_reference_et_url(self):
        class FakeClient:
            api_configured = True
            webhook_secret = "whsec_test"
            payment_ready = True

            def creer_checkout(self, **kwargs):
                assert kwargs["montant"] == 12000
                assert kwargs["commande"] == "CMD-GP"
                assert kwargs["devise"] == "XOF"
                return {"reference": "MTX-GP1",
                        "checkout_url": "https://geniuspay.ci/checkout/MTX-GP1"}

            def creer_checkout_wave(self, **kwargs):
                assert kwargs["montant"] == 12000
                assert kwargs["commande"] == "CMD-WAVE"
                assert kwargs["devise"] == "XOF"
                assert kwargs["client"]["country"] == "CI"
                return {"reference": "MTX-WAVE",
                        "checkout_url": "https://geniuspay.ci/pay/MTX-WAVE"}

        reg = prv.RegistrePrestataires(geniuspay_client=FakeClient())
        mgr = pay.GestionnairePaiements(reg)
        disponibles = mgr.moyens_disponibles("CI", ["Wave"], "XOF")
        assert {"moyen": "geniuspay_checkout",
                "prestataire": "geniuspay", "devise": "XOF"} in disponibles
        tx, new = mgr.creer_transaction(
            "CMD-GP", 12000, "XOF", "CI",
            "geniuspay_checkout", "cle-gp-1")
        assert new is True
        assert tx.reference_externe == "MTX-GP1"
        assert tx.url_paiement == "https://geniuspay.ci/checkout/MTX-GP1"

    def test_geniuspay_wave_direct_est_propose_et_route_le_paiement(self):
        class FakeClient:
            api_configured = True
            webhook_secret = "whsec_test"
            payment_ready = True

            def creer_checkout(self, **kwargs):
                raise AssertionError("Le checkout generique ne doit pas etre utilise")

            def creer_checkout_wave(self, **kwargs):
                assert kwargs["commande"] == "CMD-WAVE"
                return {"reference": "MTX-WAVE-ORDER",
                        "checkout_url": "https://geniuspay.ci/pay/MTX-WAVE-ORDER"}

        reg = prv.RegistrePrestataires(geniuspay_client=FakeClient())
        mgr = pay.GestionnairePaiements(reg)
        disponibles = mgr.moyens_disponibles("CI", ["Wave"], "XOF")
        assert {"moyen": "wave", "prestataire": "geniuspay",
                "devise": "XOF"} in disponibles

        tx, nouvelle = mgr.creer_transaction(
            "CMD-WAVE", 12000, "XOF", "CI", "wave", "cle-wave-1"
        )
        assert nouvelle is True
        assert tx.prestataire == "geniuspay"
        assert tx.reference_externe == "MTX-WAVE-ORDER"
        assert tx.url_paiement == "https://geniuspay.ci/pay/MTX-WAVE-ORDER"

    def test_geniuspay_wave_direct_non_propose_hors_ci_xof(self):
        class FakeClient:
            api_configured = True
            webhook_secret = "whsec_test"
            payment_ready = True

            def creer_checkout_wave(self, **kwargs):
                raise AssertionError("Wave ne doit pas etre propose")

        mgr = pay.GestionnairePaiements(
            prv.RegistrePrestataires(geniuspay_client=FakeClient())
        )
        assert not any(
            item["moyen"] == "wave"
            for item in mgr.moyens_disponibles("SN", ["Wave"], "XOF")
        )
        assert not any(
            item["moyen"] == "wave"
            for item in mgr.moyens_disponibles("CI", ["Wave"], "EUR")
        )

    def test_geniuspay_webhook_utilise_validateur_specifique(self):
        class FakeClient:
            api_configured = True
            webhook_secret = "whsec_test"
            payment_ready = True

            def creer_checkout(self, **kwargs):
                return {"reference": "MTX-GP2",
                        "checkout_url": "https://geniuspay.ci/checkout/MTX-GP2"}

            def webhook_paiement_reussi(self, **kwargs):
                assert kwargs["reference"] == "MTX-GP2"
                assert kwargs["commande"] == "CMD-GP2"
                return {"event": "payment.success"}

        reg = prv.RegistrePrestataires(geniuspay_client=FakeClient())
        mgr = pay.GestionnairePaiements(reg)
        tx, _ = mgr.creer_transaction(
            "CMD-GP2", 10000, "XOF", "CI",
            "geniuspay_checkout", "cle-gp-2")
        headers = {
            "X-Webhook-Timestamp": "1780000000",
            "X-Webhook-Event": "payment.success",
            "X-Webhook-Environment": "sandbox",
        }
        assert mgr.confirmer_webhook(
            tx.id, "{}", "signature", headers=headers) is True
        assert tx.statut == "reussie"

    def test_rapprochement_comptable(self):
        reg = prv.RegistrePrestataires()
        reg.tous()[0].connected = True
        reg.tous()[0].methode = "wave"
        mgr = pay.GestionnairePaiements(reg, {"cinetpay": "s"})
        mgr.creer_transaction("C1", 100, "XOF", "CI", "wave", "k1")
        mgr.creer_transaction("C2", 200, "XOF", "CI", "wave", "k2")
        lignes = mgr.rapprochement()
        assert sum(l["total"] for l in lignes) == 300


class TestFournisseurs:
    def test_cj_connecte_reellement(self):
        reg = sad.RegistreFournisseurs()
        assert list(reg.connectes()) == ["cj"]
        assert reg.connectes()["cj"].connected is True

    def test_autres_fournisseurs_non_connectes_explicites(self):
        reg = sad.RegistreFournisseurs()
        etat = reg.etat()
        assert etat["aliexpress"]["connecte"] is False
        assert etat["printful"]["connecte"] is False
        for nom, a in reg.tous().items():
            if nom != "cj":
                assert all(v is None for v in a.methodes().values())

    def test_import_csv_strict(self):
        csv_ok = ("nom_fournisseur,sku,nom_produit,prix_achat,devise,"
                  "stock,pays_expedition,delai_jours"
                  + chr(10) + "ACME,A1,Montre,4.50,USD,120,CN,12"
                  + chr(10) + "ACME,A2,Casque,abc,USD,50,CN,12"
                  + chr(10))
        g = sup.GestionnaireFournisseurs(sad.RegistreFournisseurs())
        r = g.importer_csv(csv_ok)
        assert r["ajoutes"] == [2] and r["refuses"] == [3]
        assert g.provenance() == {"csv": 1}

    def test_csv_mauvais_en_tete_refuse(self):
        g = sup.GestionnaireFournisseurs(sad.RegistreFournisseurs())
        with pytest.raises(ValueError, match="en-tete"):
            g.importer_csv("a,b\n1,2\n")

    def test_saisie_manuelle_controlee(self):
        g = sup.GestionnaireFournisseurs(sad.RegistreFournisseurs())
        e = g.saisie_manuelle(nom_fournisseur="LOCAL", sku="L1",
                               nom_produit="Sac", prix_achat="2500",
                               devise="XOF", stock="10",
                               pays_expedition="CI", delai_jours="3")
        assert e.origine == "saisie_manuelle"

    def test_catalogue_refuse_les_doublons(self):
        c = cat.CatalogueProduits()
        c.ajouter({"reference_unique": "R1", "fournisseur": "cj"})
        with pytest.raises(ValueError, match="doublon"):
            c.ajouter({"reference_unique": "R1"})

    def test_stocks_non_mesures_jamais_garantis(self):
        s = inv.GestionnaireStocks()
        assert s.stock("cj", "vid-x") is None
        assert s.disponible("cj", "vid-x", 1) is False
        s.enregistrer_mesure("cj", "vid-x", 5)
        assert s.disponible("cj", "vid-x", 5) is True
        assert s.disponible("cj", "vid-x", 6) is False
        assert s.alertes() == [{"fournisseur": "cj", "vid": "vid-x",
                                "stock": 5}]

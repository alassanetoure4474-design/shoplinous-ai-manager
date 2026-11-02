"""Tests paiement + fournisseurs SHOPLINOUS GLOBAL v6. Aucun reseau,
aucun vrai prestataire : la NON-connexion est testee elle-meme."""
import pytest

from global import payment_manager as pay
from global import payment_providers as prv
from global import supplier_manager as sup
from global import supplier_adapters as sad
from global import product_catalog as cat
from global import inventory as inv


class TestPrestataires:
    def test_aucun_prestataire_connecte_par_defaut(self):
        reg = prv.RegistrePrestataires()
        assert reg.actifs() == []
        assert set(reg.etat()) == {"cinetpay", "paydunya", "korapay",
                                   "stripe", "paypal"}
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
        mgr = pay.GestionnairePaiements(
            prv.RegistrePrestataires(), {},
            )
        # on force un prestataire connecte pour tester l idempotence
        reg = prv.RegistrePrestataires()
        reg.tous()[0].connected = True
        reg.tous()[0].methode = "wave"
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
                  "stock,pays_expedition,delai_jours\n"
                  "ACME,A1,Montre,4.50,USD,120,CN,12\n"
                  "ACME,A2,Casque,abc,USD,50,CN,12\n")
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

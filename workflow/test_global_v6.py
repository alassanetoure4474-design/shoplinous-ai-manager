"""Tests etape 3 SHOPLINOUS GLOBAL v6 : shipping, orders, tracking,
ai decision, notification, security, monitoring. Aucun reseau."""
import pytest

from shoplinous_global import shipping_manager as sh
from shoplinous_global import order_manager as om
from shoplinous_global import payment_manager as pay
from shoplinous_global import payment_providers as prv
from shoplinous_global import tracking_manager as tr
from shoplinous_global import ai_decision_engine as ai
from shoplinous_global import notification_manager as nt
from shoplinous_global import security_audit as sec
from shoplinous_global import monitoring as mo


def devis(cout, delai, dest="CI", qty=6, restrictions=True):
    return sh.DevisTransport("cj", "CJ", dest, qty, cout, "USD",
                             delai, restrictions)


class TestShippingManager:
    def test_selection_au_meilleur_cout(self):
        d = [devis(5.0, 10), devis(4.0, 14), devis(3.5, 9)]
        meilleur = sh.meilleur_devis(d, "CI", 6, 15)
        assert meilleur.cout == 3.5 and meilleur.delai_jours == 9

    def test_delai_non_conforme_exclu(self):
        d = [devis(4.0, 20)]
        assert sh.meilleur_devis(d, "CI", 6, 15) is None

    def test_mauvaise_destination_exclue(self):
        d = [devis(4.0, 10, dest="FR")]
        assert sh.meilleur_devis(d, "CI", 6, 15) is None

    def test_quantite_exacte_requise(self):
        d = [devis(4.0, 10, qty=5)]
        assert sh.meilleur_devis(d, "CI", 6, 15) is None

    def test_aucun_devis_jamais_extrapole(self):
        assert sh.meilleur_devis([], "CI", 6, 15) is None

    def test_restriction_douaniere_bloque(self):
        d = [devis(4.0, 10, restrictions=False)]
        assert sh.meilleur_devis(d, "CI", 6, 15) is None


class TestOrderManager:
    def _cmd(self):
        g = om.GestionnaireCommandes()
        c, nouvelle = g.creer("CMD-1", "CI", "XOF")
        return g, c

    def test_doublon_de_numero_refuse(self):
        g, _ = self._cmd()
        with pytest.raises(om.DoublonCommande):
            g.creer("CMD-1", "CI", "XOF")

    def test_reference_client_idempotente(self):
        g, _ = self._cmd()
        c2, nouvelle2 = g.creer("CMD-2", "CI", "XOF",
                                reference_client="panier-abc")
        c3, nouvelle3 = g.creer("CMD-3", "CI", "XOF",
                                reference_client="panier-abc")
        assert c2 is c3 and not nouvelle3

    def test_payee_impossible_sans_webhook(self):
        g, c = self._cmd()
        with pytest.raises(om.TransitionInvalide, match="webhook"):
            c.transition("payee")

    def test_commande_wave_associe_la_transaction_et_attend_le_webhook(self):
        class FakeClient:
            api_configured = True
            webhook_secret = "whsec_test"
            payment_ready = True

            def creer_checkout_wave(self, **kwargs):
                assert kwargs["commande"] == "CMD-WAVE"
                return {
                    "reference": "MTX-WAVE-ORDER",
                    "checkout_url": "https://geniuspay.ci/pay/MTX-WAVE-ORDER",
                }

            def webhook_paiement_reussi(self, **kwargs):
                assert kwargs["reference"] == "MTX-WAVE-ORDER"
                assert kwargs["commande"] == "CMD-WAVE"
                assert kwargs["montant"] == 3500
                assert kwargs["devise"] == "XOF"
                return {"event": "payment.success"}

        paiements = pay.GestionnairePaiements(
            prv.RegistrePrestataires(geniuspay_client=FakeClient())
        )
        g = om.GestionnaireCommandes(paiements)
        commande, _ = g.creer("CMD-WAVE", "CI", "XOF")

        tx, nouvelle = g.initier_paiement(
            "CMD-WAVE", 3500, "wave", "idem-cmd-wave"
        )
        assert nouvelle is True
        assert tx.prestataire == "geniuspay"
        assert tx.url_paiement.endswith("MTX-WAVE-ORDER")
        assert g.paiement_associe("CMD-WAVE") is tx
        assert commande.statut == "attente_paiement"

        # Le retour navigateur n'est jamais une preuve de paiement.
        assert paiements.confirmer_redirection(tx.id) is False
        assert commande.statut == "attente_paiement"

        headers = {
            "X-Webhook-Timestamp": "1780000000",
            "X-Webhook-Event": "payment.success",
            "X-Webhook-Environment": "sandbox",
        }
        assert g.confirmer_paiement_webhook(
            "CMD-WAVE", "{}", "signature", headers=headers
        ) is True
        assert tx.statut == "reussie"
        assert commande.statut == "payee"
        assert g.confirmer_paiement_webhook(
            "CMD-WAVE", "{}", "signature", headers=headers
        ) is True
        assert [entry[0] for entry in commande.journal].count("payee") == 1

    def test_commande_sans_transaction_ne_peut_pas_etre_payee(self):
        paiements = pay.GestionnairePaiements(prv.RegistrePrestataires())
        g = om.GestionnaireCommandes(paiements)
        commande, _ = g.creer("CMD-NO-PAYMENT", "CI", "XOF")
        assert g.confirmer_paiement_webhook(
            "CMD-NO-PAYMENT", "{}", "signature"
        ) is False
        assert commande.statut == "attente_paiement"

    def test_transmission_fournisseur_exige_autorisation(self):
        g, c = self._cmd()
        c.statut = "preparation"
        with pytest.raises(om.TransitionInvalide,
                           match="autorisation"):
            c.transition("transmission_fournisseur_autorisee")
        assert c.transition("transmission_fournisseur_autorisee",
                            autorisation_explicite=True) is True

    def test_parcours_complet_valide(self):
        g, c = self._cmd()
        c.statut = "payee"
        assert c.transition("validee")
        assert c.transition("preparation")
        assert c.transition("transmission_fournisseur_autorisee",
                            autorisation_explicite=True)
        assert c.transition("expediee")
        assert c.transition("livree")
        assert c.statut == "livree"
        assert len(c.journal) == 6

    def test_annulation_coherente(self):
        g, c = self._cmd()
        assert c.transition("annulee")
        with pytest.raises(om.TransitionInvalide):
            c.transition("livree")


class TestTracking:
    def test_suivi_et_dernier_evenement(self):
        g = tr.GestionnaireSuivi()
        g.enregistrer("CMD-1", "CJ", "expediee")
        dernier = g.dernier("CMD-1")
        assert dernier["statut"] == "expediee"
        assert g.historique("CMD-9") == []

    def test_evenement_incomplet_refuse(self):
        g = tr.GestionnaireSuivi()
        with pytest.raises(ValueError):
            g.enregistrer("", "CJ", "x")


class TestAIDecisionEngine:
    OPTIONS = [
        {"fournisseur": "cj", "cout_total": 10.0, "disponible": True,
         "delai_reel": 12, "fiabilite": 0.9, "destination_ok": True,
         "marge": 3.0},
        {"fournisseur": "local", "cout_total": 8.0,
         "disponible": True, "delai_reel": 3, "fiabilite": 0.8,
         "destination_ok": True, "marge": 2.0},
    ]

    def test_recommandation_deterministe_sur_donnees_verifiees(self):
        r = ai.recommander_fournisseur(self.OPTIONS, marge_minimale=1)
        assert r["decision"] == "recommandation"
        assert r["action"] == "AUTORISATION_REQUISE"
        assert r["fournisseur"] == "local"

    def test_option_incomplete_exclue(self):
        options = [dict(self.OPTIONS[0], delai_reel=None)]
        r = ai.recommander_fournisseur(options)
        assert r["decision"] == "aucune_option_verifiee"

    def test_marge_insuffisante_exclue(self):
        r = ai.recommander_fournisseur(self.OPTIONS, marge_minimale=5)
        assert r["decision"] == "aucune_option_verifiee"

    def test_aucune_action_d_achat_automatique(self):
        r = ai.recommander_fournisseur(self.OPTIONS)
        assert r["action"] == "AUTORISATION_REQUISE"

    def test_transport_sans_devis_echec_explicite(self):
        r = ai.recommander_transport([], "CI", 6, 15)
        assert r["decision"] == "aucun_devis_conforme"

    def test_justification_degrade_sans_ia(self):
        texte = ai.justifier({"decision": "recommandation"})
        assert isinstance(texte, str) and len(texte) > 0


class TestNotification:
    def test_journal_actif_email_non_connecte(self):
        g = nt.GestionnaireNotifications()
        canaux = g.canaux()
        assert canaux["journal"] is True
        assert canaux["email"] is False

    def test_envoi_sur_canal_non_connecte_refuse(self):
        g = nt.GestionnaireNotifications()
        r = g.envoyer("email", "a@b.cd", "bonjour")
        assert r["statut"] == "canal_non_connecte"

    def test_envoi_journal_redige_les_secrets_env(self, monkeypatch):
        monkeypatch.setenv("FREE_LLM_API_KEY", "SECRET-XYZ")
        g = nt.GestionnaireNotifications()
        r = g.envoyer("journal", "ops",
                      "configuration cle=SECRET-XYZ verifiee")
        assert "SECRET-XYZ" not in r["contenu"]
        assert "[REDACTE]" in r["contenu"]


class TestSecurityAudit:
    def test_redaction_des_secrets(self, monkeypatch):
        monkeypatch.setenv("FREE_LLM_API_KEY", "sk-super-secret")
        texte = sec.rediger("ma cle est sk-super-secret")
        assert "sk-super-secret" not in texte
        assert "[REDACTE]" in texte

    def test_signature_webhook_hmac(self):
        assert sec.verifier_signature_webhook("x", "aa" * 32, "s") is False
        import hashlib, hmac
        bonne = hmac.new(b"s", b"x", hashlib.sha256).hexdigest()
        assert sec.verifier_signature_webhook("x", bonne, "s") is True

    def test_chaine_audit_inviolable(self):
        j = sec.JournalAudit()
        j.ajouter("creation", "CMD-1")
        j.ajouter("paiement", "CMD-1 confirme")
        assert j.verifier_chaine() is True
        j.entrees()[0]["details"] = "falsifie"
        assert j.verifier_chaine() is False

    def test_pii_liste_blanche(self):
        donnees = {"nom": "Awa", "pays": "CI",
                   "numero_carte_bancaire": "4242...", "email": "a@b.cd"}
        filtre = sec.filtrer_donnees_client(donnees)
        assert "numero_carte_bancaire" not in filtre
        assert set(filtre) == {"nom", "pays", "email"}


class TestMonitoring:
    def test_sante_des_19_modules(self):
        m = mo.Monitoring()
        s = m.sante()
        assert len(s["modules"]) == 19
        assert s["modules_defaillants"] == []
        assert all(s["modules"].values())

    def test_compteurs(self):
        m = mo.Monitoring()
        m.evenement("commandes_creees")
        m.evenement("commandes_creees")
        assert m.compteurs.valeur("commandes_creees") == 2

    def test_connections_reelles_honnetes(self):
        m = mo.Monitoring()
        c = m.connections_reelles()
        assert c["fournisseurs"]["cj"]["connecte"] is True
        assert all(v["connecte"] is False
                  for v in c["paiement"].values())

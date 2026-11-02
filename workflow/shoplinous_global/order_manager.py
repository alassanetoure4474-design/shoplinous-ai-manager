"""Order Manager : machine a etats des commandes mondiales.

Statuts : attente_paiement, payee, validee, preparation,
transmission_fournisseur_autorisee, expediee, livree, annulee,
remboursee. Regles (testees) :
- Le paiement ne peut etre "payee" que sur confirmation webhook
  du Payment Manager (jamais une redirection).
- La transmission fournisseur exige une AUTORISATION EXPLICITE.
- Doublons de numero de commande impossibles ; transitions
  invalides refusees ; chaque transition est journalisee.
"""
import time

TRANSITIONS = {
    "attente_paiement": {"payee", "annulee", "expiree"},
    "payee": {"validee", "remboursee"},
    "validee": {"preparation", "annulee"},
    "preparation": {"transmission_fournisseur_autorisee", "annulee"},
    "transmission_fournisseur_autorisee": {"expediee"},
    "expediee": {"livree"},
    "livree": {"remboursee"},
    "annulee": set(),
    "remboursee": set(),
    "expiree": set(),
}

STATUTS = set(TRANSITIONS)


class DoublonCommande(ValueError):
    pass


class TransitionInvalide(ValueError):
    pass


class Commande:
    def __init__(self, numero, pays, devise, reference_client=None):
        self.numero = numero
        self.pays = pays
        self.devise = devise
        self.reference_client = reference_client
        self.statut = "attente_paiement"
        self.journal = [("attente_paiement", time.time())]

    def transition(self, nouveau, autorisation_explicite=False):
        autorises = TRANSITIONS.get(self.statut, set())
        if nouveau == "transmission_fournisseur_autorisee":
            if not autorisation_explicite:
                raise TransitionInvalide(
                    "transmission fournisseur : autorisation EXPLICITE "
                    "requise (jamais automatique)")
        if nouveau not in autorises:
            raise TransitionInvalide(
                "transition refusee: " + str(self.statut) + " -> "
                + str(nouveau))
        if self.statut == "attente_paiement" and nouveau == "payee":
            raise TransitionInvalide(
                "payee ne peut venir que de la confirmation webhook "
                "du Payment Manager")
        self.statut = nouveau
        self.journal.append((nouveau, time.time()))
        return True


class GestionnaireCommandes:
    def __init__(self, gestionnaire_paiements=None):
        self._par_numero = {}
        self._par_reference_client = {}
        self.paiements = gestionnaire_paiements

    def creer(self, numero, pays, devise, reference_client=None):
        if numero in self._par_numero:
            raise DoublonCommande("numero deja utilise: " + repr(numero))
        if reference_client and reference_client in (
                self._par_reference_client):
            return self._par_reference_client[reference_client], False
        c = Commande(numero, pays, devise, reference_client)
        self._par_numero[numero] = c
        if reference_client:
            self._par_reference_client[reference_client] = c
        return c, True

    def obtenir(self, numero):
        return self._par_numero[numero]

    def confirmer_paiement_webhook(self, numero, contenu, signature):
        """Passe la commande en payee UNIQUEMENT via le webhook signe
        du Payment Manager."""
        if self.paiements is None:
            raise RuntimeError("Payment Manager requis")
        commande = self.obtenir(numero)
        ok = self.paiements.confirmer_webhook(
            numero, contenu, signature)
        if ok:
            commande.statut = "payee"
            commande.journal.append(("payee", time.time()))
        return ok

    def transition(self, numero, nouveau, autorisation_explicite=False):
        return self.obtenir(numero).transition(
            nouveau, autorisation_explicite)

    def incoherences(self):
        problemes = []
        for numero, c in self._par_numero.items():
            if c.statut not in STATUTS:
                problemes.append({numero: "statut inconnu"})
        return problemes

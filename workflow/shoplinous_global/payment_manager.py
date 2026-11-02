"""Payment Manager : transactions, idempotence, webhooks.

Regles absolues (verifiees par tests) :
- Un paiement reussi n est JAMAIS declare a partir d une simple
  redirection navigateur : confirmer_redirection() refuse.
- Seul un webhook SIGNE (HMAC-SHA256, secret par prestataire) peut
  confirmer un paiement.
- Idempotence : une meme cle d idempotence retourne la MEME
  transaction, jamais un doublon.
- Aucun operateur non active sur le compte marchand n est affiche :
  seuls les prestataires connectes sont proposables.
"""
import hashlib
import hmac
import time


class Transaction:
    def __init__(self, identifiant, commande, montant, devise, pays,
                 moyen, prestataire, cle_idempotence):
        self.id = identifiant
        self.commande = commande
        self.montant = montant
        self.devise = devise
        self.pays = pays
        self.moyen = moyen
        self.prestataire = prestataire
        self.cle_idempotence = cle_idempotence
        self.statut = "creee"
        self.historique = [("creee", time.time())]

    def _passer(self, statut):
        self.statut = statut
        self.historique.append((statut, time.time()))


class GestionnairePaiements:
    def __init__(self, registre, secrets_webhook=None):
        self.registre = registre
        self._secrets = secrets_webhook or {}
        self._transactions = []
        self._par_idempotence = {}

    def moyens_disponibles(self, code_pays, moyens_pays, devise):
        """Liste HONNETE des moyens proposables : intersection des
        moyens du pays et des prestataires reellement connectes."""
        proposables = []
        for p in self.registre.pour_pays(code_pays, devise):
            proposables.append({
                "moyen": p.methode or p.nom, "prestataire": p.nom,
                "devise": devise})
        return proposables

    def creer_transaction(self, commande, montant, devise, pays, moyen,
                          cle_idempotence):
        if cle_idempotence in self._par_idempotence:
            return self._par_idempotence[cle_idempotence], False
        prestataires = self.registre.pour_pays(pays, devise)
        if not prestataires:
            raise RuntimeError(
                "aucun prestataire connecte pour " + pays + "/"
                + devise + " : transaction refusee plutot que simulee")
        identifiant = hashlib.sha256(
            (str(commande) + "|" + str(cle_idempotence)).encode()
        ).hexdigest()[:16]
        tx = Transaction(identifiant, commande, montant, devise, pays,
                         moyen, prestataires[0].nom, cle_idempotence)
        tx._passer("en_attente")
        self._transactions.append(tx)
        self._par_idempotence[cle_idempotence] = tx
        return tx, True

    def confirmer_redirection(self, transaction_id):
        """Une redirection navigateur ne prouve RIEN. Toujours refuse."""
        for tx in self._transactions:
            if tx.id == transaction_id:
                tx._passer("redirection_ignoree")
                return False
        raise KeyError("transaction inconnue")

    def verifier_signature(self, prestataire, contenu, signature):
        secret = self._secrets.get(prestataire)
        if not secret:
            return False
        attendu = hmac.new(secret.encode(), contenu.encode(),
                          hashlib.sha256).hexdigest()
        return hmac.compare_digest(attendu, str(signature))

    def confirmer_webhook(self, transaction_id, contenu, signature):
        """Confirmation UNIQUE par webhook signe. Signature invalide
        ou secret absent -> refus, transaction inchangee."""
        for tx in self._transactions:
            if tx.id == transaction_id:
                if not self.verifier_signature(tx.prestataire, contenu,
                                              signature):
                    tx._passer("signature_refusee")
                    return False
                if tx.statut in ("reussie", "remboursee"):
                    return True
                tx._passer("reussie")
                return True
        raise KeyError("transaction inconnue")

    def annuler(self, transaction_id):
        for tx in self._transactions:
            if tx.id == transaction_id and tx.statut == "en_attente":
                tx._passer("annulee")
                return True
        return False

    def expirations(self, delai_secondes=3600):
        maintenant = time.time()
        for tx in self._transactions:
            if tx.statut == "en_attente" and (
                    maintenant - tx.historique[0][1]) > delai_secondes:
                tx._passer("expiree")

    def rapprochement(self):
        """Rapprochement comptable : totaux par prestataire et statut,
        dans la devise de la transaction."""
        tableau = {}
        for tx in self._transactions:
            cle = (tx.prestataire, tx.devise, tx.statut)
            tableau[cle] = tableau.get(cle, 0) + tx.montant
        return [{"prestataire": k[0], "devise": k[1], "statut": k[2],
                 "total": v} for k, v in sorted(tableau.items())]

"""Payment Provider Adapters : architecture multi-prestataires.

HONNETETE STRUCTURELLE : aucun prestataire n est "connecte" tant que
le contrat marchand, la cle API et le webhook secret ne sont pas
fournis dans l environnement. Un adaptateur non connecte est visible
dans le registre mais JAMAIS propose au client. Aucune simulation
n est presentee comme une connexion reelle.

Prestataires prevus : GeniusPay, CinetPay, PayDunya, KoraPay, Stripe, PayPal.
Chaque adaptateur documente ses conditions (pays autorises, devises
de reglement, frais, delais de reversement, KYC) telles que
declarees publiquement ; elles doivent etre reconfirmees au moment
de la signature du contrat marchand.
"""
import os


class AdaptateurPaiement:
    """Interface commune. connected = contrat marchand REEL actif."""
    nom = "base"
    methode = None
    moyens_supportes = ()
    pays_supportes = ()
    devises_reglement = ()
    frais_indicatifs = None
    delai_reversement = None
    conditions_kyc = ()
    connected = False

    def est_actif(self):
        return bool(self.connected)

    def creer_paiement(self, transaction):
        raise RuntimeError(
            self.nom + " n est pas connecte : contrat marchand requis")

    def verifier_webhook(self, contenu, signature):
        raise RuntimeError(
            self.nom + " n est pas connecte : webhook secret requis")


class CinetPay(AdaptateurPaiement):
    nom = "cinetpay"
    pays_supportes = ("CI", "SN", "CM", "BF", "ML", "TG")
    devises_reglement = ("XOF", "XAF", "USD")
    frais_indicatifs = "variables par canal (mobile money)"
    delai_reversement = "a confirmer contractuellement"
    conditions_kyc = ("registre de commerce", "compte bancaire local")


class PayDunya(AdaptateurPaiement):
    nom = "paydunya"
    pays_supportes = ("CI", "SN", "BF", "ML", "TG", "BJ")
    devises_reglement = ("XOF",)
    frais_indicatifs = "variables par canal"
    delai_reversement = "a confirmer contractuellement"
    conditions_kyc = ("registre de commerce",)


class KoraPay(AdaptateurPaiement):
    nom = "korapay"
    pays_supportes = ("NG", "GH", "KE", "ZA")
    devises_reglement = ("NGN", "GHS", "KES", "ZAR", "USD")
    frais_indicatifs = "variables par canal"
    delai_reversement = "a confirmer contractuellement"
    conditions_kyc = ("KYC renforce selon volume",)


class Stripe(AdaptateurPaiement):
    nom = "stripe"
    pays_supportes = ("FR", "GB", "US", "CA")
    devises_reglement = ("EUR", "GBP", "USD", "CAD")
    frais_indicatifs = "carte : pourcentage + fixe (a confirmer)"
    delai_reversement = "7 a 14 jours selon pays"
    conditions_kyc = ("identite du representant", "rib")


class PayPal(AdaptateurPaiement):
    nom = "paypal"
    pays_supportes = ("FR", "GB", "US", "CA", "MA")
    devises_reglement = ("EUR", "GBP", "USD", "CAD")
    frais_indicatifs = "pourcentage + fixe (a confirmer)"
    delai_reversement = "variable"
    conditions_kyc = ("compte business verifie",)


class RegistrePrestataires:
    def __init__(self):
        self._prestataires = []
        for cls in (CinetPay, PayDunya, KoraPay, Stripe, PayPal):
            self._prestataires.append(cls())

    def tous(self):
        return list(self._prestataires)

    def actifs(self):
        return [p for p in self._prestataires if p.est_actif()]

    def pour_pays(self, code_pays, devise=None):
        """Seuls les prestataires CONNECTES et couvrant le pays (et la
        devise de reglement si fournie) sont retournes."""
        out = []
        for p in self.actifs():
            if code_pays in p.pays_supportes and (
                    devise is None or devise in p.devises_reglement):
                out.append(p)
        return out

    def etat(self):
        return {p.nom: {
            "connecte": p.est_actif(),
            "pays": list(p.pays_supportes),
            "devises": list(p.devises_reglement),
            "kyc": list(p.conditions_kyc)} for p in self._prestataires}

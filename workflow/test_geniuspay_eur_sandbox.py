"""Lance le test technique carte EUR avec les cles Sandbox uniquement."""
import sys

from shoplinous_global.geniuspay_eur import GeniusPayEurSandboxTester
from shoplinous_global.geniuspay import GeniusPayError


def main():
    client = GeniusPayEurSandboxTester.from_env()
    try:
        result = client.tester_carte_eur_sandbox()
    except GeniusPayError as exc:
        print("GENIUSPAY_EUR_FAILED: " + str(exc))
        return 1

    print("GENIUSPAY_EUR_SANDBOX_OK")
    print("environment=" + result["environnement"])
    print("country=" + result["pays"])
    print("amount_saisi=24.90 EUR (unites majeures)")
    print("amount_api=" + str(result["montant_api"]) + " centimes")
    print("gateways=" + ",".join(result["gateways"] or ["non_precises"]))
    print("status=" + result["statut"])
    print("webhook_success_verifie=" + str(result["webhook_verifie"]))
    print("attaques_repoussees=" + str(result["attaques_repoussees"]) + "/4")
    print("reference=" + result["reference"])
    print("transaction=simulated_sandbox_no_real_charge")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Lance le test technique carte EUR avec les cles Sandbox uniquement.

Chaque etape est signalee : en cas d'echec, la raison (sans secret) est
publiee en annotation GitHub afin de diagnostiquer sans jamais afficher
une cle.
"""
import sys

from shoplinous_global.geniuspay_eur import GeniusPayEurSandboxTester
from shoplinous_global.geniuspay import GeniusPayError


def _annoter(message: str) -> None:
    propre = "".join(c for c in message if ord(c) >= 32).replace("::", " ")
    print("::error::" + propre[:700])
    print("GENIUSPAY_EUR_FAILED: " + propre[:700])


def main():
    client = GeniusPayEurSandboxTester.from_env()
    try:
        result = client.tester_carte_eur_sandbox()
    except GeniusPayError as exc:
        _annoter("ETAPE:" + type(exc).__name__ + ":" + str(exc))
        return 1
    except Exception as exc:
        _annoter("ETAPE:INATTENDU:" + type(exc).__name__ + ":" + str(exc))
        return 1

    print("GENIUSPAY_EUR_SANDBOX_OK")
    print("environment=" + result["environnement"])
    print("country=" + result["pays"])
    print("amount_saisi=24.90 EUR (unites majeures)")
    print("amount_api=" + str(result["montant_api"]) + " centimes")
    print("gateways=" + ",".join(result["gateways"] || ["non_precises"]))
    print("status=" + result["statut"])
    print("webhook_success_verifie=" + str(result["webhook_verifie"]))
    print("attaques_repoussees=" + str(result["attaques_repoussees"]) + "/4")
    print("reference=" + result["reference"])
    print("transaction=simulated_sandbox_no_real_charge")
    return 0


if __name__ == "__main__":
    sys.exit(main())

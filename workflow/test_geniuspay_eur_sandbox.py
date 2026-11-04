"""Diagnostic carte EUR Sandbox : raison d'echec publiee en annotation.

Aucun secret n'est jamais affiche. Chaque etape est annotee pour
diagnostiquer precisement en cas d'echec.
"""
import sys
import traceback


def _annoter(message: str) -> None:
    propre = "".join(c for c in str(message) if ord(c) >= 32).replace("::", " ")
    print("::error::" + propre[:700])
    print("GENIUSPAY_EUR_DIAG: " + propre[:700], flush=True)


def main():
    print("ETAPE 1/5: imports", flush=True)
    try:
        from shoplinous_global.geniuspay_eur import GeniusPayEurSandboxTester
        from shoplinous_global.geniuspay import GeniusPayError
    except Exception as exc:
        _annoter("ETAPE_IMPORTS: " + type(exc).__name__ + ": " + str(exc))
        return 1

    print("ETAPE 2/5: construction du client depuis l'environnement", flush=True)
    try:
        client = GeniusPayEurSandboxTester.from_env()
    except Exception as exc:
        _annoter("ETAPE_CLIENT: " + type(exc).__name__ + ": " + str(exc))
        return 1

    print("ETAPE 3/5: test complet checkout EUR + relecture + webhook", flush=True)
    try:
        result = client.tester_carte_eur_sandbox()
    except GeniusPayError as exc:
        _annoter("ETAPE_TEST:" + type(exc).__name__ + ": " + str(exc))
        traceback.print_exc()
        return 1
    except Exception as exc:
        _annoter("ETAPE_TEST:INATTENDU:" + type(exc).__name__ + ": " + str(exc))
        traceback.print_exc()
        return 1

    print("ETAPE 4/5: resultat", flush=True)
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
    print("ETAPE 5/5: terminee avec succes", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

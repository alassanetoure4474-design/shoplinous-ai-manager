"""Lance le test technique Wave Direct avec les cles Sandbox uniquement."""
import sys

from shoplinous_global.geniuspay_wave import GeniusPayWaveSandboxTester
from shoplinous_global.geniuspay import GeniusPayError


def main():
    client = GeniusPayWaveSandboxTester.from_env()
    try:
        result = client.tester_wave_direct_sandbox()
    except GeniusPayError as exc:
        print("GENIUSPAY_WAVE_DIRECT_FAILED: " + str(exc))
        return 1

    print("GENIUSPAY_WAVE_DIRECT_SANDBOX_OK")
    print("environment=" + result["environnement"])
    print("country=" + result["pays"])
    print("gateway=" + result["gateway"])
    print("amount=" + str(result["montant"]) + " " + result["devise"])
    print("status=" + result["statut"])
    print("reference=" + result["reference"])
    print("transaction=simulated_sandbox_no_real_charge")
    return 0


if __name__ == "__main__":
    sys.exit(main())

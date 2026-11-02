"""Controle GeniusPay en lecture seule : compte et pays/opérateurs."""
import sys

from shoplinous_global.geniuspay import GeniusPayClient, GeniusPayError


def main():
    client = GeniusPayClient.from_env()
    if not client.api_configured:
        print("CONFIGURATION_INCOMPLETE: GENIUSPAY_API_KEY / GENIUSPAY_API_SECRET")
        return 2

    try:
        account = client.tester_connexion()
        print("GENIUSPAY_ACCOUNT_OK")
        print("environment=" + account["environnement"])
        print("status=" + account["statut"])
        if account.get("nom_marchand"):
            print("merchant=" + str(account["nom_marchand"])[:80])

        providers = client.fournisseurs_mobile_money()
        countries = providers.get("countries")
        if not isinstance(countries, list):
            print("PROVIDERS_RESPONSE_INCOMPLETE")
            return 1

        print("MOBILE_MONEY_COUNTRIES=" + str(len(countries)))
        for item in countries:
            if not isinstance(item, dict):
                continue
            code = str(item.get("country", "??"))
            names = [
                str(p.get("name", p.get("code", "")))
                for p in (item.get("providers") or [])
                if isinstance(p, dict)
            ]
            print(code + ": " + ", ".join(names))
        return 0
    except GeniusPayError as exc:
        # Les messages GeniusPayClient ne contiennent jamais les valeurs des cles.
        print("GENIUSPAY_CHECK_FAILED: " + str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())

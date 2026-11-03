"""Point d'entree du worker SHOPLINOUS image validator.

Imports robustes : selon la version du SDK, le paquet est expose soit comme
module autonome (`mistralai_workflows`), soit comme sous-module du SDK Mistral
(`mistralai.workflows`). Les deux formes sont essayees dans l'ordre.
"""

import asyncio

try:  # SDK recent : paquet autonome
    import mistralai_workflows as msw
except ImportError:  # SDK unifie : sous-module mistralai
    from mistralai import workflows as msw


async def main() -> None:
    decouverts = msw.discover_workflows()
    await msw.run_worker(decouverts)


if __name__ == "__main__":
    asyncio.run(main())

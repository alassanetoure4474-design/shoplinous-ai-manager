"""Point d'entree du worker SHOPLINOUS image validator."""

import asyncio

import mistralai_workflows
from mistralai_workflows import discover_workflows


async def main() -> None:
    decouverts = discover_workflows()
    await mistralai_workflows.run_worker(decouverts)


if __name__ == "__main__":
    asyncio.run(main())

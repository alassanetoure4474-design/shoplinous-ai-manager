"""Point d'entree du worker SHOPLINOUS image validator.

Le SDK Mistral Workflows expose directement run_worker(). Le worker lui
transmet explicitement les classes de workflow locales : aucun helper de
decouverte externe ou CLI n'est requis.
"""
import asyncio

import mistralai.workflows as workflows

from src.workflows.image_validator import ValidateurImagesWorkflow


async def main() -> None:
    await workflows.run_worker([ValidateurImagesWorkflow])


if __name__ == "__main__":
    asyncio.run(main())

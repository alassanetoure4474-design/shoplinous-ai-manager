import asyncio
import mistralai.workflows as workflows
from daily import ShoplinousDailyWorkflow

async def main():
    await workflows.run_worker([ShoplinousDailyWorkflow])

if __name__ == "__main__":
    asyncio.run(main())

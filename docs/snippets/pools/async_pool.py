import asyncio
import mqdm


async def fetch_one(i, delay=0.05):
    await asyncio.sleep(delay)
    return i * 10


async def main():
    results = await mqdm.apool(
        fetch_one,
        range(5),
        desc="fetching",
        n_workers=3,
    )
    mqdm.print(results)


asyncio.run(main())

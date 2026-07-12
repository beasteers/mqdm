import asyncio
import mqdm


async def fetch_one(i, delay=0.05):
    n = i * (1 if i%2 else -1) # variety
    for _ in mqdm.mqdm(range(50 + n), desc=f"fetching {i}", leave=False):
        await asyncio.sleep(delay)
    return i * 10


async def main():
    await mqdm.apool(
        fetch_one,
        range(10),
        desc="fetching",
        n_workers=3,
    )


asyncio.run(main())

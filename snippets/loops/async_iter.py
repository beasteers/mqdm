import asyncio
import mqdm


async def source():
    for i in range(5):
        await asyncio.sleep(0.05)
        yield i


async def main():
    async for i in mqdm.mqdm(source(), desc="streaming"):
        await asyncio.sleep(0.05)
        mqdm.print(f"handled item {i}")


asyncio.run(main())

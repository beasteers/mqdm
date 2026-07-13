import asyncio
import mqdm


async def source():
    for i in range(50):
        await asyncio.sleep(0.01)
        yield i


async def main():
    async for i in mqdm.mqdm(source(), total=50, desc="streaming"):
        await asyncio.sleep(0.05)


asyncio.run(main())

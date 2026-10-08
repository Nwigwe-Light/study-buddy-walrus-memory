import asyncio
import os
from dotenv import load_dotenv
from memwal import MemWal, RecallParams

load_dotenv()

async def main():
    memwal = MemWal.create(
        key=os.environ["MEMWAL_PRIVATE_KEY"],
        account_id=os.environ["MEMWAL_ACCOUNT_ID"],
        env="staging",
        namespace="demo",
    )

    print(await memwal.health())
    await memwal.remember_and_wait("I live in Onitsha and I am studying for exams.")

    result = await memwal.recall(RecallParams(query="What do we know about this user?"))
    for memory in result.results:
        print(memory.text, f"(distance: {memory.distance:.3f})")

    await memwal.close()

asyncio.run(main())
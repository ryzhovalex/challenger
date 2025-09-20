import aiosqlite as driver
from pathlib import Path
import location

Connection = driver.Connection
con: Connection


async def connect() -> Connection:
    return await driver.connect(location.user("data.db"))
         

class transaction:
    async def __aenter__(self):
        self.con = await connect()
        await self.con.execute("BEGIN")
        return self.con

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            await self.con.commit()
        else:
            await self.con.rollback()
        await self.con.close()


async def init():
    pass


async def deinit():
    pass

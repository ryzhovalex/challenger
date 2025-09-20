import aiosqlite as driver
from typing import Any
from pathlib import Path
import location

class Connection:
    def __await__(self):
        self.con = yield from driver.connect(location.user("data.db")).__await__()
        self.con.row_factory = Record
        return self.con

    async def close(self):
        await self.con.close()

    async def __aenter__(self):
        return await self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()


class Record(driver.Row):
    def __getattr__(self, name) -> Any:
        keys = list(self.keys())
        if name in keys:
            return self[name]
        raise AttributeError(f"Record '{self.__class__.__name__}' has no key '{name}', available keys: {keys}")


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


def connect() -> Connection:
    return Connection()

async def init():
    pass


async def deinit():
    pass

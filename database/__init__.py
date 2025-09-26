from typing import Any
from pathlib import Path
import location
from database import driver
from database.driver import Record, Connection, Cursor


class transaction:
    """
    Everything goes through transactions.
    """
    async def __aenter__(self):
        self.con = await driver.connect(location.user("data.db"))
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

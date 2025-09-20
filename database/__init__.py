import aiosqlite as driver

Connection = driver.Connection
con: Connection


async def connect() -> Connection:
    return await driver.connect(Path(data_dir, "data.db"))
         

class transaction:
    async def __aenter__(self):
        self.con = connect()
        await con.execute("BEGIN")
        return con

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            await con.commit()
        else:
            await con.rollback()


async def init():
    pass


async def deinit():
    pass

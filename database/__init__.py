import aiosqlite as driver

Connection = driver.Connection

async def connect() -> Connection:
    return database.connect(Path(data_dir, "data.db"))


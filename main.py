project_name = "challenger"

import httpx
import asyncio
import platform
import sys
from datetime import datetime, timezone

import location
location.init(project_name)

import log
log.init()

import config
config.init()

import xtime
xtime.init()

import build


async def init():
    local_date = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    log.info(f"{local_date}; {project_name} {build.version} ({'debug' if build.debug else 'release'} build {build.time}, {platform.system()} {platform.version()}, Python {python_version})")

async def deinit():
    pass

async def run():
    r = await request_steam("IPlayerService/GetOwnedGames/v1/?key={key}&steamid={steamid}")
    print(r, r.json(), sep="\n")

async def request_steam(route: str) -> httpx.Response:
    addr = "https://api.steampowered.com/"
    key = "34525A80B57ECF3B15AEBBC170409F20"
    steamid = "76561198016051984"
    data = {
        "key": key,
        "steamid": steamid,
    }
    async with httpx.AsyncClient() as client:
        return await client.get(addr + route.format(**data))

async def main():
    await init()
    await log.ainit()

    try:
        await run()
    except Exception as e:
        log.error(f"App is closed unexpectedly with an error: {e}", trace=e)
        raise e
    finally:
        await deinit()


if __name__ == "__main__":
    asyncio.run(main())

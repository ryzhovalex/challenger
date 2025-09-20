project_name = "challenger"

import httpx
from typing import Any
import asyncio
import platform
import web
import sys
import byteop
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

import pydantic


class User(pydantic.BaseModel):
    id: int
    profile_url: str
    avatar32: str
    avatar64: str
    avatar184: str
    username: str
    fullname: str
    current_game_id: int = 0
    current_game_name: str = ""
    registered_timestamp: int = 0

class Achievement(pydantic.BaseModel):
    id: str
    name: str
    description: str
    icon: str
    completed: bool
    unlock_timestamp: int


class Game(pydantic.BaseModel):
    id: int
    name: str
    play_time: int
    last_play_time: int
    achievements: list[Achievement]
    icon: str


requests_made = 0
completion = 0.0
games = []
completed_achievements = 0
total_achievements = 0


async def init():
    local_date = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    log.info(f"{local_date}; {project_name} {build.version} ({'debug' if build.debug else 'release'} build {build.time}, {platform.system()} {platform.version()}, Python {python_version})")
    web.init(get_web_user)


async def deinit():
    web.deinit()


async def get_web_user(id: int) -> web.User:
    return User(
        auth="whocares",
        username="whocares",
        fullname="whocares",
        permissions=[],
    )

@web.endpoint_module("home", response_headers={"content-type": "text/html"})
async def home(d: bytes) -> bytes:
    return byteop.string_to_bytes("<div>Hello!</div>")

async def run():
    await update_steam()
    await web.run()
    return 

async def update_steam():
    global user
    global games
    global completion
    global total_achievements
    global completed_achievements

    completion = 0.0
    games = []
    completed_achievements = 0
    total_achievements = 0

    key = "34525A80B57ECF3B15AEBBC170409F20"
    steamid = "76561198016051984"

    raw_user = (await request_steam(f"ISteamUser/GetPlayerSummaries/v0002/?key={key}&steamids={steamid}", {}))["response"]["players"][0]
    user = User(
        id = raw_user["steamid"],
        username = raw_user["profileurl"].split("/")[-2],
        fullname = raw_user["personaname"],
        profile_url = raw_user["profileurl"],
        avatar32 = raw_user["avatar"],
        avatar64 = raw_user["avatarmedium"],
        avatar184 = raw_user["avatarfull"],
        # current_game_id = raw_user["gameid"],
        # current_game_name = raw_user["gameextrainfo"],
        # registered_timestamp = raw_user["timecreated"],
    )

    r = await request_steam(f"IPlayerService/GetOwnedGames/v1/?key={key}&steamid={steamid}&include_appinfo=true&include_played_free_games=true", {})
    games = r["response"]["games"]

    tasks = []
    stats = []
    for game in games:
        # stat = await request_steam(f"ISteamUserStats/GetUserStatsForGame/v0002/?key={key}&steamid={steamid}&appid={game['appid']}", {})
        stat = await request_steam(f"ISteamUserStats/GetPlayerAchievements/v0001/?key={key}&steamid={steamid}&appid={game['appid']}&l=en", {})
        if stat == {}:
            stats.append([])
        else:
            stats.append(stat["playerstats"].get("achievements", []))

    # global_stats = []
    # for game in games:
    #     stat = await request_steam(f"ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/?key={key}&steamid={steamid}&gameid={game['appid']}", {})
    #     global_stats.append(stat)

    for raw_game, stat in zip(games, stats):
        achievements = []
        for s in stat:
            achievement = Achievement(
                id = s["apiname"],
                name = s["name"],
                description = s["description"],
                icon = "",  # @todo find out
                completed = s["achieved"],
                unlock_timestamp = s["unlocktime"],
            )
            achievements.append(achievement)
            total_achievements += 1
            if achievement.completed:
                completed_achievements += 1

        game = Game(
            id = raw_game["appid"],
            name = raw_game["name"],
            play_time = raw_game["playtime_forever"] * 60 * 1000,
            last_play_time = raw_game["rtime_last_played"] * 1000,
            achievements = achievements,
            icon = raw_game["img_icon_url"],
        )
        games.append(game)

    completion = completed_achievements / total_achievements


async def request_steam(route: str, default: Any) -> Any:
    global requests_made
    global current_parallel_requests
    global max_parallel_requests

    addr = "https://api.steampowered.com/"

    log.info(f"request '{route}'")
    requests_made += 1

    async with httpx.AsyncClient() as client:

        try:
            r = await client.get(addr + route)
            if r.status_code >= 400:
                log.error(f"request to '{route}' resulted in response #{r.status_code}")
                return default
            log.info(f"got response from '{route}'")
            return r.json()
        except Exception as e:
            log.error(f"request to '{route}' resulted in error: {e}")
            return default


async def main():
    global requests_made
    await init()
    await log.ainit()

    try:
        await run()
    except Exception as e:
        log.error(f"App is closed unexpectedly with an error: {e}", trace=e)
        raise e
    finally:
        log.info(f"made {requests_made} requests")
        await deinit()


if __name__ == "__main__":
    asyncio.run(main())

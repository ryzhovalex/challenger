project_name = "challenger"

import httpx
import datetime as dt
import sys
import aiofiles
import mako
import mako.template
import mako.lookup
from pathlib import Path
import tempfile
from typing import Any
import asyncio
import platform
import web
import sys
import database
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
    steam_id: int
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
    id: int
    steam_id: str
    name: str
    description: str
    icon: str
    completed: bool
    unlock_timestamp: int


class Game(pydantic.BaseModel):
    id: int
    steam_id: int
    name: str
    play_time: int
    last_play_time: int
    achievement_ids: list[int]
    icon: str


async def init():
    local_date = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    log.info(f"{local_date}; {project_name} {build.version} ({'debug' if build.debug else 'release'} build {build.time}, {platform.system()} {platform.version()}, Python {python_version})")
    await database.init()
    web.init(get_web_user)


async def deinit():
    web.deinit()
    await database.deinit()


async def get_web_user(id: int) -> web.User:
    return User(
        auth="whocares",
        username="whocares",
        fullname="whocares",
        permissions=[],
    )

@web.endpoint_module("home")
async def endpoint_home(d: bytes) -> bytes:
    lookup = mako.lookup.TemplateLookup(directories=["./"])
    template = mako.template.Template(filename="home.html", module_directory=Path(tempfile.gettempdir(), "mako_modules"), lookup=lookup)
    args = {}
    async with database.transaction() as con:
        async with con.execute("SELECT * FROM xuser LIMIT 1") as cur:
            row = await cur.fetchone()
            if row == None:
                raise Exception("missing user")
            args["avatar"] = row.avatar64
            args["fullname"] = row.fullname
        async with con.execute("SELECT completed, total, completion FROM completion ORDER BY id DESC LIMIT 1") as cur:
            row = await cur.fetchone()
            if row == None:
                raise Exception("missing completion info")
            args["completed"] = row.completed
            args["total"] = row.total
            args["completion"] = row.completion
        async with con.execute("SELECT last_timestamp FROM sync LIMIT 1") as cur:
            row = await cur.fetchone()
            if row == None:
                raise Exception("missing sync data")
            args["last_update_date"] = dt.datetime.fromtimestamp(row.last_timestamp, dt.UTC)

    web.as_html()
    return byteop.string_to_bytes(template.render(**args))

def crucial_task(task):
    try:
        message = f"Crucial task '{task.name}' has been finished."
        if task.cancelled():
            message += " Cancelled."
        elif task.exception() is not None:
            message += f" Exception: {task.exception()}"
        else:
            message += f" Result: {task.result()}"
        log.error(message)
    finally:
        sys.exit(1) 

async def run():
    steam_syncer_task = asyncio.create_task(steam_syncer())
    steam_syncer_task.add_done_callback(crucial_task)
    await web.run()
    return 

async def steam_syncer():
    last_timestamp = 0

    async with database.transaction() as con:
        async with con.execute("SELECT last_timestamp FROM sync") as cur:
            row = await cur.fetchone()
            assert row is not None
            last_timestamp = row[0]

    cooldown = 24 * 60 * 60

    next_date = dt.datetime.fromtimestamp(last_timestamp + cooldown, dt.UTC)
    log.info(f"planned steam sync at {next_date}")

    while True:
        time_diff = last_timestamp + cooldown - xtime.timestamp()
        if time_diff > 0:
            await asyncio.sleep(time_diff)

        log.info(f"start planned steam sync")
        async with database.transaction() as con:
            await sync_steam(con)
        last_timestamp = xtime.timestamp()
        async with database.transaction() as con:
            await con.execute("UPDATE sync SET last_timestamp = ?", (last_timestamp,))
        next_date = dt.datetime.fromtimestamp(last_timestamp + cooldown, dt.UTC)
        log.info(f"planned steam sync has been finished, next one will be at {next_date}")

@web.endpoint_function("main", "sync")
async def endpoint_sync(d: bytes) -> bytes:
    async with database.transaction() as con:
        await sync_steam(con)
    web.as_html()
    return byteop.string_to_bytes("ok")

async def sync_steam(con: database.Connection):
    global sync_in_progress
    if sync_in_progress:
        raise Exception("cannot start sync: another sync in progress")

    sync_in_progress = True

    try:
        completion = 0.0
        games = []
        completed_achievements = 0
        total_achievements = 0

        key = "34525A80B57ECF3B15AEBBC170409F20"
        steamid = "76561198016051984"

        raw_user = (await request_steam(f"ISteamUser/GetPlayerSummaries/v0002/?key={key}&steamids={steamid}", {}))["response"]["players"][0]
        user = User(
            id = 0,
            steam_id = raw_user["steamid"],
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
        async with con.execute("SELECT id FROM xuser") as cur:
            exists = await cur.fetchone() is not None
        if exists:
            await con.execute(
                "UPDATE xuser SET profile_url = ?, avatar32 = ?, avatar64 = ?, avatar184 = ?, username = ?, fullname = ?, current_game_id = ?, current_game_name = ?, registered_timestamp = ? WHERE steam_id = ?",
                (user.profile_url, user.avatar32, user.avatar64, user.avatar184, user.username, user.fullname, user.current_game_id, user.current_game_name, user.registered_timestamp, user.steam_id)
            )
        else:
            await con.execute(
                "INSERT INTO xuser (steam_id, profile_url, avatar32, avatar64, avatar184, username, fullname, current_game_id, current_game_name, registered_timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user.steam_id, user.profile_url, user.avatar32, user.avatar64, user.avatar184, user.username, user.fullname, user.current_game_id, user.current_game_name, user.registered_timestamp)
            )

        r = await request_steam(f"IPlayerService/GetOwnedGames/v1/?key={key}&steamid={steamid}&include_appinfo=true&include_played_free_games=true", {})
        games = r["response"]["games"]

        for raw_game in games:

            game = Game(
                id = 0,
                steam_id = raw_game["appid"],
                name = raw_game["name"],
                play_time = raw_game["playtime_forever"] * 60 * 1000,
                last_play_time = raw_game["rtime_last_played"] * 1000,
                achievement_ids = [],
                icon = raw_game["img_icon_url"],
            )

            async with con.execute("SELECT id FROM game WHERE steam_id = ?", (game.steam_id,)) as cur:
                exists = await cur.fetchone() is not None
            if exists:
                await con.execute(
                    "UPDATE game SET name = ?, play_time = ?, last_play_time = ?, icon = ? WHERE steam_id = ?",
                    (game.name, game.play_time, game.last_play_time, game.icon, game.steam_id),
                )
            else:
                await con.execute(
                    "INSERT INTO game (steam_id, name, play_time, last_play_time, icon) VALUES (?, ?, ?, ?, ?)",
                    (game.steam_id, game.name, game.play_time, game.last_play_time, game.icon),
                )

            # stat = await request_steam(f"ISteamUserStats/GetUserStatsForGame/v0002/?key={key}&steamid={steamid}&appid={game['appid']}", {})
            raw_stat = await request_steam(f"ISteamUserStats/GetPlayerAchievements/v0001/?key={key}&steamid={steamid}&appid={game.steam_id}&l=en", {})
            stat = []
            if raw_stat != {}:
                stat = raw_stat["playerstats"].get("achievements", [])
            for s in stat:
                achievement = Achievement(
                    id = 0,
                    steam_id = s["apiname"],
                    name = s["name"],
                    description = s["description"],
                    icon = "",  # @todo find out
                    completed = s["achieved"],
                    unlock_timestamp = s["unlocktime"],
                )

                async with con.execute("SELECT achievement.id FROM achievement JOIN game ON game.id = achievement.game_id WHERE achievement.steam_id = ? AND game.steam_id = ?", (achievement.steam_id, game.steam_id)) as cur:
                    exists = await cur.fetchone() is not None
                if exists:
                    await con.execute(
                        "UPDATE achievement SET name = ?, description = ?, icon = ?, completed = ?, unlock_timestamp = ?, game_id = (SELECT id FROM game WHERE steam_id = ?) WHERE steam_id = ?",
                        (achievement.name, achievement.description, achievement.icon, achievement.completed, achievement.unlock_timestamp, game.steam_id, achievement.steam_id)
                    )
                else:
                    await con.execute(
                        "INSERT INTO achievement (steam_id, name, description, icon, completed, unlock_timestamp, game_id) VALUES (?, ?, ?, ?, ?, ?, (SELECT id FROM game WHERE steam_id = ?))",
                        (achievement.steam_id, achievement.name, achievement.description, achievement.icon, achievement.completed, achievement.unlock_timestamp, game.steam_id)
                    )

                total_achievements += 1
                if achievement.completed:
                    completed_achievements += 1

        # global_stats = []
        # for game in games:
        #     stat = await request_steam(f"ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/?key={key}&steamid={steamid}&gameid={game['appid']}", {})
        #     global_stats.append(stat)

        if total_achievements > 0:
            completion = completed_achievements / total_achievements

        # completions are accumulated to form a story
        skip_story = False
        async with con.execute("SELECT * FROM completion ORDER BY id DESC LIMIT 1") as cur:
            row = await cur.fetchone()
            if row is not None and row.completion == completion and row.completed == completed_achievements and row.total == total_achievements:
                log.info("skip completion story add: nothing changed")
                skip_story = True
        if not skip_story:
            await con.execute("INSERT INTO completion (id, completion, completed, total) VALUES (?, ?, ?, ?)", (xtime.timestamp(), completion, completed_achievements, total_achievements))
    finally:
        sync_in_progress = False


content_types = {
    'html': 'text/html',
    'css': 'text/css',
    'js': 'application/javascript',
    'json': 'application/json',
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif': 'image/gif',
    'svg': 'image/svg+xml',
    'pdf': 'application/pdf',
    'zip': 'application/zip',
    'txt': 'text/plain',
    'xml': 'application/xml',
}


@web.endpoint_module_variable("share", response_coded=False)
async def endpoint_share(d: bytes) -> bytes:
    filename = web.request_variable()
    if "/" in filename:
        raise Exception("cannot change directories")
    path = location.source(Path("share", filename))
    extension = path.suffix.removeprefix(".")
    async with aiofiles.open(path, "rb") as f:
        content = await f.read()

        content_type = content_types.get(extension, "application/octet-stream")
        web.response_header("content-type", content_type)
        web.response_header("content-disposition", f"inline; filename={filename}")

        return content


async def request_steam(route: str, default: Any) -> Any:
    global current_parallel_requests
    global max_parallel_requests

    addr = "https://api.steampowered.com/"

    async with httpx.AsyncClient() as client:

        try:
            r = await client.get(addr + route)
            if r.status_code >= 400:
                log.error(f"request to '{route}' resulted in a response #{r.status_code} with an error: {r.text}")
                return default
            # log.info(f"got response from '{route}'")
            return r.json()
        except Exception as e:
            log.error(f"request to '{route}' resulted in error: {e}")
            return default


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

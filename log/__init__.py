import asyncio
import contextvars
import json
from pathlib import Path
import sys
import traceback
from typing import Any

import aiofiles
import colorama
import xrandom
import location
import xtime
import build

log_file: Any = None
file_write_tasks: dict[str, asyncio.Task] = {}
context = contextvars.ContextVar("log_context")

def debug(message: Any):
    if build.debug:
        print(f"{colorama.Fore.BLUE}DEBUG{colorama.Fore.RESET}: " + str(message), file=sys.stderr)  # noqa: T201

def extra(k: str, v: Any):
    d = context.get({})
    d[k] = v
    context.set(d)

def info(message: str):
    try:
        _save("info", message, None)
    except asyncio.QueueFull:
        print(f"CONSOLE: Log queue full.", file=sys.stderr)  # noqa: T201

def warn(message: str):
    try:
        _save("warning", "WARNING: " + message, None)
    except asyncio.QueueFull:
        print(f"CONSOLE: Log queue full.", file=sys.stderr)  # noqa: T201

def error(message: str, trace: Exception | None = None):
    """
    Note that for `trace` to work properly we need to catch an exception
    and immediatelly log-trace it using this function, or the traceback data
    will be incorrect.
    """
    trace_id: str | None = None

    # Trace error to special storage.
    if trace:
        loc_dir = location.user(Path("logs", "traces"))
        loc_dir.mkdir(parents=True, exist_ok=True)
        trace_id = xrandom.makeid()
        loc_name = trace_id
        loc = Path(loc_dir, loc_name + ".log")
        with loc.open("w+") as file:
            file.write(f"Trace #{trace_id} for an error '{trace}':\n" + traceback.format_exc())
    try:
        _save("error", "ERROR: " + message, trace_id)
    except asyncio.QueueFull:
        print(f"CONSOLE: Log queue full.", file=sys.stderr)  # noqa: T201

postponed = []

def _save(type: str, message: str, trace_id: str | None):
    if log_file is None:
        postponed.append((type, message, trace_id))
        return
    timestamp = xtime.timestamp()
    time = xtime.time()

    trace_message = ""
    if trace_id:
        trace_message = f" (trace '{trace_id}')"
    message =  f"{message} {trace_message}"

    # Nested into struct message do not need newline.
    message = message.strip()

    ctx = context.get({})
    module = ctx.pop("module", "")
    message_st = {
        "timestamp": timestamp,
        "time": time,
        "message": message,
        "type": type,
        "module": module,
        "context": ctx,
    }

    console_message = f"[{time:.3f}] {message}"
    console_message = console_message.strip() + "\n"

    if type == "error":
        console_message = console_message.replace("ERROR: ", f"{colorama.Fore.RED}ERROR{colorama.Fore.RESET}: ")
    elif type == "warning":
        console_message = console_message.replace("WARNING: ", f"{colorama.Fore.YELLOW}WARNING{colorama.Fore.RESET}: ")

    print(console_message, sep="", end="", file=sys.stderr)  # noqa: T201

    async def _write_file():
        try:
            # We save a new log for each server run.
            #
            # Each line of log_TIME.txt is a json object, but the whole file is not considered as a valid JSON.
            dump = json.dumps(message_st)
            dump = dump.strip()
            dump += "\n"
            await log_file.write(dump)

            # flush is needed to update file immediatelly for the external software
            # @perf Is it performant to call flush everytime write is done? If it's not, we can do it periodically, i.e. on each 5th log.
            await log_file.flush()
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"{colorama.Fore.RED}CRITICAL{colorama.Fore.RESET}: Failed to write to a log file with an error: {e}")

    task_id = xrandom.makeid()
    task = asyncio.create_task(_write_file())
    file_write_tasks[task_id] = task
    task.add_done_callback(lambda _: file_write_tasks.pop(task_id, None))

def init():
    pass

async def ainit():
    timestamp = xtime.timestamp()
    path = location.user(Path("log", f"{timestamp}.txt"))
    if path.exists():
        error(f"Log '{path}' already exist. Overwriting.")
    path.parent.mkdir(parents=True, exist_ok=True)
    global log_file
    log_file = await aiofiles.open(path, "w+")

    for p in postponed:
        _save(*p)
    postponed.clear()

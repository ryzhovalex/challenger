"""
Runtime is presented by `time` function and is measured as float seconds.

UTC timestamp is presented by `timestamp` function and is measured as integer seconds.
"""

import math
import time as native_time

started_ts: int = 0
started_ts_float: float = 0.0

def init():
    global started_ts
    started_ts = timestamp()
    global started_ts_float
    started_ts_float = native_time.time()

def timestamp() -> int:
    # in such case it's better to be behind the time, than in front of it
    return math.floor(native_time.time())

def time() -> float:
    return native_time.time() - started_ts_float

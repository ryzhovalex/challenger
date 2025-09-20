from datetime import datetime, timezone
import os
import sys
import xtime
import log
from pathlib import Path

_user: Path

def cwd(p: str | Path) -> Path:
    return Path(Path.cwd(), p)

def user(p: str | Path) -> Path:
    # @todo disallow path outs
    return Path(_user, p)

def source(p: str | Path) -> Path:
    return Path(Path(__file__).parent.parent, p)

def init(project_name: str):
    homedir = Path.home()

    # Define user dir:
    # * `~/appdata/roaming/PROJECT` on Windows.
    # * `~/.PROJECT` on Linux/MacOS.
    global _user
    if os.name == "nt":  # Windows.
        _user = Path(homedir, "AppData", "Roaming", project_name)
    else:  # Linux or macOS.
        _user = Path(homedir, "."+project_name)
    _user.mkdir(parents=True, exist_ok=True)

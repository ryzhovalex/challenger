import configparser
import location

_config: configparser.ConfigParser

def init():
    path = location.user("user.cfg")
    path.touch(exist_ok=True)

    global _config
    _config = configparser.ConfigParser()
    _config.read(path, "utf-8")

def get(section: str, key: str, default: str = "") -> str:
    return _config.get(section, key, fallback=default)
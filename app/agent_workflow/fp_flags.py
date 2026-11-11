import os


def flag(name: str, default: bool) -> bool:
    """Read at call time, so a test can set the environment."""
    raw = (os.environ.get(name) or "").strip().lower()
    if raw in {"on", "1", "true", "yes"}: return True
    if raw in {"off", "0", "false", "no"}: return False
    return default

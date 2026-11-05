import os
from urllib.parse import urlparse


class KeyRing:
    """Load X_API_KEY, X_API_KEY_2, ... and if they need, replace
    the first one."""

    def __init__(self, env_prefix: str) -> None:
        self.env_prefix = env_prefix
        self.keys: list[str] = []
        first = os.environ.get(f"{env_prefix}_API_KEY")
        if first:
            self.keys.append(first)
        i = 2
        while (key := os.environ.get(f"{env_prefix}_API_KEY_{i}")):
            self.keys.append(key)
            i += 1
        if not self.keys:
            raise RuntimeError(f"No keys {env_prefix}_API_KEY found..")
        self._index = 0

    def current(self) -> str:
        return self.keys[self._index]

    def rotate(self) -> str:
        self._index = (self._index + 1) % len(self.keys)
        return self.current()


def provider_prefix(url: str) -> str:
    """'https://openrouter.ai/api/v1' -> 'OPENROUTER'."""

    host = urlparse(url).hostname or ""
    parts = host.split(".")
    if parts[0] in ("api", "www") and len(parts) > 1:
        name = parts[1]
    elif parts[0] == "generativelanguage":
        name = "gemini"
    else:
        name = parts[0]

    return name.upper()

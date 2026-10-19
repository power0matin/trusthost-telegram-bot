from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic, max_items: int = 512) -> None:
        self._clock = clock
        self._max = max_items
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires <= self._clock():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        if len(self._data) >= self._max:
            now = self._clock()
            for k in [k for k, (exp, _) in self._data.items() if exp <= now]:
                self._data.pop(k, None)
            if len(self._data) >= self._max:
                self._data.pop(next(iter(self._data)))
        self._data[key] = (self._clock() + ttl, value)

    def invalidate(self, *prefixes: str) -> None:
        if not prefixes:
            self._data.clear()
            return
        for k in [k for k in self._data if k.startswith(prefixes)]:
            self._data.pop(k, None)

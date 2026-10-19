"""Non-blocking in-process guard against duplicate concurrent operations (double clicks)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class OperationInProgress(Exception):
    """Raised when the same operation is already running."""


class OperationGuard:
    def __init__(self) -> None:
        self._active: set[str] = set()

    def is_active(self, key: str) -> bool:
        return key in self._active

    @asynccontextmanager
    async def acquire(self, key: str) -> AsyncIterator[None]:
        if key in self._active:
            raise OperationInProgress(key)
        self._active.add(key)
        try:
            yield
        finally:
            self._active.discard(key)

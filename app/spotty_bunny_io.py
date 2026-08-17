"""Run blocking Spotty Bunny I/O with ``asyncio.to_thread``."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any


class ImmediateIo:
    """Run work on the caller (unit tests)."""

    def submit(
        self,
        fn: Callable[[], Any],
        on_done: Callable[[Any], None],
    ) -> None:
        try:
            on_done(fn())
        except Exception as exc:
            on_done(exc)


class ThreadIo:
    """Background asyncio loop; each job uses ``asyncio.to_thread``."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=self._run,
            name="spotty-bunny-io",
            daemon=True,
        )
        thread.start()

    def submit(
        self,
        fn: Callable[[], Any],
        on_done: Callable[[Any], None],
    ) -> None:
        async def work() -> None:
            try:
                result = await asyncio.to_thread(fn)
            except Exception as exc:
                result = exc
            on_done(result)

        asyncio.run_coroutine_threadsafe(work(), self._loop)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

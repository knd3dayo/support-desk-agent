from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import TypeVar

T = TypeVar("T")


def run_awaitable_sync(awaitable: Coroutine[object, object, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        with asyncio.Runner() as runner:
            return runner.run(awaitable)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_in_thread, awaitable)
        return future.result()


def _run_in_thread(awaitable: Coroutine[object, object, T]) -> T:
    with asyncio.Runner() as runner:
        return runner.run(awaitable)
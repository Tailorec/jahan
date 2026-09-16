"""The event loop the module owns, on a thread of its own.

`complete` is synchronous to its caller and concurrent inside, so the coroutines cannot run on a loop
the caller controls — a notebook is already inside a running loop, and a caller on the main thread has
no loop at all. One private loop, started lazily and shared by every client, answers both. The thread
is daemonised: it never holds a process open."""

import asyncio
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any

_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            started = threading.Event()

            def serve() -> None:
                asyncio.set_event_loop(loop)
                loop.call_soon(started.set)
                loop.run_forever()

            threading.Thread(target=serve, name="simcore-inference", daemon=True).start()
            started.wait()
            _loop = loop
        return _loop


def run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    """Drive one coroutine to completion on the module's loop and return its result, blocking only the
    calling thread. Safe to call from inside a running event loop, because that loop is not this one."""
    future: Future = asyncio.run_coroutine_threadsafe(coroutine, _ensure_loop())
    return future.result()

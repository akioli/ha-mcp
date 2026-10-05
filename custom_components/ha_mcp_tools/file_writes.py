"""Coordinate component mutations of one file within a Home Assistant loop."""

from __future__ import annotations

import asyncio
import os
import stat
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from weakref import WeakValueDictionary

_LOCKS: WeakValueDictionary[tuple[asyncio.AbstractEventLoop, Path], asyncio.Lock] = (
    WeakValueDictionary()
)


@asynccontextmanager
async def file_write_guard(
    target: Path, executor: Callable[..., Awaitable[Any]]
) -> AsyncIterator[None]:
    """Serialize component mutations, including aliases of the same file.

    External editors and other processes do not participate in this lock.
    Resolution belongs in the executor because it can access the filesystem.
    """
    resolved = await executor(target.resolve)
    key = (asyncio.get_running_loop(), resolved)
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    async with lock:
        yield


async def await_file_write[T](write: Awaitable[T]) -> T:
    """Drain a started executor write before allowing its guard to unwind.

    Cancelling an executor Future cannot stop its running thread. Shield the
    same job through repeated cancellation, then propagate cancellation after
    completion; never retry the filesystem operation.
    """
    future = asyncio.ensure_future(write)
    cancelled: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(future)
            break
        except asyncio.CancelledError as error:
            if future.cancelled():
                raise
            cancelled = cancelled or error
        except Exception as error:
            if cancelled is not None:
                raise cancelled from error
            raise
    if cancelled is not None:
        raise cancelled
    return result


class FileChangedDuringEditError(OSError):
    """The current source differs from the content used to prepare an edit."""


def atomic_replace_text(
    target: Path, content: str, *, expected_content: str | None = None
) -> None:
    """Replace a file using a private temporary sibling, cleaning it on failure.

    An optional source recheck detects external changes during preparation;
    it cannot exclude a non-cooperating writer after that final check.
    """
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = None
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            if mode is not None:
                os.fchmod(stream.fileno(), mode)
            stream.write(content)
        if expected_content is not None:
            try:
                current = target.read_text(newline="")
            except FileNotFoundError:
                current = ""
            if current != expected_content:
                raise FileChangedDuringEditError(
                    "File changed during the edit; nothing was written. "
                    "Request a fresh preview before retrying."
                )
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

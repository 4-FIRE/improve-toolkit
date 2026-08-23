"""MCP stdio transport compatible with Python 3.10+ and current AnyIO releases."""

from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator, Generic, TypeVar

import anyio

import mcp.types as types
from mcp.shared.message import SessionMessage


T = TypeVar("T")


class _ReceiveStream(Generic[T]):
    def __init__(self, queue: asyncio.Queue[T | None]) -> None:
        self._queue = queue
        self._closed = False

    async def __aenter__(self) -> "_ReceiveStream[T]":
        return self

    async def __aexit__(self, *_args) -> None:
        await self.aclose()

    def __aiter__(self) -> "_ReceiveStream[T]":
        return self

    async def __anext__(self) -> T:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def receive(self) -> T:
        item = await self._queue.get()
        if item is None:
            raise anyio.EndOfStream
        return item

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(None)


class _SendStream(Generic[T]):
    def __init__(self, output_queue: queue.Queue[T | None]) -> None:
        self._queue = output_queue
        self._closed = False

    async def __aenter__(self) -> "_SendStream[T]":
        return self

    async def __aexit__(self, *_args) -> None:
        await self.aclose()

    async def send(self, item: T) -> None:
        if self._closed:
            raise anyio.ClosedResourceError
        self._queue.put_nowait(item)

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(None)


@asynccontextmanager
async def stdio_server() -> AsyncIterator[
    tuple[
        _ReceiveStream[SessionMessage | Exception],
        _SendStream[SessionMessage],
    ]
]:
    """Expose MCP streams with blocking UTF-8 stdio and thread-safe queues.

    MCP's stock transport uses AnyIO async-file and memory-stream adapters.
    Some Python 3.13/AnyIO combinations leave those sends pending after the
    first message. This Adapter keeps the MCP stream Interface but uses stable
    direct POSIX fd readiness plus a blocking stdout daemon thread. Windows
    uses a stdin thread because its default event loop cannot watch console
    file descriptors. Only parsed messages cross the event-loop boundary.
    """
    incoming: asyncio.Queue[SessionMessage | Exception | None] = asyncio.Queue()
    outgoing: queue.Queue[SessionMessage | None] = queue.Queue()
    read_stream = _ReceiveStream(incoming)
    write_stream = _SendStream(outgoing)
    loop = asyncio.get_running_loop()
    stdin_fd = sys.stdin.fileno()
    stdin_buffer = bytearray()
    stdin_was_blocking = os.get_blocking(stdin_fd) if sys.platform != "win32" else True

    def parse_line(raw_line: bytes) -> SessionMessage | Exception:
        try:
            message = types.JSONRPCMessage.model_validate_json(
                raw_line.decode("utf-8", errors="replace")
            )
            return SessionMessage(message)
        except Exception as exc:  # noqa: BLE001 - protocol errors cross the stream
            return exc

    def enqueue(item: SessionMessage | Exception | None) -> None:
        incoming.put_nowait(item)

    def stdin_ready() -> None:
        try:
            chunk = os.read(stdin_fd, 65536)
        except BlockingIOError:
            return
        if not chunk:
            if stdin_buffer:
                enqueue(parse_line(bytes(stdin_buffer)))
                stdin_buffer.clear()
            loop.remove_reader(stdin_fd)
            enqueue(None)
            return
        stdin_buffer.extend(chunk)
        while b"\n" in stdin_buffer:
            raw_line, _, remainder = stdin_buffer.partition(b"\n")
            stdin_buffer[:] = remainder
            if raw_line.strip():
                enqueue(parse_line(raw_line))

    def stdin_reader() -> None:
        try:
            while True:
                raw_line = sys.stdin.buffer.readline()
                if not raw_line:
                    break
                loop.call_soon_threadsafe(enqueue, parse_line(raw_line))
        except (BrokenPipeError, RuntimeError):
            pass
        finally:
            try:
                loop.call_soon_threadsafe(enqueue, None)
            except RuntimeError:
                pass

    def stdout_writer() -> None:
        try:
            while True:
                session_message = outgoing.get()
                if session_message is None:
                    return
                payload = session_message.message.model_dump_json(
                    by_alias=True,
                    exclude_none=True,
                )
                sys.stdout.buffer.write(payload.encode("utf-8") + b"\n")
                sys.stdout.buffer.flush()
        except (BrokenPipeError, OSError):
            pass

    reader_thread = None
    writer_thread = threading.Thread(
        target=stdout_writer,
        name="improve-mcp-stdout",
        daemon=True,
    )
    if sys.platform == "win32":
        reader_thread = threading.Thread(
            target=stdin_reader,
            name="improve-mcp-stdin",
            daemon=True,
        )
        reader_thread.start()
    else:
        os.set_blocking(stdin_fd, False)
        loop.add_reader(stdin_fd, stdin_ready)
    writer_thread.start()
    try:
        yield read_stream, write_stream
    finally:
        if sys.platform != "win32":
            loop.remove_reader(stdin_fd)
            os.set_blocking(stdin_fd, stdin_was_blocking)
        await write_stream.aclose()

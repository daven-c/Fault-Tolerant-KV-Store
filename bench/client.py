"""Asyncio client for the KV store's line protocol, with leader redirection."""

from __future__ import annotations

import asyncio
import time


class Unavailable(Exception):
    """No node acknowledged the request before the deadline."""


class KVClient:
    """One persistent connection, one request in flight (the server's sessions are strictly
    request/response). Follows `NOT_LEADER <addr>` redirects and fails over on connection errors."""

    def __init__(self, addrs: list[str], request_timeout: float = 1.0, start: int = 0):
        self.addrs = addrs
        self.request_timeout = request_timeout
        self.target = start % len(addrs)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def call_once(self, line: str, timeout: float | None = None) -> str:
        """Send to the current target without retrying. Raises on any transport failure."""
        timeout = self.request_timeout if timeout is None else timeout
        try:
            if self._writer is None:
                host, port = self.addrs[self.target].split(":")
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(host, int(port)), timeout)
            self._writer.write(line.encode() + b"\n")
            await self._writer.drain()
            raw = await asyncio.wait_for(self._reader.readline(), timeout)
            if not raw:
                raise ConnectionResetError("server closed connection")
            return raw.decode(errors="replace").rstrip("\r\n")
        except BaseException:
            # The request may still be pending server-side; never reuse this connection.
            self.close()
            raise

    async def execute(self, line: str, deadline: float) -> str:
        """Retry across nodes until a non-redirect reply arrives or `deadline` (monotonic) passes."""
        while time.monotonic() < deadline:
            try:
                reply = await self.call_once(line, min(self.request_timeout, max(0.01, deadline - time.monotonic())))
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                self._rotate()
                await asyncio.sleep(0.01)
                continue
            if not reply.startswith("NOT_LEADER"):
                return reply
            self.close()
            parts = reply.split()
            if len(parts) > 1 and parts[1] in self.addrs and self.addrs.index(parts[1]) != self.target:
                self.target = self.addrs.index(parts[1])
            else:
                self._rotate()
                await asyncio.sleep(0.02)  # election in progress
        raise Unavailable(line)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
        self._reader = self._writer = None

    def _rotate(self) -> None:
        self.close()
        self.target = (self.target + 1) % len(self.addrs)


async def find_leader(addrs: list[str], candidates: list[int], timeout: float = 10.0) -> int:
    """Index of the node that accepts a client command (followers answer NOT_LEADER)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for i in candidates:
            c = KVClient(addrs, request_timeout=0.5, start=i)
            try:
                if not (await c.call_once("GET __probe__")).startswith("NOT_LEADER"):
                    return i
            except (OSError, asyncio.TimeoutError):
                pass
            finally:
                c.close()
        await asyncio.sleep(0.05)
    raise Unavailable("no leader elected")

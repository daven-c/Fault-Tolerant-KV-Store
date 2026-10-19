"""Process-level control of a local Raft cluster: spawn, kill, restart, inspect AOFs."""

from __future__ import annotations

import re
import signal
import socket
import subprocess
import time
from pathlib import Path

AOF_LINE = re.compile(r'^(SET|DEL) "([^"]*)"(?: "([^"]*)")?$')


class Cluster:
    """N server processes on 127.0.0.1:<base_port + i>, all sharing one scratch working directory.

    The server writes AOFs/node_<id>.aof relative to its cwd, so every cluster gets a fresh
    directory and runs never see each other's state.
    """

    def __init__(self, binary: Path, size: int, workdir: Path, base_port: int = 18000):
        self.binary = str(binary)
        self.size = size
        self.workdir = Path(workdir)
        self.base_port = base_port
        self.addrs = [f"127.0.0.1:{base_port + i}" for i in range(size)]
        self.procs: list[subprocess.Popen | None] = [None] * size

    def __enter__(self) -> "Cluster":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        for i in range(self.size):
            if _port_open(self.base_port + i):
                raise RuntimeError(f"port {self.base_port + i} already in use; pass --base-port")
        for i in range(self.size):
            self.start_node(i, wait=False)
        for i in range(self.size):
            self._wait_listening(i)

    def start_node(self, i: int, wait: bool = True) -> None:
        with open(self.workdir / f"node_{i}.log", "ab") as log:
            self.procs[i] = subprocess.Popen(
                [self.binary, str(i), *self.addrs],
                cwd=self.workdir, stdout=log, stderr=subprocess.STDOUT,
            )
        if wait:
            self._wait_listening(i)

    def kill_node(self, i: int, sig: int = signal.SIGKILL) -> None:
        proc = self.procs[i]
        if proc is not None and proc.poll() is None:
            proc.send_signal(sig)
            proc.wait(timeout=5)
        self.procs[i] = None

    def stop(self) -> None:
        for i in range(self.size):
            self.kill_node(i)

    def alive(self) -> list[int]:
        return [i for i, p in enumerate(self.procs) if p is not None and p.poll() is None]

    def aof_state(self, i: int) -> dict[str, str]:
        """Replay node i's AOF into the key/value map it represents (harness keys excluded)."""
        state: dict[str, str] = {}
        path = self.workdir / "AOFs" / f"node_{i}.aof"
        if not path.exists():
            return state
        for line in path.read_text(errors="replace").splitlines():
            m = AOF_LINE.match(line)
            if not m or m.group(2).startswith("__"):
                continue
            if m.group(1) == "SET":
                state[m.group(2)] = m.group(3) or ""
            else:
                state.pop(m.group(2), None)
        return state

    def _wait_listening(self, i: int, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            proc = self.procs[i]
            if proc is None or proc.poll() is not None:
                raise RuntimeError(f"node {i} exited during startup; see {self.workdir}/node_{i}.log")
            if _port_open(self.base_port + i):
                return
            time.sleep(0.01)
        raise RuntimeError(f"node {i} did not start listening within {timeout}s")


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0

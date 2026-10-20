#!/usr/bin/env python3
"""Interactive cluster dashboard: a local web UI that runs a real Raft cluster you can poke at.

    python3 dashboard/server.py              # builds the server, opens http://localhost:8090
    python3 dashboard/server.py --nodes 3 --port 9000 --no-browser

The backend owns the server processes (create, kill, restart, pause/resume), polls each node's
STATUS once every 200 ms, derives an event log from the changes, runs an optional closed-loop
load generator, and serves a small JSON API to the single-page frontend in index.html.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import random
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "bench"))

from cluster import Cluster  # noqa: E402
from harness import build, find_toolchain  # noqa: E402

MAX_NODES = 7
POLL_INTERVAL = 0.2


# ------------------------------------------------------------------------------------------------
# Line-protocol client
# ------------------------------------------------------------------------------------------------

class Conn:
    """One persistent connection to one node; one request at a time."""

    def __init__(self, addr: str, timeout: float = 1.0):
        host, port = addr.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def call(self, line: str, multiline: bool = False) -> str:
        self.sock.sendall(line.encode() + b"\n")
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        if multiline:  # KEYS replies with several lines and no terminator: drain until quiet
            self.sock.settimeout(0.05)
            try:
                while True:
                    chunk = self.sock.recv(65536)
                    if not chunk:
                        break
                    self.buf += chunk
            except socket.timeout:
                pass
            finally:
                self.sock.settimeout(1.0)
            reply, self.buf = self.buf, b""
            return reply.decode(errors="replace").rstrip("\n")
        line_bytes, self.buf = self.buf.split(b"\n", 1)
        return line_bytes.decode(errors="replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def route(addrs: list[str], line: str, start: int, deadline: float,
          multiline: bool = False) -> tuple[str, int, list[str]]:
    """Send `line` to the cluster, following NOT_LEADER redirects. Returns (reply, node, hops)."""
    target, hops = start, []
    while time.monotonic() < deadline:
        try:
            conn = Conn(addrs[target], timeout=max(0.05, min(1.0, deadline - time.monotonic())))
            try:
                reply = conn.call(line, multiline)
            finally:
                conn.close()
        except OSError:
            hops.append(f"node {target}: unreachable")
            target = (target + 1) % len(addrs)
            time.sleep(0.02)
            continue
        if not reply.startswith("NOT_LEADER"):
            return reply, target, hops
        parts = reply.split()
        hops.append(f"node {target}: {reply}")
        if len(parts) > 1 and parts[1] in addrs and addrs.index(parts[1]) != target:
            target = addrs.index(parts[1])
        else:
            target = (target + 1) % len(addrs)
            time.sleep(0.05)
    raise TimeoutError("not acknowledged within 5 s: a write commits only once a majority of nodes "
                       "has it, so check that enough nodes are up")


# ------------------------------------------------------------------------------------------------
# Cluster manager
# ------------------------------------------------------------------------------------------------

class Manager:
    def __init__(self, binary: Path, base_port: int):
        self.binary = binary
        self.base_port = base_port
        self.lock = threading.RLock()
        self.cluster: Cluster | None = None
        self.workdir: Path | None = None
        self.paused: set[int] = set()
        self.status: list[dict] = []
        self.events: deque[dict] = deque(maxlen=200)
        self.event_seq = 0
        self.generation = 0
        self.started_at = time.time()
        # load generator
        self.load_clients = 0
        self.load_threads: list[threading.Thread] = []
        self.load_gen = 0
        self.buckets: deque[dict] = deque(maxlen=60)
        self.bucket_lock = threading.Lock()
        self.load_ok = 0
        self.load_errors = 0
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._bucket_loop, daemon=True).start()

    # --- events ---------------------------------------------------------------------------------

    def event(self, kind: str, text: str) -> None:
        with self.lock:
            self.event_seq += 1
            self.events.append({"id": self.event_seq, "t": time.time(), "kind": kind, "text": text})

    # --- lifecycle ------------------------------------------------------------------------------

    def create(self, size: int) -> None:
        size = max(1, min(MAX_NODES, size))
        with self.lock:
            self._teardown()
            self.generation += 1
            self.workdir = Path(tempfile.mkdtemp(prefix="kvdash-"))
            self.cluster = Cluster(self.binary, size, self.workdir, self.base_port)
            self.paused = set()
            self.status = []
            self.cluster.start()
            self.event("cluster", f"Created a {size}-node cluster on ports "
                                  f"{self.base_port}-{self.base_port + size - 1}")
        self._restart_load()

    def _teardown(self) -> None:
        if self.cluster is None:
            return
        for i in list(self.paused):
            self._signal(i, signal.SIGCONT)
        self.cluster.stop()
        if self.workdir:
            shutil.rmtree(self.workdir, ignore_errors=True)
        self.cluster = None

    def shutdown(self) -> None:
        self.load_clients = 0
        self.load_gen += 1
        with self.lock:
            self._teardown()

    def _signal(self, i: int, sig: int) -> None:
        proc = self.cluster.procs[i] if self.cluster else None
        if proc is not None and proc.poll() is None:
            os.kill(proc.pid, sig)

    def node_action(self, i: int, action: str) -> None:
        with self.lock:
            if self.cluster is None or not 0 <= i < self.cluster.size:
                raise ValueError("no such node")
            alive = i in self.cluster.alive()
            if action == "kill" and alive:
                self._signal(i, signal.SIGCONT)
                self.cluster.kill_node(i)
                self.paused.discard(i)
                self.event("kill", f"Killed node {i} (SIGKILL)")
            elif action == "restart":
                if alive:
                    self._signal(i, signal.SIGCONT)
                    self.cluster.kill_node(i)
                self.paused.discard(i)
                self.cluster.start_node(i)
                self.event("restart", f"Restarted node {i}; it restores its Raft state from disk")
            elif action == "pause" and alive and i not in self.paused:
                self._signal(i, signal.SIGSTOP)
                self.paused.add(i)
                self.event("pause", f"Paused node {i} (SIGSTOP): it stops responding but keeps its sockets")
            elif action == "resume" and i in self.paused:
                self._signal(i, signal.SIGCONT)
                self.paused.discard(i)
                self.event("resume", f"Resumed node {i} (SIGCONT)")
            else:
                raise ValueError(f"can't {action} node {i} right now")

    # --- polling --------------------------------------------------------------------------------

    def _poll_loop(self) -> None:
        conns: dict[str, Conn] = {}
        gen = -1
        while True:
            time.sleep(POLL_INTERVAL)
            with self.lock:
                cluster, paused = self.cluster, set(self.paused)
                if self.generation != gen:
                    for c in conns.values():
                        c.close()
                    conns, gen = {}, self.generation
                    prev: list[dict] = []
                else:
                    prev = self.status
            if cluster is None:
                continue
            alive = set(cluster.alive())
            snapshot = []
            for i, addr in enumerate(cluster.addrs):
                node = {"id": i, "addr": addr, "status": "down"}
                if i in paused:
                    node["status"] = "paused"
                elif i in alive:
                    # A cached connection dies when its node restarts; retry once on a fresh one.
                    for attempt in range(2):
                        try:
                            conn = conns.get(addr) or Conn(addr, timeout=0.3)
                            conns[addr] = conn
                            node.update(json.loads(conn.call("STATUS")))
                            node["status"] = node.pop("state")
                            break
                        except (OSError, ValueError):
                            stale = conns.pop(addr, None)
                            if stale:
                                stale.close()
                            node["status"] = "unresponsive"
                else:
                    conns.pop(addr, None)
                # keep the last known Raft numbers for nodes that can't answer right now
                if node["status"] in ("paused", "down", "unresponsive") and i < len(prev):
                    for k in ("term", "log", "commit", "applied", "keys", "last_log_term"):
                        if k in prev[i]:
                            node[k] = prev[i][k]
                snapshot.append(node)
            self._diff(prev, snapshot)
            with self.lock:
                if self.generation == gen:
                    self.status = snapshot

    def _diff(self, prev: list[dict], cur: list[dict]) -> None:
        if not prev:
            return
        leader_before = next((n for n in prev if n["status"] == "leader"), None)
        leader_now = next((n for n in cur if n["status"] == "leader"), None)
        for p, c in zip(prev, cur):
            if c["status"] == "candidate" and (p["status"] != "candidate" or p.get("term") != c.get("term")):
                self.event("election", f"Node {c['id']} timed out and started an election for term {c.get('term')}")
            if p["status"] in ("follower", "candidate", "leader") and c["status"] == "unresponsive":
                self.event("warn", f"Node {c['id']} stopped answering")
        if leader_now and (not leader_before or leader_before["id"] != leader_now["id"]
                           or leader_before.get("term") != leader_now.get("term")):
            self.event("leader", f"Node {leader_now['id']} is leader for term {leader_now.get('term')}")
        elif leader_before and not leader_now:
            self.event("warn", "No leader: the cluster can't accept writes until one is elected")

    # --- commands -------------------------------------------------------------------------------

    def command(self, line: str, target: int | None) -> dict:
        with self.lock:
            if self.cluster is None:
                raise ValueError("create a cluster first")
            addrs = list(self.cluster.addrs)
            leader = next((n["id"] for n in self.status if n["status"] == "leader"), 0)
        multiline = line.strip().upper().startswith("KEYS")
        t0 = time.monotonic()
        if target is not None:
            conn = Conn(addrs[target], timeout=3.0)
            try:
                reply = conn.call(line, multiline)
            finally:
                conn.close()
            node, hops = target, []
        else:
            reply, node, hops = route(addrs, line, leader, time.monotonic() + 5.0, multiline)
        return {"reply": reply, "node": node, "hops": hops, "ms": round((time.monotonic() - t0) * 1000, 2)}

    # --- load generator -------------------------------------------------------------------------

    def set_load(self, clients: int) -> None:
        self.load_clients = max(0, min(64, clients))
        self._restart_load()
        self.event("load", f"Load generator: {self.load_clients} concurrent client(s)"
                   if self.load_clients else "Load generator stopped")

    def _restart_load(self) -> None:
        self.load_gen += 1
        gen = self.load_gen
        for w in range(self.load_clients):
            threading.Thread(target=self._load_worker, args=(gen, w), daemon=True).start()

    def _load_worker(self, gen: int, w: int) -> None:
        rng = random.Random(w)
        conn: Conn | None = None
        target = 0
        while self.load_gen == gen:
            with self.lock:
                addrs = list(self.cluster.addrs) if self.cluster else []
                leader = next((n["id"] for n in self.status if n["status"] == "leader"), None)
            if not addrs or leader is None:
                time.sleep(0.1)
                continue
            if conn is None or target != leader:
                if conn:
                    conn.close()
                try:
                    conn, target = Conn(addrs[leader], timeout=1.0), leader
                except OSError:
                    conn = None
                    time.sleep(0.05)
                    continue
            key = f"load:{rng.randrange(1000)}"
            line = f"SET {key} {rng.randrange(10**6)}" if rng.random() < 0.5 else f"GET {key}"
            t0 = time.monotonic()
            try:
                reply = conn.call(line)
                ok = not reply.startswith(("NOT_LEADER", "ERR"))
            except OSError:
                conn.close()
                conn, ok = None, False
            self._record(ok, (time.monotonic() - t0) * 1000)
            if not ok:
                time.sleep(0.02)
        if conn:
            conn.close()

    def _record(self, ok: bool, ms: float) -> None:
        with self.bucket_lock:
            if not self.buckets:
                return
            b = self.buckets[-1]
            if ok:
                b["ops"] += 1
                b["lat"].append(ms)
                self.load_ok += 1
            else:
                b["errors"] += 1
                self.load_errors += 1

    def _bucket_loop(self) -> None:
        while True:
            with self.bucket_lock:
                self.buckets.append({"t": time.time(), "ops": 0, "errors": 0, "lat": []})
            time.sleep(1.0)

    def load_series(self) -> list[dict]:
        with self.bucket_lock:
            out = []
            for b in list(self.buckets)[:-1]:  # the newest bucket is still filling
                lat = sorted(b["lat"])
                p50 = lat[len(lat) // 2] if lat else None
                p99 = lat[min(len(lat) - 1, int(len(lat) * 0.99))] if lat else None
                out.append({"t": b["t"], "ops": b["ops"], "errors": b["errors"],
                            "p50": None if p50 is None else round(p50, 2),
                            "p99": None if p99 is None else round(p99, 2)})
            return out

    # --- snapshot for the UI --------------------------------------------------------------------

    def state(self, since: int) -> dict:
        with self.lock:
            nodes = [dict(n) for n in self.status]
            events = [e for e in self.events if e["id"] > since]
            size = self.cluster.size if self.cluster else 0
            generation = self.generation
        return {"size": size, "generation": generation, "nodes": nodes, "events": events,
                "load": {"clients": self.load_clients, "series": self.load_series(),
                         "ok": self.load_ok, "errors": self.load_errors},
                "max_nodes": MAX_NODES}


# ------------------------------------------------------------------------------------------------
# HTTP
# ------------------------------------------------------------------------------------------------

def make_handler(mgr: Manager):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # keep the terminal quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode())

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path.startswith("/api/state"):
                since = 0
                if "since=" in self.path:
                    try:
                        since = int(self.path.split("since=")[1].split("&")[0])
                    except ValueError:
                        pass
                self._json(200, mgr.state(since))
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "invalid JSON"})
            parts = self.path.strip("/").split("/")
            try:
                if parts == ["api", "cluster"]:
                    mgr.create(int(body.get("size", 5)))
                    self._json(200, {"ok": True})
                elif len(parts) == 4 and parts[:2] == ["api", "node"]:
                    mgr.node_action(int(parts[2]), parts[3])
                    self._json(200, {"ok": True})
                elif parts == ["api", "command"]:
                    line = str(body.get("line", "")).strip()
                    if not line or "\n" in line:
                        return self._json(400, {"error": "enter one command"})
                    target = body.get("target")
                    self._json(200, mgr.command(line, None if target is None else int(target)))
                elif parts == ["api", "load"]:
                    mgr.set_load(int(body.get("clients", 0)))
                    self._json(200, {"ok": True})
                else:
                    self._json(404, {"error": "unknown endpoint"})
            except (ValueError, TimeoutError, OSError) as e:
                self._json(409, {"error": str(e)})

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8090, help="dashboard port (default 8090)")
    ap.add_argument("--nodes", type=int, default=5, help="initial cluster size (default 5)")
    ap.add_argument("--base-port", type=int, default=20000, help="first server port (default 20000)")
    ap.add_argument("--bin", help="use an already-built server binary")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = ap.parse_args()

    if args.bin:
        binary = Path(args.bin).resolve()
    else:
        print("Building server (Release)...", flush=True)
        binary, _, _ = build(None, find_toolchain(None), "Release")

    mgr = Manager(binary, args.base_port)
    atexit.register(mgr.shutdown)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    mgr.create(args.nodes)

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(mgr))
    url = f"http://localhost:{args.port}"
    print(f"Dashboard running at {url}  (Ctrl-C to stop; the cluster stops with it)", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

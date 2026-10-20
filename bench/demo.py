#!/usr/bin/env python3
"""Narrated live demo: a real cluster on localhost, driven through the KV store's main features.

    python3 bench/demo.py               # 5-node cluster, ~1 minute
    python3 bench/demo.py --pace 0      # no pauses between steps
    python3 bench/demo.py --nodes 3

Steps: leader election, client redirects, replication, throughput, leader crash under load
(with a lost-write audit), losing quorum safely, and recovery/catch-up of restarted nodes.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from client import KVClient, Unavailable, find_leader  # noqa: E402
from cluster import Cluster  # noqa: E402
from harness import build, find_toolchain  # noqa: E402
from scenarios import summarize  # noqa: E402

TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if TTY else text


bold = lambda t: _c("1", t)  # noqa: E731
dim = lambda t: _c("2", t)  # noqa: E731
green = lambda t: _c("32", t)  # noqa: E731
red = lambda t: _c("31", t)  # noqa: E731
cyan = lambda t: _c("36", t)  # noqa: E731
yellow = lambda t: _c("33", t)  # noqa: E731


class Demo:
    def __init__(self, cluster: Cluster, pace: float, total_steps: int):
        self.cluster = cluster
        self.pace = pace
        self.steps = itertools.count(1)
        self.total = total_steps

    async def step(self, title: str, blurb: str) -> None:
        await asyncio.sleep(self.pace)
        print(f"\n{bold(cyan(f'[{next(self.steps)}/{self.total}] {title}'))}")
        print(dim(f"    {blurb}"))

    def name(self, i: int) -> str:
        return f"node {i} ({self.cluster.addrs[i]})"

    def roster(self, leader: int | None) -> str:
        alive = set(self.cluster.alive())
        cells = []
        for i in range(self.cluster.size):
            if i not in alive:
                cells.append(red(f"{i}:down"))
            elif i == leader:
                cells.append(green(f"{i}:LEADER"))
            else:
                cells.append(f"{i}:follower")
        return "cluster: " + "  ".join(cells)


def ok(text: str) -> None:
    print(f"    {green('✓')} {text}")


def bad(text: str) -> None:
    print(f"    {red('✗')} {text}")


def crash(text: str) -> None:
    print(f"    {yellow('↯')} {text}")


def info(text: str) -> None:
    print(f"    {text}")


async def run(cluster: Cluster, pace: float) -> bool:
    d = Demo(cluster, pace, total_steps=8)
    n = cluster.size
    addrs = cluster.addrs
    all_good = True

    # 1. Election ---------------------------------------------------------------------------
    await d.step("Leader election",
                 f"Start {n} server processes. Each waits a random 300-500 ms, then campaigns for votes.")
    t0 = time.monotonic()
    cluster.start()
    leader = await find_leader(addrs, cluster.alive())
    ok(f"{d.name(leader)} won the election in {(time.monotonic() - t0) * 1000:.0f} ms")
    info(d.roster(leader))

    # 2. Redirects -----------------------------------------------------------------------------
    await d.step("Client redirection",
                 "Only the leader accepts commands; followers point clients to it.")
    follower = next(i for i in range(n) if i != leader)
    probe = KVClient(addrs, start=follower)
    reply = await probe.call_once("SET greeting hello")
    probe.close()
    info(f"SET greeting hello  →  {d.name(follower)} replies {yellow(reply)}")
    client = KVClient(addrs, start=follower)
    reply = await client.execute('SET greeting "hello, raft"', time.monotonic() + 5)
    ok(f"client followed the redirect; leader replied {yellow(reply)}")
    reply = await client.execute("GET greeting", time.monotonic() + 5)
    ok(f"GET greeting  →  {yellow(reply)}")

    # 3. Replication -----------------------------------------------------------------------
    await d.step("Replication",
                 "A write is acknowledged only after a majority has it; every replica then applies it to its AOF.")
    t0 = time.monotonic()
    await client.execute("SET city Lisbon", time.monotonic() + 5)
    ok(f"SET city Lisbon committed in {(time.monotonic() - t0) * 1000:.2f} ms")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and any(cluster.aof_state(i).get("city") != "Lisbon" for i in range(n)):
        await asyncio.sleep(0.02)
    for i in range(n):
        value = cluster.aof_state(i).get("city")
        (ok if value == "Lisbon" else bad)(f"{d.name(i)} AOF: city = {value}")

    # 4. Throughput --------------------------------------------------------------------------
    await d.step("Throughput",
                 "32 concurrent clients doing 50/50 SET/GET for 3 seconds.")
    latencies: list[float] = []
    stop_at = time.monotonic() + 3.0

    async def worker(w: int) -> None:
        c = KVClient(addrs, start=leader)
        for seq in itertools.count():
            if time.monotonic() >= stop_at:
                break
            line = f"SET k{w}:{seq % 100} v{seq}" if seq % 2 else f"GET k{w}:{seq % 100}"
            t = time.monotonic()
            try:
                await c.execute(line, t + 2)
                latencies.append((time.monotonic() - t) * 1000)
            except Unavailable:
                pass
        c.close()

    async def ticker() -> None:
        last, t_last = 0, time.monotonic()
        while time.monotonic() < stop_at:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            done = len(latencies)
            rate = (done - last) / (now - t_last)
            bar = "█" * int(rate / 500)
            info(f"{rate:>8,.0f} ops/s  {cyan(bar)}")
            last, t_last = done, now

    await asyncio.gather(ticker(), *(worker(w) for w in range(32)))
    s = summarize(latencies)
    ok(f"{s['n']:,} ops in 3 s ({s['n'] / 3:,.0f} ops/s)  ·  latency p50 {s['p50']:.2f} ms, p99 {s['p99']:.2f} ms")

    # 5. Leader crash ---------------------------------------------------------------------
    await d.step("Leader crash under load",
                 "16 writers keep writing unique keys while the leader is killed with SIGKILL.")
    acked: dict[str, str] = {}
    stop = asyncio.Event()

    async def writer(w: int) -> None:
        c = KVClient(addrs, request_timeout=0.5, start=leader)
        for seq in itertools.count():
            if stop.is_set():
                break
            key, val = f"crash:{w}:{seq}", f"v{seq}"
            try:
                if await c.execute(f"SET {key} {val}", time.monotonic() + 0.5) == "OK":
                    acked[key] = val
            except Unavailable:
                pass
        c.close()

    writers = [asyncio.create_task(writer(w)) for w in range(16)]
    await asyncio.sleep(1.0)
    before = len(acked)
    killed = leader
    t_kill = time.monotonic()
    cluster.kill_node(killed)
    crash(f"killed {d.name(killed)} after {before:,} acknowledged writes")
    await KVClient(addrs, request_timeout=0.3, start=(killed + 1) % n).execute("SET __probe__ 1", t_kill + 30)
    outage = (time.monotonic() - t_kill) * 1000
    leader = await find_leader(addrs, cluster.alive())
    ok(f"{d.name(leader)} took over; writes resumed after {outage:.0f} ms")
    await asyncio.sleep(1.0)
    stop.set()
    await asyncio.gather(*writers)
    info(d.roster(leader))

    deadline = time.monotonic() + 5
    missing: list[str] = []
    while time.monotonic() < deadline:
        state = cluster.aof_state(leader)
        missing = [k for k, v in acked.items() if state.get(k) != v]
        if not missing:
            break
        await asyncio.sleep(0.1)
    if missing:
        all_good = False
        bad(f"{len(missing):,} of {len(acked):,} acknowledged writes missing on the new leader")
    else:
        ok(f"audit: all {len(acked):,} acknowledged writes present on the new leader — none lost")

    # 6. Minority failure ---------------------------------------------------------------------
    majority = n // 2 + 1
    tolerable = n - majority
    await d.step("Surviving a minority of failures",
                 f"A {n}-node cluster needs {majority} nodes for a majority, so it tolerates {tolerable} failure(s).")
    for i in [i for i in cluster.alive() if i != leader][: tolerable - 1]:
        cluster.kill_node(i)
        crash(f"killed {d.name(i)}")
    info(d.roster(leader))
    client = KVClient(addrs, start=leader)
    t0 = time.monotonic()
    reply = await client.execute("SET status degraded-but-up", time.monotonic() + 5)
    ok(f"with {len(cluster.alive())}/{n} nodes up, SET still commits ({reply}, {(time.monotonic() - t0) * 1000:.1f} ms)")

    # 7. Majority failure ---------------------------------------------------------------------
    await d.step("Losing quorum safely",
                 "With a majority down, the leader must not acknowledge writes — it can't guarantee durability.")
    extra = next(i for i in cluster.alive() if i != leader)
    cluster.kill_node(extra)
    crash(f"killed {d.name(extra)}")
    info(d.roster(leader))
    pending = KVClient(addrs, start=leader)
    try:
        reply = await pending.call_once("SET status split-brain?", timeout=2.0)
        all_good = False
        bad(f"write acknowledged without a majority: {reply}")
    except (OSError, asyncio.TimeoutError):
        ok(f"only {len(cluster.alive())}/{n} nodes up: write NOT acknowledged after 2 s (correct)")
    finally:
        pending.close()

    # 8. Recovery -------------------------------------------------------------------------
    await d.step("Recovery and catch-up",
                 "Restart every crashed node. Each restores its persisted Raft state and fetches only what it missed.")
    down = [i for i in range(n) if i not in cluster.alive()]
    t0 = time.monotonic()
    for i in down:
        cluster.start_node(i)
        info(f"restarted {d.name(i)}")
    reply = await client.execute("SET status recovered", time.monotonic() + 15)
    ok(f"quorum restored: writes accepted again after {(time.monotonic() - t0) * 1000:.0f} ms ({reply})")
    client.close()

    target = cluster.aof_state(leader)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and any(cluster.aof_state(i) != target for i in range(n)):
        await asyncio.sleep(0.1)
        target = cluster.aof_state(leader)
    caught_up = (time.monotonic() - t0) * 1000
    states = [cluster.aof_state(i) for i in range(n)]
    if all(s == states[0] for s in states):
        ok(f"all {n} replicas identical ({len(states[0]):,} keys) {caught_up:.0f} ms after restart")
    else:
        all_good = False
        bad("replicas did not converge within 20 s")
    leader = await find_leader(addrs, cluster.alive())
    info(d.roster(leader))
    return all_good


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodes", type=int, default=5, help="cluster size (default 5)")
    ap.add_argument("--pace", type=float, default=1.0, help="seconds to pause between steps (default 1)")
    ap.add_argument("--bin", help="use an already-built server binary")
    ap.add_argument("--base-port", type=int, default=19000)
    args = ap.parse_args()
    if args.nodes < 3:
        sys.exit("the demo needs at least 3 nodes")

    print(bold("Fault-Tolerant KV Store — live demo"))
    if args.bin:
        binary = Path(args.bin).resolve()
    else:
        print(dim("Building server (Release)..."))
        binary, _, _ = build(None, find_toolchain(None), "Release")

    workdir = Path(tempfile.mkdtemp(prefix="kvdemo-"))
    cluster = Cluster(binary, args.nodes, workdir, args.base_port)
    try:
        passed = asyncio.run(run(cluster, args.pace))
    finally:
        cluster.stop()
        shutil.rmtree(workdir, ignore_errors=True)

    print()
    print(bold(green("Demo complete: every guarantee held.")) if passed
          else bold(red("Demo complete, but a guarantee was violated (see ✗ above).")))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

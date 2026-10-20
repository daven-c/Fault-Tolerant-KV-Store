"""Benchmark and fault-injection scenarios. Each returns a JSON-serialisable dict."""

from __future__ import annotations

import asyncio
import itertools
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from client import KVClient, Unavailable, find_leader
from cluster import Cluster


@dataclass
class Env:
    binary: Path
    nodes: int
    base_port: int
    scratch: Path
    quick: bool
    seed: int
    failover_writers: int = 32
    _ids: itertools.count = field(default_factory=itertools.count)

    def cluster(self, name: str) -> Cluster:
        return Cluster(self.binary, self.nodes, self.scratch / f"{name}-{next(self._ids)}", self.base_port)


def summarize(samples: list[float]) -> dict:
    if not samples:
        return {"n": 0}
    s = sorted(samples)

    def pct(p: float) -> float:
        return round(s[max(0, math.ceil(p / 100 * len(s)) - 1)], 3)

    return {"n": len(s), "mean": round(sum(s) / len(s), 3), "p50": pct(50), "p90": pct(90),
            "p99": pct(99), "max": round(s[-1], 3)}


async def _wait_until(predicate, timeout: float, interval: float = 0.05) -> float | None:
    """Poll `predicate` until true; returns elapsed ms, or None on timeout."""
    t0 = time.monotonic()
    while True:
        if predicate():
            return (time.monotonic() - t0) * 1000
        if time.monotonic() - t0 > timeout:
            return None
        await asyncio.sleep(interval)


# --------------------------------------------------------------------------------------------
# Election: time from launching a fresh cluster to the first acknowledged write.
# --------------------------------------------------------------------------------------------

async def election(env: Env) -> dict:
    samples = []
    for _ in range(3 if env.quick else 5):
        cluster = env.cluster("election")
        t0 = time.monotonic()
        with cluster:
            await KVClient(cluster.addrs, 0.5).execute("SET __boot__ 1", t0 + 15)
            samples.append((time.monotonic() - t0) * 1000)
    return {"time_to_first_write_ms": summarize(samples), "samples_ms": [round(x, 1) for x in samples]}


# --------------------------------------------------------------------------------------------
# Throughput: closed-loop clients at increasing concurrency, then a replica convergence check.
# --------------------------------------------------------------------------------------------

async def _load(addrs: list[str], leader: int, clients: int, duration: float, warmup: float,
                write_ratio: float, keyspace: int, value: str, seed: int) -> dict:
    t_start = time.monotonic()
    measure_from, stop_at = t_start + warmup, t_start + warmup + duration
    lat: dict[str, list[float]] = {"SET": [], "GET": []}
    errors = 0

    async def worker(w: int) -> None:
        nonlocal errors
        rng = random.Random(seed * 1000 + w)
        c = KVClient(addrs, request_timeout=2.0, start=leader)
        while (t := time.monotonic()) < stop_at:
            key = f"key:{rng.randrange(keyspace)}"
            op = "SET" if rng.random() < write_ratio else "GET"
            line = f"SET {key} {value}" if op == "SET" else f"GET {key}"
            try:
                reply = await c.execute(line, t + 2.0)
                ok = not reply.startswith("ERR")
            except Unavailable:
                ok = False
            done = time.monotonic()
            if t >= measure_from and done <= stop_at:
                if ok:
                    lat[op].append((done - t) * 1000)
                else:
                    errors += 1
        c.close()

    cpu0 = time.process_time()
    await asyncio.gather(*(worker(w) for w in range(clients)))
    cpu = time.process_time() - cpu0
    ops = len(lat["SET"]) + len(lat["GET"])
    return {
        "clients": clients,
        "ops": ops,
        "ops_per_sec": round(ops / duration, 1),
        "errors": errors,
        "latency_ms": {"all": summarize(lat["SET"] + lat["GET"]), "set": summarize(lat["SET"]),
                       "get": summarize(lat["GET"])},
        # >0.9 means the Python load generator itself was the bottleneck, not the server.
        "client_cpu_util": round(cpu / (time.monotonic() - t_start), 2),
    }


async def throughput(env: Env) -> dict:
    levels = [1, 16] if env.quick else [1, 4, 16, 64]
    duration, warmup = (2.0, 0.5) if env.quick else (5.0, 1.0)
    params = {"write_ratio": 0.5, "keyspace": 1000, "value_bytes": 64, "duration_s": duration,
              "warmup_s": warmup}
    results = []
    cluster = env.cluster("throughput")
    with cluster:
        leader = await find_leader(cluster.addrs, cluster.alive())
        for clients in levels:
            results.append(await _load(cluster.addrs, leader, clients, duration, warmup,
                                       params["write_ratio"], params["keyspace"],
                                       "v" * params["value_bytes"], env.seed))
        # Every replica's AOF should replay to the same state once traffic stops.
        def converged() -> bool:
            states = [cluster.aof_state(i) for i in range(cluster.size)]
            return all(s == states[0] for s in states)

        converge_ms = await _wait_until(converged, timeout=5.0, interval=0.1)
        final = [cluster.aof_state(i) for i in range(cluster.size)]
        diverged = sum(1 for s in final if s != final[0])
    return {"params": params, "levels": results, "replicas_converged": converge_ms is not None,
            "convergence_ms": None if converge_ms is None else round(converge_ms, 1),
            "diverged_replicas": diverged}


# --------------------------------------------------------------------------------------------
# Failover: SIGKILL the leader under write load. Measures the unavailability window, verifies
# that no acknowledged write was lost, then restarts the dead node and times its catch-up.
# --------------------------------------------------------------------------------------------

RECOVERY_TIMEOUT_S = 30.0


async def _failover_trial(env: Env, trial: int, writers: int, catchup_timeout: float) -> dict:
    rng = random.Random(env.seed + trial)
    cluster = env.cluster("failover")
    with cluster:
        addrs = cluster.addrs
        leader = await find_leader(addrs, cluster.alive())
        acked: dict[str, str] = {}
        acked_after_kill = 0
        killed_at: float | None = None
        stop = asyncio.Event()

        async def writer(w: int) -> None:
            nonlocal acked_after_kill
            c = KVClient(addrs, request_timeout=0.5, start=leader)
            for seq in itertools.count():
                if stop.is_set():
                    break
                key, val = f"fo:{w}:{seq}", f"t{trial}w{w}s{seq}"
                try:
                    if await c.execute(f"SET {key} {val}", time.monotonic() + 0.5) == "OK":
                        acked[key] = val
                        acked_after_kill += killed_at is not None
                except Unavailable:
                    pass
            c.close()

        tasks = [asyncio.create_task(writer(w)) for w in range(writers)]
        await asyncio.sleep(1.0)

        killed_at = time.monotonic()
        cluster.kill_node(leader)
        try:
            await KVClient(addrs, request_timeout=0.3, start=(leader + 1) % cluster.size).execute(
                "SET __failover__ 1", killed_at + RECOVERY_TIMEOUT_S)
            failover_ms: float | None = (time.monotonic() - killed_at) * 1000
        except Unavailable:
            failover_ms = None

        await asyncio.sleep(1.0)
        stop.set()
        await asyncio.gather(*tasks)

        def missing(node: int) -> list[str]:
            state = cluster.aof_state(node)
            return [k for k, v in acked.items() if state.get(k) != v]

        lost: int | None = None
        sample: list[str] = []
        mismatches = 0
        # Durability can only be judged once a new leader has committed in its term; until then
        # survivors may hold acked entries in their logs without having applied them yet.
        if failover_ms is not None:
            new_leader = await find_leader(addrs, cluster.alive())
            # Every acknowledged write must be applied on the new leader...
            await _wait_until(lambda: not missing(new_leader), timeout=5.0, interval=0.1)
            lost = len(missing(new_leader))

            # ...and readable through the client API (sampled; reads go through the Raft log).
            sample = rng.sample(sorted(acked), min(100, len(acked)))

            async def reader(keys: list[str]) -> None:
                nonlocal mismatches
                c = KVClient(addrs, request_timeout=1.0, start=new_leader)
                for k in keys:
                    try:
                        if await c.execute(f"GET {k}", time.monotonic() + 5) != f'"{acked[k]}"':
                            mismatches += 1
                    except Unavailable:
                        mismatches += 1
                c.close()

            await asyncio.gather(*(reader(sample[i::16]) for i in range(16)))

        # Recovery: restart the crashed node and wait until its AOF holds every acked write.
        cluster.start_node(leader)
        catchup_ms = await _wait_until(lambda: not missing(leader), timeout=catchup_timeout, interval=0.1)

    return {"failover_ms": None if failover_ms is None else round(failover_ms, 1), "acked_writes": len(acked),
            "acked_after_kill": acked_after_kill, "lost_acked_writes": lost,
            "read_mismatches": mismatches, "read_sample": len(sample),
            "catchup_ms": None if catchup_ms is None else round(catchup_ms, 1)}


async def failover(env: Env) -> dict:
    catchup_timeout = 10.0 if env.quick else 20.0
    trials = [await _failover_trial(env, t, writers=env.failover_writers, catchup_timeout=catchup_timeout)
              for t in range(3 if env.quick else 5)]
    catchups = [t["catchup_ms"] for t in trials if t["catchup_ms"] is not None]
    recovered = [t for t in trials if t["failover_ms"] is not None]
    return {
        "failover_ms": summarize([t["failover_ms"] for t in recovered]),
        "failover_timeouts": len(trials) - len(recovered),
        "recovery_timeout_s": RECOVERY_TIMEOUT_S,
        "lost_acked_writes": sum(t["lost_acked_writes"] for t in recovered),
        "read_mismatches": sum(t["read_mismatches"] for t in trials),
        "acked_writes": sum(t["acked_writes"] for t in trials),
        "catchup_ms": summarize(catchups),
        "catchup_timeouts": len(trials) - len(catchups),
        "catchup_timeout_s": catchup_timeout,
        "writers": env.failover_writers,
        "trials": trials,
    }


# --------------------------------------------------------------------------------------------
# Quorum: with a minority of followers down the cluster must keep accepting writes; with a
# majority down it must NOT acknowledge any write; restoring a node must restore liveness.
# --------------------------------------------------------------------------------------------

async def quorum(env: Env) -> dict:
    cluster = env.cluster("quorum")
    with cluster:
        leader = await find_leader(cluster.addrs, cluster.alive())
        followers = [i for i in range(cluster.size) if i != leader]
        minority = (cluster.size - 1) // 2
        down = followers[:minority]
        for i in down:
            cluster.kill_node(i)

        client = KVClient(cluster.addrs, request_timeout=1.0, start=leader)
        try:
            minority_ok = await client.execute("SET q:minority 1", time.monotonic() + 5) == "OK"
        except Unavailable:
            minority_ok = False

        extra = followers[minority]
        cluster.kill_node(extra)
        down.append(extra)
        try:
            reply = await KVClient(cluster.addrs, start=leader).call_once("SET q:majority 1", timeout=3.0)
            majority_acked = reply == "OK"
        except (OSError, asyncio.TimeoutError):
            majority_acked = False

        cluster.start_node(extra)
        t0 = time.monotonic()
        try:
            restored = await client.execute("SET q:restored 1", t0 + 15) == "OK"
        except Unavailable:
            restored = False
        restore_ms = (time.monotonic() - t0) * 1000
        client.close()

    return {"nodes_down_minority": minority, "minority_down_write_ok": minority_ok,
            "majority_down_write_acked": majority_acked, "quorum_restored_write_ok": restored,
            "quorum_restore_ms": round(restore_ms, 1) if restored else None}


# --------------------------------------------------------------------------------------------
# Raft RPC: drive one real node directly over its RPC port, acting as a fake leader/candidate,
# to check protocol rules that are hard to hit by chance in a live cluster.
# --------------------------------------------------------------------------------------------

FAKE_TERM = 1000  # far above any term the lone node reaches by timing out on its own


async def _rpc(addr: str, line: str) -> str:
    host, port = addr.split(":")
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), 1.0)
    try:
        writer.write(line.encode() + b"\n")
        await writer.drain()
        return (await asyncio.wait_for(reader.readline(), 1.0)).decode().strip()
    finally:
        writer.close()


def _append(prev_index: int, prev_term: int, commit: int, entries: list[tuple[int, str]],
            term: int = FAKE_TERM) -> str:
    payload = "".join(f" {t} {cmd}\x01" for t, cmd in entries)
    return f"AppendEntries {term} 1 {prev_index} {prev_term} {commit}{payload}"


async def raft_rpc(env: Env) -> dict:
    # Peers 1 and 2 are never started: the harness plays their part.
    cluster = env.cluster("raft-rpc")
    cluster.workdir.mkdir(parents=True, exist_ok=True)
    try:
        cluster.start_node(0)
        node = cluster.addrs[0]

        # A stale, shorter AppendEntries delivered after a longer one must not drop entries.
        await _rpc(node, _append(0, 0, 0, [(FAKE_TERM, "SET a 1"), (FAKE_TERM, "SET b 2")]))
        await _rpc(node, _append(0, 0, 0, [(FAKE_TERM, "SET a 1")]))
        kept = (await _rpc(node, _append(2, FAKE_TERM, 2, []))).startswith("Success")
        applied = await _wait_until(lambda: cluster.aof_state(0) == {"a": "1", "b": "2"}, timeout=2.0) is not None

        # A new leader must still overwrite an uncommitted entry from an older term.
        T = FAKE_TERM
        await _rpc(node, _append(2, T, 2, [(T, "SET c old")]))
        reply = await _rpc(node, _append(2, T, 3, [(T + 1, "SET c new")], term=T + 1))
        replaced = reply.startswith("Success") and await _wait_until(
            lambda: cluster.aof_state(0).get("c") == "new", timeout=2.0) is not None

        # One vote per term, even across a crash and restart.
        vote_term = FAKE_TERM + 10
        # Both candidates claim a log at least as up to date as the node's (last term T + 1).
        first = await _rpc(node, f"RequestVote {vote_term} 1 100 {T + 1}")
        cluster.kill_node(0)
        cluster.start_node(0)
        second = await _rpc(cluster.addrs[0], f"RequestVote {vote_term} 2 100 {T + 1}")
    finally:
        cluster.stop()

    return {
        "stale_append_keeps_entries": kept and applied,
        "conflicting_entry_replaced": replaced,
        "first_vote_granted": first.startswith("VoteGranted"),
        "second_vote_after_restart_denied": second.startswith("VoteDenied"),
        "replies": {"first_vote": first, "second_vote": second},
    }


# --------------------------------------------------------------------------------------------
# Idle leader change: kill the leader right after a write is acknowledged and send no further
# traffic. The new leader must still get every acknowledged write applied on all survivors.
# --------------------------------------------------------------------------------------------

async def idle_leader_change(env: Env) -> dict:
    trials, applied_ms = 3 if env.quick else 5, []
    for trial in range(trials):
        cluster = env.cluster("idle-leader-change")
        with cluster:
            leader = await find_leader(cluster.addrs, cluster.alive())
            client = KVClient(cluster.addrs, start=leader)
            for i in range(20):
                await client.execute(f"SET idle:{i} t{trial}", time.monotonic() + 5)
            client.close()
            cluster.kill_node(leader)  # immediately after the last acknowledgement
            survivors = cluster.alive()
            ms = await _wait_until(
                lambda: all(cluster.aof_state(i).get("idle:19") == f"t{trial}" for i in survivors),
                timeout=5.0)
            applied_ms.append(ms)
    done = [m for m in applied_ms if m is not None]
    return {"trials": trials, "applied_everywhere": len(done), "applied_ms": summarize(done),
            "timeout_s": 5.0}


SCENARIOS = {"election": election, "throughput": throughput, "failover": failover, "quorum": quorum,
             "raft_rpc": raft_rpc, "idle_leader_change": idle_leader_change}

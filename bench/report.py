"""Pass/fail checks, headline metrics, and Markdown rendering for result files."""

from __future__ import annotations


def _get(result: dict, *path, default=None):
    node = result.get("scenarios", {})
    for p in path:
        if callable(p):
            node = p(node)
        elif isinstance(node, dict) and p in node:
            node = node[p]
        else:
            return default
        if node is None:
            return default
    return node


def _level(clients_pick):
    return lambda levels: clients_pick(levels) if levels else None


_single = _level(lambda ls: next((l for l in ls if l["clients"] == 1), None))
_peak = _level(lambda ls: max(ls, key=lambda l: l["ops_per_sec"]))
_widest = _level(lambda ls: ls[-1])

# (label, path into result["scenarios"], better direction)
HEADLINES = [
    ("Peak throughput (ops/s)", ("throughput", "levels", _peak, "ops_per_sec"), "higher"),
    ("Single-client write latency p50 (ms)", ("throughput", "levels", _single, "latency_ms", "set", "p50"), "lower"),
    ("Single-client write latency p99 (ms)", ("throughput", "levels", _single, "latency_ms", "set", "p99"), "lower"),
    ("p99 latency at max concurrency (ms)", ("throughput", "levels", _widest, "latency_ms", "all", "p99"), "lower"),
    ("Cold-start election to first write, p50 (ms)", ("election", "time_to_first_write_ms", "p50"), "lower"),
    ("Leader failover unavailability, p50 (ms)", ("failover", "failover_ms", "p50"), "lower"),
    ("Leader failover unavailability, max (ms)", ("failover", "failover_ms", "max"), "lower"),
    ("Leader crashes not recovered within 30 s", ("failover", "failover_timeouts"), "lower"),
    ("Restarted node catch-up, p50 (ms)", ("failover", "catchup_ms", "p50"), "lower"),
    ("Restarted node catch-up timeouts", ("failover", "catchup_timeouts"), "lower"),
    ("Lost acknowledged writes", ("failover", "lost_acked_writes"), "lower"),
]


# Election/failover timings include randomized 300-500 ms election timeouts, so run-to-run
# swings of this size are expected and should not be reported as improvements.
NOISE_PCT = 20


def headline_values(result: dict) -> list[tuple[str, object, str]]:
    return [(label, _get(result, *path), better) for label, path, better in HEADLINES]


def checks(result: dict) -> list[dict]:
    """Correctness properties. Each is None (not run), True or False."""
    s = result.get("scenarios", {})
    out = []

    def add(name, scenario, passed, detail):
        if scenario not in s:
            passed, detail = None, "not run"
        elif "error" in s[scenario]:
            passed, detail = False, f"scenario crashed: {s[scenario]['error']}"
        out.append({"name": name, "passed": passed, "detail": detail})

    tp, fo, q = s.get("throughput", {}), s.get("failover", {}), s.get("quorum", {})
    add("Replicas converge to identical state", "throughput", tp.get("replicas_converged"),
        f"{tp.get('diverged_replicas')} diverged replica(s)")
    add("No request errors under steady load", "throughput",
        all(l["errors"] == 0 for l in tp.get("levels", [])),
        f"{sum(l['errors'] for l in tp.get('levels', []))} errors")
    add("Cluster recovers from every leader crash", "failover", fo.get("failover_timeouts") == 0,
        f"{fo.get('failover_timeouts')} trial(s) without a writable leader after {fo.get('recovery_timeout_s')}s")
    verified = len(fo.get("trials", [])) - (fo.get("failover_timeouts") or 0)
    add("No acknowledged write lost across leader crash", "failover",
        (fo.get("lost_acked_writes") == 0 and fo.get("read_mismatches") == 0) if verified else None,
        f"{fo.get('lost_acked_writes')} lost of {fo.get('acked_writes')} acked "
        f"(verified in {verified} trial(s)); "
        f"{fo.get('read_mismatches')} read mismatches")
    add("Restarted node catches up", "failover", fo.get("catchup_timeouts") == 0,
        f"{fo.get('catchup_timeouts')} trial(s) exceeded {fo.get('catchup_timeout_s')}s")
    add("Available with minority of nodes down", "quorum", q.get("minority_down_write_ok"),
        f"{q.get('nodes_down_minority')} follower(s) killed")
    add("No write acknowledged without quorum", "quorum", q.get("majority_down_write_acked") is False,
        "majority killed, leader left alone")
    add("Liveness restored when quorum returns", "quorum", q.get("quorum_restored_write_ok"),
        f"{q.get('quorum_restore_ms')} ms")
    r = s.get("raft_rpc", {})
    add("Stale AppendEntries never truncates the log", "raft_rpc",
        r.get("stale_append_keeps_entries") and r.get("conflicting_entry_replaced"),
        "shorter RPC delivered after a longer one; conflicting suffix still replaced")
    add("At most one vote per term across restarts", "raft_rpc",
        r.get("first_vote_granted") and r.get("second_vote_after_restart_denied"),
        f"after restart: {r.get('replies', {}).get('second_vote')}")
    return out


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.1f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _mark(passed) -> str:
    return {True: "PASS", False: "FAIL", None: "n/a"}[passed]


def render(result: dict) -> str:
    m = result["meta"]
    lines = [
        f"# KV store benchmark: `{m['label']}`",
        "",
        f"- Commit: `{m['git_sha'][:10]}`{' (uncommitted changes)' if m['git_dirty'] else ''}",
        f"- Cluster: {m['nodes']} nodes, {m['build_type']} build",
        f"- Host: {m['host']['platform']}, {m['host']['cpu_count']} CPUs",
        f"- Run at: {m['timestamp']} ({m['wall_seconds']:.0f}s)",
        f"- Reproduce: `{m['command']}`",
        "",
        "## Headline metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    lines += [f"| {label} | {_fmt(v)} |" for label, v, _ in headline_values(result)]
    lines += ["", "## Correctness checks", "", "| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {c['name']} | {_mark(c['passed'])} | {c['detail']} |" for c in result["checks"]]

    levels = _get(result, "throughput", "levels") or []
    if levels:
        lines += ["", "## Throughput by concurrency", "",
                  "| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |",
                  "|---:|---:|---:|---:|---:|---:|---:|"]
        for l in levels:
            a = l["latency_ms"]["all"]
            lines.append(f"| {l['clients']} | {_fmt(l['ops_per_sec'])} | {_fmt(a.get('p50'))} | "
                         f"{_fmt(a.get('p99'))} | {_fmt(a.get('max'))} | {l['errors']} | "
                         f"{l['client_cpu_util']:.0%} |")
    trials = _get(result, "failover", "trials") or []
    if trials:
        lines += ["", "## Failover trials", "",
                  "| # | Unavailable ms | Acked writes | Lost | Catch-up ms |", "|---:|---:|---:|---:|---:|"]
        for i, t in enumerate(trials):
            unavailable = _fmt(t["failover_ms"]) if t["failover_ms"] is not None else "no recovery"
            catchup = _fmt(t["catchup_ms"]) if t["catchup_ms"] is not None else "timeout"
            lines.append(f"| {i} | {unavailable} | {_fmt(t['acked_writes'])} | "
                         f"{_fmt(t['lost_acked_writes'])} | {catchup} |")
    return "\n".join(lines) + "\n"


def compare(before: dict, after: dict) -> str:
    b, a = before["meta"], after["meta"]
    lines = [
        f"# Benchmark comparison: `{b['label']}` → `{a['label']}`",
        "",
        f"- Before: `{b['git_sha'][:10]}`{'*' if b['git_dirty'] else ''} ({b['timestamp']})",
        f"- After: `{a['git_sha'][:10]}`{'*' if a['git_dirty'] else ''} ({a['timestamp']})",
        f"- Cluster: {a['nodes']} nodes on {a['host']['platform']}",
        "",
        "| Metric | Before | After | Change |",
        "|---|---:|---:|---:|",
    ]
    for (label, vb, better), (_, va, _) in zip(headline_values(before), headline_values(after)):
        lines.append(f"| {label} | {_fmt(vb)} | {_fmt(va)} | {_delta(vb, va, better)} |")
    lines += ["", "| Check | Before | After |", "|---|---|---|"]
    for cb, ca in zip(before["checks"], after["checks"]):
        lines.append(f"| {cb['name']} | {_mark(cb['passed'])} | {_mark(ca['passed'])} |")
    return "\n".join(lines) + "\n"


def _delta(before, after, better: str) -> str:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return "—"
    if before == after:
        return "no change"
    if before == 0 or after == 0:
        return f"{after - before:+,}"
    improved = (after > before) == (better == "higher")
    factor = max(before, after) / min(before, after)
    pct = (after - before) / before * 100
    if abs(pct) < NOISE_PCT:
        return f"{pct:+.0f}% (within noise)"
    tag = "better" if improved else "worse"
    return f"{pct:+.0f}% ({factor:.1f}× {tag})" if factor >= 2 else f"{pct:+.0f}% ({tag})"

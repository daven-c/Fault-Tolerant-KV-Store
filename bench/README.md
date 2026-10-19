# Benchmark & Fault-Injection Harness

A reproducible harness that builds the server, runs real multi-process clusters on localhost,
injects crashes, and checks correctness properties. Every run writes a JSON + Markdown result
stamped with the git commit, host, and the exact command, so any number can be regenerated.

Requires Python 3.9+ (standard library only), CMake, and the same Boost/vcpkg setup as the
main build. The vcpkg toolchain is auto-detected from `$CMAKE_TOOLCHAIN_FILE`, `$VCPKG_ROOT`,
or an existing `build/CMakeCache.txt`; pass `--toolchain` to override.

## Usage

```bash
python3 bench/harness.py run                     # build working tree (Release), run all scenarios (~3 min)
python3 bench/harness.py run --quick             # shorter smoke run (~1 min)
python3 bench/harness.py run --ref main          # benchmark any commit/branch/tag
python3 bench/harness.py run --nodes 5           # different cluster size
python3 bench/harness.py run --scenarios failover,quorum
python3 bench/harness.py run --strict            # exit 1 if any correctness check fails (CI)
python3 bench/harness.py run --keep-logs         # keep node logs/AOFs for debugging

python3 bench/harness.py compare bench/results/before.json bench/results/after.json
python3 bench/harness.py report  bench/results/before.json
```

Clusters run in a temp directory on ports 18000+ (`--base-port`), so they never touch the
repo's `AOFs/` or a cluster started with `launch.sh`.

## Scenarios

| Scenario | What it does | What it measures / verifies |
|---|---|---|
| `election` | Launch a fresh cluster, repeatedly | Time from process start to first committed write |
| `throughput` | Closed-loop clients (1, 4, 16, 64) doing 50/50 SET/GET over 1,000 keys | ops/s, p50/p90/p99/max latency per op type, errors; then checks every replica's AOF replays to the same state |
| `failover` | 32 writers on unique keys; `SIGKILL` the leader; restart it | Unavailability window (kill → first acknowledged write); **every acknowledged write is still present** (checked on the new leader's AOF and by sampled reads); time for the restarted node to catch up |
| `quorum` | Kill a minority of followers, then one more, then restore one | Writes succeed with a minority down; **no write is acknowledged without a majority**; liveness returns with quorum |

## Showing an improvement

1. Record a baseline before changing anything (or later, with `--ref <old-commit>`).
2. Make the change and run again.
3. `compare` the two files. Each headline metric gets a delta. Changes under 20% are marked
   *within noise*: election and failover timings include randomized 300–500 ms election
   timeouts, so smaller swings are expected run to run.

```bash
python3 bench/harness.py run --ref bbaeb26 --label before
python3 bench/harness.py run --label after
python3 bench/harness.py compare bench/results/before.json bench/results/after.json --out bench/results/COMPARISON.md
```

Use the same machine and `--nodes` for both sides. Throughput rows report the load
generator's own CPU use; above ~90% the Python client, not the server, is the limit.

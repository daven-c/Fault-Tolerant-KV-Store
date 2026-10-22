# KV store benchmark: `election-timer-fix`

- Commit: `fe22edf15c` (uncommitted changes)
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-22T15:30:27-04:00 (52s)
- Reproduce: `python3 bench/harness.py run --label election-timer-fix`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 12,207.0 |
| Single-client write latency p50 (ms) | 0.3 |
| Single-client write latency p99 (ms) | 0.4 |
| p99 latency at max concurrency (ms) | 17.3 |
| Cold-start election to first write, p50 (ms) | 354.3 |
| Leader failover unavailability, p50 (ms) | 324.0 |
| Leader failover unavailability, max (ms) | 388.0 |
| Leader crashes not recovered within 30 s | 0 |
| Restarted node catch-up, p50 (ms) | 565.1 |
| Restarted node catch-up timeouts | 0 |
| Lost acknowledged writes | 0 |

## Correctness checks

| Check | Result | Detail |
|---|---|---|
| Replicas converge to identical state | PASS | 0 diverged replica(s) |
| No request errors under steady load | PASS | 0 errors |
| Cluster recovers from every leader crash | PASS | 0 trial(s) without a writable leader after 30.0s |
| No acknowledged write lost across leader crash | PASS | 0 lost of 98368 acked (verified in 5 trial(s)); 0 read mismatches |
| Restarted node catches up | PASS | 0 trial(s) exceeded 20.0s |
| Available with minority of nodes down | PASS | 1 follower(s) killed |
| No write acknowledged without quorum | PASS | majority killed, leader left alone |
| Liveness restored when quorum returns | PASS | 1.1 ms |
| Stale AppendEntries never truncates the log | PASS | shorter RPC delivered after a longer one; conflicting suffix still replaced |
| At most one vote per term across restarts | PASS | after restart: VoteDenied 1010 |
| Acked writes applied everywhere after an idle leader change | PASS | 5/5 trial(s) within 5.0s, no client traffic |

## Throughput by concurrency

| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4,251.4 | 0.2 | 0.3 | 0.7 | 0 | 15% |
| 4 | 7,380.8 | 0.5 | 0.9 | 1.9 | 0 | 35% |
| 16 | 10,037.2 | 1.5 | 2.9 | 32.4 | 0 | 40% |
| 64 | 12,207.0 | 4.5 | 17.3 | 51.5 | 0 | 36% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 371.6 | 19,988 | 0 | 564.2 |
| 1 | 324.0 | 20,080 | 0 | 568.1 |
| 2 | 323.5 | 19,135 | 0 | 569.5 |
| 3 | 388.0 | 19,864 | 0 | 564.6 |
| 4 | 322.1 | 19,301 | 0 | 565.1 |

# KV store benchmark: `fix-match-index`

- Commit: `bbaeb265c1` (uncommitted changes)
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-19T16:18:22-04:00 (154s)
- Reproduce: `python3 bench/harness.py run --label fix-match-index`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 409.6 |
| Single-client write latency p50 (ms) | 150.6 |
| Single-client write latency p99 (ms) | 198.3 |
| p99 latency at max concurrency (ms) | 231.7 |
| Cold-start election to first write, p50 (ms) | 535.2 |
| Leader failover unavailability, p50 (ms) | 391.8 |
| Leader failover unavailability, max (ms) | 506.8 |
| Leader crashes not recovered within 30 s | 0 |
| Restarted node catch-up, p50 (ms) | — |
| Restarted node catch-up timeouts | 5 |
| Lost acknowledged writes | 0 |

## Correctness checks

| Check | Result | Detail |
|---|---|---|
| Replicas converge to identical state | PASS | 0 diverged replica(s) |
| No request errors under steady load | PASS | 0 errors |
| Cluster recovers from every leader crash | PASS | 0 trial(s) without a writable leader after 30.0s |
| No acknowledged write lost across leader crash | PASS | 0 lost of 2240 acked (verified in 5 trial(s)); 0 read mismatches |
| Restarted node catches up | FAIL | 5 trial(s) exceeded 20.0s |
| Available with minority of nodes down | PASS | 1 follower(s) killed |
| No write acknowledged without quorum | PASS | majority killed, leader left alone |
| Liveness restored when quorum returns | PASS | 366.3 ms |

## Throughput by concurrency

| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6.4 | 150.7 | 198.3 | 198.3 | 0 | 0% |
| 4 | 25.6 | 150.9 | 196.5 | 196.5 | 0 | 0% |
| 16 | 102.4 | 151.1 | 226.3 | 230.9 | 0 | 1% |
| 64 | 409.6 | 151.2 | 231.7 | 233.8 | 0 | 4% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 474.0 | 448 | 0 | timeout |
| 1 | 506.8 | 448 | 0 | timeout |
| 2 | 391.0 | 448 | 0 | timeout |
| 3 | 385.5 | 448 | 0 | timeout |
| 4 | 391.8 | 448 | 0 | timeout |

# KV store benchmark: `improved`

- Commit: `bbaeb265c1` (uncommitted changes)
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-19T16:31:13-04:00 (52s)
- Reproduce: `python3 bench/harness.py run --label improved`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 5,580.2 |
| Single-client write latency p50 (ms) | 1.0 |
| Single-client write latency p99 (ms) | 6.1 |
| p99 latency at max concurrency (ms) | 73.8 |
| Cold-start election to first write, p50 (ms) | 517.7 |
| Leader failover unavailability, p50 (ms) | 393.8 |
| Leader failover unavailability, max (ms) | 455.3 |
| Leader crashes not recovered within 30 s | 0 |
| Restarted node catch-up, p50 (ms) | 816.4 |
| Restarted node catch-up timeouts | 0 |
| Lost acknowledged writes | 0 |

## Correctness checks

| Check | Result | Detail |
|---|---|---|
| Replicas converge to identical state | PASS | 0 diverged replica(s) |
| No request errors under steady load | PASS | 0 errors |
| Cluster recovers from every leader crash | PASS | 0 trial(s) without a writable leader after 30.0s |
| No acknowledged write lost across leader crash | PASS | 0 lost of 32679 acked (verified in 5 trial(s)); 0 read mismatches |
| Restarted node catches up | PASS | 0 trial(s) exceeded 20.0s |
| Available with minority of nodes down | PASS | 1 follower(s) killed |
| No write acknowledged without quorum | PASS | majority killed, leader left alone |
| Liveness restored when quorum returns | PASS | 8.3 ms |

## Throughput by concurrency

| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 844.8 | 0.9 | 5.4 | 89.4 | 0 | 15% |
| 4 | 1,277.0 | 1.5 | 34.4 | 460.1 | 0 | 19% |
| 16 | 3,062.2 | 3.2 | 51.8 | 256.9 | 0 | 28% |
| 64 | 5,580.2 | 9.1 | 73.8 | 107.6 | 0 | 39% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 325.4 | 8,012 | 0 | 782.3 |
| 1 | 302.3 | 7,070 | 0 | 441.0 |
| 2 | 397.1 | 8,327 | 0 | 816.4 |
| 3 | 393.8 | 7,706 | 0 | 947.5 |
| 4 | 455.3 | 1,564 | 0 | 914.7 |

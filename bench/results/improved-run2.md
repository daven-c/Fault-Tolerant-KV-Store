# KV store benchmark: `improved-run2`

- Commit: `bbaeb265c1` (uncommitted changes)
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-19T16:32:12-04:00 (54s)
- Reproduce: `python3 bench/harness.py run --label improved-run2`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 7,025.8 |
| Single-client write latency p50 (ms) | 0.8 |
| Single-client write latency p99 (ms) | 2.9 |
| p99 latency at max concurrency (ms) | 31.0 |
| Cold-start election to first write, p50 (ms) | 427.2 |
| Leader failover unavailability, p50 (ms) | 415.2 |
| Leader failover unavailability, max (ms) | 1,154.7 |
| Leader crashes not recovered within 30 s | 0 |
| Restarted node catch-up, p50 (ms) | 1,014.9 |
| Restarted node catch-up timeouts | 0 |
| Lost acknowledged writes | 0 |

## Correctness checks

| Check | Result | Detail |
|---|---|---|
| Replicas converge to identical state | PASS | 0 diverged replica(s) |
| No request errors under steady load | PASS | 0 errors |
| Cluster recovers from every leader crash | PASS | 0 trial(s) without a writable leader after 30.0s |
| No acknowledged write lost across leader crash | PASS | 0 lost of 18853 acked (verified in 5 trial(s)); 0 read mismatches |
| Restarted node catches up | PASS | 0 trial(s) exceeded 20.0s |
| Available with minority of nodes down | PASS | 1 follower(s) killed |
| No write acknowledged without quorum | PASS | majority killed, leader left alone |
| Liveness restored when quorum returns | PASS | 6.8 ms |

## Throughput by concurrency

| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1,180.6 | 0.7 | 2.9 | 62.3 | 0 | 18% |
| 4 | 2,436.2 | 1.3 | 6.3 | 63.2 | 0 | 27% |
| 16 | 4,125.8 | 2.7 | 27.9 | 145.3 | 0 | 33% |
| 64 | 7,025.8 | 8.0 | 31.0 | 75.9 | 0 | 44% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 425.7 | 4,918 | 0 | 1,075.2 |
| 1 | 415.2 | 4,833 | 0 | 4,129.3 |
| 2 | 333.5 | 1,149 | 0 | 480.2 |
| 3 | 1,154.7 | 3,916 | 0 | 933.6 |
| 4 | 407.2 | 4,037 | 0 | 1,014.9 |

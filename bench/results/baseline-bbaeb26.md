# KV store benchmark: `baseline-bbaeb26`

- Commit: `bbaeb265c1`
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-19T16:08:31-04:00 (163s)
- Reproduce: `python3 bench/harness.py run --label baseline-bbaeb26`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 409.6 |
| Single-client write latency p50 (ms) | 150.8 |
| Single-client write latency p99 (ms) | 296.9 |
| p99 latency at max concurrency (ms) | 157.6 |
| Cold-start election to first write, p50 (ms) | 491.9 |
| Leader failover unavailability, p50 (ms) | 473.6 |
| Leader failover unavailability, max (ms) | 5,666.3 |
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
| No acknowledged write lost across leader crash | PASS | 0 lost of 2222 acked (verified in 5 trial(s)); 0 read mismatches |
| Restarted node catches up | FAIL | 5 trial(s) exceeded 20.0s |
| Available with minority of nodes down | PASS | 1 follower(s) killed |
| No write acknowledged without quorum | PASS | majority killed, leader left alone |
| Liveness restored when quorum returns | PASS | 300.9 ms |

## Throughput by concurrency

| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6.2 | 150.8 | 296.9 | 296.9 | 0 | 0% |
| 4 | 25.6 | 150.9 | 151.6 | 151.6 | 0 | 0% |
| 16 | 109.4 | 150.9 | 157.0 | 157.1 | 0 | 1% |
| 64 | 409.6 | 150.9 | 157.6 | 158.9 | 0 | 1% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 5,666.3 | 449 | 0 | timeout |
| 1 | 459.8 | 448 | 0 | timeout |
| 2 | 473.6 | 448 | 0 | timeout |
| 3 | 549.3 | 448 | 0 | timeout |
| 4 | 412.6 | 429 | 0 | timeout |

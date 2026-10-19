# KV store benchmark: `fix-log-truncation`

- Commit: `3f468ca9f0` (uncommitted changes)
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-19T16:50:07-04:00 (48s)
- Reproduce: `python3 bench/harness.py run --label fix-log-truncation`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 7,188.2 |
| Single-client write latency p50 (ms) | 0.8 |
| Single-client write latency p99 (ms) | 3.1 |
| p99 latency at max concurrency (ms) | 28.1 |
| Cold-start election to first write, p50 (ms) | 378.8 |
| Leader failover unavailability, p50 (ms) | 373.2 |
| Leader failover unavailability, max (ms) | 430.5 |
| Leader crashes not recovered within 30 s | 0 |
| Restarted node catch-up, p50 (ms) | 787.7 |
| Restarted node catch-up timeouts | 0 |
| Lost acknowledged writes | 0 |

## Correctness checks

| Check | Result | Detail |
|---|---|---|
| Replicas converge to identical state | PASS | 0 diverged replica(s) |
| No request errors under steady load | PASS | 0 errors |
| Cluster recovers from every leader crash | PASS | 0 trial(s) without a writable leader after 30.0s |
| No acknowledged write lost across leader crash | PASS | 0 lost of 39796 acked (verified in 5 trial(s)); 0 read mismatches |
| Restarted node catches up | PASS | 0 trial(s) exceeded 20.0s |
| Available with minority of nodes down | PASS | 1 follower(s) killed |
| No write acknowledged without quorum | PASS | majority killed, leader left alone |
| Liveness restored when quorum returns | PASS | 0.6 ms |
| Stale AppendEntries never truncates the log | PASS | shorter RPC delivered after a longer one; conflicting suffix still replaced |
| At most one vote per term across restarts | FAIL | after restart: VoteGranted 1010 |

## Throughput by concurrency

| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1,175.2 | 0.7 | 3.1 | 79.5 | 0 | 17% |
| 4 | 2,704.8 | 1.3 | 4.8 | 20.7 | 0 | 29% |
| 16 | 4,960.2 | 2.7 | 11.7 | 143.8 | 0 | 39% |
| 64 | 7,188.2 | 8.0 | 28.1 | 57.8 | 0 | 49% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 430.5 | 6,336 | 0 | 553.3 |
| 1 | 373.2 | 8,913 | 0 | 787.7 |
| 2 | 316.6 | 8,274 | 0 | 669.7 |
| 3 | 387.9 | 8,947 | 0 | 791.4 |
| 4 | 367.9 | 7,326 | 0 | 1,190.2 |

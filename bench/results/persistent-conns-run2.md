# KV store benchmark: `persistent-conns-run2`

- Commit: `aad0206b0c` (uncommitted changes)
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-19T16:55:46-04:00 (48s)
- Reproduce: `python3 bench/harness.py run --label persistent-conns-run2`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 9,202.2 |
| Single-client write latency p50 (ms) | 0.3 |
| Single-client write latency p99 (ms) | 1.5 |
| p99 latency at max concurrency (ms) | 20.0 |
| Cold-start election to first write, p50 (ms) | 351.9 |
| Leader failover unavailability, p50 (ms) | 388.3 |
| Leader failover unavailability, max (ms) | 1,848.8 |
| Leader crashes not recovered within 30 s | 0 |
| Restarted node catch-up, p50 (ms) | 460.2 |
| Restarted node catch-up timeouts | 0 |
| Lost acknowledged writes | 0 |

## Correctness checks

| Check | Result | Detail |
|---|---|---|
| Replicas converge to identical state | PASS | 0 diverged replica(s) |
| No request errors under steady load | PASS | 0 errors |
| Cluster recovers from every leader crash | PASS | 0 trial(s) without a writable leader after 30.0s |
| No acknowledged write lost across leader crash | PASS | 0 lost of 72508 acked (verified in 5 trial(s)); 0 read mismatches |
| Restarted node catches up | PASS | 0 trial(s) exceeded 20.0s |
| Available with minority of nodes down | PASS | 1 follower(s) killed |
| No write acknowledged without quorum | PASS | majority killed, leader left alone |
| Liveness restored when quorum returns | PASS | 1.8 ms |
| Stale AppendEntries never truncates the log | PASS | shorter RPC delivered after a longer one; conflicting suffix still replaced |
| At most one vote per term across restarts | PASS | after restart: VoteDenied 1010 |

## Throughput by concurrency

| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2,857.8 | 0.3 | 1.3 | 54.2 | 0 | 15% |
| 4 | 4,584.0 | 0.6 | 3.9 | 161.2 | 0 | 30% |
| 16 | 7,419.2 | 1.9 | 6.0 | 22.1 | 0 | 40% |
| 64 | 9,202.2 | 6.1 | 20.0 | 55.5 | 0 | 40% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 1,848.8 | 15,965 | 0 | 567.6 |
| 1 | 377.8 | 13,448 | 0 | 454.7 |
| 2 | 334.2 | 15,397 | 0 | 566.5 |
| 3 | 401.3 | 15,292 | 0 | 453.1 |
| 4 | 388.3 | 12,406 | 0 | 460.2 |

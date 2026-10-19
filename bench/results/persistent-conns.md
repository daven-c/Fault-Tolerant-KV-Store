# KV store benchmark: `persistent-conns`

- Commit: `aad0206b0c` (uncommitted changes)
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-19T16:54:50-04:00 (49s)
- Reproduce: `python3 bench/harness.py run --label persistent-conns`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 13,276.2 |
| Single-client write latency p50 (ms) | 0.3 |
| Single-client write latency p99 (ms) | 1.0 |
| p99 latency at max concurrency (ms) | 12.0 |
| Cold-start election to first write, p50 (ms) | 429.2 |
| Leader failover unavailability, p50 (ms) | 375.5 |
| Leader failover unavailability, max (ms) | 1,105.6 |
| Leader crashes not recovered within 30 s | 0 |
| Restarted node catch-up, p50 (ms) | 566.3 |
| Restarted node catch-up timeouts | 0 |
| Lost acknowledged writes | 0 |

## Correctness checks

| Check | Result | Detail |
|---|---|---|
| Replicas converge to identical state | PASS | 0 diverged replica(s) |
| No request errors under steady load | PASS | 0 errors |
| Cluster recovers from every leader crash | PASS | 0 trial(s) without a writable leader after 30.0s |
| No acknowledged write lost across leader crash | PASS | 0 lost of 65972 acked (verified in 5 trial(s)); 0 read mismatches |
| Restarted node catches up | PASS | 0 trial(s) exceeded 20.0s |
| Available with minority of nodes down | PASS | 1 follower(s) killed |
| No write acknowledged without quorum | PASS | majority killed, leader left alone |
| Liveness restored when quorum returns | PASS | 1.0 ms |
| Stale AppendEntries never truncates the log | PASS | shorter RPC delivered after a longer one; conflicting suffix still replaced |
| At most one vote per term across restarts | PASS | after restart: VoteDenied 1010 |

## Throughput by concurrency

| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3,297.0 | 0.3 | 0.9 | 67.6 | 0 | 15% |
| 4 | 5,931.4 | 0.5 | 2.1 | 91.5 | 0 | 31% |
| 16 | 5,039.8 | 2.5 | 14.5 | 126.8 | 0 | 33% |
| 64 | 13,276.2 | 4.3 | 12.0 | 47.6 | 0 | 33% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 336.2 | 18,042 | 0 | 566.3 |
| 1 | 1,105.6 | 17,127 | 0 | 562.9 |
| 2 | 318.0 | 16,887 | 0 | 448.0 |
| 3 | 974.7 | 8,264 | 0 | 622.0 |
| 4 | 375.5 | 5,652 | 0 | 691.7 |

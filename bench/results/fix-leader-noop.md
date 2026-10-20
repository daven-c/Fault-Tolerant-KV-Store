# KV store benchmark: `fix-leader-noop`

- Commit: `a3a71dbb21` (uncommitted changes)
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-20T11:19:50-04:00 (53s)
- Reproduce: `python3 bench/harness.py run --label fix-leader-noop`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 13,148.4 |
| Single-client write latency p50 (ms) | 0.3 |
| Single-client write latency p99 (ms) | 0.6 |
| p99 latency at max concurrency (ms) | 8.7 |
| Cold-start election to first write, p50 (ms) | 363.3 |
| Leader failover unavailability, p50 (ms) | 365.7 |
| Leader failover unavailability, max (ms) | 1,980.2 |
| Leader crashes not recovered within 30 s | 0 |
| Restarted node catch-up, p50 (ms) | 447.8 |
| Restarted node catch-up timeouts | 0 |
| Lost acknowledged writes | 0 |

## Correctness checks

| Check | Result | Detail |
|---|---|---|
| Replicas converge to identical state | PASS | 0 diverged replica(s) |
| No request errors under steady load | PASS | 0 errors |
| Cluster recovers from every leader crash | PASS | 0 trial(s) without a writable leader after 30.0s |
| No acknowledged write lost across leader crash | PASS | 0 lost of 87710 acked (verified in 5 trial(s)); 0 read mismatches |
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
| 1 | 3,761.0 | 0.3 | 0.5 | 5.3 | 0 | 14% |
| 4 | 6,519.8 | 0.6 | 1.0 | 8.1 | 0 | 36% |
| 16 | 10,600.0 | 1.5 | 2.4 | 18.4 | 0 | 44% |
| 64 | 13,148.4 | 4.6 | 8.7 | 22.0 | 0 | 41% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 351.8 | 17,672 | 0 | 447.4 |
| 1 | 365.7 | 17,201 | 0 | 445.9 |
| 2 | 368.5 | 17,376 | 0 | 448.0 |
| 3 | 356.7 | 17,449 | 0 | 447.8 |
| 4 | 1,980.2 | 18,012 | 0 | 560.3 |

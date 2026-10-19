# KV store benchmark: `fix-persist-raft-state`

- Commit: `5cbecd7567` (uncommitted changes)
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-19T16:52:59-04:00 (48s)
- Reproduce: `python3 bench/harness.py run --label fix-persist-raft-state`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 10,005.0 |
| Single-client write latency p50 (ms) | 0.6 |
| Single-client write latency p99 (ms) | 20.5 |
| p99 latency at max concurrency (ms) | 31.4 |
| Cold-start election to first write, p50 (ms) | 407.8 |
| Leader failover unavailability, p50 (ms) | 389.5 |
| Leader failover unavailability, max (ms) | 796.4 |
| Leader crashes not recovered within 30 s | 0 |
| Restarted node catch-up, p50 (ms) | 444.7 |
| Restarted node catch-up timeouts | 0 |
| Lost acknowledged writes | 0 |

## Correctness checks

| Check | Result | Detail |
|---|---|---|
| Replicas converge to identical state | PASS | 0 diverged replica(s) |
| No request errors under steady load | PASS | 0 errors |
| Cluster recovers from every leader crash | PASS | 0 trial(s) without a writable leader after 30.0s |
| No acknowledged write lost across leader crash | PASS | 0 lost of 79686 acked (verified in 5 trial(s)); 0 read mismatches |
| Restarted node catches up | PASS | 0 trial(s) exceeded 20.0s |
| Available with minority of nodes down | PASS | 1 follower(s) killed |
| No write acknowledged without quorum | PASS | majority killed, leader left alone |
| Liveness restored when quorum returns | PASS | 2.0 ms |
| Stale AppendEntries never truncates the log | PASS | shorter RPC delivered after a longer one; conflicting suffix still replaced |
| At most one vote per term across restarts | PASS | after restart: VoteDenied 1010 |

## Throughput by concurrency

| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 716.4 | 0.6 | 16.1 | 141.8 | 0 | 10% |
| 4 | 5,652.6 | 0.7 | 1.4 | 18.9 | 0 | 25% |
| 16 | 10,005.0 | 1.4 | 4.0 | 184.8 | 0 | 36% |
| 64 | 9,711.8 | 5.1 | 31.4 | 195.6 | 0 | 34% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 420.2 | 15,814 | 0 | 444.9 |
| 1 | 359.7 | 16,331 | 0 | 444.7 |
| 2 | 389.5 | 16,104 | 0 | 444.1 |
| 3 | 796.4 | 15,735 | 0 | 443.9 |
| 4 | 359.7 | 15,702 | 0 | 1,157.5 |

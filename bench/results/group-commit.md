# KV store benchmark: `group-commit`

- Commit: `33d9b1d432` (uncommitted changes)
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-22T16:17:54-04:00 (54s)
- Reproduce: `python3 bench/harness.py run --label group-commit`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 26,730.0 |
| Single-client write latency p50 (ms) | 0.2 |
| Single-client write latency p99 (ms) | 0.3 |
| p99 latency at max concurrency (ms) | 4.6 |
| Cold-start election to first write, p50 (ms) | 406.8 |
| Leader failover unavailability, p50 (ms) | 375.1 |
| Leader failover unavailability, max (ms) | 857.8 |
| Leader crashes not recovered within 30 s | 0 |
| Restarted node catch-up, p50 (ms) | 178.1 |
| Restarted node catch-up timeouts | 0 |
| Lost acknowledged writes | 0 |

## Correctness checks

| Check | Result | Detail |
|---|---|---|
| Replicas converge to identical state | PASS | 0 diverged replica(s) |
| No request errors under steady load | PASS | 0 errors |
| Cluster recovers from every leader crash | PASS | 0 trial(s) without a writable leader after 30.0s |
| No acknowledged write lost across leader crash | PASS | 0 lost of 344463 acked (verified in 5 trial(s)); 0 read mismatches |
| Restarted node catches up | PASS | 0 trial(s) exceeded 20.0s |
| Available with minority of nodes down | PASS | 1 follower(s) killed |
| No write acknowledged without quorum | PASS | majority killed, leader left alone |
| Liveness restored when quorum returns | PASS | 2.0 ms |
| Stale AppendEntries never truncates the log | PASS | shorter RPC delivered after a longer one; conflicting suffix still replaced |
| At most one vote per term across restarts | PASS | after restart: VoteDenied 1010 |
| Late votes from an earlier election are ignored | PASS | grant for term 1 arrived in term 4; node is candidate |
| Acked writes applied everywhere after an idle leader change | PASS | 5/5 trial(s) within 5.0s, no client traffic |

## Throughput by concurrency

| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4,822.8 | 0.2 | 0.3 | 2.1 | 0 | 18% |
| 4 | 9,478.4 | 0.4 | 0.6 | 1.4 | 0 | 44% |
| 16 | 21,494.6 | 0.7 | 1.1 | 9.2 | 0 | 80% |
| 64 | 26,730.0 | 2.3 | 4.6 | 7.1 | 0 | 89% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 329.0 | 65,964 | 0 | 172.9 |
| 1 | 857.8 | 69,048 | 0 | 178.1 |
| 2 | 375.1 | 71,438 | 0 | 178.6 |
| 3 | 352.4 | 71,408 | 0 | 182.4 |
| 4 | 742.9 | 66,605 | 0 | 176.6 |

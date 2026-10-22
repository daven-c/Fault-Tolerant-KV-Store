# KV store benchmark: `group-commit-run2`

- Commit: `33d9b1d432` (uncommitted changes)
- Cluster: 3 nodes, Release build
- Host: macOS-27.0-arm64-arm-64bit-Mach-O, 10 CPUs
- Run at: 2026-10-22T16:19:05-04:00 (54s)
- Reproduce: `python3 bench/harness.py run --label group-commit-run2`

## Headline metrics

| Metric | Value |
|---|---:|
| Peak throughput (ops/s) | 28,272.8 |
| Single-client write latency p50 (ms) | 0.2 |
| Single-client write latency p99 (ms) | 0.3 |
| p99 latency at max concurrency (ms) | 4.4 |
| Cold-start election to first write, p50 (ms) | 391.0 |
| Leader failover unavailability, p50 (ms) | 458.5 |
| Leader failover unavailability, max (ms) | 745.5 |
| Leader crashes not recovered within 30 s | 0 |
| Restarted node catch-up, p50 (ms) | 179.9 |
| Restarted node catch-up timeouts | 0 |
| Lost acknowledged writes | 0 |

## Correctness checks

| Check | Result | Detail |
|---|---|---|
| Replicas converge to identical state | PASS | 0 diverged replica(s) |
| No request errors under steady load | PASS | 0 errors |
| Cluster recovers from every leader crash | PASS | 0 trial(s) without a writable leader after 30.0s |
| No acknowledged write lost across leader crash | PASS | 0 lost of 350055 acked (verified in 5 trial(s)); 0 read mismatches |
| Restarted node catches up | PASS | 0 trial(s) exceeded 20.0s |
| Available with minority of nodes down | PASS | 1 follower(s) killed |
| No write acknowledged without quorum | PASS | majority killed, leader left alone |
| Liveness restored when quorum returns | PASS | 2.1 ms |
| Stale AppendEntries never truncates the log | PASS | shorter RPC delivered after a longer one; conflicting suffix still replaced |
| At most one vote per term across restarts | PASS | after restart: VoteDenied 1010 |
| Late votes from an earlier election are ignored | PASS | grant for term 1 arrived in term 4; node is candidate |
| Acked writes applied everywhere after an idle leader change | PASS | 5/5 trial(s) within 5.0s, no client traffic |

## Throughput by concurrency

| Clients | ops/s | p50 ms | p99 ms | max ms | errors | client CPU |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4,832.6 | 0.2 | 0.3 | 0.6 | 0 | 17% |
| 4 | 9,544.2 | 0.4 | 0.6 | 5.0 | 0 | 43% |
| 16 | 20,640.4 | 0.7 | 1.5 | 10.2 | 0 | 78% |
| 64 | 28,272.8 | 2.2 | 4.4 | 6.7 | 0 | 90% |

## Failover trials

| # | Unavailable ms | Acked writes | Lost | Catch-up ms |
|---:|---:|---:|---:|---:|
| 0 | 699.3 | 70,907 | 0 | 178.8 |
| 1 | 458.5 | 70,926 | 0 | 182.3 |
| 2 | 348.1 | 71,037 | 0 | 181.6 |
| 3 | 745.5 | 65,284 | 0 | 170.6 |
| 4 | 352.0 | 71,901 | 0 | 179.9 |

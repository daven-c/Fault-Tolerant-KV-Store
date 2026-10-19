# Benchmark comparison: `baseline-bbaeb26` → `persistent-conns`

- Before: `bbaeb265c1` (2026-10-19T16:08:31-04:00)
- After: `aad0206b0c`* (2026-10-19T16:54:50-04:00)
- Cluster: 3 nodes on macOS-27.0-arm64-arm-64bit-Mach-O

| Metric | Before | After | Change |
|---|---:|---:|---:|
| Peak throughput (ops/s) | 409.6 | 13,276.2 | +3141% (32.4× better) |
| Single-client write latency p50 (ms) | 150.8 | 0.3 | -100% (521.9× better) |
| Single-client write latency p99 (ms) | 296.9 | 1.0 | -100% (312.2× better) |
| p99 latency at max concurrency (ms) | 157.6 | 12.0 | -92% (13.1× better) |
| Cold-start election to first write, p50 (ms) | 491.9 | 429.2 | -13% (within noise) |
| Leader failover unavailability, p50 (ms) | 473.6 | 375.5 | -21% (better) |
| Leader failover unavailability, max (ms) | 5,666.3 | 1,105.6 | -80% (5.1× better) |
| Leader crashes not recovered within 30 s | 0 | 0 | no change |
| Restarted node catch-up, p50 (ms) | — | 566.3 | — |
| Restarted node catch-up timeouts | 5 | 0 | -5 |
| Lost acknowledged writes | 0 | 0 | no change |

| Check | Before | After |
|---|---|---|
| Replicas converge to identical state | PASS | PASS |
| No request errors under steady load | PASS | PASS |
| Cluster recovers from every leader crash | PASS | PASS |
| No acknowledged write lost across leader crash | PASS | PASS |
| Restarted node catches up | FAIL | PASS |
| Available with minority of nodes down | PASS | PASS |
| No write acknowledged without quorum | PASS | PASS |
| Liveness restored when quorum returns | PASS | PASS |

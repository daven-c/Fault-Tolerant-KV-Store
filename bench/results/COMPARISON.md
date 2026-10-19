# Benchmark comparison: `baseline-bbaeb26` → `improved`

- Before: `bbaeb265c1` (2026-10-19T16:08:31-04:00)
- After: `bbaeb265c1`* (2026-10-19T16:31:13-04:00)
- Cluster: 3 nodes on macOS-27.0-arm64-arm-64bit-Mach-O

| Metric | Before | After | Change |
|---|---:|---:|---:|
| Peak throughput (ops/s) | 409.6 | 5,580.2 | +1262% (13.6× better) |
| Single-client write latency p50 (ms) | 150.8 | 1.0 | -99% (152.2× better) |
| Single-client write latency p99 (ms) | 296.9 | 6.1 | -98% (48.8× better) |
| p99 latency at max concurrency (ms) | 157.6 | 73.8 | -53% (2.1× better) |
| Cold-start election to first write, p50 (ms) | 491.9 | 517.7 | +5% (within noise) |
| Leader failover unavailability, p50 (ms) | 473.6 | 393.8 | -17% (within noise) |
| Leader failover unavailability, max (ms) | 5,666.3 | 455.3 | -92% (12.4× better) |
| Leader crashes not recovered within 30 s | 0 | 0 | no change |
| Restarted node catch-up, p50 (ms) | — | 816.4 | — |
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

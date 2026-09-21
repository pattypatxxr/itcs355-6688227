# Lab 3 - Load test report

## Stated target (written BEFORE measurement)
- p95 latency <= 500 ms at 10 concurrent users (warm), error rate < 1%
- Client: WSL in Bangkok -> Azure Container Apps japanwest (network RTT included)
- Cold start reported separately (scale-to-zero)

## Setup
- Azure Container Apps, japanwest, 0.5 vCPU / 1 GiB, minReplicas=0, maxReplicas=1 (no scale-out)
- Model registry version 2; load generator: Locust, 60 s per level, mix 90% /predict + 10% /predict/batch (50 rows)
- Client in Bangkok, so ~135 ms network RTT is included in every latency figure

## Results (aggregated, warm, error rate 0% at every level)
| users | RPS | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| 1 | 5.2 | 140 | 160 | 170 |
| 10 | 44.4 | 150 | 260 | 370 |
| 20 | 33.8 | 490 | 940 | 1200 |
| 30 | 31.6 | 860 | 1400 | 1700 |
| 40 | 32.5 | 1200 | 1700 | 2000 |
| 50 | 30.2 | 1500 | 2700 | 3100 |

Target check: at 10 users p95 = 260 ms <= 500 ms and errors = 0% -> target met.
Throughput peaks at 10 users and plateaus at ~30 rps from 20 users; latency then grows linearly with users
(queueing on a single 0.5 vCPU replica).

## Cold start (measured separately, scale-to-zero, 3 rounds)
| round | cold request | next (warm) request |
|---|---|---|
| 1 | 61.2 s | 0.40 s |
| 2 | 61.1 s | 0.41 s |
| 3 | 63.1 s | 0.40 s |
## Breaking point / Batch / Payload / Instance size / Canary / Cost
(เติมตัวเลขจาก Step 1-6)

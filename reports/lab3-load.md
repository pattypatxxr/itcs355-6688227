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

## Canary Detection (Task 4)

1. **Metric that reveals the difference**: ROC-AUC computed from labeled replay
   (test-set rows re-sent through the live endpoint, split by `model_version` in the
   response). Latency and error rate were identical between v2 and canary v4 — both
   serve 200s in the same latency range — so those metrics show no difference at all.
   Ground-truth offline AUC: v2=0.8533, v4=0.8299 (a real, designed-in 2.3-point gap).

2. **Detection time**: **Not achieved within this canary window.** With a 90/10 split
   and ~1,200 requests sent (119 routed to canary), the 95% CI on canary AUC still
   overlapped v2's AUC. Extrapolating from the true v4 AUC, the CI does not stop
   overlapping v2 even at n=3,000 canary-labeled requests (30,000 total at 10%
   traffic) — see `reports/canary_full_log_analysis` above. A 2.3-point AUC gap is
   simply too small for AUC-on-a-10%-sample to resolve at any traffic volume that's
   practical to run in a lab session.

3. **What would make detection faster**:
   - A larger canary traffic share (see #4)
   - A paired/DeLong significance test instead of independent Hanley-McNeil CIs,
     since it uses the correlation between models' scores on the same rows and is
     substantially more powerful for small score gaps
   - A metric closer to the actual harm (e.g. false-negative rate on the positive
     class specifically, which is more sensitive to a 2-3 point AUC drop than
     aggregate AUC)
   - Accuracy and Brier score were tried first and were *worse* at detecting the
     gap than AUC — with 14% positive-class prevalence, both are dominated by the
     majority class and stayed flat regardless of canary quality (see below)

4. **At 50/50 split**: canary would accumulate labeled samples 5x faster per unit
   time (same total traffic, half going to canary instead of a tenth), so detection
   — if achievable at all for this gap size — would take roughly 1/5 the requests.
   The direct cost: half of all users receive predictions from the degraded model
   for the entire detection window, not just one in ten.

5. **Tie to real numbers**: v2 (production, registry version 2) has metric_val=0.8426,
   metric_test=0.8533. The canary used here (registry version 4, trained locally with
   `--n-estimators 10 --max-depth 2`, seed=20260101, same data_version as v2) has
   metric_val=0.8071, metric_test=0.8299 — a deliberate, documented 2.3-point test-AUC
   regression, registered with full lineage tags and `do_not_promote=true`. Registry
   version 3 exists but was not used: its git_commit does not match this repo's
   history and its origin could not be verified, so it was excluded rather than
   trusted.

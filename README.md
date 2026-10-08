# ITCS355 Lab 1 — Reproducible Training

> **Course materials live in [`course/`](course/README.md)** — syllabus, slides, the faculty
> specification, all five lab handouts, and the project brief. Every document is Markdown and
> renders on GitHub, diagrams included. New to the repo? Start with the
> [portability reference](course/reference/cloud-portability-reference.md).
> Keep this block when you edit the rest of this file; it is not part of the Lab 1 deliverable.

Predicting machine failure within 7 days from sensor readings. The model is not the point;
whether a stranger can reproduce it is.

> **This README is graded.** A grader with Docker and nothing else from your setup runs one
> command and compares the result against the claim below. Edit every `<...>` and delete the
> instruction blocks marked **REPLACE** before submitting.

---

## Reproduce

```bash
make reproduce
```

expected test_roc_auc: 0.8482 ± 0.0005

Runtime: about 40 seconds on 4 cores. No cloud account or credentials needed for this command —
that is deliberate, and it is why a grader can run it.

---

## The problem

240 machines, 25 readings each, 6 sensor features, binary target `failed_within_7d` with a
positive rate near 12%.

Machines have persistent characteristics — a hot-running machine reads hot in every row. So the
train/validation/test split is **grouped by `machine_id`**: every reading from one machine lands
in exactly one partition. Splitting row-wise instead lets the model memorise the machine and
reports a validation score that will never survive production. `tests/test_data.py` asserts this
property holds, and Lab 4 turns it into a CI gate.

Bringing your own dataset is allowed. Replace `scripts/make_dataset.py`, update the schema in
`src/data.py`, and keep every test passing.

---

## Layout

```
src/          Layer 1 — provider-neutral. No SDKs, no bucket names, no absolute paths.
cloudlayer/   Layer 3 — the only place a provider SDK may be imported.
scripts/      Dataset generation, cloud check, portability audit, metric verification.
tests/        Data contract tests and split property tests.
```

`src/config.py` is the single point of environment knowledge. Everything else reads from it.
`make portability-audit` enforces the rule; it fails the build if a provider string appears in
`src/` or `tests/`.

---

## Setup

```bash
cp cloud.env.example cloud.env      # fill in, never commit
make setup
make cloud-check                    # eight slots, all PASS
make data                           # generate the dataset
make test                           # 10 tests, all passing
```

Post your `make cloud-check` output in the course channel before Session 1.

---

## What you must finish

Four `TODO` markers are left in the repo deliberately. Each is a graded decision, not busywork.

| Where | What |
|---|---|
| `requirements.txt` | Regenerate with `pip-compile --generate-hashes` |
| `Dockerfile` | Pin the base image by digest; add `--require-hashes` |
| `cloudlayer/<your provider>.py` | Implement `upload`, `download`, `push_image` |
| This README | The reproducibility trade-off question below |

Then:

```bash
make image-push        # image reaches your registry, digest-pinned
dvc init && dvc remote add -d storage ${BLOB_URI}/dvc
dvc add data/raw && dvc push
```

Run five or more tracked runs varying something meaningful — not five identical runs with
different seeds.

---

## Reproducibility trade-off

I would drop the digest-pinned base image first. If `python:3.11-slim` moves to a new patch
release, the build usually still succeeds with near-identical package behavior, so the failure
mode is rare and often silent-safe. Dropping hashed dependencies is worse: a republished wheel
under the same version number changes what actually runs, with no build error to flag it.
Dropping seed control is worst of all. In my own five tracked runs, changing only the seed
(42 → 123, identical hyperparameters) moved `test_roc_auc` by 0.014–0.022 — a bigger swing than
any hyperparameter change I tried — because the seed also reshuffles the train/val/test split,
not just the model. That makes runs incomparable, which defeats the entire point of tracking them.

---

## Notes for the grader

- The Makefile's `reproduce` target originally mounted only `data` and `reports` as Docker
  volumes, not `mlruns`. This caused `PermissionError: [Errno 13] Permission denied:
  '/app/mlruns'` on every run, because MLflow tries to create `mlruns/` inside the container
  even when `MLFLOW_TRACKING_URI` points at sqlite. I added a `-v "$$PWD/mlruns:/app/mlruns"`
  mount to fix it locally. This looks like a scaffolding gap that likely affects the whole
  cohort, not something specific to my setup — flagged to the instructor separately.
- My Azure for Students subscription is restricted by an `Allowed locations` policy to
  `japanwest` only. `southeastasia` and `eastus` were both rejected with
  `RequestDisallowedByAzure`. All resources (storage account, ACR) are provisioned in
  `japanwest` instead; `cloud.env` reflects this.
- `make reproduce` was verified deterministic: two consecutive runs with the fixed seed
  (`20260101` from the Makefile) produced byte-identical `data_fingerprint` and an exact-match
  `test_roc_auc` of `0.8482378548603715`, hence the tight `± 0.0005` tolerance above.
- `dvc pull` requires Azure credentials scoped to my storage account
  (`itcs3556688227`), authenticated via `DefaultAzureCredential`. A grader without
  those credentials cannot pull directly. If you need to verify the DVC-tracked
  data, I can grant your Azure AD account (or the grading service principal)
  "Storage Blob Data Reader" on this storage account — message me the identity to
  grant, or I can generate a time-limited SAS token for read-only access instead.
---

## Checklist before you submit

- [ ] `make reproduce` works from a fresh clone, on a machine that is not yours
- [ ] `make verify` passes against your claim line
- [ ] `make test` — all tests pass
- [ ] `make portability-audit` — clean
- [ ] Image builds for `linux/amd64` and is pushed, digest-pinned
- [ ] `dvc push` completed; a grader can `dvc pull`
- [ ] Five or more tracked runs with params, metrics, data fingerprint, and commit SHA
- [ ] Every **REPLACE** block above is gone (the course-materials block at the top stays)
- [ ] `git log -p | grep -i -E "secret|password|AKIA|BEGIN PRIVATE"` returns nothing

That last check is not optional. A credential in Git history is an automatic deduction in this
course, and rotating it is your responsibility, not the grader's.

## Model Promotion — Ownership

In a real organisation, promotion from Development → Production stage should be
performed by someone outside the individual contributor who trained the model —
for example, an ML platform lead, MLOps engineer, or a designated model owner role
with accountability for production reliability. It should not be the same person
who ran the training trials, since self-approval removes the independent check
promotion is meant to provide.

Required evidence before promotion:
- `reload_check.py` runs clean against the registered version (not a local file)
  and scores held-out rows successfully
- All 8 lineage fields present on the registered version: git_commit, data_version,
  mlflow_run_id, training_job_id, image_digest, seed, metric_val, metric_test
- Reported test metric matches what `reload_check.py` independently reproduces
- Comparison/justification artifact in `reports/` explaining why this version was
  chosen over the highest-scoring alternative (if different)

**Quota increase request result:** Submitted via Azure ML Studio portal
(Low priority cores, requested limit: 4). Rejected immediately with:
"Your subscription isn't eligible for a quota increase. To request a quota
increase, first upgrade to a Pay-As-You-Go subscription." This confirms the
constraint is a hard restriction of the Azure for Students subscription tier,
not a per-family or per-region limitation, and not something resolvable
without a subscription type change outside the scope of this course.

## Lab 4 — CI/CD, monitoring, drift

### Data contract tests: the incident each one would have caught

| Test | Production incident it would have caught |
|---|---|
| `test_schema_columns_present_and_typed` | An upstream producer drops, renames or adds a column, or changes a column's type (Task 3: `missing columns: ['vibration_mm_s']`). |
| `test_no_nulls_in_required_columns` | A sensor stops reporting or a join breaks, so a required column starts arriving with nulls (the null-rate threshold is zero; the message names each column and its count). |
| `test_features_within_plausible_ranges` | A feed delivers values outside the physically plausible range, e.g. a unit change or a faulty sensor (bounds in `data.PLAUSIBLE_RANGES`). |
| `test_no_machine_leaks_across_splits` | The split silently becomes row-wise, so the same machine appears in more than one split and scores look better than reality. |

**Blocked bad commit (Task 3).** PR #1 ("DO NOT MERGE") removed the `vibration_mm_s` column and
was closed without merging. CI result: 3 failed, 7 passed. The schema test named the cause
directly (`missing columns: ['vibration_mm_s']`); the nulls and ranges tests failed as a
cascade with a raw `KeyError` because the column was missing, not because values were wrong.

### Dashboard

Prometheus and Grafana run from `monitoring/docker-compose.yml`; the dashboard is committed as
code in `monitoring/dashboard.json`. It shows the five required signals: model version in
production, request rate, error rate split into 4xx and 5xx, server-side latency p50/p95/p99,
and the rolling mean/std of `temp_c` over the last 500 requests. Screenshot taken 2026-10-08
16:39 (UTC+7).

Notes: the `temp_c` panel did not record the pre-shift period (the rolling window was already
mixed when scraping started), so the evidence for the shift is the Discord alerts and the
metric table below. Server-side p95 measured at the endpoint is about 20-25 ms, far below the
~125 ms estimated in `slo.yaml` (260 ms client p95 minus ~135 ms RTT), so the 500 ms budget has
more headroom than written. The freshness SLO refers to a Lab 5 pipeline and a 21-day retrain
trigger that are planned, not implemented.

### Drift detection

- PSI per feature against a reference regenerated byte-identically with seed 20260101;
  window of the last 500 requests.
- **Threshold 0.07.** PSI between two samples of the same distribution at 500 rows has
  p99 = 0.0385 and max = 0.053 over 1,000 draws. A +3 °C shift of `temp_c` (0.3 sigma) gives
  p5 = 0.070. The line sits above the noise and below the smallest shift we care about.
- Runs as a Container Apps Job on a cron schedule (every 5 minutes during the experiment) and
  posts alerts to Discord. Scores are emitted as metrics to Application Insights.
- Known limits: the window lives in the service's memory and is lost on restart or
  scale-to-zero; the job skips silently when the window has fewer than 500 rows; metrics
  require a single worker (a test guards this).

### Injected drift (temp_c +6 °C, `scripts/inject_drift.py`)

| Time (UTC) | temp_c PSI | Note |
|---|---|---|
| 08:15 | 0.038 | baseline (manual run) |
| 08:27:22 | - | T0: injection starts |
| 08:30:20 | 0.133 | first alert (mean 79.58 -> 83.17) |
| 08:35:19 | 0.334 | window mostly replaced (mean 85.37) |

Detection latency is about 3 minutes (2 min 58 s), dominated by the 5-minute cron cadence.
Times are taken from the `drift ALERT` timestamp in the message (UTC), not Discord's local time.

### Post-mortem

- **What fired:** drift alert at 08:30:20 UTC; `temp_c` PSI 0.133 against threshold 0.07, 1 of 6 features, rising to 0.334-0.344 as the window filled with shifted data.
- **True cause:** a +6 °C mean shift in `temp_c` only. Scenario: the sensor was recalibrated and reads higher while the machines did not get hotter. Schema and null rate did not change, so this is not an upstream pipeline break.
- **Retrain, roll back, or no action:** no retrain, no rollback. The real world did not change, only the readings. Retraining would teach the model that 85 is normal, and when calibration is corrected the model would be permanently off. Confirm with the sensor owners, then either restore the calibration or apply an offset in preprocessing; keep the current model serving meanwhile.
- **Cost if unnoticed for a week:** [TO FILL]
- **Prevent or detect faster:** shorter cron interval, a per-feature mean-shift alert on a smaller window, let the drift job read a sensor/calibration change log, and monitor prediction quality when labels exist to separate data drift from concept drift.

### Teardown

`make teardown` removed the staging container app, environment and identity; no scheduled
job or container app remains. The cost report target in the Makefile is `cost`
(not `cost-report`).

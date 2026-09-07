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

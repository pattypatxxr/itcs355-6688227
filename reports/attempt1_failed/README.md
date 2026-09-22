First canary attempt (2026-09-21). Failed before serving any traffic:
revision `stable2` got MODEL_VERSION=3 (a model that was never registered at the
time) via `az containerapp update`, which inherits template from the latest
revision instead of the intended source. Revision `rb1`, created to roll back,
lost MODEL_VERSION entirely via `--remove-env-vars`, causing a full outage
(all requests 503/504) until recovered by resetting traffic to itcs355-serve--0000001.
Files here are timestamps from this failed attempt, kept for the record —
not evidence of a working canary. See the successful attempt's files
(canary_t0_v2.txt, canary_rollback_v2.txt, canary_probe_full_log.csv, etc.)
for real detection evidence.

# Calibration Control: schedule calibration, manage certificates, block use of overdue instruments

72-hour code challenge solution. Database + backend + frontend + synthetic data generator + validation + tests.
**Pure Python 3.10+ standard library. No `pip install`, no build step, no external data.**

## Quick start
```bash
cd "72 hour code challenge"
python -m calibration.server --data data/full --port 8000     # open http://127.0.0.1:8000
python -m unittest discover -s tests -v                        # 18 tests, ~1 s
python scripts/repro_check.py                                  # regenerate twice, compare checksums
```
Use `--data data/starter` for the small dataset (200 instruments / 500 calibrations / 10,000 uses).

## Regenerate data (same generator for every scale)
```bash
python -m calibration.generate --preset full    --out data/full    --seed 20261022      # 2,000 / 5,000 / 100,000
python -m calibration.generate --preset starter --out data/starter                      # 200 / 500 / 10,000
python -m calibration.generate --assets 500 --events 1200 --uses 20000 --out data/custom --formats csv,db
```
`--formats` is any of `csv,json,sql,db` (default all). The shipped `data/full` contains `csv,db` only to keep the zip small (JSON/SQL: add `--formats csv,json,sql,db`). Fixed default seed: **20261022**.
Output folder: `csv/` `json/` `sql/seed.sql` `calibration.db` `ground_truth/` `docs/DATA_DICTIONARY.md` `docs/schema.sql` `manifest.json` (command, seed, row counts, SHA-256) `source_manifest.json` `validation_summary.json` `evaluation.json`.

## What the app does
| Screen | Purpose |
|---|---|
| **Use gate** | Enter an asset and time: GO / WARN / HOLD with the reason. **Record use** is refused (HTTP 409) when policy prohibits it; a `USE_BLOCKED` alert and an audit record are appended. |
| Overview | KPIs, monthly use vs prohibited use, decision mix, downtime. |
| Instruments | Search/filter; detail shows calibration history, certificates (mismatch / missing flagged), work orders, alerts, audit trail. |
| Alerts | Filter by exception type. |
| Data quality | Validation checks and detector-vs-ground-truth precision/recall. |

API: `GET /api/summary | /api/assets?q=&status= | /api/assets/<id> | /api/alerts?type= | /api/check?asset_id=&at= | /api/validation | /api/evaluation`, `POST /api/use {asset_id, used_at}`.

## Business rules (`calibration/rules.py`, single implementation used by generator, detector and API)
1. `due_date = performed_date + plan.interval_days`. The due date itself is still valid; due+1 is overdue (boundary cases are generated and tested).
2. A **FAIL** calibration quarantines the asset until its CORRECTIVE_ACTION work order is closed (open = still quarantined). An IMPACT_ASSESSMENT work order is created and counts the uses made since the previous calibration (`affected_use_count`). After closure the as-left calibration governs.
3. After the due date an **emergency extension** for that cycle (limited by the type's `max_extension_days`) keeps use compliant.
4. Overdue and `prohibit_use_when_overdue = 1` -> `PROHIBITED_OVERDUE` (block). Otherwise `ADVISORY_OVERDUE` (warn only).
5. State changes are new rows (audit_record, work_order, calibration_event); nothing is overwritten. The asset `status` is a snapshot at 2026-12-31 derived from the rules.

## Design
* `schema.py` is the single source of truth: data dictionary (type, required, allowed values, units, uniqueness, rule) -> SQLite DDL, generic validators and `DATA_DICTIONARY.md`.
* `generate.py` builds parents first (supplier, instrument_type + N:M bridge, asset, plan), then events (calibration -> extension -> certificate -> work orders -> uses -> alerts -> audit). Outcomes (PASS/FAIL, late, quarantine, windows) come from documented rules; derived values (deviation, result, due date, status, affected uses) are computed from source records.
* `detect.py` is an independent detector working only from stored tables; it produces the alerts. `evaluate.py` is the only module that reads ground truth, and scores the detector against it.
* IDs: `AST-000001`, `CAL-<asset-id>-2026-000001`, `CERT-<calibration-id>`, `WO-2026-000001`, `USE-<asset-id>-<yyyymmddThhmmss>`; plus `PLN-<asset-id>`, `EXT-2026-`, `ALT-2026-`, `AUD-`, `SUP-`, `ITY-`.

## Edge cases (injected + labelled in `ground_truth/`, never in input tables)
| Required case | issue_type |
|---|---|
| Due date inconsistent with plan | `DUE_DATE_INCONSISTENT` |
| Expired instrument used without exception | `EXPIRED_USE_NO_EXCEPTION` (also `USE_WHILE_QUARANTINED`, `OVERDUE_USE_NONBLOCKING`) |
| Certificate refers to another asset | `CERT_ASSET_MISMATCH` |
| Failed calibration without impact assessment | `IMPACT_ASSESSMENT_MISSING` |
| Certificate gaps, emergency extensions, due-date boundary uses | `MISSING_CERTIFICATE`, `EXTENSION_USE`, `BOUNDARY_DUE_DATE_USE` |

## Full dataset (seed 20261022)
| table | rows |
|---|---|
| supplier | 14 |
| instrument_type | 12 |
| instrument_type_supplier | 48 |
| asset | 2,000 |
| calibration_plan | 2,000 |
| emergency_extension | 183 |
| calibration_event | 5,000 |
| certificate | 4,900 |
| work_order | 5,591 |
| production_use | 100,000 |
| alert | 543 |
| audit_record | 18,968 |

Use decisions: COMPLIANT: 99,441, PROHIBITED_QUARANTINE: 10, ADVISORY_OVERDUE: 276, COMPLIANT_EXTENSION: 182, PROHIBITED_OVERDUE: 91.

| issue_type | ground-truth rows | detector precision | detector recall |
|---|---|---|---|
| DUE_DATE_INCONSISTENT | 25 | 1.0 | 1.0 |
| EXPIRED_USE_NO_EXCEPTION | 91 | 1.0 | 1.0 |
| USE_WHILE_QUARANTINED | 10 | 1.0 | 1.0 |
| OVERDUE_USE_NONBLOCKING | 276 | 1.0 | 1.0 |
| EXTENSION_USE | 182 | 1.0 | 1.0 |
| BOUNDARY_DUE_DATE_USE | 170 | 1.0 | 1.0 |
| CERT_ASSET_MISMATCH | 20 | 1.0 | 1.0 |
| MISSING_CERTIFICATE | 100 | 1.0 | 1.0 |
| IMPACT_ASSESSMENT_MISSING | 21 | 1.0 | 1.0 |

107 validation checks (PK uniqueness, FK integrity, enums, ID formats, date ordering, arithmetic reconciliation, lifecycle chain, duplicates) all pass. Reproducibility: two runs give identical row counts and SHA-256 for every CSV and the ground truth.

## Tests (`tests/test_all.py`)
Volume, validation, edge-case coverage, detector = ground truth, ground-truth separation/no leakage, due-date correctness, impact-assessment rule, validator catches corruption, append-only audit, reproducibility, rule boundaries (due date inclusive, extension, quarantine, advisory policy), API (summary, 404, blocked use + alert, recorded use).

## Honest notes and assumptions
* Detector precision/recall of 1.0 is expected: ground truth is produced by the generator's window model and the detector is a separate implementation of the same documented policy. It proves consistency and catches regressions, not real-world accuracy.
* `CAL-<asset-id>-2026-NNNNNN` uses one global counter ordered by date (the brief does not say per-asset).
* Calibration plan intervals (90/120/180/365 days) are derived from events per asset so the 5,000-event target is met exactly; they never exceed the type's default interval.
* All data is synthetic; no public dataset is used (see `source_manifest.json`). Dates cover calendar 2026; as-of date 2026-12-31.
* Roles in the brief (operator, engineer, planner, OT/IT admin) appear as actor/ID prefixes (`OPR-`, `MENG-`, `QENG-`, `ADMIN-`); there is no login/authorization layer.
* The server is a demo (stdlib `http.server`, no auth); put a real gateway in front for production.

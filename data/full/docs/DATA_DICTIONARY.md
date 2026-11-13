# Data dictionary

Generated from `calibration/schema.py` (single source of truth for DDL, validation and this document).

**Cardinality:** supplier 1:N asset (manufacturer); instrument_type 1:N asset; instrument_type N:M supplier via bridge `instrument_type_supplier`; asset 1:1 active calibration_plan; asset 1:N calibration_event; calibration_event 0..1:1 certificate; calibration_event 1:N work_order (CALIBRATION, CORRECTIVE_ACTION, IMPACT_ASSESSMENT); asset 1:N production_use; asset 1:N emergency_extension; asset 1:N alert / audit_record. Ground truth lives outside the schema (`ground_truth/`).

## supplier

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| supplier_id | str | Y |  | Y | SUP-NNN |
| name | str | Y |  | Y | unique |
| role | str | Y | CALIBRATION_LAB, MANUFACTURER |  |  |
| iso17025_accredited | bool | Y |  |  | must be 1 for CALIBRATION_LAB |
| country | str | Y |  |  | country name |
| status | str | Y | ACTIVE, SUSPENDED |  | labs used for calibration must be ACTIVE |

## instrument_type

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| type_id | str | Y |  | Y | ITY-NNN |
| name | str | Y |  |  |  |
| measurand | str | Y |  |  |  |
| unit | str | Y |  |  | measurement unit (e.g. bar, degC) |
| default_interval_days | int | Y | unit: days |  | max interval any plan of this type may use |
| tolerance_pct | real | Y | unit: % |  | >0 |
| criticality | str | Y | LOW, MEDIUM, HIGH |  |  |
| prohibit_use_when_overdue | bool | Y |  |  | policy flag: 1 = system must block overdue use |
| max_extension_days | int | Y | unit: days |  | 0 = emergency extensions not allowed |

## instrument_type_supplier

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| type_id | str | Y | FK -> instrument_type.type_id | composite | bridge N:M type<->approved lab |
| supplier_id | str | Y | FK -> supplier.supplier_id | composite | must be a CALIBRATION_LAB |
| approved_from | date | Y |  |  |  |

## asset

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| asset_id | str | Y |  | Y | AST-NNNNNN, immutable |
| serial_number | str | Y |  | Y | unique |
| name | str | Y |  |  |  |
| type_id | str | Y | FK -> instrument_type.type_id |  |  |
| manufacturer_id | str | Y | FK -> supplier.supplier_id |  |  |
| location | str | Y |  |  | plant area |
| commissioned_date | date | Y |  |  | <= first calibration |
| status | str | Y | IN_SERVICE, QUARANTINED, OVERDUE |  | snapshot at as-of date derived by rules; history in audit_record |

## calibration_plan

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| plan_id | str | Y |  | Y | PLN-<asset-id> |
| asset_id | str | Y | FK -> asset.asset_id |  | 1 active plan per asset |
| interval_days | int | Y | unit: days |  | <= instrument_type.default_interval_days |
| tolerance_pct | real | Y | unit: % |  | = type tolerance |
| reference_value | real | Y |  |  | nominal calibration point |
| unit | str | Y |  |  |  |
| effective_from | date | Y |  |  |  |
| effective_to | date | N |  |  | null while ACTIVE |
| status | str | Y | ACTIVE, SUPERSEDED |  |  |

## emergency_extension

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| extension_id | str | Y |  | Y | EXT-2026-NNNNNN |
| asset_id | str | Y | FK -> asset.asset_id |  |  |
| plan_id | str | Y | FK -> calibration_plan.plan_id |  |  |
| due_date_original | date | Y |  |  | due date of the cycle being extended |
| extended_until | date | Y |  |  | extended_until - due_date_original <= type.max_extension_days |
| approved_by | str | Y |  |  | quality engineer id |
| approved_on | date | Y |  |  | = due_date_original |
| reason | str | Y | PRODUCTION_CRITICAL, LAB_BACKLOG, SPARE_UNAVAILABLE |  |  |
| status | str | Y | ACTIVE, EXPIRED |  | ACTIVE if extended_until >= as-of date |

## calibration_event

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| calibration_id | str | Y |  | Y | CAL-<asset-id>-2026-NNNNNN (global counter ordered by date) |
| asset_id | str | Y | FK -> asset.asset_id |  |  |
| plan_id | str | Y | FK -> calibration_plan.plan_id |  |  |
| lab_supplier_id | str | Y | FK -> supplier.supplier_id |  |  |
| performed_date | date | Y |  |  | unique per asset |
| performed_by | str | Y |  |  | engineer id |
| reference_value | real | Y |  |  |  |
| measured_value | real | Y |  |  |  |
| unit | str | Y |  |  |  |
| tolerance_pct | real | Y | unit: % |  |  |
| deviation_pct | real | Y | unit: % |  | round(abs(measured-reference)/reference*100,4) |
| result | str | Y | PASS, FAIL |  | PASS iff deviation_pct <= tolerance_pct |
| interval_days_applied | int | Y | unit: days |  | = plan.interval_days |
| next_due_date | date | Y |  |  | performed_date + interval_days_applied (inclusive last valid day) |
| days_late | int | Y | unit: days |  | performed - previous due date if >0 else 0 |
| emergency_extension_id | str | N | FK -> emergency_extension.extension_id |  | extension that bridged the overdue gap |
| status | str | Y | COMPLETED |  |  |

## certificate

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| cert_id | str | Y |  | Y | CERT-<calibration_id> |
| calibration_id | str | Y | FK -> calibration_event.calibration_id | Y | 1:1 optional (gaps exist) |
| asset_id | str | Y | FK -> asset.asset_id |  | must equal calibration_event.asset_id |
| certificate_number | str | Y |  | Y | unique |
| lab_supplier_id | str | Y | FK -> supplier.supplier_id |  |  |
| issued_date | date | Y |  |  | >= performed_date |
| valid_until | date | Y |  |  | = performed_date + plan interval |
| result | str | Y | PASS, FAIL |  | = event.result |
| status | str | Y | VALID, SUPERSEDED, EXPIRED |  | latest per asset: VALID/EXPIRED vs as-of; older SUPERSEDED |

## work_order

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| wo_id | str | Y |  | Y | WO-2026-NNNNNN |
| wo_type | str | Y | CALIBRATION, CORRECTIVE_ACTION, IMPACT_ASSESSMENT |  |  |
| asset_id | str | Y | FK -> asset.asset_id |  |  |
| calibration_id | str | Y | FK -> calibration_event.calibration_id |  | triggering/related calibration |
| status | str | Y | OPEN, CLOSED |  | CLOSED iff closed_date not null |
| assigned_role | str | Y | MAINTENANCE_ENGINEER, QUALITY_ENGINEER |  |  |
| opened_date | date | Y |  |  |  |
| due_date | date | Y |  |  | >= opened_date |
| closed_date | date | N |  |  | >= opened_date |
| downtime_hours | real | Y | unit: h |  | >=0 |
| affected_use_count | int | N |  |  | IMPACT_ASSESSMENT only: uses between previous calibration and failed calibration |

## production_use

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| use_id | str | Y |  | Y | USE-<asset-id>-YYYYMMDDTHHMMSS |
| asset_id | str | Y | FK -> asset.asset_id |  |  |
| used_at | datetime | Y |  |  | ISO-8601 plant local time; baseline 06:00-22:00 |
| production_line | str | Y |  |  | LINE-NN |
| batch_id | str | Y |  |  | BATCH-YYYYMMDD-NNN |
| operator_id | str | Y |  |  | OPR-NNN |
| duration_min | int | Y | unit: min |  | >0 |
| compliance_status | str | Y | COMPLIANT, COMPLIANT_EXTENSION, ADVISORY_OVERDUE, PROHIBITED_OVERDUE, PROHIBITED_QUARANTINE, PROHIBITED_NO_CALIBRATION |  | derived by calibration.rules from source records |
| calibration_id | str | N | FK -> calibration_event.calibration_id |  | governing calibration |
| exception_id | str | N | FK -> emergency_extension.extension_id |  | extension that made an overdue use compliant |

## alert

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| alert_id | str | Y |  | Y | ALT-2026-NNNNNN |
| alert_type | str | Y | EXPIRED_USE_NO_EXCEPTION, USE_WHILE_QUARANTINED, OVERDUE_USE_NONBLOCKING, DUE_DATE_INCONSISTENT, CERT_ASSET_MISMATCH, MISSING_CERTIFICATE, IMPACT_ASSESSMENT_MISSING, USE_BLOCKED |  |  |
| severity | str | Y | LOW, MEDIUM, HIGH |  |  |
| asset_id | str | Y | FK -> asset.asset_id |  |  |
| entity_type | str | Y | production_use, calibration_event, certificate |  |  |
| entity_id | str | Y |  |  | id of the offending record |
| raised_at | datetime | Y |  |  |  |
| status | str | Y | OPEN, ACKNOWLEDGED |  |  |
| message | str | Y |  |  |  |

## audit_record

| field | type | required | allowed values / units | unique | validation rule |
|---|---|---|---|---|---|
| audit_id | str | Y |  | Y | AUD-NNNNNNN, append-only |
| entity_type | str | Y | ASSET, CALIBRATION_EVENT, WORK_ORDER, EXTENSION |  |  |
| entity_id | str | Y |  |  |  |
| asset_id | str | Y | FK -> asset.asset_id |  |  |
| action | str | Y | ASSET_COMMISSIONED, CALIBRATION_COMPLETED, STATUS_CHANGED, RETURNED_TO_SERVICE, EXTENSION_APPROVED, WO_OPENED, WO_CLOSED, USE_BLOCKED |  |  |
| from_state | str | N |  |  | lifecycle actions only |
| to_state | str | N |  |  | lifecycle actions only |
| actor | str | Y |  |  |  |
| occurred_at | datetime | Y |  |  |  |
| details | str | N |  |  |  |

## ground_truth (separate file, never joined into inputs)

| field | meaning |
|---|---|
| issue_id | GT-NNNNNN |
| issue_type | DUE_DATE_INCONSISTENT, EXPIRED_USE_NO_EXCEPTION, USE_WHILE_QUARANTINED, OVERDUE_USE_NONBLOCKING, EXTENSION_USE, BOUNDARY_DUE_DATE_USE, CERT_ASSET_MISMATCH, MISSING_CERTIFICATE, IMPACT_ASSESSMENT_MISSING |
| entity_type / entity_id / asset_id | offending record |
| origin | NATURAL (emerged from generation rules) or INJECTED (deliberate edge case) |
| expected_decision | status the rules engine must assign to a use event, or `FLAG` for record-level anomalies |
| description | human readable |

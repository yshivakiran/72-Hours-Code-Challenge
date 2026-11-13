"""Single source of truth: data dictionary -> SQLite DDL, validators, docs.
Field tuple: (name, type, required, kind, note)
kind: PK | FK:table.col | PKFK:table.col | ENUM:A|B | UNIT:x | ''"""
TABLES = {}
def T(name, *fields): TABLES[name] = list(fields)

COMPLIANCE = "COMPLIANT|COMPLIANT_EXTENSION|ADVISORY_OVERDUE|PROHIBITED_OVERDUE|PROHIBITED_QUARANTINE|PROHIBITED_NO_CALIBRATION"
ALERT_TYPES = "EXPIRED_USE_NO_EXCEPTION|USE_WHILE_QUARANTINED|OVERDUE_USE_NONBLOCKING|DUE_DATE_INCONSISTENT|CERT_ASSET_MISMATCH|MISSING_CERTIFICATE|IMPACT_ASSESSMENT_MISSING|USE_BLOCKED"
ISSUE_TYPES = ["DUE_DATE_INCONSISTENT", "EXPIRED_USE_NO_EXCEPTION", "USE_WHILE_QUARANTINED", "OVERDUE_USE_NONBLOCKING",
               "EXTENSION_USE", "BOUNDARY_DUE_DATE_USE", "CERT_ASSET_MISMATCH", "MISSING_CERTIFICATE", "IMPACT_ASSESSMENT_MISSING"]
ALERT_SEVERITY = {"EXPIRED_USE_NO_EXCEPTION": "HIGH", "USE_WHILE_QUARANTINED": "HIGH", "CERT_ASSET_MISMATCH": "HIGH",
                  "IMPACT_ASSESSMENT_MISSING": "HIGH", "USE_BLOCKED": "MEDIUM", "DUE_DATE_INCONSISTENT": "MEDIUM",
                  "MISSING_CERTIFICATE": "MEDIUM", "OVERDUE_USE_NONBLOCKING": "LOW"}
UNIQUE = {("supplier", "name"), ("asset", "serial_number"), ("certificate", "calibration_id"), ("certificate", "certificate_number")}
ID_PATTERNS = {
    "supplier": r"^SUP-\d{3}$", "instrument_type": r"^ITY-\d{3}$", "asset": r"^AST-\d{6}$", "calibration_plan": r"^PLN-AST-\d{6}$",
    "calibration_event": r"^CAL-AST-\d{6}-2026-\d{6}$", "certificate": r"^CERT-CAL-AST-\d{6}-2026-\d{6}$", "work_order": r"^WO-2026-\d{6}$",
    "production_use": r"^USE-AST-\d{6}-\d{8}T\d{6}$", "emergency_extension": r"^EXT-2026-\d{6}$", "alert": r"^ALT-2026-\d{6}$", "audit_record": r"^AUD-\d{7}$"}
DATE_ORDER = [("calibration_event", "performed_date", "next_due_date"), ("certificate", "issued_date", "valid_until"),
              ("work_order", "opened_date", "due_date"), ("work_order", "opened_date", "closed_date"),
              ("emergency_extension", "due_date_original", "extended_until"), ("calibration_plan", "effective_from", "effective_to")]

T("supplier", ("supplier_id", "str", "Y", "PK", "SUP-NNN"), ("name", "str", "Y", "", "unique"),
  ("role", "str", "Y", "ENUM:CALIBRATION_LAB|MANUFACTURER", ""), ("iso17025_accredited", "bool", "Y", "", "must be 1 for CALIBRATION_LAB"),
  ("country", "str", "Y", "", "country name"), ("status", "str", "Y", "ENUM:ACTIVE|SUSPENDED", "labs used for calibration must be ACTIVE"))
T("instrument_type", ("type_id", "str", "Y", "PK", "ITY-NNN"), ("name", "str", "Y", "", ""), ("measurand", "str", "Y", "", ""),
  ("unit", "str", "Y", "", "measurement unit (e.g. bar, degC)"), ("default_interval_days", "int", "Y", "UNIT:days", "max interval any plan of this type may use"),
  ("tolerance_pct", "real", "Y", "UNIT:%", ">0"), ("criticality", "str", "Y", "ENUM:LOW|MEDIUM|HIGH", ""),
  ("prohibit_use_when_overdue", "bool", "Y", "", "policy flag: 1 = system must block overdue use"),
  ("max_extension_days", "int", "Y", "UNIT:days", "0 = emergency extensions not allowed"))
T("instrument_type_supplier", ("type_id", "str", "Y", "PKFK:instrument_type.type_id", "bridge N:M type<->approved lab"),
  ("supplier_id", "str", "Y", "PKFK:supplier.supplier_id", "must be a CALIBRATION_LAB"), ("approved_from", "date", "Y", "", ""))
T("asset", ("asset_id", "str", "Y", "PK", "AST-NNNNNN, immutable"), ("serial_number", "str", "Y", "", "unique"), ("name", "str", "Y", "", ""),
  ("type_id", "str", "Y", "FK:instrument_type.type_id", ""), ("manufacturer_id", "str", "Y", "FK:supplier.supplier_id", ""),
  ("location", "str", "Y", "", "plant area"), ("commissioned_date", "date", "Y", "", "<= first calibration"),
  ("status", "str", "Y", "ENUM:IN_SERVICE|QUARANTINED|OVERDUE", "snapshot at as-of date derived by rules; history in audit_record"))
T("calibration_plan", ("plan_id", "str", "Y", "PK", "PLN-<asset-id>"), ("asset_id", "str", "Y", "FK:asset.asset_id", "1 active plan per asset"),
  ("interval_days", "int", "Y", "UNIT:days", "<= instrument_type.default_interval_days"), ("tolerance_pct", "real", "Y", "UNIT:%", "= type tolerance"),
  ("reference_value", "real", "Y", "", "nominal calibration point"), ("unit", "str", "Y", "", ""), ("effective_from", "date", "Y", "", ""),
  ("effective_to", "date", "N", "", "null while ACTIVE"), ("status", "str", "Y", "ENUM:ACTIVE|SUPERSEDED", ""))
T("emergency_extension", ("extension_id", "str", "Y", "PK", "EXT-2026-NNNNNN"), ("asset_id", "str", "Y", "FK:asset.asset_id", ""),
  ("plan_id", "str", "Y", "FK:calibration_plan.plan_id", ""), ("due_date_original", "date", "Y", "", "due date of the cycle being extended"),
  ("extended_until", "date", "Y", "", "extended_until - due_date_original <= type.max_extension_days"), ("approved_by", "str", "Y", "", "quality engineer id"),
  ("approved_on", "date", "Y", "", "= due_date_original"), ("reason", "str", "Y", "ENUM:PRODUCTION_CRITICAL|LAB_BACKLOG|SPARE_UNAVAILABLE", ""),
  ("status", "str", "Y", "ENUM:ACTIVE|EXPIRED", "ACTIVE if extended_until >= as-of date"))
T("calibration_event", ("calibration_id", "str", "Y", "PK", "CAL-<asset-id>-2026-NNNNNN (global counter ordered by date)"),
  ("asset_id", "str", "Y", "FK:asset.asset_id", ""), ("plan_id", "str", "Y", "FK:calibration_plan.plan_id", ""),
  ("lab_supplier_id", "str", "Y", "FK:supplier.supplier_id", ""), ("performed_date", "date", "Y", "", "unique per asset"),
  ("performed_by", "str", "Y", "", "engineer id"), ("reference_value", "real", "Y", "", ""), ("measured_value", "real", "Y", "", ""),
  ("unit", "str", "Y", "", ""), ("tolerance_pct", "real", "Y", "UNIT:%", ""),
  ("deviation_pct", "real", "Y", "UNIT:%", "round(abs(measured-reference)/reference*100,4)"),
  ("result", "str", "Y", "ENUM:PASS|FAIL", "PASS iff deviation_pct <= tolerance_pct"),
  ("interval_days_applied", "int", "Y", "UNIT:days", "= plan.interval_days"),
  ("next_due_date", "date", "Y", "", "performed_date + interval_days_applied (inclusive last valid day)"),
  ("days_late", "int", "Y", "UNIT:days", "performed - previous due date if >0 else 0"),
  ("emergency_extension_id", "str", "N", "FK:emergency_extension.extension_id", "extension that bridged the overdue gap"),
  ("status", "str", "Y", "ENUM:COMPLETED", ""))
T("certificate", ("cert_id", "str", "Y", "PK", "CERT-<calibration_id>"), ("calibration_id", "str", "Y", "FK:calibration_event.calibration_id", "1:1 optional (gaps exist)"),
  ("asset_id", "str", "Y", "FK:asset.asset_id", "must equal calibration_event.asset_id"), ("certificate_number", "str", "Y", "", "unique"),
  ("lab_supplier_id", "str", "Y", "FK:supplier.supplier_id", ""), ("issued_date", "date", "Y", "", ">= performed_date"),
  ("valid_until", "date", "Y", "", "= performed_date + plan interval"), ("result", "str", "Y", "ENUM:PASS|FAIL", "= event.result"),
  ("status", "str", "Y", "ENUM:VALID|SUPERSEDED|EXPIRED", "latest per asset: VALID/EXPIRED vs as-of; older SUPERSEDED"))
T("work_order", ("wo_id", "str", "Y", "PK", "WO-2026-NNNNNN"), ("wo_type", "str", "Y", "ENUM:CALIBRATION|CORRECTIVE_ACTION|IMPACT_ASSESSMENT", ""),
  ("asset_id", "str", "Y", "FK:asset.asset_id", ""), ("calibration_id", "str", "Y", "FK:calibration_event.calibration_id", "triggering/related calibration"),
  ("status", "str", "Y", "ENUM:OPEN|CLOSED", "CLOSED iff closed_date not null"), ("assigned_role", "str", "Y", "ENUM:MAINTENANCE_ENGINEER|QUALITY_ENGINEER", ""),
  ("opened_date", "date", "Y", "", ""), ("due_date", "date", "Y", "", ">= opened_date"), ("closed_date", "date", "N", "", ">= opened_date"),
  ("downtime_hours", "real", "Y", "UNIT:h", ">=0"), ("affected_use_count", "int", "N", "", "IMPACT_ASSESSMENT only: uses between previous calibration and failed calibration"))
T("production_use", ("use_id", "str", "Y", "PK", "USE-<asset-id>-YYYYMMDDTHHMMSS"), ("asset_id", "str", "Y", "FK:asset.asset_id", ""),
  ("used_at", "datetime", "Y", "", "ISO-8601 plant local time; baseline 06:00-22:00"), ("production_line", "str", "Y", "", "LINE-NN"),
  ("batch_id", "str", "Y", "", "BATCH-YYYYMMDD-NNN"), ("operator_id", "str", "Y", "", "OPR-NNN"), ("duration_min", "int", "Y", "UNIT:min", ">0"),
  ("compliance_status", "str", "Y", "ENUM:" + COMPLIANCE, "derived by calibration.rules from source records"),
  ("calibration_id", "str", "N", "FK:calibration_event.calibration_id", "governing calibration"),
  ("exception_id", "str", "N", "FK:emergency_extension.extension_id", "extension that made an overdue use compliant"))
T("alert", ("alert_id", "str", "Y", "PK", "ALT-2026-NNNNNN"), ("alert_type", "str", "Y", "ENUM:" + ALERT_TYPES, ""),
  ("severity", "str", "Y", "ENUM:LOW|MEDIUM|HIGH", ""), ("asset_id", "str", "Y", "FK:asset.asset_id", ""),
  ("entity_type", "str", "Y", "ENUM:production_use|calibration_event|certificate", ""), ("entity_id", "str", "Y", "", "id of the offending record"),
  ("raised_at", "datetime", "Y", "", ""), ("status", "str", "Y", "ENUM:OPEN|ACKNOWLEDGED", ""), ("message", "str", "Y", "", ""))
T("audit_record", ("audit_id", "str", "Y", "PK", "AUD-NNNNNNN, append-only"), ("entity_type", "str", "Y", "ENUM:ASSET|CALIBRATION_EVENT|WORK_ORDER|EXTENSION", ""),
  ("entity_id", "str", "Y", "", ""), ("asset_id", "str", "Y", "FK:asset.asset_id", ""),
  ("action", "str", "Y", "ENUM:ASSET_COMMISSIONED|CALIBRATION_COMPLETED|STATUS_CHANGED|RETURNED_TO_SERVICE|EXTENSION_APPROVED|WO_OPENED|WO_CLOSED|USE_BLOCKED", ""),
  ("from_state", "str", "N", "", "lifecycle actions only"), ("to_state", "str", "N", "", "lifecycle actions only"), ("actor", "str", "Y", "", ""),
  ("occurred_at", "datetime", "Y", "", ""), ("details", "str", "N", "", ""))
GT_FIELDS = ["issue_id", "issue_type", "entity_type", "entity_id", "asset_id", "origin", "expected_decision", "description"]
SQLT = {"str": "TEXT", "date": "TEXT", "datetime": "TEXT", "int": "INTEGER", "bool": "INTEGER", "real": "REAL"}

def cols(t): return [f[0] for f in TABLES[t]]
def pks(t): return [f[0] for f in TABLES[t] if f[3].startswith("PK")]
def fks(t):
    for f in TABLES[t]:
        if f[3].startswith("FK:") or f[3].startswith("PKFK:"): yield f[0], f[3].split(":", 1)[1].split(".")
def enums(t): return {f[0]: set(f[3][5:].split("|")) for f in TABLES[t] if f[3].startswith("ENUM:")}

def ddl():
    out = []
    for t, fs in TABLES.items():
        lines = [f"  {f[0]} {SQLT[f[1]]}{' NOT NULL' if f[2] == 'Y' else ''}" for f in fs]
        lines.append(f"  PRIMARY KEY ({', '.join(pks(t))})")
        lines += [f"  FOREIGN KEY ({c}) REFERENCES {rt}({rc})" for c, (rt, rc) in fks(t)]
        lines += [f"  UNIQUE ({c})" for (tt, c) in sorted(UNIQUE) if tt == t]
        out.append(f"CREATE TABLE {t} (\n" + ",\n".join(lines) + "\n);")
    out += ["CREATE INDEX ix_use_asset ON production_use(asset_id, used_at);", "CREATE INDEX ix_use_status ON production_use(compliance_status);",
            "CREATE INDEX ix_cal_asset ON calibration_event(asset_id, performed_date);", "CREATE INDEX ix_wo_asset ON work_order(asset_id);",
            "CREATE INDEX ix_alert_asset ON alert(asset_id);", "CREATE INDEX ix_audit_asset ON audit_record(asset_id);"]
    return "\n".join(out)

def dictionary_md():
    L = ["# Data dictionary", "", "Generated from `calibration/schema.py` (single source of truth for DDL, validation and this document).", "",
         "**Cardinality:** supplier 1:N asset (manufacturer); instrument_type 1:N asset; instrument_type N:M supplier via bridge `instrument_type_supplier`; "
         "asset 1:1 active calibration_plan; asset 1:N calibration_event; calibration_event 0..1:1 certificate; calibration_event 1:N work_order "
         "(CALIBRATION, CORRECTIVE_ACTION, IMPACT_ASSESSMENT); asset 1:N production_use; asset 1:N emergency_extension; asset 1:N alert / audit_record. "
         "Ground truth lives outside the schema (`ground_truth/`).", ""]
    for t, fs in TABLES.items():
        L += [f"## {t}", "", "| field | type | required | allowed values / units | unique | validation rule |", "|---|---|---|---|---|---|"]
        for n, ty, rq, k, note in fs:
            if k.startswith("ENUM:"): allowed = k[5:].replace("|", ", ")
            elif k.startswith("UNIT:"): allowed = "unit: " + k[5:]
            elif "FK" in k: allowed = "FK -> " + k.split(":", 1)[1]
            else: allowed = ""
            uniq = "Y" if ((k == "PK") or (t, n) in UNIQUE) else ("composite" if k.startswith("PKFK") else "")
            L.append(f"| {n} | {ty} | {rq} | {allowed} | {uniq} | {note} |")
        L.append("")
    L += ["## ground_truth (separate file, never joined into inputs)", "", "| field | meaning |", "|---|---|", "| issue_id | GT-NNNNNN |",
          "| issue_type | " + ", ".join(ISSUE_TYPES) + " |", "| entity_type / entity_id / asset_id | offending record |",
          "| origin | NATURAL (emerged from generation rules) or INJECTED (deliberate edge case) |",
          "| expected_decision | status the rules engine must assign to a use event, or `FLAG` for record-level anomalies |", "| description | human readable |", ""]
    return "\n".join(L)

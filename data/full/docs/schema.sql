CREATE TABLE supplier (
  supplier_id TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  iso17025_accredited INTEGER NOT NULL,
  country TEXT NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY (supplier_id),
  UNIQUE (name)
);
CREATE TABLE instrument_type (
  type_id TEXT NOT NULL,
  name TEXT NOT NULL,
  measurand TEXT NOT NULL,
  unit TEXT NOT NULL,
  default_interval_days INTEGER NOT NULL,
  tolerance_pct REAL NOT NULL,
  criticality TEXT NOT NULL,
  prohibit_use_when_overdue INTEGER NOT NULL,
  max_extension_days INTEGER NOT NULL,
  PRIMARY KEY (type_id)
);
CREATE TABLE instrument_type_supplier (
  type_id TEXT NOT NULL,
  supplier_id TEXT NOT NULL,
  approved_from TEXT NOT NULL,
  PRIMARY KEY (type_id, supplier_id),
  FOREIGN KEY (type_id) REFERENCES instrument_type(type_id),
  FOREIGN KEY (supplier_id) REFERENCES supplier(supplier_id)
);
CREATE TABLE asset (
  asset_id TEXT NOT NULL,
  serial_number TEXT NOT NULL,
  name TEXT NOT NULL,
  type_id TEXT NOT NULL,
  manufacturer_id TEXT NOT NULL,
  location TEXT NOT NULL,
  commissioned_date TEXT NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY (asset_id),
  FOREIGN KEY (type_id) REFERENCES instrument_type(type_id),
  FOREIGN KEY (manufacturer_id) REFERENCES supplier(supplier_id),
  UNIQUE (serial_number)
);
CREATE TABLE calibration_plan (
  plan_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  interval_days INTEGER NOT NULL,
  tolerance_pct REAL NOT NULL,
  reference_value REAL NOT NULL,
  unit TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  status TEXT NOT NULL,
  PRIMARY KEY (plan_id),
  FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);
CREATE TABLE emergency_extension (
  extension_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  plan_id TEXT NOT NULL,
  due_date_original TEXT NOT NULL,
  extended_until TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  approved_on TEXT NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY (extension_id),
  FOREIGN KEY (asset_id) REFERENCES asset(asset_id),
  FOREIGN KEY (plan_id) REFERENCES calibration_plan(plan_id)
);
CREATE TABLE calibration_event (
  calibration_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  plan_id TEXT NOT NULL,
  lab_supplier_id TEXT NOT NULL,
  performed_date TEXT NOT NULL,
  performed_by TEXT NOT NULL,
  reference_value REAL NOT NULL,
  measured_value REAL NOT NULL,
  unit TEXT NOT NULL,
  tolerance_pct REAL NOT NULL,
  deviation_pct REAL NOT NULL,
  result TEXT NOT NULL,
  interval_days_applied INTEGER NOT NULL,
  next_due_date TEXT NOT NULL,
  days_late INTEGER NOT NULL,
  emergency_extension_id TEXT,
  status TEXT NOT NULL,
  PRIMARY KEY (calibration_id),
  FOREIGN KEY (asset_id) REFERENCES asset(asset_id),
  FOREIGN KEY (plan_id) REFERENCES calibration_plan(plan_id),
  FOREIGN KEY (lab_supplier_id) REFERENCES supplier(supplier_id),
  FOREIGN KEY (emergency_extension_id) REFERENCES emergency_extension(extension_id)
);
CREATE TABLE certificate (
  cert_id TEXT NOT NULL,
  calibration_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  certificate_number TEXT NOT NULL,
  lab_supplier_id TEXT NOT NULL,
  issued_date TEXT NOT NULL,
  valid_until TEXT NOT NULL,
  result TEXT NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY (cert_id),
  FOREIGN KEY (calibration_id) REFERENCES calibration_event(calibration_id),
  FOREIGN KEY (asset_id) REFERENCES asset(asset_id),
  FOREIGN KEY (lab_supplier_id) REFERENCES supplier(supplier_id),
  UNIQUE (calibration_id),
  UNIQUE (certificate_number)
);
CREATE TABLE work_order (
  wo_id TEXT NOT NULL,
  wo_type TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  calibration_id TEXT NOT NULL,
  status TEXT NOT NULL,
  assigned_role TEXT NOT NULL,
  opened_date TEXT NOT NULL,
  due_date TEXT NOT NULL,
  closed_date TEXT,
  downtime_hours REAL NOT NULL,
  affected_use_count INTEGER,
  PRIMARY KEY (wo_id),
  FOREIGN KEY (asset_id) REFERENCES asset(asset_id),
  FOREIGN KEY (calibration_id) REFERENCES calibration_event(calibration_id)
);
CREATE TABLE production_use (
  use_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  used_at TEXT NOT NULL,
  production_line TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  operator_id TEXT NOT NULL,
  duration_min INTEGER NOT NULL,
  compliance_status TEXT NOT NULL,
  calibration_id TEXT,
  exception_id TEXT,
  PRIMARY KEY (use_id),
  FOREIGN KEY (asset_id) REFERENCES asset(asset_id),
  FOREIGN KEY (calibration_id) REFERENCES calibration_event(calibration_id),
  FOREIGN KEY (exception_id) REFERENCES emergency_extension(extension_id)
);
CREATE TABLE alert (
  alert_id TEXT NOT NULL,
  alert_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  raised_at TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL,
  PRIMARY KEY (alert_id),
  FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);
CREATE TABLE audit_record (
  audit_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  action TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT,
  actor TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  details TEXT,
  PRIMARY KEY (audit_id),
  FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);
CREATE INDEX ix_use_asset ON production_use(asset_id, used_at);
CREATE INDEX ix_use_status ON production_use(compliance_status);
CREATE INDEX ix_cal_asset ON calibration_event(asset_id, performed_date);
CREATE INDEX ix_wo_asset ON work_order(asset_id);
CREATE INDEX ix_alert_asset ON alert(asset_id);
CREATE INDEX ix_audit_asset ON audit_record(asset_id);
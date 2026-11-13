"""Independent detector: derives anomaly findings purely from stored records (no ground-truth access)."""
from .rules import Ruleset, add_days

USE_MAP = {"PROHIBITED_OVERDUE": "EXPIRED_USE_NO_EXCEPTION", "PROHIBITED_QUARANTINE": "USE_WHILE_QUARANTINED",
           "ADVISORY_OVERDUE": "OVERDUE_USE_NONBLOCKING", "COMPLIANT_EXTENSION": "EXTENSION_USE", "PROHIBITED_NO_CALIBRATION": "EXPIRED_USE_NO_EXCEPTION"}

def findings(t, rs=None):
    rs = rs or Ruleset(t)
    out = []  # (issue_type, entity_type, entity_id, asset_id)
    for u in t["production_use"]:
        d = u["used_at"][:10]
        st, _, _, due = rs.evaluate(u["asset_id"], d)
        it = USE_MAP.get(st)
        if st == "COMPLIANT" and d == due: it = "BOUNDARY_DUE_DATE_USE"
        if it: out.append((it, "production_use", u["use_id"], u["asset_id"]))
    ev = {e["calibration_id"]: e for e in t["calibration_event"]}
    for e in ev.values():
        if e["next_due_date"] != add_days(e["performed_date"], rs.interval[e["asset_id"]]):
            out.append(("DUE_DATE_INCONSISTENT", "calibration_event", e["calibration_id"], e["asset_id"]))
    certs = {c["calibration_id"] for c in t["certificate"]}
    for c in t["certificate"]:
        if c["asset_id"] != ev[c["calibration_id"]]["asset_id"]:
            out.append(("CERT_ASSET_MISMATCH", "certificate", c["cert_id"], ev[c["calibration_id"]]["asset_id"]))
    ia = {w["calibration_id"] for w in t["work_order"] if w["wo_type"] == "IMPACT_ASSESSMENT"}
    for cid, e in ev.items():
        if cid not in certs: out.append(("MISSING_CERTIFICATE", "calibration_event", cid, e["asset_id"]))
        if e["result"] == "FAIL" and cid not in ia: out.append(("IMPACT_ASSESSMENT_MISSING", "calibration_event", cid, e["asset_id"]))
    return out

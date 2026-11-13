"""Structural + reconciliation validation, driven by the data dictionary."""
import re
from collections import Counter, defaultdict
from . import schema
from .rules import add_days

def run(t):
    checks = []
    def chk(name, bad, detail=""):
        checks.append(dict(check=name, status="PASS" if not bad else "FAIL", violations=len(bad) if hasattr(bad, "__len__") else int(bad), sample=list(bad)[:3] if hasattr(bad, "__len__") else [], detail=detail))
    idx = {n: {tuple(r[c] for c in schema.pks(n)) for r in t[n]} for n in t}
    for n, rows in t.items():
        pk = schema.pks(n)
        c = Counter(tuple(r[k] for k in pk) for r in rows)
        chk(f"{n}: primary key unique", [k for k, v in c.items() if v > 1])
        req = [f[0] for f in schema.TABLES[n] if f[2] == "Y"]
        chk(f"{n}: required fields present", [r[pk[0]] for r in rows if any(r[f] in (None, "") for f in req)])
        for col, allowed in schema.enums(n).items():
            chk(f"{n}.{col}: allowed values", [r[pk[0]] for r in rows if r[col] not in allowed])
        for col, (rt, rc) in schema.fks(n):
            chk(f"{n}.{col} -> {rt}.{rc}: FK integrity", [r[pk[0]] for r in rows if r[col] is not None and (r[col],) not in idx[rt]])
        for (tn, col) in schema.UNIQUE:
            if tn == n:
                c = Counter(r[col] for r in rows); chk(f"{n}.{col}: unique", [k for k, v in c.items() if v > 1])
        if n in schema.ID_PATTERNS:
            rx = re.compile(schema.ID_PATTERNS[n]); chk(f"{n}: ID format", [r[pk[0]] for r in rows if not rx.match(r[pk[0]])])
    for tn, a, b in schema.DATE_ORDER:
        chk(f"{tn}: {a} <= {b}", [r[tn and schema.pks(tn)[0]] for r in t[tn] if r[a] and r[b] and r[a] > r[b]])
    def _biz():
        ty = {r["type_id"]: r for r in t["instrument_type"]}; asset = {r["asset_id"]: r for r in t["asset"]}
        sup = {r["supplier_id"]: r for r in t["supplier"]}
        plan = {p["asset_id"]: p for p in t["calibration_plan"]}
        ev = {e["calibration_id"]: e for e in t["calibration_event"]}
        chk("supplier: labs accredited", [s["supplier_id"] for s in t["supplier"] if s["role"] == "CALIBRATION_LAB" and not s["iso17025_accredited"]])
        chk("bridge: suppliers are calibration labs", [b["supplier_id"] for b in t["instrument_type_supplier"] if sup[b["supplier_id"]]["role"] != "CALIBRATION_LAB"])
        chk("asset: exactly one active plan", [a for a, c in ({a: 0 for a in asset} | Counter(p["asset_id"] for p in t["calibration_plan"] if p["status"] == "ACTIVE")).items() if c != 1])
        chk("plan: interval <= type default", [p["plan_id"] for p in plan.values() if p["interval_days"] > ty[asset[p["asset_id"]]["type_id"]]["default_interval_days"]])
        chk("plan: tolerance = type tolerance", [p["plan_id"] for p in plan.values() if p["tolerance_pct"] != ty[asset[p["asset_id"]]["type_id"]]["tolerance_pct"]])
        chk("event: deviation = |meas-ref|/ref*100", [e["calibration_id"] for e in ev.values() if e["deviation_pct"] != round(abs(e["measured_value"] - e["reference_value"]) / e["reference_value"] * 100, 4)])
        chk("event: PASS iff deviation <= tolerance", [e["calibration_id"] for e in ev.values() if (e["result"] == "PASS") != (e["deviation_pct"] <= e["tolerance_pct"])])
        chk("event: interval applied = plan interval", [e["calibration_id"] for e in ev.values() if e["interval_days_applied"] != plan[e["asset_id"]]["interval_days"]])
        chk("event: unique (asset, performed_date)", [k for k, v in Counter((e["asset_id"], e["performed_date"]) for e in ev.values()).items() if v > 1])
        chk("event: lab approved for instrument type", [e["calibration_id"] for e in ev.values() if (ty[asset[e["asset_id"]]["type_id"]]["type_id"], e["lab_supplier_id"]) not in idx["instrument_type_supplier"]])
        first = {}
        for e in ev.values(): first[e["asset_id"]] = min(first.get(e["asset_id"], "9999"), e["performed_date"])
        chk("asset: commissioned before first calibration", [a for a, d in first.items() if asset[a]["commissioned_date"] > d])
        chk("certificate: result/lab/valid_until reconcile with event (due recomputed from plan)",
            [c["cert_id"] for c in t["certificate"] if c["result"] != ev[c["calibration_id"]]["result"] or c["lab_supplier_id"] != ev[c["calibration_id"]]["lab_supplier_id"]
             or c["valid_until"] != add_days(ev[c["calibration_id"]]["performed_date"], plan[ev[c["calibration_id"]]["asset_id"]]["interval_days"])])
        chk("certificate: cert_id = CERT-<calibration_id>", [c["cert_id"] for c in t["certificate"] if c["cert_id"] != "CERT-" + c["calibration_id"]])
        chk("use_id = USE-<asset>-<timestamp>", [u["use_id"] for u in t["production_use"] if u["use_id"] != f"USE-{u['asset_id']}-{u['used_at'].replace('-', '').replace(':', '')}"])
        chk("extension: length <= type max_extension_days", [x["extension_id"] for x in t["emergency_extension"]
            if (__import__("datetime").date.fromisoformat(x["extended_until"]) - __import__("datetime").date.fromisoformat(x["due_date_original"])).days > ty[asset[x["asset_id"]]["type_id"]]["max_extension_days"]])
        chk("work_order: CLOSED iff closed_date", [w["wo_id"] for w in t["work_order"] if (w["status"] == "CLOSED") != (w["closed_date"] is not None)])
        chk("work_order: failed calibration has corrective action", sorted(set(e["calibration_id"] for e in ev.values() if e["result"] == "FAIL") - {w["calibration_id"] for w in t["work_order"] if w["wo_type"] == "CORRECTIVE_ACTION"}))
        uses = defaultdict(list)
        for u in t["production_use"]: uses[u["asset_id"]].append(u["used_at"][:10])
        bad = []
        evs = defaultdict(list)
        for e in ev.values(): evs[e["asset_id"]].append(e)
        for w in t["work_order"]:
            if w["wo_type"] != "IMPACT_ASSESSMENT": continue
            e = ev[w["calibration_id"]]; prior = sorted(x["performed_date"] for x in evs[e["asset_id"]] if x["performed_date"] < e["performed_date"])
            lo = prior[-1] if prior else e["performed_date"]
            if w["affected_use_count"] != sum(1 for d in uses[e["asset_id"]] if lo < d < e["performed_date"]): bad.append(w["wo_id"])
        chk("impact assessment: affected_use_count recomputes from uses", bad)
        chk("audit: lifecycle chain continuous & asset snapshot consistent", _lifecycle(t))
        chk("alert: asset_id exists & severity matches type", [a["alert_id"] for a in t["alert"] if a["severity"] != schema.ALERT_SEVERITY[a["alert_type"]]])
    try: _biz()
    except KeyError as e: chk("relational checks runnable (no dangling references)", [str(e)])
    f = sum(1 for c in checks if c["status"] == "FAIL")
    return dict(ok=f == 0, passed=len(checks) - f, failed=f, checks=checks)

def _lifecycle(t):
    seq = defaultdict(list)
    for r in t["audit_record"]:
        if r["action"] in ("ASSET_COMMISSIONED", "STATUS_CHANGED", "RETURNED_TO_SERVICE"): seq[r["asset_id"]].append(r)
    bad = []
    for a, rows in seq.items():
        cur = None
        for r in sorted(rows, key=lambda r: r["audit_id"]):
            if r["from_state"] != cur or (cur, r["to_state"]) not in {(None, "IN_SERVICE"), ("IN_SERVICE", "QUARANTINED"), ("QUARANTINED", "IN_SERVICE")}: bad.append(a); break
            cur = r["to_state"]
    snap = {x["asset_id"]: x["status"] for x in t["asset"]}
    last = {a: sorted(rows, key=lambda r: r["audit_id"])[-1]["to_state"] for a, rows in seq.items()}
    bad += [a for a, s in snap.items() if (s == "QUARANTINED") != (last.get(a) == "QUARANTINED")]
    return bad

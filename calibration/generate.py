"""Deterministic synthetic data generator (same code for starter and full scale).
Usage: python -m calibration.generate --preset full --out data/full"""
import argparse, bisect, csv, hashlib, itertools, json, os, random, shutil, sqlite3
from datetime import date, datetime, timedelta
from . import schema, rules, detect, validate, evaluate

START, END = date(2026, 1, 1), date(2026, 12, 31)
PRESETS = {"starter": (200, 500, 10000), "full": (2000, 5000, 100000)}
def D(off): return (START + timedelta(days=off)).isoformat()

LABS = ["Apex Metrology Labs", "Northfield Calibration", "Meridian Test & Cal", "Sterling Standards Lab",
        "Orion Precision Cal", "Harbor Metrology", "Keystone Calibration Services", "Vertex Measurement Lab"]
MFRS = ["Fortis Instruments", "Gaugeworks", "Precisa Devices", "Technomet", "Alder Sensors", "Brightline Controls"]
COUNTRIES = ["Germany", "USA", "India", "UK", "Japan", "Switzerland"]
# name, measurand, unit, default interval, tolerance %, criticality, prohibit-when-overdue, max extension days
TYPES = [("Pressure Gauge", "pressure", "bar", 180, 1.0, "HIGH", 1, 14), ("Digital Thermometer", "temperature", "degC", 365, 0.5, "MEDIUM", 1, 10),
         ("Torque Wrench", "torque", "N.m", 180, 4.0, "HIGH", 1, 7), ("Flow Meter", "flow", "L/min", 365, 2.0, "HIGH", 1, 14),
         ("Load Cell", "force", "kg", 365, 0.5, "HIGH", 1, 10), ("Vernier Caliper", "length", "mm", 365, 0.5, "LOW", 0, 0),
         ("Micrometer", "length", "mm", 365, 0.3, "MEDIUM", 1, 7), ("pH Meter", "acidity", "pH", 180, 1.5, "MEDIUM", 1, 5),
         ("Multimeter", "voltage", "V", 365, 1.0, "LOW", 0, 0), ("Humidity Sensor", "humidity", "%RH", 365, 2.0, "MEDIUM", 0, 0),
         ("Conductivity Meter", "conductivity", "uS/cm", 180, 2.0, "MEDIUM", 1, 5), ("Analytical Balance", "mass", "g", 365, 0.1, "HIGH", 1, 10)]
AREAS = ["Assembly", "Paint Shop", "Machining", "Quality Lab", "Packaging", "Utilities", "Test Bay"]
ACCEPT = {"V": 1.0, "E": 1.0, "O_block": 0.05, "O_warn": 0.7, "Q": 0.04}

def build(n_assets, n_events, n_uses, seed):
    R = random.Random(seed)
    t = {k: [] for k in schema.TABLES}
    gt = []
    def G(it, et, eid, aid, origin, dec, desc): gt.append(dict(issue_type=it, entity_type=et, entity_id=eid, asset_id=aid, origin=origin, expected_decision=dec, description=desc))
    for i, n in enumerate(LABS + MFRS, 1):
        lab = i <= len(LABS)
        t["supplier"].append(dict(supplier_id=f"SUP-{i:03d}", name=n, role="CALIBRATION_LAB" if lab else "MANUFACTURER",
                                  iso17025_accredited=int(lab), country=COUNTRIES[i % 6], status="ACTIVE"))
    labs = [s["supplier_id"] for s in t["supplier"] if s["role"] == "CALIBRATION_LAB"]
    mfrs = [s["supplier_id"] for s in t["supplier"] if s["role"] == "MANUFACTURER"]
    types = []
    for i, (n, m, u, iv, tol, cr, pr, mx) in enumerate(TYPES, 1):
        r = dict(type_id=f"ITY-{i:03d}", name=n, measurand=m, unit=u, default_interval_days=iv, tolerance_pct=tol, criticality=cr,
                 prohibit_use_when_overdue=pr, max_extension_days=mx)
        t["instrument_type"].append(r); types.append(r)
        for l in R.sample(labs, 4): t["instrument_type_supplier"].append(dict(type_id=r["type_id"], supplier_id=l, approved_from="2025-01-01"))
    # --- how many calibrations per asset (sum exactly n_events)
    ty_of = [R.choice(types) for _ in range(n_assets)]
    mins = [1 if x["default_interval_days"] == 365 else 2 for x in ty_of]
    if not (sum(mins) <= n_events <= 4 * n_assets): raise ValueError("events must be between %d and %d for %d assets" % (sum(mins), 4 * n_assets, n_assets))
    ns = [max(m, R.choices([1, 2, 3, 4], [.12, .38, .32, .18])[0]) for m in mins]
    while sum(ns) < n_events:
        i = R.randrange(n_assets)
        if ns[i] < 4: ns[i] += 1
    while sum(ns) > n_events:
        i = R.randrange(n_assets)
        if ns[i] > mins[i]: ns[i] -= 1
    info, evs, exts = {}, [], []
    for i in range(n_assets):
        aid, ty, n = f"AST-{i + 1:06d}", ty_of[i], ns[i]
        iv = {1: 365, 2: 180, 3: 120, 4: 90}[n]
        t["asset"].append(dict(asset_id=aid, serial_number=f"SN{R.randint(10**7, 10**8 - 1)}-{i + 1:05d}", name=f"{ty['name']} {i + 1:04d}",
                               type_id=ty["type_id"], manufacturer_id=R.choice(mfrs), location=R.choice(AREAS),
                               commissioned_date=(START - timedelta(days=R.randint(30, 1500))).isoformat(), status="IN_SERVICE"))
        ref = round(R.uniform(10, 500), 2)
        pid = f"PLN-{aid}"
        t["calibration_plan"].append(dict(plan_id=pid, asset_id=aid, interval_days=iv, tolerance_pct=ty["tolerance_pct"], reference_value=ref,
                                          unit=ty["unit"], effective_from="2026-01-01", effective_to=None, status="ACTIVE"))
        first = int((364 - (n - 1) * iv) * R.random() ** 1.5)
        offs, late = [first], [0]
        for j in range(1, n):
            due = offs[-1] + iv
            maxd = 364 - (n - 1 - j) * iv - due
            if R.random() < 0.15 and maxd >= 2: d = R.randint(2, min(maxd, 35))
            else: d = -R.randint(0, 5)
            offs.append(due + d); late.append(max(d, 0))
        chain = []
        approved = [l for l in labs if any(b["type_id"] == ty["type_id"] and b["supplier_id"] == l for b in t["instrument_type_supplier"])]
        for j in range(n):
            tol = ty["tolerance_pct"]
            dev = tol * (R.uniform(1.05, 2.2) if R.random() < 0.06 else R.uniform(0.02, 0.95))
            meas = round(ref * (1 + R.choice((-1, 1)) * dev / 100), 4)
            devc = round(abs(meas - ref) / ref * 100, 4)
            res = "PASS" if devc <= tol else "FAIL"
            e = dict(aid=aid, pid=pid, off=offs[j], late=late[j], iv=iv, ref=ref, meas=meas, dev=devc, tol=tol, res=res, unit=ty["unit"],
                     lab=R.choice(approved), by=f"{R.choice(['MENG', 'QENG'])}-{R.randint(1, 25):03d}", ext=None,
                     qclose=offs[j] + R.randint(2, 6) if res == "FAIL" else None, j=j)
            chain.append(e); evs.append(e)
        for j in range(n):
            due, nxt = offs[j] + iv, (offs[j + 1] if j + 1 < n else 365)
            if due < nxt - 1 and ty["max_extension_days"] > 0 and R.random() < 0.35:
                x = dict(aid=aid, pid=pid, due=due, days=R.randint(3, ty["max_extension_days"]))
                exts.append(x); chain[j]["xo"] = x
                if j + 1 < n: chain[j + 1]["ext"] = x
        segs = []
        def seg(a, b, k, f=0):
            b = min(b, 364)
            if a <= b: segs.append((a, b, k, f))
        for j, e in enumerate(chain):
            due, nxt = offs[j] + iv, (offs[j + 1] if j + 1 < n else 365)
            s = e["off"] + 1
            if e["res"] == "FAIL": seg(s, min(e["qclose"], nxt - 1), "Q"); s = e["qclose"] + 1
            seg(s, min(due, nxt - 1), "V", 1 if due <= nxt - 1 else 0)
            if due < nxt - 1:
                o = due + 1
                if "xo" in e: eend = min(due + e["xo"]["days"], nxt - 1); seg(o, eend, "E"); o = eend + 1
                seg(o, nxt - 1, "O")
        info[aid] = dict(ty=ty, iv=iv, chain=chain, segs=segs, weight=R.lognormvariate(0, 0.8), block=ty["prohibit_use_when_overdue"] == 1)
    # --- extensions
    for k, x in enumerate(sorted(exts, key=lambda x: (x["due"], x["aid"])), 1):
        x["id"] = f"EXT-2026-{k:06d}"
        t["emergency_extension"].append(dict(extension_id=x["id"], asset_id=x["aid"], plan_id=x["pid"], due_date_original=D(x["due"]),
            extended_until=D(x["due"] + x["days"]), approved_by=f"QENG-{R.randint(1, 25):03d}", approved_on=D(x["due"]),
            reason=R.choice(["PRODUCTION_CRITICAL", "LAB_BACKLOG", "SPARE_UNAVAILABLE"]), status="ACTIVE" if x["due"] + x["days"] >= 364 else "EXPIRED"))
    # --- calibration events
    for k, e in enumerate(sorted(evs, key=lambda e: (e["off"], e["aid"])), 1):
        e["cid"] = f"CAL-{e['aid']}-2026-{k:06d}"
        t["calibration_event"].append(dict(calibration_id=e["cid"], asset_id=e["aid"], plan_id=e["pid"], lab_supplier_id=e["lab"],
            performed_date=D(e["off"]), performed_by=e["by"], reference_value=e["ref"], measured_value=e["meas"], unit=e["unit"],
            tolerance_pct=e["tol"], deviation_pct=e["dev"], result=e["res"], interval_days_applied=e["iv"],
            next_due_date=D(e["off"] + e["iv"]), days_late=e["late"], emergency_extension_id=e["ext"]["id"] if e["ext"] else None, status="COMPLETED"))
    ev_rows = {r["calibration_id"]: r for r in t["calibration_event"]}
    fails = [e for e in evs if e["res"] == "FAIL"]
    # --- injected edge case 1: due date inconsistent with plan
    for e in R.sample(evs, max(3, round(n_events * 0.005))):
        r = ev_rows[e["cid"]]; shift = R.choice((-1, 1)) * R.randint(5, 30)
        r["next_due_date"] = rules.add_days(r["next_due_date"], shift)
        G("DUE_DATE_INCONSISTENT", "calibration_event", e["cid"], e["aid"], "INJECTED", "FLAG", f"next_due_date shifted {shift:+d}d from performed+interval")
    # --- certificates (with gaps)
    cn = itertools.count(1)
    gaps = {e["cid"] for e in R.sample(evs, max(2, round(n_events * 0.02)))}
    for e in sorted(evs, key=lambda e: e["cid"]):
        if e["cid"] in gaps:
            G("MISSING_CERTIFICATE", "calibration_event", e["cid"], e["aid"], "NATURAL", "FLAG", "certificate gap: no certificate issued"); continue
        t["certificate"].append(dict(cert_id=f"CERT-{e['cid']}", calibration_id=e["cid"], asset_id=e["aid"], certificate_number=f"{e['lab'][4:]}-2026-{next(cn):06d}",
            lab_supplier_id=e["lab"], issued_date=D(min(e["off"] + R.randint(0, 5), 364)), valid_until=D(e["off"] + e["iv"]), result=e["res"], status="VALID"))
    last = {}
    for c in sorted(t["certificate"], key=lambda c: (c["asset_id"], c["issued_date"])): last[c["asset_id"]] = c
    for c in t["certificate"]:
        c["status"] = "SUPERSEDED" if last[c["asset_id"]] is not c else ("VALID" if c["valid_until"] >= END.isoformat() else "EXPIRED")
    # --- injected edge case 2: certificate refers to another asset
    aids = list(info)
    for c in R.sample(t["certificate"], max(3, round(n_events * 0.004))):
        c["asset_id"] = R.choice([a for a in aids if a != c["asset_id"]])
        G("CERT_ASSET_MISMATCH", "certificate", c["cert_id"], ev_rows[c["calibration_id"]]["asset_id"], "INJECTED", "FLAG", f"certificate asset_id replaced with {c['asset_id']}")
    # --- work orders; injected edge case 3: failed calibration without impact assessment
    skip_ia = {e["cid"] for e in R.sample(fails, min(len(fails), max(2, round(len(fails) * 0.07))))} if fails else set()
    wos = []
    for e in evs:
        op = e["off"] - R.randint(3, 14)
        wos.append(dict(wo_type="CALIBRATION", asset_id=e["aid"], calibration_id=e["cid"], status="CLOSED", assigned_role="MAINTENANCE_ENGINEER",
                        opened_date=D(op), due_date=D(e["off"]), closed_date=D(e["off"]), downtime_hours=round(R.uniform(0.5, 4), 1), affected_use_count=None, _k=0))
        if e["res"] == "FAIL":
            qc = e["qclose"]
            wos.append(dict(wo_type="CORRECTIVE_ACTION", asset_id=e["aid"], calibration_id=e["cid"], status="CLOSED" if qc <= 364 else "OPEN",
                            assigned_role="MAINTENANCE_ENGINEER", opened_date=D(e["off"]), due_date=D(e["off"] + 5), closed_date=D(qc) if qc <= 364 else None,
                            downtime_hours=float((min(qc, 364) - e["off"]) * 24), affected_use_count=None, _k=1))
            if e["cid"] in skip_ia:
                G("IMPACT_ASSESSMENT_MISSING", "calibration_event", e["cid"], e["aid"], "INJECTED", "FLAG", "failed calibration has no impact assessment work order")
            else:
                o = min(e["off"] + 1, 364); c = o + R.randint(2, 7)
                wos.append(dict(wo_type="IMPACT_ASSESSMENT", asset_id=e["aid"], calibration_id=e["cid"], status="CLOSED" if c <= 364 else "OPEN",
                                assigned_role="QUALITY_ENGINEER", opened_date=D(o), due_date=D(o + 7), closed_date=D(c) if c <= 364 else None,
                                downtime_hours=0.0, affected_use_count=0, _k=2))
    for k, w in enumerate(sorted(wos, key=lambda w: (w["opened_date"], w["_k"], w["calibration_id"])), 1):
        w["wo_id"] = f"WO-2026-{k:06d}"; w.pop("_k"); t["work_order"].append(w)
    t["work_order"].sort(key=lambda w: w["wo_id"])
    rs = rules.Ruleset(t)
    # --- production use
    ids = list(info)
    cum = list(itertools.accumulate(info[a]["weight"] * sum(b - a_ + 1 for a_, b, _, _ in info[a]["segs"]) for a in ids))
    seen, uses = set(), []
    def add(aid, off, kind, bnd, origin):
        sec = R.randint(6 * 3600, 22 * 3600 - 1); ts = datetime(2026, 1, 1) + timedelta(days=off, seconds=sec)
        uid = f"USE-{aid}-{ts:%Y%m%dT%H%M%S}"
        while uid in seen: ts += timedelta(seconds=1); uid = f"USE-{aid}-{ts:%Y%m%dT%H%M%S}"
        seen.add(uid); uses.append((uid, aid, ts, kind, bnd, origin))
    n_inj, n_bnd = max(5, round(n_uses * 0.0005)), max(5, round(n_uses * 0.0004))
    ovs = [(a, s) for a in ids if info[a]["block"] for s in info[a]["segs"] if s[2] == "O"]
    vb = [(a, s) for a in ids for s in info[a]["segs"] if s[2] == "V" and s[3]]
    if not ovs: n_inj = 0
    if not vb: n_bnd = 0
    for _ in range(n_inj):
        a, s = R.choice(ovs); add(a, s[0] if R.random() < .5 else R.randint(s[0], s[1]), "O", False, "INJECTED")
    for _ in range(n_bnd):
        a, s = R.choice(vb); add(a, s[1], "V", True, "INJECTED")
    while len(uses) < n_uses:
        a = ids[min(bisect.bisect_left(cum, R.random() * cum[-1]), len(ids) - 1)]
        ss = info[a]["segs"]; tot = sum(b - x + 1 for x, b, _, _ in ss)
        if not tot: continue
        r = R.randrange(tot)
        for s in ss:
            if r < s[1] - s[0] + 1: off = s[0] + r; break
            r -= s[1] - s[0] + 1
        k = s[2] if s[2] != "O" else ("O_block" if info[a]["block"] else "O_warn")
        if R.random() < ACCEPT[k]: add(a, off, s[2], s[2] == "V" and s[3] == 1 and off == s[1], "NATURAL")
    uses.sort(key=lambda u: (u[2], u[1]))
    uoffs = {}
    for uid, aid, ts, kind, bnd, origin in uses:
        d = ts.date().isoformat(); st, cid, xid, _ = rs.evaluate(aid, d)
        t["production_use"].append(dict(use_id=uid, asset_id=aid, used_at=ts.isoformat(), production_line=f"LINE-{R.randint(1, 12):02d}",
            batch_id=f"BATCH-{ts:%Y%m%d}-{R.randint(1, 40):03d}", operator_id=f"OPR-{R.randint(1, 60):03d}", duration_min=R.randint(5, 240),
            compliance_status=st, calibration_id=cid, exception_id=xid))
        uoffs.setdefault(aid, []).append((ts.date() - START).days)
        lab = {"O": ("EXPIRED_USE_NO_EXCEPTION", "PROHIBITED_OVERDUE") if info[aid]["block"] else ("OVERDUE_USE_NONBLOCKING", "ADVISORY_OVERDUE"),
               "Q": ("USE_WHILE_QUARANTINED", "PROHIBITED_QUARANTINE"), "E": ("EXTENSION_USE", "COMPLIANT_EXTENSION")}.get(kind)
        if bnd: lab = ("BOUNDARY_DUE_DATE_USE", "COMPLIANT")
        if lab: G(lab[0], "production_use", uid, aid, origin, lab[1], f"generator window={kind}")
    # derived: impact assessment affected_use_count = uses since previous calibration (exclusive) until failed calibration
    for w in t["work_order"]:
        if w["wo_type"] == "IMPACT_ASSESSMENT":
            ch = info[w["asset_id"]]["chain"]; e = next(c for c in ch if c["cid"] == w["calibration_id"])
            lo = ch[e["j"] - 1]["off"] if e["j"] else e["off"]
            lst = sorted(uoffs.get(w["asset_id"], [])); w["affected_use_count"] = bisect.bisect_left(lst, e["off"]) - bisect.bisect_right(lst, lo)
    # asset status snapshot
    for a in t["asset"]:
        st = rs.evaluate(a["asset_id"], END.isoformat())[0]
        a["status"] = "QUARANTINED" if st == "PROHIBITED_QUARANTINE" else ("IN_SERVICE" if st.startswith("COMPLIANT") else "OVERDUE")
    # alerts from the independent detector
    msgs = {"EXPIRED_USE_NO_EXCEPTION": "Overdue instrument used with no emergency extension", "USE_WHILE_QUARANTINED": "Instrument used while quarantined after failed calibration",
            "OVERDUE_USE_NONBLOCKING": "Overdue instrument used (policy is advisory)", "DUE_DATE_INCONSISTENT": "Stored due date differs from performed date + plan interval",
            "CERT_ASSET_MISMATCH": "Certificate references a different asset than its calibration", "MISSING_CERTIFICATE": "Calibration has no certificate",
            "IMPACT_ASSESSMENT_MISSING": "Failed calibration has no impact assessment"}
    ur = {u["use_id"]: u for u in t["production_use"]}
    al = []
    for it, et, eid, aid in detect.findings(t, rs):
        if it not in msgs: continue
        at = ur[eid]["used_at"] if et == "production_use" else ev_rows.get(eid, {}).get("performed_date", "2026-01-01") + "T08:00:00"
        if et == "certificate": at = ev_rows["CAL" + eid[8:]]["performed_date"] + "T08:00:00"
        al.append((at, eid, it, et, aid))
    for k, (at, eid, it, et, aid) in enumerate(sorted(al), 1):
        t["alert"].append(dict(alert_id=f"ALT-2026-{k:06d}", alert_type=it, severity=schema.ALERT_SEVERITY[it], asset_id=aid, entity_type=et, entity_id=eid,
            raised_at=at, status="ACKNOWLEDGED" if at < "2026-11-01" and schema.ALERT_SEVERITY[it] != "HIGH" else "OPEN", message=msgs[it]))
    # append-only audit trail
    au = []
    def A(et, eid, aid, act, fr, to, actor, day, hms, det=None): au.append((f"{day}T{hms}", eid, act, dict(entity_type=et, entity_id=eid, asset_id=aid, action=act, from_state=fr, to_state=to, actor=actor, details=det)))
    for a in t["asset"]: A("ASSET", a["asset_id"], a["asset_id"], "ASSET_COMMISSIONED", None, "IN_SERVICE", "ADMIN-001", a["commissioned_date"], "07:00:00")
    for e in evs:
        d = D(e["off"]); A("CALIBRATION_EVENT", e["cid"], e["aid"], "CALIBRATION_COMPLETED", None, None, e["by"], d, "10:00:00", f"result={e['res']}")
        if e["res"] == "FAIL":
            A("ASSET", e["aid"], e["aid"], "STATUS_CHANGED", "IN_SERVICE", "QUARANTINED", "SYSTEM", d, "10:05:00", f"failed {e['cid']}")
            if e["qclose"] <= 364: A("ASSET", e["aid"], e["aid"], "RETURNED_TO_SERVICE", "QUARANTINED", "IN_SERVICE", "QENG-001", D(e["qclose"]), "16:05:00")
    for x in t["emergency_extension"]: A("EXTENSION", x["extension_id"], x["asset_id"], "EXTENSION_APPROVED", None, None, x["approved_by"], x["approved_on"], "11:00:00", x["reason"])
    for w in t["work_order"]:
        A("WORK_ORDER", w["wo_id"], w["asset_id"], "WO_OPENED", None, None, "SYSTEM", w["opened_date"], "07:30:00", w["wo_type"])
        if w["closed_date"]: A("WORK_ORDER", w["wo_id"], w["asset_id"], "WO_CLOSED", None, None, "SYSTEM", w["closed_date"], "16:00:00", w["wo_type"])
    for k, (at, eid, act, row) in enumerate(sorted(au, key=lambda x: (x[0], x[1], x[2])), 1):
        t["audit_record"].append(dict(audit_id=f"AUD-{k:07d}", occurred_at=at, **row))
    return t, gt

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f: h.update(f.read())
    return h.hexdigest()

def write_all(t, gt, out, formats, params):
    if os.path.exists(out): shutil.rmtree(out)
    for d in ("csv", "json", "sql", "ground_truth", "docs"): os.makedirs(os.path.join(out, d))
    gt = sorted(gt, key=lambda g: (g["issue_type"], g["entity_id"]))
    for k, g in enumerate(gt, 1): g["issue_id"] = f"GT-{k:06d}"
    sums = {}
    if "csv" in formats:
        for name in schema.TABLES:
            p = os.path.join(out, "csv", name + ".csv")
            with open(p, "w", newline="") as f:
                w = csv.DictWriter(f, schema.cols(name), lineterminator="\n"); w.writeheader()
                for r in t[name]: w.writerow({c: ("" if r[c] is None else r[c]) for c in schema.cols(name)})
            sums[f"csv/{name}.csv"] = sha(p)
    gp = os.path.join(out, "ground_truth", "ground_truth.csv")
    with open(gp, "w", newline="") as f:
        w = csv.DictWriter(f, schema.GT_FIELDS, lineterminator="\n"); w.writeheader(); w.writerows(gt)
    sums["ground_truth/ground_truth.csv"] = sha(gp)
    json.dump(gt, open(os.path.join(out, "ground_truth", "ground_truth.json"), "w"))
    if "json" in formats:
        for name in schema.TABLES: json.dump([{c: r[c] for c in schema.cols(name)} for r in t[name]], open(os.path.join(out, "json", name + ".json"), "w"))
    db = os.path.join(out, "calibration.db")
    con = sqlite3.connect(db); con.executescript(schema.ddl())
    for name in schema.TABLES:
        cs = schema.cols(name)
        con.executemany(f"INSERT INTO {name} ({','.join(cs)}) VALUES ({','.join('?' * len(cs))})", [[r[c] for c in cs] for r in t[name]])
    con.commit()
    if "sql" in formats:
        with open(os.path.join(out, "sql", "seed.sql"), "w") as f:
            for line in con.iterdump(): f.write(line + "\n")
    con.close()
    if "db" not in formats: os.remove(db)
    open(os.path.join(out, "docs", "DATA_DICTIONARY.md"), "w").write(schema.dictionary_md())
    open(os.path.join(out, "docs", "schema.sql"), "w").write(schema.ddl())
    counts = {n: len(r) for n, r in t.items()}
    V = validate.run(t); E = evaluate.run(t, gt)
    json.dump(V, open(os.path.join(out, "validation_summary.json"), "w"), indent=1)
    json.dump(E, open(os.path.join(out, "evaluation.json"), "w"), indent=1)
    json.dump(dict(generator="calibration.generate v1.0", command=params["command"], seed=params["seed"], parameters=params, as_of=END.isoformat(),
                   row_counts=counts, ground_truth_rows=len(gt), sha256=sums), open(os.path.join(out, "manifest.json"), "w"), indent=1)
    json.dump(dict(external_data_used=False, note="All data is synthetic, generated from a fixed seed. No external datasets, personal or confidential data. "
                   "Instrument classes/tolerances are plausible engineering values chosen by the author; no public dataset is redistributed."),
              open(os.path.join(out, "source_manifest.json"), "w"), indent=1)
    return counts, V, E

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", choices=PRESETS, default="full")
    ap.add_argument("--assets", type=int); ap.add_argument("--events", type=int); ap.add_argument("--uses", type=int)
    ap.add_argument("--seed", type=int, default=20261022); ap.add_argument("--out", default="data/full")
    ap.add_argument("--formats", default="csv,json,sql,db")
    a = ap.parse_args(argv)
    d = PRESETS[a.preset]
    n = (a.assets or d[0], a.events or d[1], a.uses or d[2])
    t, gt = build(*n, a.seed)
    params = dict(assets=n[0], events=n[1], uses=n[2], seed=a.seed, formats=a.formats,
                  command=f"python -m calibration.generate --assets {n[0]} --events {n[1]} --uses {n[2]} --seed {a.seed} --out {a.out}")
    counts, V, E = write_all(t, gt, a.out, a.formats.split(","), params)
    print("rows:", counts); print("validation:", V["passed"], "passed,", V["failed"], "failed"); print("detector vs ground truth:", E["summary"])

if __name__ == "__main__": main()

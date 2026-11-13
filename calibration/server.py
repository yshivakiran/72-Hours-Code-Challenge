"""Zero-dependency backend: JSON API over SQLite + static frontend.
Run: python -m calibration.server --data data/full --port 8000"""
import argparse, json, os, sqlite3, threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from . import rules, schema

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

class App:
    def __init__(self, data):
        self.dir, self.db, self.lock = data, os.path.join(data, "calibration.db"), threading.Lock()
        t = {n: self.q(f"SELECT * FROM {n}") for n in ("instrument_type", "asset", "calibration_plan", "calibration_event", "work_order", "emergency_extension")}
        self.rs = rules.Ruleset(t)

    def q(self, sql, args=()):
        con = sqlite3.connect(self.db); con.row_factory = sqlite3.Row
        try: return [dict(r) for r in con.execute(sql, args)]
        finally: con.close()

    def summary(self):
        one = lambda s: self.q(s)[0]["n"]
        return dict(
            counts=dict(assets=one("SELECT count(*) n FROM asset"), calibrations=one("SELECT count(*) n FROM calibration_event"), uses=one("SELECT count(*) n FROM production_use"),
                        open_alerts=one("SELECT count(*) n FROM alert WHERE status='OPEN'"), open_work_orders=one("SELECT count(*) n FROM work_order WHERE status='OPEN'")),
            asset_status=self.q("SELECT status k, count(*) n FROM asset GROUP BY status"),
            use_compliance=self.q("SELECT compliance_status k, count(*) n FROM production_use GROUP BY 1 ORDER BY n DESC"),
            alerts_by_type=self.q("SELECT alert_type k, severity, count(*) n FROM alert GROUP BY 1,2 ORDER BY n DESC"),
            calibration=dict(pass_rate=round(one("SELECT avg(result='PASS') n FROM calibration_event"), 4), failed=one("SELECT count(*) n FROM calibration_event WHERE result='FAIL'"),
                             late=one("SELECT count(*) n FROM calibration_event WHERE days_late>0"),
                             certificate_gaps=one("SELECT count(*) n FROM calibration_event e LEFT JOIN certificate c ON c.calibration_id=e.calibration_id WHERE c.cert_id IS NULL"),
                             failed_without_impact_assessment=one("SELECT count(*) n FROM calibration_event e WHERE result='FAIL' AND NOT EXISTS (SELECT 1 FROM work_order w WHERE w.calibration_id=e.calibration_id AND w.wo_type='IMPACT_ASSESSMENT')"),
                             extensions=one("SELECT count(*) n FROM emergency_extension")),
            downtime_hours=self.q("SELECT wo_type k, round(sum(downtime_hours),1) n FROM work_order GROUP BY 1"),
            monthly=self.q("SELECT substr(used_at,1,7) m, count(*) uses, sum(compliance_status LIKE 'PROHIBITED%') prohibited, sum(compliance_status IN ('ADVISORY_OVERDUE')) advisory FROM production_use GROUP BY 1 ORDER BY 1"))

    def assets(self, p):
        w, a = ["1=1"], []
        if p.get("q"): w.append("(a.asset_id LIKE ? OR a.name LIKE ? OR a.serial_number LIKE ?)"); a += [f"%{p['q']}%"] * 3
        if p.get("status"): w.append("a.status=?"); a.append(p["status"])
        sql = f"""SELECT a.asset_id,a.name,a.status,a.location,t.name type_name,t.prohibit_use_when_overdue blocking,pl.interval_days,
          (SELECT max(performed_date) FROM calibration_event e WHERE e.asset_id=a.asset_id) last_calibrated,
          date((SELECT max(performed_date) FROM calibration_event e WHERE e.asset_id=a.asset_id),'+'||pl.interval_days||' days') due_date,
          (SELECT count(*) FROM alert al WHERE al.asset_id=a.asset_id) alerts
          FROM asset a JOIN instrument_type t ON t.type_id=a.type_id JOIN calibration_plan pl ON pl.asset_id=a.asset_id AND pl.status='ACTIVE'
          WHERE {' AND '.join(w)} ORDER BY a.asset_id LIMIT ? OFFSET ?"""
        return self.q(sql, a + [min(int(p.get("limit", 100)), 500), int(p.get("offset", 0))])

    def asset(self, aid):
        r = self.q("SELECT a.*,t.name type_name,t.prohibit_use_when_overdue,t.max_extension_days FROM asset a JOIN instrument_type t USING(type_id) WHERE asset_id=?", (aid,))
        if not r: return None
        g = lambda s: self.q(s, (aid,))
        return dict(asset=r[0], plan=g("SELECT * FROM calibration_plan WHERE asset_id=?"),
                    calibrations=g("SELECT e.*,c.cert_id,c.certificate_number,c.asset_id cert_asset_id FROM calibration_event e LEFT JOIN certificate c USING(calibration_id) WHERE e.asset_id=? ORDER BY performed_date"),
                    work_orders=g("SELECT * FROM work_order WHERE asset_id=? ORDER BY opened_date"), extensions=g("SELECT * FROM emergency_extension WHERE asset_id=?"),
                    alerts=g("SELECT * FROM alert WHERE asset_id=? ORDER BY raised_at"), recent_uses=g("SELECT * FROM production_use WHERE asset_id=? ORDER BY used_at DESC LIMIT 25"),
                    audit=g("SELECT * FROM audit_record WHERE asset_id=? ORDER BY audit_id"))

    def check(self, aid, at):
        if aid not in self.rs.asset: return None
        st, cid, xid, due = self.rs.evaluate(aid, at[:10])
        msg = {"COMPLIANT": "Calibration valid.", "COMPLIANT_EXTENSION": "Overdue but covered by an emergency extension.", "ADVISORY_OVERDUE": "Overdue. Policy for this instrument type is advisory: use allowed with warning.",
               "PROHIBITED_OVERDUE": "Calibration overdue. Policy prohibits use until recalibrated or an emergency extension is approved.",
               "PROHIBITED_QUARANTINE": "Failed calibration: instrument is quarantined until the corrective action is closed.",
               "PROHIBITED_NO_CALIBRATION": "No calibration on record."}[st]
        return dict(asset_id=aid, at=at, status=st, allowed=not rules.is_blocked(st), calibration_id=cid, extension_id=xid, due_date=due, message=msg)

    def record_use(self, b):
        at = b.get("used_at") or datetime.now().replace(microsecond=0).isoformat()
        res = self.check(b.get("asset_id", ""), at)
        if res is None: return 404, dict(error="unknown asset_id")
        with self.lock:
            con = sqlite3.connect(self.db)
            try:
                if not res["allowed"]:  # prevention: block, raise alert, append audit record. Nothing is overwritten.
                    n = con.execute("SELECT count(*) FROM alert").fetchone()[0] + 1; m = con.execute("SELECT count(*) FROM audit_record").fetchone()[0] + 1
                    con.execute("INSERT INTO alert VALUES (?,?,?,?,?,?,?,?,?)", (f"ALT-2026-{n:06d}", "USE_BLOCKED", "MEDIUM", res["asset_id"], "calibration_event", res["calibration_id"] or "n/a", at, "OPEN", "Use attempt blocked: " + res["status"]))
                    con.execute("INSERT INTO audit_record VALUES (?,?,?,?,?,?,?,?,?,?)", (f"AUD-{m:07d}", "ASSET", res["asset_id"], res["asset_id"], "USE_BLOCKED", None, None, b.get("operator_id", "OPR-000"), at, res["status"]))
                    con.commit(); return 409, dict(res, blocked=True, alert_id=f"ALT-2026-{n:06d}")
                uid = f"USE-{res['asset_id']}-{at.replace('-', '').replace(':', '')[:15]}"
                con.execute("INSERT INTO production_use VALUES (?,?,?,?,?,?,?,?,?,?)", (uid, res["asset_id"], at, b.get("production_line", "LINE-01"), b.get("batch_id", "BATCH-MANUAL-001"), b.get("operator_id", "OPR-000"), int(b.get("duration_min", 30)), res["status"], res["calibration_id"], res["extension_id"]))
                con.commit(); return 201, dict(res, use_id=uid, blocked=False)
            except sqlite3.IntegrityError as e: return 409, dict(error=str(e))
            finally: con.close()

def make_handler(app):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def send(self, code, obj, ctype="application/json"):
            body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            u = urlparse(self.path); p = {k: v[0] for k, v in parse_qs(u.query).items()}; path = u.path
            try:
                if path in ("/", "/index.html"): return self.send(200, open(os.path.join(ROOT, "index.html"), "rb").read(), "text/html; charset=utf-8")
                if path == "/api/summary": return self.send(200, app.summary())
                if path == "/api/assets": return self.send(200, app.assets(p))
                if path.startswith("/api/assets/"):
                    r = app.asset(path.rsplit("/", 1)[1]); return self.send(200 if r else 404, r or dict(error="not found"))
                if path == "/api/alerts":
                    w, a = ["1=1"], []
                    if p.get("type"): w.append("alert_type=?"); a.append(p["type"])
                    if p.get("severity"): w.append("severity=?"); a.append(p["severity"])
                    return self.send(200, app.q(f"SELECT * FROM alert WHERE {' AND '.join(w)} ORDER BY raised_at DESC LIMIT ?", a + [min(int(p.get("limit", 200)), 1000)]))
                if path == "/api/check":
                    r = app.check(p.get("asset_id", ""), p.get("at") or datetime.now().replace(microsecond=0).isoformat()); return self.send(200 if r else 404, r or dict(error="unknown asset_id"))
                if path in ("/api/validation", "/api/evaluation"):
                    f = os.path.join(app.dir, "validation_summary.json" if path.endswith("validation") else "evaluation.json")
                    return self.send(200, open(f, "rb").read()) if os.path.exists(f) else self.send(404, dict(error="run the generator first"))
                self.send(404, dict(error="not found"))
            except Exception as e: self.send(500, dict(error=str(e)))
        def do_POST(self):
            if urlparse(self.path).path != "/api/use": return self.send(404, dict(error="not found"))
            try: body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except ValueError: return self.send(400, dict(error="invalid JSON"))
            code, obj = app.record_use(body); self.send(code, obj)
    return H

def serve(data, port=8000, host="127.0.0.1"):
    srv = ThreadingHTTPServer((host, port), make_handler(App(data))); return srv

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--data", default="data/full"); ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(); s = serve(a.data, a.port); print(f"http://127.0.0.1:{a.port}  (data: {a.data})")
    try: s.serve_forever()
    except KeyboardInterrupt: pass

import json, os, shutil, sys, tempfile, threading, unittest, urllib.error, urllib.request, csv
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from calibration import generate, rules, schema, server, validate, evaluate

N = (60, 150, 3000)
TMP = tempfile.mkdtemp()
OUT = os.path.join(TMP, "a")
T, GT = generate.build(*N, 20261022)
generate.write_all(T, GT, OUT, ["csv", "json", "sql", "db"], dict(command="test", seed=20261022, assets=N[0], events=N[1], uses=N[2]))

def tables(**kw):
    """minimal hand-built tables for rule unit tests"""
    t = dict(instrument_type=[dict(type_id="T", prohibit_use_when_overdue=kw.get("block", 1))], asset=[dict(asset_id="A", type_id="T")],
             calibration_plan=[dict(asset_id="A", interval_days=100, status="ACTIVE")], emergency_extension=kw.get("ext", []), work_order=kw.get("wo", []),
             calibration_event=[dict(calibration_id="C1", asset_id="A", performed_date="2026-01-01", result=kw.get("res", "PASS"))])
    return t

class Generation(unittest.TestCase):
    def test_volume_matches_parameters(self):
        self.assertEqual((len(T["asset"]), len(T["calibration_event"]), len(T["production_use"])), N)

    def test_validation_all_pass(self):
        v = validate.run(T)
        self.assertTrue(v["ok"], [c for c in v["checks"] if c["status"] == "FAIL"])

    def test_required_edge_cases_present_and_labelled(self):
        kinds = {g["issue_type"] for g in GT}
        for k in ("DUE_DATE_INCONSISTENT", "EXPIRED_USE_NO_EXCEPTION", "CERT_ASSET_MISMATCH", "IMPACT_ASSESSMENT_MISSING", "MISSING_CERTIFICATE", "EXTENSION_USE", "BOUNDARY_DUE_DATE_USE"):
            self.assertIn(k, kinds)

    def test_detector_matches_ground_truth_exactly(self):
        e = evaluate.run(T, GT)
        self.assertTrue(e["summary"]["all_findings_match_ground_truth"])
        self.assertEqual(e["summary"]["decision_mismatches"], 0)

    def test_ground_truth_separate_and_no_leakage(self):
        self.assertTrue(os.path.exists(os.path.join(OUT, "ground_truth", "ground_truth.csv")))
        self.assertFalse(os.path.exists(os.path.join(OUT, "csv", "ground_truth.csv")))
        self.assertEqual(evaluate.run(T, GT)["summary"]["leakage_columns_in_inputs"], [])

    def test_failed_calibration_has_corrective_action_and_impact_assessment_unless_labelled(self):
        skipped = {g["entity_id"] for g in GT if g["issue_type"] == "IMPACT_ASSESSMENT_MISSING"}
        for e in T["calibration_event"]:
            if e["result"] == "FAIL":
                types = {w["wo_type"] for w in T["work_order"] if w["calibration_id"] == e["calibration_id"]}
                self.assertIn("CORRECTIVE_ACTION", types)
                self.assertEqual("IMPACT_ASSESSMENT" in types, e["calibration_id"] not in skipped)

    def test_due_dates_correct_except_labelled(self):
        bad = {g["entity_id"] for g in GT if g["issue_type"] == "DUE_DATE_INCONSISTENT"}
        plan = {p["asset_id"]: p["interval_days"] for p in T["calibration_plan"]}
        for e in T["calibration_event"]:
            ok = e["next_due_date"] == rules.add_days(e["performed_date"], plan[e["asset_id"]])
            self.assertEqual(ok, e["calibration_id"] not in bad)

    def test_validator_catches_corruption(self):
        t = {k: [dict(r) for r in v] for k, v in T.items()}
        t["calibration_event"][0]["asset_id"] = "AST-999999"; t["production_use"][0]["use_id"] = t["production_use"][1]["use_id"]
        self.assertFalse(validate.run(t)["ok"])

    def test_history_not_overwritten_audit_chain(self):
        ids = [r["audit_id"] for r in T["audit_record"]]
        self.assertEqual(ids, sorted(ids)); self.assertEqual(len(ids), len(set(ids)))

class Reproducibility(unittest.TestCase):
    def test_same_seed_same_checksums_and_different_seed_differs(self):
        out2 = os.path.join(TMP, "b"); t2, g2 = generate.build(*N, 20261022)
        generate.write_all(t2, g2, out2, ["csv"], dict(command="test", seed=20261022))
        m1 = json.load(open(os.path.join(OUT, "manifest.json"))); m2 = json.load(open(os.path.join(out2, "manifest.json")))
        self.assertEqual(m1["sha256"], m2["sha256"]); self.assertEqual(m1["row_counts"], m2["row_counts"])
        t3, _ = generate.build(*N, 7); self.assertNotEqual(t3["production_use"][0]["use_id"], T["production_use"][0]["use_id"])

class Rules(unittest.TestCase):
    def test_due_date_boundary_inclusive(self):
        rs = rules.Ruleset(tables())  # due = 2026-04-11
        self.assertEqual(rs.evaluate("A", "2026-04-11")[0], "COMPLIANT")
        self.assertEqual(rs.evaluate("A", "2026-04-12")[0], "PROHIBITED_OVERDUE")
        self.assertEqual(rs.evaluate("A", "2025-12-31")[0], "PROHIBITED_NO_CALIBRATION")

    def test_non_blocking_policy_only_warns(self):
        self.assertEqual(rules.Ruleset(tables(block=0)).evaluate("A", "2026-06-01")[0], "ADVISORY_OVERDUE")

    def test_emergency_extension(self):
        rs = rules.Ruleset(tables(ext=[dict(extension_id="E1", asset_id="A", due_date_original="2026-04-11", extended_until="2026-04-15")]))
        self.assertEqual(rs.evaluate("A", "2026-04-15")[0], "COMPLIANT_EXTENSION"); self.assertEqual(rs.evaluate("A", "2026-04-16")[0], "PROHIBITED_OVERDUE")

    def test_quarantine_until_corrective_action_closed(self):
        wo = [dict(calibration_id="C1", wo_type="CORRECTIVE_ACTION", closed_date="2026-01-04")]
        rs = rules.Ruleset(tables(res="FAIL", wo=wo))
        self.assertEqual(rs.evaluate("A", "2026-01-04")[0], "PROHIBITED_QUARANTINE"); self.assertEqual(rs.evaluate("A", "2026-01-05")[0], "COMPLIANT")
        self.assertEqual(rules.Ruleset(tables(res="FAIL", wo=[dict(calibration_id="C1", wo_type="CORRECTIVE_ACTION", closed_date=None)])).evaluate("A", "2026-02-01")[0], "PROHIBITED_QUARANTINE")

class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = server.serve(OUT, 0); cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def get(self, p): return json.load(urllib.request.urlopen(self.base + p))
    def post(self, body):
        req = urllib.request.Request(self.base + "/api/use", json.dumps(body).encode(), {"Content-Type": "application/json"})
        try: r = urllib.request.urlopen(req); return r.status, json.load(r)
        except urllib.error.HTTPError as e: return e.code, json.load(e)

    def test_endpoints(self):
        s = self.get("/api/summary"); self.assertEqual(s["counts"]["assets"], N[0])
        self.assertEqual(len(self.get("/api/assets?limit=5")), 5)
        self.assertIn("audit", self.get("/api/assets/AST-000001")); self.assertTrue(self.get("/api/validation")["ok"])
        self.assertIn(b"Calibration Control", urllib.request.urlopen(self.base + "/").read())

    def test_unknown_asset_404(self):
        with self.assertRaises(urllib.error.HTTPError) as c: self.get("/api/check?asset_id=NOPE")
        self.assertEqual(c.exception.code, 404)

    def test_prohibited_use_is_blocked_with_alert_and_audit(self):
        g = next(g for g in GT if g["issue_type"] == "EXPIRED_USE_NO_EXCEPTION"); u = next(u for u in T["production_use"] if u["use_id"] == g["entity_id"])
        before = self.get("/api/summary")["counts"]["uses"]
        code, r = self.post(dict(asset_id=u["asset_id"], used_at=u["used_at"][:10] + "T23:00:00"))
        self.assertEqual(code, 409); self.assertTrue(r["blocked"]); self.assertEqual(self.get("/api/summary")["counts"]["uses"], before)
        self.assertTrue(any(a["alert_type"] == "USE_BLOCKED" for a in self.get(f"/api/alerts?type=USE_BLOCKED")))

    def test_compliant_use_is_recorded(self):
        u = next(u for u in T["production_use"] if u["compliance_status"] == "COMPLIANT")
        code, r = self.post(dict(asset_id=u["asset_id"], used_at=u["used_at"][:10] + "T23:30:00"))
        self.assertEqual(code, 201); self.assertFalse(r["blocked"])

if __name__ == "__main__":
    try: unittest.main()
    finally: shutil.rmtree(TMP, ignore_errors=True)

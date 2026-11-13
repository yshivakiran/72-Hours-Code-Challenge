"""Business rules engine: decides whether an instrument may be used at a given date.
Policy (deterministic):
 * due_date = performed_date + plan.interval_days; the due date itself is still valid (inclusive).
 * A FAIL calibration quarantines the asset from the calibration date until its CORRECTIVE_ACTION work order is closed
   (open => still quarantined). After closure the as-left calibration governs and its due date applies.
 * After the due date the asset is overdue. An emergency extension for that cycle (due < d <= extended_until) makes use compliant.
 * Overdue + type.prohibit_use_when_overdue=1 => PROHIBITED_OVERDUE (block); otherwise ADVISORY_OVERDUE (warn only).
Dates are ISO strings so lexicographic comparison is date comparison."""
from bisect import bisect_right
from datetime import date, timedelta

def add_days(iso, n): return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()

class Ruleset:
    def __init__(self, t):
        self.type = {r["type_id"]: r for r in t["instrument_type"]}
        self.asset = {r["asset_id"]: r for r in t["asset"]}
        self.interval = {p["asset_id"]: p["interval_days"] for p in t["calibration_plan"] if p["status"] == "ACTIVE"}
        ca = {w["calibration_id"]: w["closed_date"] for w in t["work_order"] if w["wo_type"] == "CORRECTIVE_ACTION"}
        self.ext = {(x["asset_id"], x["due_date_original"]): (x["extension_id"], x["extended_until"]) for x in t["emergency_extension"]}
        self.ev, self.dates = {}, {}
        for e in sorted(t["calibration_event"], key=lambda e: (e["asset_id"], e["performed_date"])):
            a = e["asset_id"]
            due = add_days(e["performed_date"], self.interval[a])
            self.ev.setdefault(a, []).append((e["calibration_id"], e["performed_date"], e["result"], due, ca.get(e["calibration_id"])))
            self.dates.setdefault(a, []).append(e["performed_date"])

    def blocking(self, aid): return self.type[self.asset[aid]["type_id"]]["prohibit_use_when_overdue"] == 1

    def evaluate(self, aid, d):
        """d: ISO date. Returns (status, calibration_id, extension_id, due_date)."""
        i = bisect_right(self.dates.get(aid, []), d) - 1
        if i < 0:
            return ("PROHIBITED_NO_CALIBRATION" if self.blocking(aid) else "ADVISORY_OVERDUE", None, None, None)
        cid, _, res, due, closed = self.ev[aid][i]
        if res == "FAIL" and (closed is None or d <= closed): return ("PROHIBITED_QUARANTINE", cid, None, due)
        if d <= due: return ("COMPLIANT", cid, None, due)
        x = self.ext.get((aid, due))
        if x and d <= x[1]: return ("COMPLIANT_EXTENSION", cid, x[0], due)
        return ("PROHIBITED_OVERDUE" if self.blocking(aid) else "ADVISORY_OVERDUE", cid, None, due)

def is_blocked(status): return status.startswith("PROHIBITED")

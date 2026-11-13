"""Scores the independent detector + rules engine against ground truth (ground truth is only read here)."""
from collections import Counter
from . import schema, detect

LEAK_WORDS = {"issue_type", "ground_truth", "origin", "expected_decision", "issue_id"}

def run(t, gt):
    found = {(i, e) for i, _, e, _ in detect.findings(t)}
    truth = {(g["issue_type"], g["entity_id"]) for g in gt}
    per = {}
    for it in schema.ISSUE_TYPES:
        f = {x for x in found if x[0] == it}; g = {x for x in truth if x[0] == it}
        tp = len(f & g)
        per[it] = dict(truth=len(g), found=len(f), tp=tp, fp=len(f - g), fn=len(g - f), precision=round(tp / len(f), 4) if f else None, recall=round(tp / len(g), 4) if g else None)
    exp = {g["entity_id"]: g["expected_decision"] for g in gt if g["entity_type"] == "production_use"}
    wrong = [u["use_id"] for u in t["production_use"] if u["compliance_status"] != exp.get(u["use_id"], "COMPLIANT") and not (u["use_id"] in exp and exp[u["use_id"]] == "COMPLIANT")]
    n = len(t["production_use"])
    leak = [(n_, c) for n_ in t for c in schema.cols(n_) if c in LEAK_WORDS]
    return dict(summary=dict(use_decision_accuracy=round(1 - len(wrong) / max(n, 1), 6), use_events=n, decision_mismatches=len(wrong),
                             all_findings_match_ground_truth=found == truth, ground_truth_rows=len(truth), leakage_columns_in_inputs=leak),
                per_issue_type=per, use_status_counts=dict(Counter(u["compliance_status"] for u in t["production_use"])),
                origin_counts=dict(Counter(g["origin"] for g in gt)))

"""Step 10: regenerate twice with the same seed and compare row counts + checksums."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from calibration import generate

def main(preset="starter"):
    with tempfile.TemporaryDirectory() as d:
        runs = []
        for i in (1, 2):
            out = os.path.join(d, f"run{i}"); generate.main(["--preset", preset, "--out", out, "--formats", "csv"])
            m = json.load(open(os.path.join(out, "manifest.json"))); runs.append((m["row_counts"], m["sha256"]))
        same = runs[0] == runs[1]
        print("row counts identical:", runs[0][0] == runs[1][0]); print("sha256 of every CSV + ground truth identical:", runs[0][1] == runs[1][1])
        print("REPRODUCIBLE" if same else "NOT REPRODUCIBLE"); return 0 if same else 1

if __name__ == "__main__": sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "starter"))

#!/usr/bin/env python3
"""
Function Health lab analysis.

Merges all test rounds from ~/.function-health/exports/ into a single dataset and
classifies every marker against BOTH bands the export carries:

  rangeString  - the lab REFERENCE range (wide). The `inRange` boolean is computed
                 against this, and this is what the Function UI flags on.
  optimalRange - Function's own OPTIMAL band (narrow). Not used by the flag at all.

The gap between those two is where most findings live: a marker can sit far outside
the optimal band and still report `inRange: true`.

Interval notation in optimalRange is real interval notation and must be parsed as
such -- "[a,b]" inclusive, "(a,b)" exclusive, "[a,)" open upper, "(,b]" open lower.
Naive two-number regex parsing silently skips every single-bounded range.

Outputs (written to ../reports/ by default, so personal data stays out of this folder):
  merged-results.json  - all rounds, all markers, normalized + classified
  findings.json        - just the markers with problems, grouped by class

Usage:  python3 analyze.py [--quiet] [--out DIR]
"""

import json
import os
import re
import sys
from pathlib import Path

EXPORTS = Path.home() / ".function-health" / "exports"
DEFAULT_OUTDIR = Path(__file__).resolve().parent.parent / "reports"

# Optimal ranges that are degenerate or aspirational rather than clinical thresholds.
# Keyed by biomarker name -> reason. These are excluded from findings.
ARTIFACTS = {
    "Prolactin": "optimal stored as [5,5] - degenerate interval, not a real threshold",
    "Lead ": "optimal [0,0] - aspirational zero; any detectable amount reads 'above'",
    "Mercury": "optimal [0,0] - aspirational zero; value is at the detection limit",
    "Thyroglobulin Antibodies (TgAb)": "optimal <=1 vs a detection floor of 2 - trivially 'above'",
}


def parse_interval(s):
    """Parse interval notation into (lower_bound, upper_bound, lo_inclusive, hi_inclusive).

    Returns None if the string is not an interval (e.g. "NEGATIVE", "A", "").
    Either bound may be None, meaning unbounded on that side.
    """
    if not s or s[0] not in "[(":
        return None
    m = re.match(r"^([\[\(])\s*([^,]*?)\s*,\s*([^\]\)]*?)\s*([\]\)])$", s)
    if not m:
        return None
    ob, lo_s, hi_s, cb = m.groups()
    try:
        lo = float(lo_s) if lo_s else None
        hi = float(hi_s) if hi_s else None
    except ValueError:
        return None
    return lo, hi, ob == "[", cb == "]"


def classify(value, optimal):
    """Classify a numeric value against an optimal interval.

    Returns one of: 'optimal', 'above_optimal', 'below_optimal', 'at_ceiling',
    'at_floor', or None when the comparison cannot be made.
    """
    iv = parse_interval(optimal)
    if iv is None or value is None:
        return None
    lo, hi, lo_inc, hi_inc = iv
    if lo is not None:
        if value < lo or (value == lo and not lo_inc):
            return "below_optimal"
    if hi is not None:
        if value > hi or (value == hi and not hi_inc):
            return "above_optimal"
    # Inside the band -- flag the edges, they matter clinically.
    if hi is not None and value == hi:
        return "at_ceiling"
    if lo is not None and value == lo:
        return "at_floor"
    return "optimal"


def classify_censored(bound, optimal):
    """Classify a result reported only as '<bound' (below the assay's reporting limit).

    The true value is somewhere under `bound`, so only some conclusions are safe:
    below the optimal floor if bound <= floor; optimal if the band starts at zero and
    bound fits under the ceiling; otherwise 'indeterminate'.
    """
    iv = parse_interval(optimal)
    if iv is None or bound is None:
        return None
    lo, hi, lo_inc, hi_inc = iv
    if lo is not None and lo > 0 and bound <= lo:
        return "below_optimal"
    if (lo is None or lo == 0) and hi is not None and bound <= hi:
        return "optimal"
    return "indeterminate"


def to_float(v):
    """Coerce a result to float. Handles '<30', '>= 40', '<OR=10', '1,665'."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    s = re.sub(r"^(<OR=|>OR=|<=|>=|<|>)", "", s).strip()
    try:
        return float(s)
    except ValueError:
        return None


def load_rounds():
    """Load every round directory into {date: [results]}, plus round metadata."""
    rounds = {}
    meta = {}
    for d in sorted(p for p in EXPORTS.iterdir() if p.is_dir()):
        rf = d / "results.json"
        if not rf.exists():
            continue
        rounds[d.name] = json.loads(rf.read_text())
        mf = d / "round-meta.json"
        if mf.exists():
            meta[d.name] = json.loads(mf.read_text())
    return rounds, meta


def build(rounds):
    """Normalize + classify every result across every round."""
    merged = []
    for date, results in rounds.items():
        for r in results:
            name = r.get("biomarkerName", "")
            raw = r.get("calculatedResult")
            val = to_float(raw)
            optimal = r.get("optimalRange") or ""
            # calculatedResult drops the '<' on censored results ('<30' -> '30'), so read
            # the censoring from displayResult or a value under the limit looks like the limit.
            display = str(r.get("displayResult") or raw or "").strip()
            censored = display.startswith("<")
            status = classify_censored(val, optimal) if censored else classify(val, optimal)
            merged.append(
                {
                    "round": date,
                    "biomarkerName": name,
                    "value": display if censored else raw,
                    "numericValue": val,
                    "censored": censored,
                    "units": r.get("units") or "",
                    "inRange": r.get("inRange"),
                    "optimalRange": optimal,
                    "referenceRange": r.get("rangeString") or "",
                    "optimalStatus": status,
                    "isArtifact": name in ARTIFACTS,
                    "artifactReason": ARTIFACTS.get(name),
                    "dateOfService": r.get("dateOfService"),
                    "requisitionId": r.get("requisitionId"),
                }
            )
    return merged


def derived(merged, round_date):
    """Ratios the panel does not report but that follow from markers it does."""
    by = {m["biomarkerName"]: m["numericValue"] for m in merged if m["round"] == round_date}

    def g(*names):
        for n in names:
            for k, v in by.items():
                if k.strip() == n:
                    return v
        return None

    glucose = g("Glucose")
    insulin = g("Insulin")
    trig = g("Triglycerides")
    hdl = g("HDL-Cholesterol")

    out = {}
    if glucose and insulin:
        out["HOMA-IR"] = {
            "value": round(glucose * insulin / 405, 2),
            "formula": "glucose * insulin / 405",
            "threshold": "> 2.5-2.9 indicates insulin resistance",
        }
    if trig and hdl:
        out["Triglyceride/HDL ratio"] = {
            "value": round(trig / hdl, 2),
            "formula": "triglycerides / HDL-C",
            "threshold": "> 3 elevated in men; independent insulin-resistance proxy",
        }
    return out


def main():
    quiet = "--quiet" in sys.argv
    outdir = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else DEFAULT_OUTDIR
    outdir.mkdir(parents=True, exist_ok=True)
    rounds, meta = load_rounds()
    merged = build(rounds)

    latest_full = max(rounds, key=lambda d: len(rounds[d]))

    flagged = [m for m in merged if m["inRange"] is False]
    silent = [
        m
        for m in merged
        if m["inRange"] is True
        and m["optimalStatus"] in ("above_optimal", "below_optimal")
        and not m["isArtifact"]
    ]
    edges = [m for m in merged if m["inRange"] is True and m["optimalStatus"] in ("at_ceiling", "at_floor")]
    artifacts = [m for m in merged if m["isArtifact"]]

    findings = {
        "rounds": {d: {"resultCount": len(r), "meta": meta.get(d)} for d, r in rounds.items()},
        "flaggedOutOfRange": flagged,
        "silentlySuboptimal": silent,
        "atOptimalEdge": edges,
        "artifacts": artifacts,
        "derived": {d: derived(merged, d) for d in rounds},
    }

    (outdir / "merged-results.json").write_text(json.dumps(merged, indent=2))
    (outdir / "findings.json").write_text(json.dumps(findings, indent=2))

    if quiet:
        return

    def show(title, rows):
        print(f"\n{'=' * 78}\n{title}  ({len(rows)})\n{'=' * 78}")
        for m in sorted(rows, key=lambda x: x["biomarkerName"]):
            st = (m["optimalStatus"] or "").replace("_optimal", "").upper()[:5]
            print(
                f"  {st:6}{m['biomarkerName'][:40]:42}{str(m['value'])[:9]:>9} "
                f"{m['units'][:11]:12} opt={m['optimalRange'][:14]:15} ref={m['referenceRange'][:16]}"
            )

    for d in sorted(rounds):
        print(f"round {d}: {len(rounds[d])} markers")
    print(f"\nlargest round: {latest_full}")

    show("FLAGGED OUT OF RANGE (inRange=false)", flagged)
    show("SILENTLY SUBOPTIMAL (inRange=true, outside optimal band)", silent)
    show("AT THE OPTIMAL EDGE (inRange=true, exactly on a bound)", edges)
    show("ARTIFACTS (excluded from findings)", artifacts)

    print(f"\n{'=' * 78}\nDERIVED RATIOS\n{'=' * 78}")
    for d, dv in findings["derived"].items():
        for k, v in dv.items():
            print(f"  [{d}] {k:26} = {v['value']:<8} {v['threshold']}")

    print(f"\nwrote {outdir / 'merged-results.json'}")
    print(f"wrote {outdir / 'findings.json'}")


if __name__ == "__main__":
    main()

"""
Why this script exists
----------------------
Raw data sources are inconsistent. Rather than normalizing at runtime,
we normalize once here so the app can rely on a consistent schema.

This follows a "fail early" approach — issues are surfaced during
data processing instead of causing silent errors in the app.

Tradeoff:
- Preprocessing adds a step but improves reliability and keeps app logic simple.

Usage
-----
  python normalize_data.py                      # uses default paths
  python normalize_data.py --input-dir ./raw    # custom input directory
  python normalize_data.py --strict             # exit non-zero if unfixed issues found
  python normalize_data.py --validate-only      # check only, write nothing (CI-friendly)
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Any


# ── Markup configuration ──────────────────────────────────────────────────────
# Per-category markup rates applied to baseCost to produce _retailPrice.
# Edit these to adjust margins without touching app code.
# Categories not listed fall back to DEFAULT_MARKUP.

DEFAULT_MARKUP = 0.35  # 35% — standard parts markup

MARKUP_BY_CATEGORY = {
    "Air Conditioner": 0.30,
    "Heat Pump":       0.30,
    "Furnace":         0.30,
    "Rooftop Unit":    0.25,   # commercial — often negotiated
    "Package Unit":    0.25,
    "Mini-Split":      0.30,
    "Compressor":      0.40,   # high-demand replacement part
    "Motor":           0.40,
    "Coil":            0.38,
    "Thermostat":      0.45,   # high margin category
    "Capacitor":       0.50,   # very low cost, high markup
    "Gas Valve":       0.38,
    "Control Board":   0.40,
    "Ignitor":         0.45,
    "Air Handler":     0.30,
    "Humidifier":      0.35,
    "Air Cleaner":     0.35,
    "Air Purifier":    0.35,
}

# System age threshold (years) above which to flag as replacement candidate
REPLACEMENT_AGE_THRESHOLD = 15

# Illinois sales tax rate
ILLINOIS_TAX_RATE = 0.0975


# ── Issue tracking ─────────────────────────────────────────────────────────────

class NormalizationReport:
    """
    Collects every issue found during normalization so we can print a
    single structured report at the end rather than crashing on the first
    problem. In a CI pipeline you'd post this report as an artifact.
    """

    def __init__(self):
        self.issues: list[dict] = []
        self.fixes: list[dict] = []

    def issue(self, source: str, record_id: str, field: str, description: str):
        self.issues.append({
            "source": source, "id": record_id,
            "field": field, "description": description, "fixed": False
        })

    def fix(self, source: str, record_id: str, field: str, description: str):
        self.fixes.append({
            "source": source, "id": record_id,
            "field": field, "description": description
        })
        self.issues.append({
            "source": source, "id": record_id,
            "field": field, "description": description, "fixed": True
        })

    def print_summary(self):
        print("\n" + "═" * 60)
        print("  NORMALIZATION REPORT")
        print("═" * 60)

        if not self.issues:
            print("  ✓ No issues found. All data is clean.")
        else:
            unfixed = [i for i in self.issues if not i["fixed"]]
            print(f"\n  Found {len(self.issues)} issue(s): "
                  f"{len(self.fixes)} auto-fixed, {len(unfixed)} need attention\n")

            by_source: dict[str, list] = {}
            for issue in self.issues:
                by_source.setdefault(issue["source"], []).append(issue)

            for source, items in by_source.items():
                print(f"  [{source}]")
                for item in items:
                    prefix = "  ✓" if item["fixed"] else "  ⚠"
                    print(f"    {prefix} {item['id']} · {item['field']}: {item['description']}")
                print()

        print("═" * 60 + "\n")

    @property
    def has_unfixed_issues(self) -> bool:
        return any(not i["fixed"] for i in self.issues)


report = NormalizationReport()


# ── Normalizers ────────────────────────────────────────────────────────────────

def normalize_customers(raw: list[dict]) -> list[dict]:
    """
    Known issues in the raw export:
    - CUST008 uses 'property_type' (snake_case) instead of 'propertyType'
    - CUST008 uses 'sqft' instead of 'squareFootage'
    - Some commercial records missing lastServiceDate (flagged, not fatal)
    - CUST005 missing phone (flagged)
    - CUST007 missing systemAge (flagged)
    """
    cleaned = []

    for raw_rec in raw:
        rec = dict(raw_rec)
        rid = rec.get("id", "UNKNOWN")

        # ── Field name normalization ──────────────────────────────────────────
        # CUST008 was exported from a different tool using snake_case.
        # We detect both variants explicitly — we don't do a blanket
        # snake_case → camelCase conversion because that would silently swallow
        # future export format changes we'd want to know about.

        if "property_type" in rec and "propertyType" not in rec:
            report.fix("customers", rid, "property_type",
                       "Renamed 'property_type' → 'propertyType' (snake_case export bug)")
            rec["propertyType"] = rec.pop("property_type")

        if "sqft" in rec and "squareFootage" not in rec:
            report.fix("customers", rid, "sqft",
                       "Renamed 'sqft' → 'squareFootage' (snake_case export bug)")
            rec["squareFootage"] = rec.pop("sqft")

        # ── Type coercion ─────────────────────────────────────────────────────

        if "squareFootage" in rec:
            try:
                rec["squareFootage"] = int(rec["squareFootage"])
            except (TypeError, ValueError):
                report.issue("customers", rid, "squareFootage",
                             f"Cannot coerce '{rec['squareFootage']}' to int — left as-is")

        if "systemAge" in rec and rec["systemAge"] is not None:
            try:
                age = int(rec["systemAge"])
                if age < 0:
                    raise ValueError("negative age")
                rec["systemAge"] = age
            except (TypeError, ValueError):
                report.issue("customers", rid, "systemAge",
                             f"Invalid systemAge '{rec['systemAge']}' — removed")
                del rec["systemAge"]

        if "lastServiceDate" in rec and rec["lastServiceDate"] is not None:
            try:
                datetime.strptime(rec["lastServiceDate"], "%Y-%m-%d")
            except ValueError:
                report.issue("customers", rid, "lastServiceDate",
                             f"Invalid date '{rec['lastServiceDate']}' (expected YYYY-MM-DD)")

        # ── Missing field warnings ────────────────────────────────────────────

        for field in ("id", "name", "address"):
            if not rec.get(field):
                report.issue("customers", rid, field, f"Required field missing or null")

        if not rec.get("phone"):
            report.issue("customers", rid, "phone",
                         "No phone number — tech cannot call ahead")

        if not rec.get("lastServiceDate"):
            report.issue("customers", rid, "lastServiceDate",
                         "No last service date — visit history unavailable")

        if rec.get("systemAge") is None:
            report.issue("customers", rid, "systemAge",
                         "System age unknown — replacement warnings will not fire")

        # ── Computed fields ───────────────────────────────────────────────────

        rec["_replacementCandidate"] = (rec.get("systemAge") or 0) >= REPLACEMENT_AGE_THRESHOLD

        if isinstance(rec.get("propertyType"), str):
            rec["propertyType"] = rec["propertyType"].lower()

        cleaned.append(rec)

    return cleaned


def normalize_equipment(raw: list[dict]) -> list[dict]:
    """
    Known issues:
    - EQ012 and EQ028 use 'base_cost' instead of 'baseCost'

    Markup decision
    ---------------
    baseCost is the wholesale cost. We compute _retailPrice here using
    per-category rates from MARKUP_BY_CATEGORY. Doing this in the pipeline
    means margin changes require editing one config dict and re-running —
    not hunting through app code. The app reads _retailPrice directly.
    """
    cleaned = []

    for raw_rec in raw:
        rec = dict(raw_rec)
        rid = rec.get("id", "UNKNOWN")

        # ── Field name normalization ──────────────────────────────────────────

        if "base_cost" in rec and "baseCost" not in rec:
            report.fix("equipment", rid, "base_cost",
                       "Renamed 'base_cost' → 'baseCost' (snake_case export bug)")
            rec["baseCost"] = rec.pop("base_cost")

        # ── Type validation ───────────────────────────────────────────────────

        if "baseCost" in rec:
            try:
                rec["baseCost"] = float(rec["baseCost"])
                if rec["baseCost"] <= 0:
                    raise ValueError("non-positive")
            except (TypeError, ValueError):
                report.issue("equipment", rid, "baseCost",
                             f"Invalid baseCost '{rec.get('baseCost')}' — pricing will be wrong")

        # ── Computed fields ───────────────────────────────────────────────────

        if isinstance(rec.get("baseCost"), (int, float)) and rec["baseCost"] > 0:
            category = rec.get("category", "")
            markup = MARKUP_BY_CATEGORY.get(category, DEFAULT_MARKUP)
            rec["_retailPrice"] = round(rec["baseCost"] * (1 + markup), 2)
            rec["_markupPct"] = markup

        for field in ("id", "name", "category", "brand", "baseCost"):
            if not rec.get(field):
                report.issue("equipment", rid, field, f"Required field missing")

        if not rec.get("modelNumber"):
            report.issue("equipment", rid, "modelNumber",
                         "No model number — techs can't verify part compatibility in the field")

        cleaned.append(rec)

    return cleaned


def normalize_labor(raw: list[dict]) -> list[dict]:
    """
    labor_rates.json is the cleanest file — no field name inconsistencies.
    Main validation: hour ranges must be sane. We also add _midpointHours
    as a convenience default for quick estimates.
    """
    cleaned = []

    for raw_rec in raw:
        rec = dict(raw_rec)
        key = f"{rec.get('jobType','?')}/{rec.get('level','?')}"

        eh = rec.get("estimatedHours", {})
        min_h = eh.get("min")
        max_h = eh.get("max")

        if min_h is None or max_h is None:
            report.issue("labor_rates", key, "estimatedHours",
                         "Missing min or max — range display will be incomplete")
        elif not (isinstance(min_h, (int, float)) and isinstance(max_h, (int, float))):
            report.issue("labor_rates", key, "estimatedHours",
                         "min/max must be numbers")
        elif min_h >= max_h:
            report.issue("labor_rates", key, "estimatedHours",
                         f"min ({min_h}) >= max ({max_h}) — invalid range")
        else:
            rec["_midpointHours"] = round((min_h + max_h) / 2, 1)

        rate = rec.get("hourlyRate")
        if not isinstance(rate, (int, float)) or rate <= 0:
            report.issue("labor_rates", key, "hourlyRate",
                         f"Invalid hourlyRate '{rate}'")

        cleaned.append(rec)

    return cleaned


# ── I/O helpers ───────────────────────────────────────────────────────────────

def load_json(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Cannot find {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: {path} is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)


def write_json(data: Any, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {path}  ({len(data)} records)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Normalize HVAC estimator data files")
    parser.add_argument("--input-dir", default="data",
                        help="Directory containing raw JSON files (default: data)")
    parser.add_argument("--output-dir", default="data/clean",
                        help="Directory for cleaned output files (default: data/clean)")
    parser.add_argument("--strict", action="store_true",
                        help="Exit with code 1 if any unfixed issues are found")
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate only — do not write output files (useful in CI)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    print(f"\nNormalizing data from '{input_dir}' → '{output_dir}'")
    print(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    raw_customers = load_json(input_dir / "customers.json")
    raw_equipment = load_json(input_dir / "equipment.json")
    raw_labor     = load_json(input_dir / "labor_rates.json")

    print(f"  Loaded {len(raw_customers)} customers, "
          f"{len(raw_equipment)} equipment items, "
          f"{len(raw_labor)} labor rates")

    clean_customers = normalize_customers(raw_customers)
    clean_equipment = normalize_equipment(raw_equipment)
    clean_labor     = normalize_labor(raw_labor)

    if args.validate_only:
        print("\n  --validate-only: skipping file writes")
    else:
        print()
        write_json(clean_customers, output_dir / "customers.json")
        write_json(clean_equipment, output_dir / "equipment.json")
        write_json(clean_labor,     output_dir / "labor_rates.json")

        meta = {
            "normalizedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "counts": {
                "customers": len(clean_customers),
                "equipment": len(clean_equipment),
                "laborRates": len(clean_labor),
            },
            "taxRate": ILLINOIS_TAX_RATE,
            "markupConfig": MARKUP_BY_CATEGORY,
            "issueCount": len(report.issues),
            "autoFixCount": len(report.fixes),
        }
        write_json(meta, output_dir / "meta.json")

    report.print_summary()

    if (args.strict or args.validate_only) and report.has_unfixed_issues:
        print("Exiting with code 1 due to unfixed issues.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

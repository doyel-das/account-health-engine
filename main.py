#!/usr/bin/env python3
"""CLI entrypoint for the account health scoring engine."""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

import scorer
import generate_data
import report as report_module

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
ACCOUNTS_CSV = DATA_DIR / "accounts.csv"
DB_PATH = DATA_DIR / "health.db"


def print_table(results):
    has_delta = any(r.get("delta") is not None for r in results)
    delta_header = f"{'Δ':>7}" if has_delta else ""
    header = f"{'Acct':<8}{'Name':<30}{'Seg':<11}{'Score':>7}  {'Tier':<8}{'Renew(d)':>9}{'ARR':>12}{delta_header}  Override"
    print(header)
    print("-" * len(header))
    for r in results:
        override_flag = "!" if r["overrides"] else ""
        arr = r["arr"] or 0
        delta_str = ""
        if has_delta:
            delta = r.get("delta")
            delta_str = f"{'—' if delta is None else (('+' if delta >= 0 else '') + str(delta)):>7}"
        print(f"{r['account_id']:<8}{r['account_name'][:29]:<30}{r['segment']:<11}"
              f"{r['health_score']:>7.1f}  {r['tier']:<8}{r['days_to_renewal']:>9}{arr:>12,.0f}{delta_str}  {override_flag}")


def print_detail(results):
    for r in results:
        delta_str = ""
        if r.get("delta") is not None:
            sign = "+" if r["delta"] >= 0 else ""
            delta_str = f"  (Δ {sign}{r['delta']} vs prior run)"
        print(f"\n=== {r['account_name']} ({r['account_id']}) — {r['health_score']} {r['tier']}{delta_str} ===")
        if r["overrides"]:
            print("OVERRIDES TRIGGERED:")
            for o in r["overrides"]:
                print(f"  - {o}")
        print(f"{'Metric':<32}{'Raw':>10}{'Norm':>8}{'Weight%':>9}  Note")
        for b in r["breakdown"]:
            raw = "—" if b["raw_value"] is None else b["raw_value"]
            norm = "—" if b["normalized"] is None else b["normalized"]
            note = b["reason"] or ("proxy value" if b["is_proxy"] else "")
            print(f"{b['label']:<32}{str(raw):>10}{str(norm):>8}{b['effective_weight_pct']:>9}  {note}")
        print(f"Urgency score: {r['urgency_score']}")
        print(f"Intervention: {r['intervention']}")


def export_csv(results, path):
    fieldnames = ["account_id", "account_name", "segment", "csm", "arr", "days_to_renewal",
                  "health_score", "tier", "urgency_score", "overrides", "intervention"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "account_id": r["account_id"], "account_name": r["account_name"],
                "segment": r["segment"], "csm": r["csm"], "arr": r["arr"],
                "days_to_renewal": r["days_to_renewal"], "health_score": r["health_score"],
                "tier": r["tier"], "urgency_score": r["urgency_score"],
                "overrides": "; ".join(r["overrides"]), "intervention": r["intervention"],
            })
    print(f"Exported {len(results)} rows to {path}")


def compute_trend_deltas(results, prior_path):
    prior = {}
    with open(prior_path, newline="") as f:
        for row in csv.DictReader(f):
            prior[row["account_id"]] = float(row["health_score"])
    for r in results:
        prev = prior.get(r["account_id"])
        r["delta"] = round(r["health_score"] - prev, 1) if prev is not None else None
    return results


def run_queries(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    print("\n-- Tier breakdown is computed at scoring time, not stored in SQL --")
    print("-- (see the scored portfolio table above for tier counts/ARR/avg score) --")

    print("\n-- CSM performance: avg account ARR and account count per CSM --")
    cur.execute("""
        SELECT csm, COUNT(*) as accounts, ROUND(AVG(arr), 0) as avg_arr
        FROM accounts GROUP BY csm ORDER BY accounts DESC
    """)
    for csm, count, avg_arr in cur.fetchall():
        print(f"{csm:<15}{count:>4} accounts   avg ARR ${avg_arr:,.0f}")

    print("\n-- Accounts renewing within 90 days --")
    cur.execute("""
        SELECT account_name, days_to_renewal, arr FROM accounts
        WHERE days_to_renewal <= 90 ORDER BY days_to_renewal
    """)
    for name, days, arr in cur.fetchall():
        print(f"{name:<32}{days:>5}d   ${arr:,.0f}")

    conn.close()


def run_validation(results, outcomes_path, config):
    outcomes = {}
    with open(outcomes_path, newline="") as f:
        for row in csv.DictReader(f):
            outcomes[row["account_id"]] = int(row["churned"])

    tp = fp = fn = tn = 0
    for r in results:
        predicted_risk = r["tier"] in ("Red",) or bool(r["overrides"])
        actual_churn = outcomes.get(r["account_id"])
        if actual_churn is None:
            continue
        if predicted_risk and actual_churn:
            tp += 1
        elif predicted_risk and not actual_churn:
            fp += 1
        elif not predicted_risk and actual_churn:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print(f"\nValidation against {outcomes_path}")
    print(f"TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"Precision: {precision:.2f}  (target >= 0.65)")
    print(f"Recall:    {recall:.2f}  (target >= 0.70)")
    print(f"F1:        {f1:.2f}")

    if recall < 0.70:
        print("Recall is below target — consider lowering the red_ceiling (score_bands.red upper bound) "
              "to flag more accounts as Red.")
    if precision < 0.50:
        print("Precision is below target — consider raising the red_ceiling to reduce false positives.")


def main():
    parser = argparse.ArgumentParser(description="Account health scoring engine")
    parser.add_argument("--segment", choices=["enterprise", "smb"], help="Filter by segment")
    parser.add_argument("--profile", help="Use a saved weight profile (e.g. renewal_push)")
    parser.add_argument("--prior", help="Path to a prior scoring CSV to compute trend deltas")
    parser.add_argument("--export-csv", help="Export full results to this CSV path")
    parser.add_argument("--detail", action="store_true", help="Print full signal breakdown per account")
    parser.add_argument("--generate-data", action="store_true", help="Regenerate synthetic data")
    parser.add_argument("--queries", action="store_true", help="Run leadership portfolio SQL queries")
    parser.add_argument("--validate", help="Path to outcomes.csv for precision/recall validation")
    parser.add_argument("--report", action="store_true", help="Generate the HTML report")
    args = parser.parse_args()

    if args.generate_data:
        generate_data.generate()
        if not (args.queries or args.validate or args.detail or args.export_csv or args.report):
            return

    if not ACCOUNTS_CSV.exists():
        print(f"No data found at {ACCOUNTS_CSV}. Run with --generate-data first.", file=sys.stderr)
        sys.exit(1)

    config = scorer.load_config()
    accounts = scorer.load_accounts_csv(ACCOUNTS_CSV)
    results = scorer.score_portfolio(accounts, config, profile=args.profile, segment_filter=args.segment)
    results = scorer.sort_by_urgency(results)

    if args.prior:
        results = compute_trend_deltas(results, args.prior)

    if args.detail:
        print_detail(results)
    else:
        print_table(results)

    if args.export_csv:
        export_csv(results, args.export_csv)

    if args.queries:
        run_queries(DB_PATH)

    if args.validate:
        run_validation(results, args.validate, config)

    if args.report:
        report_module.generate_report(results, config, DB_PATH, ROOT / "output" / "health_report.html")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Full pipeline: generate synthetic data, score the portfolio, build the HTML report."""
from pathlib import Path

import generate_data
import scorer
import report as report_module
from main import print_table, export_csv

ROOT = Path(__file__).parent


def main():
    print("Step 1/3: Generating synthetic data...")
    generate_data.generate()

    print("\nStep 2/3: Scoring portfolio...")
    config = scorer.load_config()
    accounts = scorer.load_accounts_csv(ROOT / "data" / "accounts.csv")
    results = scorer.score_portfolio(accounts, config)
    results = scorer.sort_by_urgency(results)
    print_table(results)
    export_csv(results, ROOT / "output" / "scored_accounts.csv")

    print("\nStep 3/3: Building HTML report...")
    report_module.generate_report(results, config, ROOT / "data" / "health.db",
                                   ROOT / "output" / "health_report.html")

    print("\nDone. Open output/health_report.html in a browser.")


if __name__ == "__main__":
    main()

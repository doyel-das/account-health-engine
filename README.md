**[→ Live interactive demo](https://doyel-das.github.io/account-health-engine)**

# Account Health Engine

A configurable account health scoring engine for B2B SaaS customer success teams,
built against a synthetic healthcare AI SaaS portfolio. It scores accounts 0–100
across seven weighted signals, applies override rules that escalate accounts
regardless of score, ranks the portfolio by renewal urgency (not just health),
and produces a self-contained HTML report with trend charts and Claude-drafted
intervention emails.

This is a rule-based engine, not a machine learning model — every score and
recommendation is traceable to a specific input and a specific rule.

**Live demo:** [doyel-das.github.io/account-health-engine](https://doyel-das.github.io/account-health-engine/)
— a static snapshot of `output/health_report.html` served via GitHub Pages.
The "Draft intervention email" button on the Accounts tab calls the Anthropic
API directly from your browser; it will prompt for your own API key (stored
only in your browser's `localStorage`, never sent anywhere but Anthropic) —
no key is bundled in the page.

## What it does

- Reads accounts from `data/accounts.csv` (or a SQLite database for richer detail)
- Scores each account using 7 configurable, weighted signals
- Assigns risk tiers — Red (0–40), Yellow (41–70), Green (71–100)
- Applies override conditions that force an account to Red regardless of its
  computed score (e.g. a renewal in 30 days, silent churn, churn language from
  the CSM)
- Ranks the portfolio by **urgency**, not raw health score, so a mediocre
  account renewing next week outranks a worse account renewing next year
- Outputs a terminal table, a CSV export, a SQLite database, and a
  self-contained HTML report with portfolio trends, per-account drill-in,
  user-level detail, CSM pulse history, and AI-drafted intervention emails

## Project structure

```
account_health_engine/
├── main.py              # CLI entrypoint
├── run.py               # Full pipeline: generate data → score → report
├── scorer.py            # Core scoring engine
├── generate_data.py     # Synthetic data generator
├── report.py            # HTML report generator
├── README.md
├── config/
│   └── weights.json     # Weight config, normalization specs, saved profiles
├── data/                # Created at runtime (CSVs + SQLite DB)
└── output/              # Created at runtime (HTML report, CSV exports)
```

## Quickstart

```bash
python run.py   # uses only the Python standard library — nothing to install
```

`run.py` generates the synthetic portfolio, scores it, and writes
`output/health_report.html`. Open that file in any browser — it has no
external dependencies (no CDN scripts, no build step).

## CLI usage

```bash
python main.py                              # score from data/accounts.csv
python main.py --segment enterprise         # filter by segment
python main.py --profile renewal_push       # use a saved weight profile
python main.py --prior data/prior_run.csv   # compute score trend deltas
python main.py --export-csv results.csv     # export full results
python main.py --detail                     # print full signal breakdown per account
python main.py --generate-data              # regenerate synthetic data
python main.py --queries                    # run leadership portfolio SQL queries
python main.py --validate data/outcomes.csv # precision/recall vs. known churn outcomes
python main.py --report                     # write output/health_report.html
```

## Input fields

| Field | Description |
|---|---|
| `account_id` | Unique account identifier |
| `account_name` | Display name |
| `segment` | `enterprise` or `smb` — determines which weight table applies |
| `arr` | Annual recurring revenue |
| `csm` | Assigned customer success manager |
| `renewal_date` / `days_to_renewal` | Contract renewal date and days remaining |
| `login_freq_per_wk` | Average sessions per week (higher is better) |
| `feature_adoption_pct` | % of available features used, 0–100 (higher is better) |
| `support_tickets_per_mo` | Support tickets opened per month (lower is better) |
| `days_since_engagement` | Days since the last meaningful touchpoint (lower is better) |
| `onboarding_completion_pct` | % of onboarding completed, 0–100 (higher is better) |
| `nps_raw` | Raw NPS response, 0–10. ≥9 = promoter, 7–8 = passive, ≤6 = detractor |
| `csm_pulse` | CSM's structured read of account sentiment, 1–5 (see rubric below) |

## CSM pulse rubric

| Score | Meaning |
|---|---|
| 1 | Churn language — customer has explicitly signaled intent to leave or evaluate alternatives |
| 2 | Dissatisfied — recurring friction, complaints, or disengagement from the champion |
| 3 | Neutral — steady, unremarkable, transactional relationship |
| 4 | Stable — healthy, responsive relationship with no red flags |
| 5 | Expansion-ready — actively asking about more seats, modules, or use cases |

## Scoring methodology

Each signal is normalized to a 0–100 scale (percentages are used as-is;
rate-based and count-based signals are linearly scaled against a configured
min/max, inverted for "lower is better" signals), then combined as a weighted
average using the segment's weight table.

**Enterprise weights**

| Signal | Weight |
|---|---|
| Login frequency | 15% |
| Feature adoption | 15% |
| Support tickets | 10% |
| Days since engagement | 10% |
| Onboarding completion | 10% |
| NPS | 10% |
| CSM pulse | 30% |

**SMB weights**

| Signal | Weight |
|---|---|
| Login frequency | 25% |
| Feature adoption | 20% |
| Support tickets | 15% |
| Days since engagement | 15% |
| Onboarding completion | 15% |
| NPS | 10% |
| CSM pulse | 0% (not available — SMB accounts are not assigned a dedicated CSM) |

Score bands (`config/weights.json` → `score_bands`): Red 0–40, Yellow 41–70,
Green 71–100.

### Missing data handling

If a signal is `null`/missing in the source data, or marked
`"available": false` for the segment, it is **excluded** from that account's
score and the remaining weights are renormalized to sum to 100%. An account is
never penalized for a metric it doesn't report.

**Exception — silent disengagement proxy:** if `nps_raw` is missing *and*
`days_since_engagement >= 14`, the engine treats the missing NPS as a
detractor proxy (`2.0` on the 0–10 scale) instead of excluding it. The
reasoning: an account that has gone quiet long enough to also have no NPS data
is showing the same signal a detractor score would — silence is informative,
not neutral.

### Override conditions

These escalate an account to Red regardless of its computed score:

1. Renewal within 30 days **and** score < 70
2. Already Red **and** renewal within 90 days
3. Login frequency < 0.5/week **and** ≥14 days since engagement (silent churn)
4. `csm_pulse == 1` (explicit churn language)

Overrides are evaluated against raw signal values, so a churn-language pulse
score still triggers an override even on a segment (SMB) where `csm_pulse` is
excluded from the weighted score itself.

### Urgency ranking

The portfolio table is sorted by **urgency**, not health score:

```
urgency = health_score − renewal_proximity_penalty − override_penalty
```

Renewal proximity penalty scales with how soon the contract renews (steepest
inside 30 days); the override penalty is a flat deduction when any override is
active. This means a Yellow account renewing in 10 days outranks a Red account
renewing in 200 days — the table reflects what needs attention *this week*,
not just what scores worst.

## Saved weight profiles

Defined in `config/weights.json` → `profiles`, selected via `--profile`:

- **`renewal_push`** — upweights `days_since_engagement` (20%) and
  `support_tickets_per_mo` (15%) for accounts approaching a renewal decision.
- **`new_account_onboarding`** — upweights `onboarding_completion_pct` (30%)
  and `feature_adoption_pct` (20–25%) for early-lifecycle accounts where
  onboarding execution is the leading risk signal.

Each profile defines a full weight table per segment (not a delta), so the
weights always sum to 100% per segment without runtime rebalancing logic.

## HTML report

`python run.py` or `python main.py --report` writes
`output/health_report.html` — a single file with no external JS/CSS, built
with vanilla canvas charts.

- **Portfolio tab** — summary metrics (accounts scored, avg score, tier
  counts, renewals in 90 days, total and at-risk ARR) and a sortable account
  table. Override accounts show a red `!` badge; clicking a row jumps to that
  account's card in the Accounts tab.
- **Trends tab** — portfolio average score over 6 weeks, a per-account
  multi-line trend chart with show/hide toggles, and a stacked Green/Yellow/Red
  tier distribution chart.
- **Accounts tab** — one expandable card per account with the full signal
  breakdown (raw value, normalized score, effective post-renormalization
  weight, and an "excluded — not collected" note for unavailable metrics), a
  90-day trend chart, the account's users with individual risk tiers, CSM
  pulse history, the recommended intervention, and a **"Draft intervention
  email"** button.

The draft button calls the Anthropic API directly from the browser
(`claude-sonnet-4-6`, `max_tokens: 1000`) with the account's context loaded
into the system prompt. It prompts once for an API key and stores it in
`localStorage` — there is no backend and no key is bundled into the report.
The draft is for the CSM to read and send manually; there is no email
integration.

## Validation mode

```bash
python main.py --validate data/outcomes.csv
```

`outcomes.csv` format: `account_id,churned` (0 or 1). The engine treats any
account that is Red, or has an active override, as a "predicted risk" and
compares against the known outcome to report:

- True positives, false positives, false negatives, true negatives
- Precision, recall, F1

Target benchmarks: precision ≥ 0.65, recall ≥ 0.70. If recall falls short, the
guidance is to **lower** the Red ceiling (catch more at-risk accounts, accept
more false positives). If precision falls short, **raise** it (fewer, higher
-confidence Red calls).

## Known limitations

1. **Activity is a proxy for value, not value itself.** Login frequency and
   feature adoption measure usage, not whether the product is actually solving
   the customer's problem.
2. **Account-level aggregation hides user-level risk.** A healthy aggregate
   score can mask a disengaged executive sponsor — the User tier in the
   Accounts tab is a partial mitigation, not a fix.
3. **Weights are illustrative, not empirically validated.** They reflect
   reasonable CS judgment, not a fitted model against real churn outcomes.
4. **CSM pulse is inherently subjective.** It is the highest-weighted signal
   for enterprise accounts and is also the least standardized.
5. **This is a static snapshot, not a live system.** It reflects whatever was
   in `data/accounts.csv` at generation time; there is no streaming ingestion.
6. **The underlying data is synthetic and illustrative**, generated to exercise
   the scoring logic and override conditions — it is not real customer data
   and the specific numbers should not be read as benchmarks.
7. **False positive fatigue is a real operational risk.** Aggressive override
   rules (e.g. any renewal within 90 days of a Red score) can flood a CS team
   with escalations if thresholds aren't tuned against actual outcomes via
   `--validate`.

## Methodology references

This engine's structure — weighted signal scoring, tiering, override rules,
and an urgency-vs-health distinction — follows patterns documented by:

- [Gainsight](https://www.gainsight.com/) — health scorecards and CS Ops methodology
- [Vitally](https://www.vitally.io/) — account health and segmentation practices
- [ChurnZero](https://churnzero.com/) — churn risk scoring and playbooks
- [TSIA](https://www.tsia.com/) — Technology & Services Industry Association research on customer success metrics

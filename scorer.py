"""Core scoring engine: signal normalization, weighting, overrides, urgency, intervention text."""
import csv
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config" / "weights.json"

METRICS = [
    "login_freq_per_wk", "feature_adoption_pct", "support_tickets_per_mo",
    "days_since_engagement", "onboarding_completion_pct", "nps_raw", "csm_pulse",
]

METRIC_LABELS = {
    "login_freq_per_wk": "Login frequency (per week)",
    "feature_adoption_pct": "Feature adoption %",
    "support_tickets_per_mo": "Support tickets per month",
    "days_since_engagement": "Days since last engagement",
    "onboarding_completion_pct": "Onboarding completion %",
    "nps_raw": "NPS (raw)",
    "csm_pulse": "CSM pulse",
}


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_weights(config, segment, profile=None):
    if profile:
        return config["profiles"][profile][segment]
    return config["segments"][segment]


def normalize_value(metric, raw_value, config):
    spec = config["normalization"][metric]
    if spec["type"] == "percent":
        return clamp(float(raw_value), 0, 100)
    if spec["type"] == "linear":
        lo, hi = spec["min"], spec["max"]
        return clamp((float(raw_value) - lo) / (hi - lo) * 100, 0, 100)
    if spec["type"] == "inverted_linear":
        lo, hi = spec["min"], spec["max"]
        return clamp(100 - (float(raw_value) - lo) / (hi - lo) * 100, 0, 100)
    raise ValueError(f"Unknown normalization type for {metric}")


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def is_missing(value):
    return value is None or value == "" or (isinstance(value, str) and value.strip() == "")


def score_account(account, config, segment, profile=None):
    """Returns dict with health_score, tier, signal breakdown, overrides, urgency."""
    weights = get_weights(config, segment, profile)

    nps_value = account.get("nps_raw")
    nps_is_proxy = False
    if is_missing(nps_value):
        proxy_cfg = config["nps_proxy"]
        days_since = account.get("days_since_engagement")
        if not is_missing(days_since) and float(days_since) >= proxy_cfg["days_since_engagement_at_least"]:
            nps_value = proxy_cfg["proxy_value"]
            nps_is_proxy = True

    raw_values = dict(account)
    raw_values["nps_raw"] = nps_value

    breakdown = []
    weighted_sum = 0.0
    total_weight = 0.0
    for metric in METRICS:
        metric_cfg = weights[metric]
        configured_available = metric_cfg.get("available", True)
        raw = raw_values.get(metric)
        included = configured_available and not is_missing(raw)
        normalized = None
        effective_weight = 0.0
        reason = None
        if included:
            normalized = normalize_value(metric, raw, config)
            effective_weight = metric_cfg["weight"]
            weighted_sum += normalized * effective_weight
            total_weight += effective_weight
        else:
            reason = "excluded — not collected" if not configured_available else "excluded — missing data"
        breakdown.append({
            "metric": metric,
            "label": METRIC_LABELS[metric],
            "raw_value": raw,
            "normalized": round(normalized, 1) if normalized is not None else None,
            "configured_weight": metric_cfg["weight"],
            "included": included,
            "is_proxy": metric == "nps_raw" and nps_is_proxy,
            "reason": reason,
        })

    health_score = round(weighted_sum / total_weight, 1) if total_weight > 0 else 0.0

    # renormalize effective weights for display (post-hoc, after we know total_weight)
    for b in breakdown:
        if b["included"]:
            b["effective_weight_pct"] = round(b["configured_weight"] / total_weight * 100, 1)
        else:
            b["effective_weight_pct"] = 0.0

    tier, overrides = apply_overrides(account, health_score, config)
    urgency = compute_urgency(health_score, account, overrides)
    intervention = recommend_intervention(tier, overrides, account)

    return {
        "account_id": account.get("account_id"),
        "health_score": health_score,
        "tier": tier,
        "overrides": overrides,
        "breakdown": breakdown,
        "urgency_score": urgency,
        "intervention": intervention,
    }


def tier_from_score(score, bands):
    for tier_name, (lo, hi) in bands.items():
        if lo <= score <= hi:
            return tier_name.capitalize()
    return "Yellow"


def apply_overrides(account, health_score, config):
    cfg = config["overrides"]
    bands = config["score_bands"]
    base_tier = tier_from_score(health_score, bands)

    triggered = []
    days_to_renewal = account.get("days_to_renewal")
    days_to_renewal = float(days_to_renewal) if not is_missing(days_to_renewal) else None

    rule = cfg["renewal_score_threshold"]
    if days_to_renewal is not None and days_to_renewal <= rule["renewal_days_at_most"] and health_score < rule["score_below"]:
        triggered.append(f"Renewal within {rule['renewal_days_at_most']} days and score below {rule['score_below']}")

    if base_tier == "Red" and days_to_renewal is not None and days_to_renewal <= cfg["red_renewal_window_days"]:
        triggered.append(f"Red account renewing within {cfg['red_renewal_window_days']} days")

    sc = cfg["silent_churn"]
    login_freq = account.get("login_freq_per_wk")
    days_since_eng = account.get("days_since_engagement")
    if not is_missing(login_freq) and not is_missing(days_since_eng):
        if float(login_freq) < sc["login_freq_below"] and float(days_since_eng) >= sc["days_since_engagement_at_least"]:
            triggered.append("Silent churn: login frequency below 0.5/wk and 14+ days since engagement")

    csm_pulse = account.get("csm_pulse")
    if not is_missing(csm_pulse) and int(float(csm_pulse)) == cfg["csm_pulse_churn_language"]:
        triggered.append("CSM pulse = 1 (churn language reported)")

    tier = "Red" if triggered else base_tier
    return tier, triggered


def compute_urgency(health_score, account, overrides):
    days_to_renewal = account.get("days_to_renewal")
    days_to_renewal = float(days_to_renewal) if not is_missing(days_to_renewal) else 999

    if days_to_renewal <= 30:
        renewal_penalty = 30
    elif days_to_renewal <= 60:
        renewal_penalty = 15
    elif days_to_renewal <= 90:
        renewal_penalty = 5
    else:
        renewal_penalty = 0

    override_penalty = 25 if overrides else 0
    return round(health_score - renewal_penalty - override_penalty, 1)


def recommend_intervention(tier, overrides, account):
    days_to_renewal = account.get("days_to_renewal")
    days_to_renewal = float(days_to_renewal) if not is_missing(days_to_renewal) else None

    silent_churn = any("Silent churn" in o for o in overrides)
    pulse_one = any("CSM pulse = 1" in o for o in overrides)

    if overrides:
        if pulse_one:
            return ("CSM Pulse override (churn language): treat as Red. Schedule an executive "
                    "sponsor call within 48 hours regardless of score or renewal date.")
        if silent_churn:
            return ("Silent churn override: map all stakeholders across the account and re-engage "
                    "via phone or in-person outreach only — do not rely on email.")
        if days_to_renewal is not None and days_to_renewal <= 30:
            return ("Override active with renewal in ≤30 days: same-day escalation, loop in the "
                    "CS leader, do not rely on email. Save rate inside 30 days of renewal is below 18%.")
        return ("Override active with renewal beyond 30 days: escalate to the CS leader within 48 "
                "hours and run a full account review.")

    if tier == "Red":
        return ("Red (no override): CSM action within 48 hours, full account review, and "
                "executive sponsor contact.")
    if tier == "Yellow":
        return ("Yellow: proactive outreach within 5 business days and a feature adoption audit.")
    # Green
    if days_to_renewal is not None and days_to_renewal <= 90:
        return ("Green with renewal ≤90 days out: begin the renewal conversation and "
                "introduce expansion positioning.")
    return "Green: maintain current cadence and monitor for drift."


def load_accounts_csv(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def coerce_account_types(row):
    """CSV rows are all strings; coerce numeric fields, leaving blanks as None."""
    out = dict(row)
    int_fields = {"days_to_renewal", "days_since_engagement"}
    float_fields = {"arr", "login_freq_per_wk", "feature_adoption_pct", "support_tickets_per_mo",
                     "onboarding_completion_pct", "nps_raw", "csm_pulse"}
    for k, v in out.items():
        if is_missing(v):
            out[k] = None
            continue
        if k in int_fields:
            out[k] = int(float(v))
        elif k in float_fields:
            out[k] = float(v)
    return out


def score_portfolio(accounts, config, profile=None, segment_filter=None):
    results = []
    for raw_account in accounts:
        account = coerce_account_types(raw_account)
        if segment_filter and account.get("segment") != segment_filter:
            continue
        result = score_account(account, config, account["segment"], profile)
        result["account_name"] = account.get("account_name")
        result["segment"] = account.get("segment")
        result["arr"] = account.get("arr")
        result["csm"] = account.get("csm")
        result["days_to_renewal"] = account.get("days_to_renewal")
        result["renewal_date"] = account.get("renewal_date")
        results.append(result)
    return results


def sort_by_urgency(results):
    return sorted(results, key=lambda r: r["urgency_score"])


def fetch_score_history(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT account_id, week_ending, health_score FROM score_history ORDER BY week_ending")
    rows = cur.fetchall()
    conn.close()
    history = {}
    for account_id, week_ending, score in rows:
        history.setdefault(account_id, []).append({"week_ending": week_ending, "health_score": score})
    return history


def fetch_users(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT account_id, user_name, role, role_type, logins_per_wk, days_since_active, nps FROM users")
    rows = cur.fetchall()
    conn.close()
    users = {}
    for account_id, name, role, role_type, logins, days_inactive, nps in rows:
        users.setdefault(account_id, []).append({
            "user_name": name, "role": role, "role_type": role_type,
            "logins_per_wk": logins, "days_since_active": days_inactive, "nps": nps,
        })
    return users


def fetch_pulse_log(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT account_id, date, csm, pulse_score, notes FROM csm_pulse_log ORDER BY date")
    rows = cur.fetchall()
    conn.close()
    log = {}
    for account_id, d, csm, pulse, notes in rows:
        log.setdefault(account_id, []).append({"date": d, "csm": csm, "pulse_score": pulse, "notes": notes})
    return log

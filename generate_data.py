"""Synthetic data generator for the account health scoring engine.

Generates a small, realistic-looking healthcare AI SaaS portfolio:
accounts, users, weekly score history, and CSM pulse logs. Writes CSVs
and a SQLite database under data/.
"""
import csv
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

LAST_NAMES = [
    "Okafor", "Mehta", "Rivera", "Chen", "Webb", "Tanaka", "Patel", "Diallo",
    "Zhang", "Kim", "Santos", "Hassan", "Williams", "Nguyen", "Al-Rashid",
]
FIRST_NAMES = [
    "Maria", "Raj", "James", "Wei", "Sarah", "Kenji", "Anita", "Amara",
    "Lin", "Soo-Jin", "Carlos", "Layla", "David", "Mai", "Omar",
]

ROLES = [
    ("Chief Medical Officer", "executive"),
    ("Hospitalist", "clinician"),
    ("Emergency Medicine", "clinician"),
    ("IT/Admin", "admin"),
]

ARCHETYPES = {
    "critical":   dict(login_rate=0.20, feature_pct=28, tickets=3.2, engagement_days=18, onboarding=95, csm_pulse=1),
    "declining":  dict(login_rate=0.40, feature_pct=42, tickets=2.1, engagement_days=12, onboarding=90, csm_pulse=2),
    "stagnant":   dict(login_rate=0.55, feature_pct=50, tickets=1.4, engagement_days=7,  onboarding=80, csm_pulse=3),
    "recovering": dict(login_rate=0.70, feature_pct=62, tickets=0.9, engagement_days=4,  onboarding=88, csm_pulse=4),
    "healthy":    dict(login_rate=0.88, feature_pct=78, tickets=0.5, engagement_days=2,  onboarding=97, csm_pulse=4),
}

ACCOUNTS = [
    ("ACC001", "Midwest Health System", "enterprise", 480000, 22, "critical"),
    ("ACC002", "Valley Medical Group", "enterprise", 310000, 68, "declining"),
    ("ACC003", "Coastal Physician Partners", "smb", 85000, 44, "stagnant"),
    ("ACC004", "Summit Regional Health", "enterprise", 275000, 112, "recovering"),
    ("ACC005", "Northern Integrated Care", "smb", 72000, 180, "healthy"),
    ("ACC006", "Lakewood Hospitalist Group", "smb", 55000, 210, "contradictory"),
    ("ACC007", "Pacific Academic Medical Ctr", "enterprise", 620000, 95, "healthy"),
    ("ACC008", "Tri-County Urgent Care", "smb", 48000, 15, "critical"),
    ("ACC009", "Heartland Health Network", "enterprise", 390000, 60, "stagnant"),
    ("ACC010", "Blue Ridge Medical Partners", "smb", 63000, 140, "recovering"),
    ("ACC011", "Metro Surgical Associates", "smb", 41000, 30, "declining"),
    ("ACC012", "Cascade Regional Hospital", "enterprise", 510000, 200, "healthy"),
]

CSMS = ["M. Okafor", "R. Mehta", "J. Rivera", "S. Tanaka", "A. Diallo"]

PULSE_NOTES = {
    1: [
        "Customer mentioned evaluating alternative vendors during QBR.",
        "Exec sponsor said the team is 'not seeing the value anymore.'",
        "Renewal conversation stalled; champion went quiet after escalation.",
    ],
    2: [
        "Frustration with support response times raised again this week.",
        "Usage dropped sharply after the champion's team reorg.",
        "Open ticket backlog is creating visible friction with clinicians.",
    ],
    3: [
        "No major news either way; steady but unremarkable usage.",
        "Champion responsive but engagement is mostly transactional.",
        "Nothing escalated this cycle; holding pattern continues.",
    ],
    4: [
        "Champion proactively shared a positive internal usage report.",
        "Onboarding of new unit went smoothly, team is engaged.",
        "Stable relationship, regular cadence maintained without issues.",
    ],
    5: [
        "Customer asked about expansion to two additional facilities.",
        "Champion is referenceable and open to a case study.",
        "Strong executive sponsorship, actively asking about new modules.",
    ],
}


def jitter(value, pct=0.15, rng=random):
    return value * (1 + rng.uniform(-pct, pct))


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def gen_account_row(acc_id, name, segment, arr, renewal_days, archetype, rng):
    if archetype == "contradictory":
        params = dict(login_rate=1.1, feature_pct=55, tickets=1.0, engagement_days=3, onboarding=85, csm_pulse=None)
    else:
        params = ARCHETYPES[archetype]

    login_freq = round(clamp(jitter(params["login_rate"], rng=rng), 0, 5), 2)

    feature_pct = round(clamp(jitter(params["feature_pct"], rng=rng), 0, 100), 1)
    tickets = round(clamp(jitter(params["tickets"], rng=rng), 0, 10), 2)
    engagement_days = round(clamp(jitter(params["engagement_days"], rng=rng), 0, 60))
    onboarding = round(clamp(jitter(params["onboarding"], rng=rng), 0, 100), 1)
    csm_pulse = params["csm_pulse"]

    nps_raw = None
    if archetype == "contradictory":
        nps_raw = 9
    elif csm_pulse is not None:
        base_nps = {1: 2, 2: 4, 3: 6, 4: 8, 5: 9.5}[csm_pulse]
        nps_raw = round(clamp(jitter(base_nps, rng=rng), 0, 10), 1)
    else:
        nps_raw = round(clamp(jitter(6, rng=rng), 0, 10), 1)

    # randomly null out per spec
    if rng.random() < 0.10:
        nps_raw = None
    if archetype != "contradictory" and rng.random() < 0.20:
        csm_pulse = None
    if rng.random() < 0.08:
        feature_pct = None

    renewal_date = date.today() + timedelta(days=renewal_days)

    return {
        "account_id": acc_id,
        "account_name": name,
        "segment": segment,
        "arr": arr,
        "csm": rng.choice(CSMS),
        "renewal_date": renewal_date.isoformat(),
        "days_to_renewal": renewal_days,
        "login_freq_per_wk": login_freq,
        "feature_adoption_pct": feature_pct,
        "support_tickets_per_mo": tickets,
        "days_since_engagement": engagement_days,
        "onboarding_completion_pct": onboarding,
        "nps_raw": nps_raw,
        "csm_pulse": csm_pulse,
        "_archetype": archetype,
    }


def gen_users(account_row, rng):
    n_users = rng.randint(3, 5)
    roles = ROLES + [ROLES[rng.randrange(len(ROLES))] for _ in range(max(0, n_users - len(ROLES)))]
    roles = roles[:n_users]
    users = []
    used_names = set()
    for role_title, role_type in roles:
        while True:
            full_name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if full_name not in used_names:
                used_names.add(full_name)
                break
        archetype = account_row["_archetype"]
        if role_type == "executive" and archetype in ("critical", "declining"):
            logins_wk = round(clamp(jitter(0.1, pct=0.5, rng=rng), 0, 1), 2)
            days_since_active = round(clamp(jitter(25, rng=rng), 5, 60))
        else:
            base_login = account_row["login_freq_per_wk"] or 0.5
            logins_wk = round(clamp(jitter(base_login, rng=rng), 0, 6), 2)
            days_since_active = round(clamp(jitter(account_row["days_since_engagement"] or 5, rng=rng), 0, 45))
        nps_user = account_row["nps_raw"]
        nps_user = round(clamp(jitter(nps_user, rng=rng), 0, 10), 1) if nps_user is not None else None
        users.append({
            "account_id": account_row["account_id"],
            "user_name": full_name,
            "role": role_title,
            "role_type": role_type,
            "logins_per_wk": logins_wk,
            "days_since_active": days_since_active,
            "nps": nps_user,
        })
    return users


def gen_score_history(account_row, rng):
    """6 weekly snapshots trending toward the current state."""
    history = []
    current_login = account_row["login_freq_per_wk"] or 0.5
    current_feature = account_row["feature_adoption_pct"] or 50
    current_csm = account_row["csm_pulse"] or 3
    archetype = account_row["_archetype"]
    trend_sign = {"recovering": -1, "declining": 1, "critical": 1, "stagnant": 0, "healthy": 0, "contradictory": 0}[archetype]

    today = date.today()
    for i in range(6, 0, -1):
        week_date = today - timedelta(weeks=i - 1)
        drift = trend_sign * (i - 1) * rng.uniform(0.03, 0.06)
        login = clamp(current_login * (1 - drift), 0, 5)
        feature = clamp(current_feature * (1 - drift), 0, 100)
        csm_pulse = clamp(current_csm + (drift * 3 if trend_sign else 0), 1, 5)
        proxy_score = (login / 3 * 30) + (feature / 100 * 30) + (csm_pulse / 5 * 40)
        proxy_score = round(clamp(proxy_score, 5, 98), 1)
        history.append({
            "account_id": account_row["account_id"],
            "week_ending": week_date.isoformat(),
            "health_score": proxy_score,
        })
    return history


def gen_pulse_log(account_row, rng):
    csm = account_row["csm"]
    pulse = account_row["csm_pulse"] or 3
    entries = []
    today = date.today()
    for i in range(3):
        entry_date = today - timedelta(weeks=(i + 1) * 3)
        p = int(clamp(round(jitter(pulse, pct=0.2, rng=rng)), 1, 5))
        note = rng.choice(PULSE_NOTES[p])
        entries.append({
            "account_id": account_row["account_id"],
            "date": entry_date.isoformat(),
            "csm": csm,
            "pulse_score": p,
            "notes": note,
        })
    return list(reversed(entries))


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_sqlite(accounts, users, history, pulses):
    db_path = DATA_DIR / "health.db"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE accounts (
            account_id TEXT PRIMARY KEY, account_name TEXT, segment TEXT, arr REAL,
            csm TEXT, renewal_date TEXT, days_to_renewal INTEGER,
            login_freq_per_wk REAL, feature_adoption_pct REAL, support_tickets_per_mo REAL,
            days_since_engagement INTEGER, onboarding_completion_pct REAL,
            nps_raw REAL, csm_pulse INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE users (
            account_id TEXT, user_name TEXT, role TEXT, role_type TEXT,
            logins_per_wk REAL, days_since_active INTEGER, nps REAL
        )
    """)
    cur.execute("""
        CREATE TABLE score_history (
            account_id TEXT, week_ending TEXT, health_score REAL
        )
    """)
    cur.execute("""
        CREATE TABLE csm_pulse_log (
            account_id TEXT, date TEXT, csm TEXT, pulse_score INTEGER, notes TEXT
        )
    """)
    for a in accounts:
        cur.execute(
            "INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (a["account_id"], a["account_name"], a["segment"], a["arr"], a["csm"],
             a["renewal_date"], a["days_to_renewal"], a["login_freq_per_wk"],
             a["feature_adoption_pct"], a["support_tickets_per_mo"], a["days_since_engagement"],
             a["onboarding_completion_pct"], a["nps_raw"], a["csm_pulse"])
        )
    for u in users:
        cur.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
            (u["account_id"], u["user_name"], u["role"], u["role_type"],
             u["logins_per_wk"], u["days_since_active"], u["nps"])
        )
    for h in history:
        cur.execute("INSERT INTO score_history VALUES (?,?,?)",
                     (h["account_id"], h["week_ending"], h["health_score"]))
    for p in pulses:
        cur.execute("INSERT INTO csm_pulse_log VALUES (?,?,?,?,?)",
                     (p["account_id"], p["date"], p["csm"], p["pulse_score"], p["notes"]))
    conn.commit()
    conn.close()


def generate(seed=42):
    rng = random.Random(seed)
    DATA_DIR.mkdir(exist_ok=True)

    accounts, all_users, all_history, all_pulses = [], [], [], []
    for acc_id, name, segment, arr, renewal_days, archetype in ACCOUNTS:
        account_row = gen_account_row(acc_id, name, segment, arr, renewal_days, archetype, rng)
        accounts.append(account_row)
        all_users.extend(gen_users(account_row, rng))
        all_history.extend(gen_score_history(account_row, rng))
        all_pulses.extend(gen_pulse_log(account_row, rng))

    account_fields = [k for k in accounts[0].keys() if k != "_archetype"]
    write_csv(DATA_DIR / "accounts.csv", [{k: v for k, v in a.items() if k != "_archetype"} for a in accounts], account_fields)
    write_csv(DATA_DIR / "users.csv", all_users, list(all_users[0].keys()))
    write_csv(DATA_DIR / "score_history.csv", all_history, list(all_history[0].keys()))
    write_csv(DATA_DIR / "csm_pulse_log.csv", all_pulses, list(all_pulses[0].keys()))
    write_sqlite(accounts, all_users, all_history, all_pulses)

    print(f"Generated {len(accounts)} accounts, {len(all_users)} users, "
          f"{len(all_history)} score history rows, {len(all_pulses)} pulse log entries.")
    print(f"Wrote CSVs and health.db to {DATA_DIR}/")


if __name__ == "__main__":
    generate()

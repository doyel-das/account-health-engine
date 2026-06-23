"""Generates a self-contained HTML health report (no external JS/CSS dependencies)."""
import json
from collections import defaultdict

import scorer


def tier_for_score(score, bands):
    for tier_name, (lo, hi) in bands.items():
        if lo <= score <= hi:
            return tier_name.capitalize()
    return "Yellow"


def build_portfolio_history(history_by_account, bands):
    """Aggregate per-account weekly history into portfolio avg + tier distribution per week."""
    by_week = defaultdict(list)
    for account_id, entries in history_by_account.items():
        for e in entries:
            by_week[e["week_ending"]].append(e["health_score"])

    weeks = sorted(by_week.keys())
    avg_series = [round(sum(by_week[w]) / len(by_week[w]), 1) for w in weeks]

    tier_dist = []
    for w in weeks:
        counts = {"Green": 0, "Yellow": 0, "Red": 0}
        for score in by_week[w]:
            counts[tier_for_score(score, bands)] += 1
        tier_dist.append(counts)

    return {"weeks": weeks, "avg_scores": avg_series, "tier_distribution": tier_dist}


def build_user_tier(user, bands):
    logins = user.get("logins_per_wk") or 0
    days_inactive = user.get("days_since_active") or 0
    if logins < 0.5 and days_inactive >= 14:
        return "Red"
    if logins < 1.5 or days_inactive >= 7:
        return "Yellow"
    return "Green"


def generate_report(results, config, db_path, output_path):
    bands = config["score_bands"]
    history_by_account = scorer.fetch_score_history(db_path)
    users_by_account = scorer.fetch_users(db_path)
    pulse_by_account = scorer.fetch_pulse_log(db_path)

    total_accounts = len(results)
    avg_score = round(sum(r["health_score"] for r in results) / total_accounts, 1) if total_accounts else 0
    red_count = sum(1 for r in results if r["tier"] == "Red")
    yellow_count = sum(1 for r in results if r["tier"] == "Yellow")
    green_count = sum(1 for r in results if r["tier"] == "Green")
    renewals_90 = sum(1 for r in results if (r["days_to_renewal"] or 9999) <= 90)
    total_arr = sum(r["arr"] or 0 for r in results)
    at_risk_arr = sum(r["arr"] or 0 for r in results if r["tier"] == "Red" or r["overrides"])

    accounts_payload = []
    for r in results:
        account_id = r["account_id"]
        users = users_by_account.get(account_id, [])
        for u in users:
            u["tier"] = build_user_tier(u, bands)
        accounts_payload.append({
            "account_id": account_id,
            "account_name": r["account_name"],
            "segment": r["segment"],
            "csm": r["csm"],
            "arr": r["arr"],
            "days_to_renewal": r["days_to_renewal"],
            "health_score": r["health_score"],
            "tier": r["tier"],
            "urgency_score": r["urgency_score"],
            "overrides": r["overrides"],
            "breakdown": r["breakdown"],
            "intervention": r["intervention"],
            "history": history_by_account.get(account_id, []),
            "users": users,
            "pulse_log": pulse_by_account.get(account_id, [])[-4:],
        })

    portfolio_history = build_portfolio_history(history_by_account, bands)

    data_blob = {
        "summary": {
            "total_accounts": total_accounts,
            "avg_score": avg_score,
            "red_count": red_count,
            "yellow_count": yellow_count,
            "green_count": green_count,
            "renewals_90": renewals_90,
            "total_arr": total_arr,
            "at_risk_arr": at_risk_arr,
        },
        "accounts": accounts_payload,
        "portfolio_history": portfolio_history,
        "bands": bands,
    }

    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(data_blob))
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Wrote report to {output_path}")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Account Health Report</title>
<style>
  :root {
    --red: #d64545; --yellow: #d6a445; --green: #3f9142; --gray: #888;
    --bg: #f7f8fa; --card: #ffffff; --border: #e0e2e6; --text: #1f2430;
  }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--text); margin: 0; padding: 0; }
  header { background: #1f2a44; color: white; padding: 20px 32px; }
  header h1 { margin: 0; font-size: 22px; }
  header p { margin: 4px 0 0; color: #b9c2d6; font-size: 13px; }
  .tabs { display: flex; gap: 4px; padding: 0 32px; background: #1f2a44; }
  .tab-btn { background: transparent; border: none; color: #b9c2d6; padding: 12px 18px;
             cursor: pointer; font-size: 14px; border-bottom: 3px solid transparent; }
  .tab-btn.active { color: white; border-bottom-color: #5b8cff; }
  main { padding: 24px 32px 64px; max-width: 1200px; margin: 0 auto; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  .summary-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 24px; }
  .summary-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
                  padding: 14px; text-align: center; }
  .summary-card .value { font-size: 22px; font-weight: 700; }
  .summary-card .label { font-size: 11px; color: #666; margin-top: 4px; text-transform: uppercase; }
  table { width: 100%; border-collapse: collapse; background: var(--card); border-radius: 8px;
          overflow: hidden; border: 1px solid var(--border); }
  th, td { padding: 10px 12px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--border); }
  th { background: #eef1f6; cursor: pointer; user-select: none; font-size: 12px; text-transform: uppercase; }
  tr.acct-row:hover { background: #f3f6fb; cursor: pointer; }
  .badge { display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: 11px; font-weight: 600; color: white; }
  .badge-red { background: var(--red); } .badge-yellow { background: var(--yellow); } .badge-green { background: var(--green); }
  .override-flag { color: var(--red); font-weight: 800; margin-left: 4px; }
  .score-bar-wrap { width: 80px; height: 8px; background: #e6e8ec; border-radius: 4px; overflow: hidden; display: inline-block; vertical-align: middle; margin-right: 6px; }
  .score-bar-fill { height: 100%; border-radius: 4px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 14px; overflow: hidden; }
  .card-head { padding: 14px 18px; display: flex; align-items: center; gap: 14px; cursor: pointer; }
  .card-head .name { font-weight: 600; flex: 1; }
  .card-body { padding: 0 18px 18px; display: none; border-top: 1px solid var(--border); }
  .card.expanded .card-body { display: block; }
  .override-banner { background: #fdeaea; border: 1px solid var(--red); color: #8a2222; border-radius: 6px;
                      padding: 10px 14px; margin: 14px 0; font-size: 13px; }
  .override-banner ul { margin: 6px 0 0 18px; }
  h3 { font-size: 14px; text-transform: uppercase; color: #555; margin: 20px 0 8px; }
  .gray-row { color: #999; }
  .gray-row td { color: #999; }
  canvas { max-width: 100%; }
  .chart-wrap { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 20px; }
  .toggle-bar { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
  .toggle-chip { font-size: 11px; padding: 4px 10px; border-radius: 12px; border: 1px solid var(--border);
                 background: #eef1f6; cursor: pointer; }
  .toggle-chip.off { opacity: 0.35; }
  .draft-btn { background: #1f2a44; color: white; border: none; padding: 8px 14px; border-radius: 6px;
               cursor: pointer; font-size: 13px; margin-top: 10px; }
  .draft-output { background: #f3f5f8; border: 1px solid var(--border); border-radius: 6px; padding: 12px;
                  margin-top: 10px; font-size: 13px; white-space: pre-wrap; display: none; }
  .pulse-entry { border-bottom: 1px solid var(--border); padding: 8px 0; font-size: 13px; }
  .pulse-entry:last-child { border-bottom: none; }
</style>
</head>
<body>

<header>
  <h1>Account Health Report</h1>
  <p>Generated by the Account Health Scoring Engine</p>
</header>

<div class="tabs">
  <button class="tab-btn active" data-tab="portfolio">Portfolio</button>
  <button class="tab-btn" data-tab="trends">Trends</button>
  <button class="tab-btn" data-tab="accounts">Accounts</button>
</div>

<main>
  <section id="tab-portfolio" class="tab-panel active"></section>
  <section id="tab-trends" class="tab-panel"></section>
  <section id="tab-accounts" class="tab-panel"></section>
</main>

<script>
const DATA = __DATA__;

function tierClass(tier) { return tier === "Red" ? "badge-red" : tier === "Yellow" ? "badge-yellow" : "badge-green"; }
function tierColor(tier) { return tier === "Red" ? "#d64545" : tier === "Yellow" ? "#d6a445" : "#3f9142"; }
function fmtMoney(n) { return "$" + Math.round(n).toLocaleString(); }

// ---------- TAB SWITCHING ----------
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
  });
});

function gotoAccount(accountId) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  document.querySelector('.tab-btn[data-tab="accounts"]').classList.add("active");
  document.getElementById("tab-accounts").classList.add("active");
  const card = document.getElementById("card-" + accountId);
  if (card) {
    card.classList.add("expanded");
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// ---------- TAB 1: PORTFOLIO ----------
function renderPortfolio() {
  const s = DATA.summary;
  const el = document.getElementById("tab-portfolio");
  el.innerHTML = `
    <div class="summary-grid">
      <div class="summary-card"><div class="value">${s.total_accounts}</div><div class="label">Accounts Scored</div></div>
      <div class="summary-card"><div class="value">${s.avg_score}</div><div class="label">Avg Health Score</div></div>
      <div class="summary-card"><div class="value" style="color:#d64545">${s.red_count}</div><div class="label">Red</div></div>
      <div class="summary-card"><div class="value" style="color:#d6a445">${s.yellow_count}</div><div class="label">Yellow</div></div>
      <div class="summary-card"><div class="value" style="color:#3f9142">${s.green_count}</div><div class="label">Green</div></div>
      <div class="summary-card"><div class="value">${s.renewals_90}</div><div class="label">Renewals in 90d</div></div>
    </div>
    <div class="summary-grid" style="grid-template-columns: repeat(2, 1fr);">
      <div class="summary-card"><div class="value">${fmtMoney(s.total_arr)}</div><div class="label">Total ARR</div></div>
      <div class="summary-card"><div class="value" style="color:#d64545">${fmtMoney(s.at_risk_arr)}</div><div class="label">At-Risk ARR</div></div>
    </div>
    <table id="portfolio-table">
      <thead><tr>
        <th data-sort="account_name">Account</th>
        <th data-sort="segment">Segment</th>
        <th data-sort="health_score">Score</th>
        <th data-sort="tier">Tier</th>
        <th data-sort="days_to_renewal">Renewal (d)</th>
        <th data-sort="arr">ARR</th>
        <th>Intervention</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  `;
  renderPortfolioRows(DATA.accounts.slice().sort((a, b) => a.urgency_score - b.urgency_score));

  document.querySelectorAll("#portfolio-table th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      const sorted = DATA.accounts.slice().sort((a, b) => {
        if (typeof a[key] === "string") return a[key].localeCompare(b[key]);
        return a[key] - b[key];
      });
      renderPortfolioRows(sorted);
    });
  });
}

function renderPortfolioRows(rows) {
  const tbody = document.querySelector("#portfolio-table tbody");
  tbody.innerHTML = rows.map(a => `
    <tr class="acct-row" onclick="gotoAccount('${a.account_id}')">
      <td>${a.account_name}</td>
      <td>${a.segment}</td>
      <td>
        <span class="score-bar-wrap"><span class="score-bar-fill" style="width:${a.health_score}%;background:${tierColor(a.tier)}"></span></span>
        ${a.health_score}
      </td>
      <td><span class="badge ${tierClass(a.tier)}">${a.tier}</span>${a.overrides.length ? '<span class="override-flag" title="Override active">!</span>' : ''}</td>
      <td>${a.days_to_renewal}</td>
      <td>${fmtMoney(a.arr)}</td>
      <td style="font-size:12px;color:#555">${a.intervention}</td>
    </tr>
  `).join("");
}

// ---------- TAB 2: TRENDS ----------
function renderTrends() {
  const el = document.getElementById("tab-trends");
  el.innerHTML = `
    <div class="chart-wrap"><h3>Portfolio Average Health Score</h3><canvas id="chart-portfolio" height="220"></canvas></div>
    <div class="chart-wrap">
      <h3>Per-Account Trend</h3>
      <div class="toggle-bar" id="account-toggles"></div>
      <canvas id="chart-accounts" height="280"></canvas>
    </div>
    <div class="chart-wrap"><h3>Tier Distribution by Week</h3><canvas id="chart-tiers" height="220"></canvas></div>
  `;
  drawPortfolioChart();
  drawAccountToggles();
  drawTierChart();
}

function drawLineChart(canvas, series, opts) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width = canvas.clientWidth || 800;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const padL = 40, padR = 20, padT = 20, padB = 30;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const allValues = series.flatMap(s => s.values);
  const minV = 0, maxV = 100;
  const n = (opts.labels || series[0].values).length || series[0].values.length;
  const labels = opts.labels || series[0].values.map((_, i) => i);

  // axes
  ctx.strokeStyle = "#ccc"; ctx.beginPath();
  ctx.moveTo(padL, padT); ctx.lineTo(padL, padT + plotH); ctx.lineTo(padL + plotW, padT + plotH); ctx.stroke();
  ctx.fillStyle = "#888"; ctx.font = "10px sans-serif";
  [0, 40, 70, 100].forEach(v => {
    const y = padT + plotH - (v - minV) / (maxV - minV) * plotH;
    ctx.fillText(v, 4, y + 3);
  });

  function xy(i, v) {
    const x = padL + (i / (labels.length - 1 || 1)) * plotW;
    const y = padT + plotH - (v - minV) / (maxV - minV) * plotH;
    return [x, y];
  }

  // threshold lines
  (opts.thresholds || []).forEach(t => {
    const [, y] = xy(0, t.value);
    ctx.save();
    ctx.strokeStyle = t.color; ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke();
    ctx.restore();
  });

  series.forEach(s => {
    if (s.hidden) return;
    ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.beginPath();
    s.values.forEach((v, i) => {
      const [x, y] = xy(i, v);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = s.color;
    s.values.forEach((v, i) => {
      const [x, y] = xy(i, v);
      ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill();
      if (opts.labelPoints) {
        ctx.fillStyle = "#333"; ctx.font = "10px sans-serif";
        ctx.fillText(v, x - 8, y - 8);
        ctx.fillStyle = s.color;
      }
    });
  });

  ctx.fillStyle = "#888"; ctx.font = "10px sans-serif";
  labels.forEach((lab, i) => {
    const [x] = xy(i, 0);
    ctx.fillText(lab.slice(5), x - 14, padT + plotH + 16);
  });
}

function drawPortfolioChart() {
  const h = DATA.portfolio_history;
  drawLineChart(document.getElementById("chart-portfolio"),
    [{ values: h.avg_scores, color: "#5b8cff" }],
    { labels: h.weeks, labelPoints: true, thresholds: [{ value: 40, color: "#d64545" }] });
}

const ACCOUNT_COLORS = ["#5b8cff", "#d64545", "#3f9142", "#d6a445", "#9b59b6", "#1abc9c",
                         "#e67e22", "#34495e", "#e84393", "#16a085", "#7f8c8d", "#2980b9"];
let accountChartState = {};

function drawAccountToggles() {
  const wrap = document.getElementById("account-toggles");
  DATA.accounts.forEach((a, i) => {
    accountChartState[a.account_id] = true;
    const chip = document.createElement("span");
    chip.className = "toggle-chip";
    chip.textContent = a.account_name;
    chip.style.borderColor = ACCOUNT_COLORS[i % ACCOUNT_COLORS.length];
    chip.addEventListener("click", () => {
      accountChartState[a.account_id] = !accountChartState[a.account_id];
      chip.classList.toggle("off", !accountChartState[a.account_id]);
      drawAccountChart();
    });
    wrap.appendChild(chip);
  });
  drawAccountChart();
}

function drawAccountChart() {
  const labels = DATA.portfolio_history.weeks;
  const series = DATA.accounts.map((a, i) => ({
    values: a.history.map(h => h.health_score),
    color: ACCOUNT_COLORS[i % ACCOUNT_COLORS.length],
    hidden: !accountChartState[a.account_id],
  }));
  drawLineChart(document.getElementById("chart-accounts"), series,
    { labels, thresholds: [{ value: 40, color: "#d64545" }, { value: 70, color: "#d6a445" }] });
}

function drawTierChart() {
  const canvas = document.getElementById("chart-tiers");
  const ctx = canvas.getContext("2d");
  const w = canvas.width = canvas.clientWidth || 800;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const padL = 30, padR = 20, padT = 20, padB = 30;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const dist = DATA.portfolio_history.tier_distribution;
  const labels = DATA.portfolio_history.weeks;
  const total = DATA.summary.total_accounts;
  const barW = plotW / dist.length * 0.6;

  dist.forEach((counts, i) => {
    const x = padL + (i + 0.5) / dist.length * plotW - barW / 2;
    let yOffset = padT + plotH;
    [["Green", "#3f9142"], ["Yellow", "#d6a445"], ["Red", "#d64545"]].forEach(([tier, color]) => {
      const segH = (counts[tier] / total) * plotH;
      ctx.fillStyle = color;
      ctx.fillRect(x, yOffset - segH, barW, segH);
      yOffset -= segH;
    });
    ctx.fillStyle = "#888"; ctx.font = "10px sans-serif";
    ctx.fillText(labels[i].slice(5), x - 4, padT + plotH + 16);
  });
}

// ---------- TAB 3: ACCOUNTS ----------
function renderAccounts() {
  const el = document.getElementById("tab-accounts");
  el.innerHTML = DATA.accounts.map(accountCardHtml).join("");

  DATA.accounts.forEach(a => {
    const card = document.getElementById("card-" + a.account_id);
    card.querySelector(".card-head").addEventListener("click", () => {
      const wasExpanded = card.classList.contains("expanded");
      card.classList.toggle("expanded");
      if (!wasExpanded) drawAccountDetailChart(a);
    });
    const btn = card.querySelector(".draft-btn");
    if (btn) btn.addEventListener("click", () => draftEmail(a));
  });
}

function accountCardHtml(a) {
  const overrideBanner = a.overrides.length ? `
    <div class="override-banner">
      <strong>Override condition(s) active</strong>
      <ul>${a.overrides.map(o => `<li>${o}</li>`).join("")}</ul>
    </div>` : "";

  const breakdownRows = a.breakdown.map(b => `
    <tr class="${b.included ? '' : 'gray-row'}">
      <td>${b.label}${b.is_proxy ? ' <em>(proxy)</em>' : ''}</td>
      <td>${b.raw_value === null ? '—' : b.raw_value}</td>
      <td>${b.normalized === null ? '—' :
        `<span class="score-bar-wrap"><span class="score-bar-fill" style="width:${b.normalized}%;background:${tierColor(b.normalized >= 71 ? 'Green' : b.normalized >= 41 ? 'Yellow' : 'Red')}"></span></span>${b.normalized}`}</td>
      <td>${b.included ? b.effective_weight_pct + '%' : '—'}</td>
      <td>${b.reason || ''}</td>
    </tr>
  `).join("");

  const userRows = a.users.map(u => `
    <tr>
      <td>${u.user_name}</td>
      <td>${u.role}</td>
      <td><span class="badge ${tierClass(u.tier)}">${u.tier}</span></td>
      <td>${u.logins_per_wk}</td>
      <td>${u.days_since_active}</td>
      <td>${u.nps === null ? '—' : u.nps}</td>
    </tr>
  `).join("");

  const pulseEntries = a.pulse_log.map(p => `
    <div class="pulse-entry">
      <strong>${p.date}</strong> — ${p.csm}
      <span class="badge" style="background:${tierColor(p.pulse_score >= 4 ? 'Green' : p.pulse_score === 3 ? 'Yellow' : 'Red')}">Pulse ${p.pulse_score}</span><br>
      <span style="color:#555">${p.notes}</span>
    </div>
  `).join("") || "<p style='color:#999'>No pulse entries logged.</p>";

  return `
    <div class="card" id="card-${a.account_id}">
      <div class="card-head">
        <span class="name">${a.account_name}</span>
        <span style="font-size:12px;color:#777">${a.segment} · CSM ${a.csm}</span>
        <span style="font-size:12px;color:#777">${fmtMoney(a.arr)} ARR</span>
        <span class="score-bar-wrap"><span class="score-bar-fill" style="width:${a.health_score}%;background:${tierColor(a.tier)}"></span></span>
        ${a.health_score}
        <span class="badge ${tierClass(a.tier)}">${a.tier}</span>
        <span style="font-size:12px;color:#777">Renews in ${a.days_to_renewal}d</span>
      </div>
      <div class="card-body">
        ${overrideBanner}
        <h3>Signal Breakdown</h3>
        <table><thead><tr><th>Metric</th><th>Raw</th><th>Normalized</th><th>Effective Weight</th><th>Note</th></tr></thead>
        <tbody>${breakdownRows}</tbody></table>

        <h3>90-Day Score Trend</h3>
        <canvas id="chart-detail-${a.account_id}" height="160"></canvas>

        <h3>Users at this Account</h3>
        <table><thead><tr><th>Name</th><th>Role</th><th>Tier</th><th>Logins/wk</th><th>Days Inactive</th><th>NPS</th></tr></thead>
        <tbody>${userRows}</tbody></table>

        <h3>CSM Pulse History</h3>
        ${pulseEntries}

        <h3>Recommended Intervention</h3>
        <p>${a.intervention}</p>
        <button class="draft-btn">Draft intervention email</button>
        <div class="draft-output"></div>
      </div>
    </div>
  `;
}

function drawAccountDetailChart(a) {
  const canvas = document.getElementById("chart-detail-" + a.account_id);
  if (!canvas || canvas.dataset.drawn) return;
  canvas.dataset.drawn = "1";
  drawLineChart(canvas,
    [{ values: a.history.map(h => h.health_score), color: tierColor(a.tier) }],
    { labels: a.history.map(h => h.week_ending), labelPoints: true,
      thresholds: [{ value: 40, color: "#d64545" }] });
}

// ---------- CLAUDE API: DRAFT INTERVENTION EMAIL ----------
async function draftEmail(a) {
  const card = document.getElementById("card-" + a.account_id);
  const output = card.querySelector(".draft-output");
  let apiKey = localStorage.getItem("anthropic_api_key");
  if (!apiKey) {
    apiKey = prompt("Enter your Anthropic API key (stored only in this browser's localStorage):");
    if (!apiKey) return;
    localStorage.setItem("anthropic_api_key", apiKey);
  }

  output.style.display = "block";
  output.textContent = "Drafting...";

  const systemPrompt = `You are a customer success strategist drafting an intervention email for an at-risk SaaS account.
Account: ${a.account_name} (${a.segment} segment), ARR ${fmtMoney(a.arr)}, CSM ${a.csm}.
Health score: ${a.health_score}/100, tier: ${a.tier}. Renews in ${a.days_to_renewal} days.
Overrides active: ${a.overrides.length ? a.overrides.join("; ") : "none"}.
Recommended intervention: ${a.intervention}
Recent CSM pulse notes: ${a.pulse_log.map(p => p.notes).join(" | ") || "none"}
Write a concise, warm, non-alarmist email from the CSM to the customer's executive sponsor proposing a check-in. Do not mention the internal health score, tier, or override logic explicitly.`;

  try {
    const resp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "anthropic-dangerous-direct-browser-access": "true",
      },
      body: JSON.stringify({
        model: "claude-sonnet-4-6",
        max_tokens: 1000,
        system: systemPrompt,
        messages: [{ role: "user", content: "Draft the email." }],
      }),
    });
    if (!resp.ok) {
      const errText = await resp.text();
      output.textContent = "Error calling Anthropic API: " + resp.status + " " + errText;
      return;
    }
    const json = await resp.json();
    output.textContent = json.content.map(c => c.text || "").join("\n");
  } catch (err) {
    output.textContent = "Request failed: " + err.message +
      "\n\nNote: direct browser calls to the Anthropic API require the key to be entered locally each session.";
  }
}

renderPortfolio();
renderTrends();
renderAccounts();
</script>
</body>
</html>
"""

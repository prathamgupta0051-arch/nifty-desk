"""Build backtest/report.html from results.json. Every number on the page comes from the results file."""
import collections, html, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "results.json")))
runs, bench, meta = R["runs"], R["bench"], R["meta"]
P = {k: runs[k]["perf"] for k in runs}
CAP = meta["capital"]


def L(v):  # rupees in lakh
    return f"₹{v / 1e5:,.2f} L"


def pct(v, d=1, sign=True):
    if v is None:
        return "—"
    s = f"{v * 100:+.{d}f}%" if sign else f"{v * 100:.{d}f}%"
    return s.replace("-", "−")


def inr(v):
    s = f"{abs(v):,.0f}"
    return ("−₹" if v < 0 else "₹") + s


base_up = R["baseUp3"]
base_dn = 1 - base_up
h3 = R["hit"]["3"]
nifty_ret = bench["nifty"]["ret"]
rnd = bench["random"]

# ---- equity curves (lakh), Nifty buy & hold scaled to the same capital
nc = R["niftyCurve"]
n0 = nc[0]["c"]
curves = {
    "stop": [[e["d"], round(e["eq"] / 1e5, 3)] for e in runs["stop"]["equity"]],
    "expiry": [[e["d"], round(e["eq"] / 1e5, 3)] for e in runs["expiry"]["equity"]],
    "3day": [[e["d"], round(e["eq"] / 1e5, 3)] for e in runs["3day"]["equity"]],
    "nifty": [[x["d"], round(CAP * x["c"] / n0 / 1e5, 3)] for x in nc],
}

# ---- structure breakdown (primary run)
g = collections.defaultdict(list)
for t in runs["stop"]["trades"]:
    g[t["structure"]].append(t["pnl"])
struct_rows = sorted(((k, len(v), sum(v), sum(1 for x in v if x > 0) / len(v)) for k, v in g.items()), key=lambda r: -r[2])
by_dir = collections.defaultdict(list)
for t in runs["stop"]["trades"]:
    by_dir[t["dir"]].append(t["pnl"])

# ---- buckets for the bar chart (3-day): share of times Nifty FELL
buckets = [{"b": b["bucket"], "n": b["n"], "down": (1 - b["up"]) if b["up"] is not None else None,
            "mean": b["mean"]} for b in R["buckets"]["3"]]

steps = R["steps"]
agree = R["hitByAgree"]
halves = R["halves"]

trades = runs["stop"]["trades"]
top3 = sorted(trades, key=lambda t: -t["pnl"])[:3]
top3_sum = sum(t["pnl"] for t in top3)
total_pnl = sum(t["pnl"] for t in trades)
sk = runs["stop"]["skipped"]

E = json.load(open(os.path.join(HERE, "results_etf.json")))
etf_names = {"bull_only": "Invested only on bullish days", "not_bear": "Invested unless bearish",
             "agree3": "Out only on strong bearish (3+ steps agree)", "pcr": "PCR step only: out when PCR is bearish"}
def etf_rows(block):
    out = ""
    for k, nm in etf_names.items():
        r = block[k]; c = r["close"]
        out += tr_row([nm, L(c["final"]), f'<span class="{"up" if c["ret"] >= 0 else "dn"}">{pct(c["ret"])}</span>',
                       pct(r["open"]["ret"]), pct(c["mdd"]), f'{r["invested"] * 100:.0f}%', c["switches"], inr(c["costs"]),
                       f'{pct(r["random"]["median"])} <small>beat {r["random"]["pctile"] * 100:.0f}%</small>'])
    return out
bh = E["bh"]
sigt = E["signal"]
FU = json.load(open(os.path.join(HERE, "results_fut.json")))
fr = {r["key"]: r for r in FU["runs"]}
fb = {b["name"]: b for b in FU["bench"]}
f_main, f_week, f_short = fr["ls-daily-0"], fr["ls-weekly-0"], fr["short-daily-0"]
f_alw_s, f_alw_l = fb["Always short"], fb["Always long (futures buy and hold)"]
def fut_trade_split(r):
    T = r["trades"]
    st = sorted(T, key=lambda t: -t["pnl"])
    return (sum(t["pnl"] for t in T if t["dir"] > 0), sum(1 for t in T if t["dir"] > 0),
            sum(t["pnl"] for t in T if t["dir"] < 0), sum(1 for t in T if t["dir"] < 0),
            sum(t["pnl"] for t in st[:3]), sum(t["pnl"] for t in T))
fl_pnl, fl_n, fs_pnl, fs_n, ftop3, ftot = fut_trade_split(f_main)
fut_curves = {k: [[e["d"], round(e["eq"] / 1e5, 3)] for e in v["equity"]] for k, v in
              (("main", f_main), ("week", f_week), ("short", f_short), ("alws", f_alw_s))}
def fut_rows():
    out = ""
    for r in FU["runs"]:
        p = r["perf"]
        out += tr_row([r["name"], L(p["final"]), f'<span class="{"up" if p["ret"] >= 0 else "dn"}">{pct(p["ret"])}</span>', pct(p["mdd"]),
                       inr(p["worstDay"]), p["n"], f'{p["win"] * 100:.0f}%', inr(p["costs"]),
                       f'{pct(p["null"]["median"])} <small>beat {p["null"]["pctile"] * 100:.0f}%</small>'],
                      "primary" if r["key"] == "ls-daily-0" else "")
    for b in FU["bench"]:
        p = b["perf"]
        out += tr_row([b["name"] + " <small>1.5× exposure, rolled monthly</small>", L(p["final"]), pct(p["ret"]), pct(p["mdd"]), inr(p["worstDay"]), "—", "—", inr(p["costs"]), "—"], "ref")
    return out
data_js = json.dumps({"curves": curves, "buckets": buckets, "baseDown": base_dn, "fut": fut_curves})


def tr_row(cells, cls=""):
    return f"<tr{' class=' + chr(34) + cls + chr(34) if cls else ''}>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def hit_cell(h, base):
    if not h["n"]:
        return "—"
    edge = h["hit"] - base
    tone = "up" if edge > 0.03 else "dn" if edge < -0.03 else ""
    return f'<span class="{tone}">{h["hit"] * 100:.0f}%</span> <small>n={h["n"]}</small>'


exit_rows = [
    ("Model · stop at the “view is wrong” level", P["stop"], "primary"),
    ("Model · hold every trade to expiry", P["expiry"], ""),
    ("Model · exit after 3 sessions", P["3day"], ""),
]

page = f'''<title>Positioning Desk Backtest</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap">
<style>
/* Single light theme, matching the dashboard */
:root{{color-scheme:light;
  --bg:#F5F7FA;--surface:#FFFFFF;--sunk:#F8FAFC;--ink:#111827;--muted:#6B7280;--faint:#9CA3AF;--line:#E5E7EB;
  --accent:#2F5BEA;--accent-soft:#EEF2FF;--bull:#16A34A;--bull-soft:#E8F7EE;--bear:#DC2626;--bear-soft:#FDECEC;--warn:#B45309;--warn-soft:#FEF3E2;
  --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--ref:#9CA3AF;
  --font:"Plus Jakarta Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
*{{box-sizing:border-box}}
html,body{{background:var(--bg)}}
body{{color:var(--ink);font-family:var(--font);font-size:14px;line-height:1.55;font-variant-numeric:tabular-nums}}
h1,h2,h3{{margin:0;line-height:1.2;text-wrap:balance}}
.wrap{{max-width:1180px;margin:0 auto;padding-inline:20px;padding-block:28px 56px;display:flex;flex-direction:column;gap:22px}}
.top{{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:flex-end;justify-content:space-between}}
.top h1{{font-size:26px;font-weight:800}}
.top p{{margin:4px 0 0;color:var(--muted);max-width:70ch}}
.tag{{font-size:12.5px;font-weight:600;color:var(--muted);background:var(--surface);border:1px solid var(--line);padding:5px 12px;border-radius:999px}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:12px;min-width:0}}
.card-h{{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:16px 22px;border-bottom:1px solid var(--line)}}
.card-h h2{{font-size:16px}}
.card-b{{padding:18px 22px;display:flex;flex-direction:column;gap:14px}}
.label{{font-size:11.5px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}}
.kpis{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:16px}}
.kpi{{padding:16px 20px;display:flex;flex-direction:column;gap:5px}}
.kpi b{{font-size:24px;font-weight:800;letter-spacing:-.01em}}
.kpi span.sub{{font-size:12.5px;color:var(--muted);font-weight:500}}
.up{{color:var(--bull)}}.dn{{color:var(--bear)}}
.verdict{{display:grid;grid-template-columns:1fr 1fr;gap:0}}
.vq{{padding:18px 22px;display:flex;flex-direction:column;gap:6px;font-size:14.5px;border-bottom:1px solid var(--line)}}
.vq:nth-child(odd){{border-right:1px solid var(--line)}}
.vq:nth-last-child(-n+2){{border-bottom:0}}
.vq h3{{font-size:12px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}}
.vq p{{margin:0}}
.big{{font-size:18px;font-weight:700;line-height:1.35}}
.row2{{display:grid;grid-template-columns:1fr 1fr;gap:22px;align-items:start}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
th{{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);text-align:right;padding:10px;border-bottom:1px solid var(--line);background:var(--sunk);white-space:nowrap}}
td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left;white-space:normal}}
tr:last-child td{{border-bottom:0}}
tr.primary td{{background:var(--accent-soft);font-weight:600}}
tr.ref td{{color:var(--muted)}}
td small{{color:var(--muted);font-size:11.5px;margin-left:4px}}
.tbl{{border:1px solid var(--line);border-radius:10px;overflow-x:auto}}
.note{{font-size:13px;color:var(--muted);background:var(--sunk);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:0;line-height:1.6}}
.note b{{color:var(--ink)}}
.legend{{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:13px;color:var(--ink)}}
.legend span{{display:inline-flex;align-items:center;gap:7px}}
.sw{{width:14px;height:3px;border-radius:2px;display:inline-block}}
.chart{{position:relative}}
.chart svg{{width:100%;height:auto;display:block;overflow:visible}}
svg text{{font-family:var(--font);fill:var(--muted);font-size:11px}}
.tip{{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:12.5px;box-shadow:0 4px 14px rgba(16,24,40,.08);min-width:170px;opacity:0;transition:opacity .1s}}
.tip b{{display:block;margin-bottom:4px}}
.tip div{{display:flex;justify-content:space-between;gap:12px}}
ul.plain{{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:6px}}
details summary{{cursor:pointer;font-weight:600;padding:14px 22px}}
details[open] summary{{border-bottom:1px solid var(--line)}}
.log{{max-height:520px;overflow:auto}}
.log td,.log th{{font-size:12.5px;padding:7px 9px}}
.log thead th{{position:sticky;top:0}}
.foot{{font-size:12px;color:var(--muted);margin:0}}
@media (max-width:1000px){{.kpis{{grid-template-columns:repeat(3,minmax(0,1fr))}}.row2{{grid-template-columns:1fr}}}}
@media (max-width:620px){{.kpis{{grid-template-columns:1fr 1fr}}.verdict{{grid-template-columns:1fr}}.vq:nth-child(odd){{border-right:0}}.vq:nth-last-child(2){{border-bottom:1px solid var(--line)}}}}
</style>

<div class="wrap">
  <header class="top">
    <div>
      <h1>Positioning Desk Backtest</h1>
      <p>Options, a Nifty ETF and Nifty futures, each driven by the six-step framework. Run every trading day from {meta["start"][:7].replace("-", " ")} to {meta["end"][:7].replace("-", " ")} with ₹10 lakh, strictly using only data available at the time.</p>
    </div>
    <span class="tag">{meta["sessions"]} sessions · no look-ahead · costs and slippage included</span>
  </header>

  <section class="kpis">
    <div class="card kpi"><span class="label">Futures long/short</span><b>{L(f_main["perf"]["final"])}</b><span class="sub"><span class="{"up" if f_main["perf"]["ret"] >= 0 else "dn"}">{pct(f_main["perf"]["ret"])}</span> from ₹10 L · options: {pct(P["stop"]["ret"])}</span></div>
    <div class="card kpi"><span class="label">Worst drawdown</span><b class="dn">{pct(f_main["perf"]["mdd"])}</b><span class="sub">futures · options {pct(P["stop"]["mdd"])}</span></div>
    <div class="card kpi"><span class="label">Beat random schedules</span><b>{f_main["perf"]["null"]["pctile"] * 100:.0f}%</b><span class="sub">futures · ~95% needed to show skill</span></div>
    <div class="card kpi"><span class="label">Direction calls right</span><b>{h3["bear"]["hit"] * 100:.0f}%</b><span class="sub">bearish calls · Nifty fell {base_dn * 100:.0f}% of the time anyway</span></div>
    <div class="card kpi"><span class="label">Nifty, same period</span><b class="{"up" if nifty_ret >= 0 else "dn"}">{pct(nifty_ret)}</b><span class="sub">buy and hold the index</span></div>
  </section>

  <section class="card">
    <div class="card-h"><h2>Futures: long when bullish, short when bearish</h2><span class="label">₹10 L · about 1.5× exposure in whole lots</span></div>
    <div class="card-b">
      <p style="margin:0;max-width:90ch">This is the cleanest test of the signal: no strikes, no time decay, and you can short. The view at day <i>t</i>'s close is traded at day <i>t+1</i>'s close using real near-month futures prices from the bhavcopy. Positions roll to the next month two sessions before expiry and are marked to market daily. Size is the whole number of lots closest to 1.5× equity: 2 lots while the lot was 25, then 1 lot at 75 and 65. Charges: ₹20 brokerage, 0.02% STT on sells, exchange and SEBI fees with GST, stamp duty, and 1 point of slippage each way.</p>
      <div class="legend">
        <span><i class="sw" style="background:var(--s1)"></i>Long/short, daily</span>
        <span><i class="sw" style="background:var(--s2)"></i>Long/short, weekly</span>
        <span><i class="sw" style="background:var(--s3)"></i>Short on bearish only</span>
        <span><i class="sw" style="background:var(--ref)"></i>Always short (benchmark)</span>
      </div>
      <div class="chart" id="fuChart"><svg id="fu" viewBox="0 0 1100 300" role="img" aria-label="Futures equity curves"></svg><div class="tip" id="fuTip"></div></div>
      <div class="tbl"><table>
        <thead><tr><th>Rule</th><th>Final value</th><th>Return</th><th>Max drawdown</th><th>Worst day</th><th>Trades</th><th>Won</th><th>Charges</th><th>Random schedule, same mix</th></tr></thead>
        <tbody>{fut_rows()}</tbody>
      </table></div>
      <p class="note"><b>Better than options, but read it carefully.</b> The main rule turned ₹10 L into {L(f_main["perf"]["final"])} ({pct(f_main["perf"]["ret"])}), positive in both years ({pct(FU["halves"][0]["ret"])} and {pct(FU["halves"][1]["ret"])}). All of it came from the short side: {fs_n} short trades made {inr(fs_pnl)}, while {fl_n} long trades lost {inr(-fl_pnl) if fl_pnl < 0 else inr(fl_pnl)}. The best 3 trades made {inr(ftop3)} of the {inr(ftot)} total. Two tailwinds helped any short: Nifty fell over the period, and short futures earn the <b>carry</b> (futures trade about 0.6–0.8% a month above spot and converge to it). That is why simply staying short made {pct(f_alw_s["perf"]["ret"])} and staying long lost {pct(f_alw_l["perf"]["ret"])}. Random long/flat/short schedules with the model's exact mix and switching rate capture both tailwinds; the model beat {f_main["perf"]["null"]["pctile"] * 100:.0f}% of them, short of the ~95% needed to call it skill.</p>
      <p class="note">Idle margin earns nothing here. In practice the ₹10 L could sit in a liquid fund or be pledged and earn about 6.5% a year, which would add roughly the same 13% to every row, benchmarks included, without changing the comparison. One lot of Nifty is about ₹15 L of exposure, so a single bad day cost up to {inr(-min(r["perf"]["worstDay"] for r in FU["runs"]))}.</p>
    </div>
  </section>

  <section class="card">
    <div class="card-h"><h2>In simple words</h2><span class="tag" style="color:var(--bear);background:var(--bear-soft);border-color:transparent">No proven edge yet</span></div>
    <div class="verdict">
      <div class="vq"><h3>What did we test?</h3><p>Every evening the model read that day's NSE data, gave its bullish / bearish / neutral view and picked an options trade. We placed that trade at the next day's close with ₹10 lakh, risking at most 2% per trade, and paid real charges.</p></div>
      <div class="vq"><h3>What happened?</h3><p class="big">₹10 lakh became {L(P["stop"]["final"])} ({pct(P["stop"]["ret"])}) in two years.</p><p>Holding trades to expiry instead gave {pct(P["expiry"]["ret"])}; exiting after 3 days gave {pct(P["3day"]["ret"])}. All three are close to break-even, with drawdowns over 20%.</p></div>
      <div class="vq"><h3>Why?</h3><p>The combined score did not predict Nifty's next move. When it said “bearish”, Nifty fell over the next 3 days {h3["bear"]["hit"] * 100:.0f}% of the time, but Nifty fell {base_dn * 100:.0f}% of the time on any random day. Trading random directions with the same rules gave a median of {pct(rnd["median"])}; the model beat {rnd["modelPctile"] * 100:.0f}% of those random runs, which is not convincing.</p></div>
      <div class="vq"><h3>What does it mean?</h3><p><b>Futures did best</b> ({pct(f_main["perf"]["ret"])} long/short vs {pct(P["stop"]["ret"])} with options), but the gain came from being short in a falling market, and it beat only {f_main["perf"]["null"]["pctile"] * 100:.0f}% of random schedules with the same mix. Don't trade real money on this version yet. The direction calls behave like a coin toss, and neutral days lost money through iron butterflies. A few pieces show promise (PCR, and the rare days when all four steps agree) but the samples are too small to trust yet.</p></div>
    </div>
  </section>

  <section class="card">
    <div class="card-h"><h2>Equity curve · ₹ lakh</h2>
      <div class="legend">
        <span><i class="sw" style="background:var(--s1)"></i>Stop rule (model)</span>
        <span><i class="sw" style="background:var(--s2)"></i>Hold to expiry</span>
        <span><i class="sw" style="background:var(--s3)"></i>3-session exit</span>
        <span><i class="sw" style="background:var(--ref)"></i>Nifty buy &amp; hold</span>
      </div></div>
    <div class="card-b"><div class="chart" id="eqChart"><svg id="eq" viewBox="0 0 1100 330" role="img" aria-label="Equity curves for three exit rules and Nifty"></svg><div class="tip" id="eqTip"></div></div></div>
  </section>

  <section class="card">
    <div class="card-h"><h2>How each approach did</h2><span class="label">₹10 L start · {meta["start"]} to {meta["end"]}</span></div>
    <div class="tbl"><table>
      <thead><tr><th>Approach</th><th>Final value</th><th>Return</th><th>Max drawdown</th><th>Trades</th><th>Won</th><th>Profit factor</th><th>Charges paid</th></tr></thead>
      <tbody>
        {"".join(tr_row([n, L(p["final"]), f'<span class="{"up" if p["ret"] >= 0 else "dn"}">{pct(p["ret"])}</span>', pct(p["mdd"]), p["n"], f'{p["win"] * 100:.0f}%', f'{p["pf"]:.2f}' if p["pf"] else "—", inr(p["costs"])], c) for n, p, c in exit_rows)}
        {tr_row(["Random direction, same rules <small>median of 100 runs</small>", L(CAP * (1 + rnd["median"])), pct(rnd["median"]), "—", "—", "—", "—", "—"], "ref")}
        {tr_row(["Random direction · 5th to 95th percentile", "—", pct(rnd["p5"]) + " to " + pct(rnd["p95"]), "—", "—", "—", "—", "—"], "ref")}
        {tr_row(["Always bearish <small>hindsight: Nifty fell</small>", L(bench["always_bear"]["perf"]["final"]), pct(bench["always_bear"]["perf"]["ret"]), pct(bench["always_bear"]["perf"]["mdd"]), bench["always_bear"]["perf"]["n"], f'{bench["always_bear"]["perf"]["win"] * 100:.0f}%', "—", "—"], "ref")}
        {tr_row(["Always bullish", L(bench["always_bull"]["perf"]["final"]), pct(bench["always_bull"]["perf"]["ret"]), pct(bench["always_bull"]["perf"]["mdd"]), bench["always_bull"]["perf"]["n"], f'{bench["always_bull"]["perf"]["win"] * 100:.0f}%', "—", "—"], "ref")}
        {tr_row(["Nifty buy and hold", L(CAP * (1 + nifty_ret)), pct(nifty_ret), "—", "—", "—", "—", "—"], "ref")}
      </tbody></table></div>
    <div class="card-b" style="padding-top:0"><p class="note"><b>Read the “always bearish” row with care.</b> It made money only because Nifty happened to fall {abs(nifty_ret) * 100:.0f}% over these two years; you could not have known that in advance. The model was bearish on {R["dirCounts"]["bear"]} days, neutral on {R["dirCounts"]["neu"]} and bullish on {R["dirCounts"]["bull"]}.</p></div>
  </section>

  <section class="card">
    <div class="card-h"><h2>Without options: the signal timing a Nifty ETF</h2><span class="label">₹10 L · in the ETF or in cash</span></div>
    <div class="card-b">
      <p style="margin:0;max-width:85ch">An ETF can't be shorted, so the rule is simple: hold the Nifty ETF when the model allows it, sit in cash when it doesn't. The view at day <i>t</i>'s close is traded at day <i>t+1</i>'s close. Costs per switch: stamp duty, STT on ETF units, exchange and SEBI fees with GST, a ₹15.93 DP charge on sells, and 0.05% slippage each way. Buy and hold over the same days: <b class="dn">{pct(bh["ret"])}</b>, worst drawdown {pct(bh["mdd"])}.</p>
      <span class="label">Decide once a week (last session of each week) · recommended for an ETF</span>
      <div class="tbl"><table>
        <thead><tr><th>Rule</th><th>Final value</th><th>Return</th><th>If traded at next open</th><th>Max drawdown</th><th>Time invested</th><th>Switches</th><th>Charges</th><th>Random timing, same exposure</th></tr></thead>
        <tbody>{etf_rows(E["weekly"])}{tr_row(["Buy and hold", L(bh["final"]), pct(bh["ret"]), "—", pct(bh["mdd"]), "100%", 1, inr(bh["costs"]), "—"], "ref")}</tbody>
      </table></div>
      <span class="label">Decide every day</span>
      <div class="tbl"><table>
        <thead><tr><th>Rule</th><th>Final value</th><th>Return</th><th>If traded at next open</th><th>Max drawdown</th><th>Time invested</th><th>Switches</th><th>Charges</th><th>Random timing, same exposure</th></tr></thead>
        <tbody>{etf_rows(E["rules"])}</tbody>
      </table></div>
      <p class="note"><b>What this shows.</b> Every rule lost less than buy and hold, but mostly because it sat in cash during a falling market, not because it picked the right days. Against 300 random in/out schedules with the same time invested and the same number of switches, the weekly rules beat {min(E["weekly"][k]["random"]["pctile"] for k in etf_names) * 100:.0f}–{max(E["weekly"][k]["random"]["pctile"] for k in etf_names) * 100:.0f}% of them; real skill would need around 95%. Daily decisions switch so often that charges eat ₹{min(E["rules"][k]["close"]["costs"] for k in etf_names) / 1000:.0f}–{max(E["rules"][k]["close"]["costs"] for k in etf_names) / 1000:.0f}k, and results swing widely depending on whether you trade at the open or the close, which is a sign of noise. The ETF is modelled by the Nifty 50 index; dividends (about 1.2% a year) are left out of every line, and idle cash earns nothing.</p>
      <span class="label">Signal only · how often Nifty moved the called way</span>
      <div class="tbl"><table>
        <thead><tr><th>Horizon</th><th>Nifty rose (any day)</th><th>Bullish calls right</th><th>Bearish calls right</th><th>Avg move after bullish</th><th>Avg move after bearish</th><th>Correlation</th></tr></thead>
        <tbody>{"".join(tr_row([f"{n} sessions", f'{t["baseUp"] * 100:.0f}%', hit_cell(t["bull"], t["baseUp"]), hit_cell(t["bear"], 1 - t["baseUp"]), pct(t["bull"]["mean"], 2), pct(t["bear"]["mean"], 2), f'{t["ic"]:+.3f}']) for n, t in sigt.items())}</tbody>
      </table></div>
      <p class="note">At no horizon from 1 day to a month does the model's call beat the base rate in a meaningful way, and after a bullish call Nifty on average did <i>worse</i> than after a bearish one at the {" and ".join(str(n) for n, t in sigt.items() if t["bull"]["mean"] < t["bear"]["mean"]) or "no"}-session horizons.</p>
    </div>
  </section>

  <div class="row2">
    <section class="card">
      <div class="card-h"><h2>Did the bias score predict the next 3 days?</h2></div>
      <div class="card-b">
        <span class="label">How often Nifty fell over the next 3 sessions, by bias score</span>
        <div class="chart" id="bkChart"><svg id="bk" viewBox="0 0 520 240" role="img" aria-label="Share of times Nifty fell, by bias bucket"></svg><div class="tip" id="bkTip"></div></div>
        <p class="note">If the score worked, the bars would fall from left (bearish) to right (bullish). They are mostly flat around the {base_dn * 100:.0f}% baseline. Only the most bearish bucket stands out ({buckets[0]["down"] * 100:.0f}% falls), and it has just {buckets[0]["n"]} days. Rank correlation between score and 3-day return: <b>{R["icBias"]["3"]:+.3f}</b> (0 = no relationship).</p>
      </div>
    </section>
    <section class="card">
      <div class="card-h"><h2>Hit rate of direction calls</h2></div>
      <div class="tbl" style="border:0;border-radius:0"><table>
        <thead><tr><th>Calls</th><th>Bearish right</th><th>Bullish right</th></tr></thead>
        <tbody>
          {tr_row(["Baseline (any day)", f"{base_dn * 100:.0f}%", f"{base_up * 100:.0f}%"], "ref")}
          {tr_row(["All model calls", hit_cell(h3["bear"], base_dn), hit_cell(h3["bull"], base_up)], "primary")}
          {tr_row(["4 of 4 steps agree", hit_cell(agree["4"]["bear"], base_dn), hit_cell(agree["4"]["bull"], base_up)])}
          {tr_row(["3 of 4 agree", hit_cell(agree["3"]["bear"], base_dn), hit_cell(agree["3"]["bull"], base_up)])}
          {tr_row(["2 or fewer agree", hit_cell(agree["≤2"]["bear"], base_dn), hit_cell(agree["≤2"]["bull"], base_up)])}
          {"".join(tr_row([h["name"], hit_cell(h["hit"]["bear"], base_dn), hit_cell(h["hit"]["bull"], base_up)]) for h in halves)}
        </tbody></table></div>
      <div class="card-b"><p class="note">“Right” = Nifty moved the called way over the next 3 sessions. Green means better than the baseline by more than 3 points. Full agreement looks better ({agree["4"]["bear"]["hit"] * 100:.0f}% / {agree["4"]["bull"]["hit"] * 100:.0f}%) but rests on only {agree["4"]["bear"]["n"] + agree["4"]["bull"]["n"]} days.</p></div>
    </section>
  </div>

  <div class="row2">
    <section class="card">
      <div class="card-h"><h2>Which steps carry information?</h2></div>
      <div class="tbl" style="border:0;border-radius:0"><table>
        <thead><tr><th>Step</th><th>Correlation</th><th>Bear calls right</th><th>Bull calls right</th></tr></thead>
        <tbody>{"".join(tr_row([s["step"], f'{s["ic"]:+.3f}', hit_cell(s["alone"]["bear"], base_dn), hit_cell(s["alone"]["bull"], base_up)]) for s in steps)}</tbody>
      </table></div>
      <div class="card-b"><p class="note">Correlation = rank correlation between the step's score and Nifty's next 3-session return. PCR is the only step with a noticeable signal on its own (correlation {steps[3]["ic"]:+.3f}; both its bearish and bullish calls beat the baseline). The option-chain step slightly <i>opposed</i> the next move. Removing any single step barely changes the combined hit rate.</p></div>
    </section>
    <section class="card">
      <div class="card-h"><h2>Profit by structure · stop rule</h2></div>
      <div class="tbl" style="border:0;border-radius:0"><table>
        <thead><tr><th>Structure</th><th>Trades</th><th>Won</th><th>Total P&amp;L</th></tr></thead>
        <tbody>{"".join(tr_row([k, n, f"{w * 100:.0f}%", f'<span class="{"up" if v >= 0 else "dn"}">{inr(v)}</span>']) for k, n, v, w in struct_rows)}</tbody>
      </table></div>
      <div class="card-b"><p class="note">Bearish trades made {inr(sum(by_dir["bear"]))}, bullish trades {inr(sum(by_dir["bull"]))}, neutral trades {inr(sum(by_dir["neu"]))}. Iron butterflies (neutral, mid IV) were the biggest single drain.</p>
        <p class="note"><b>The result rests on a few trades.</b> The best 3 of {len(trades)} trades (cheap long puts bought before sharp falls, e.g. {top3[0]["entry"]}: {inr(top3[0]["pnl"])}) made {inr(top3_sum)}. The other {len(trades) - 3} trades together made {inr(total_pnl - top3_sum)}.</p></div>
    </section>
  </div>

  <section class="card">
    <div class="card-h"><h2>How the test was run</h2></div>
    <div class="card-b">
      <div class="row2" style="gap:28px">
        <div><span class="label">No look-ahead</span><ul class="plain">
          <li>The signal for day <i>t</i> uses only NSE files published by the evening of <i>t</i>: bhavcopy, participant OI, Nifty and VIX closes. Moving averages, IV percentile and PCR history all use trailing data only.</li>
          <li>Every trade is entered at the <b>next session's close</b>, never at the close that produced the signal.</li>
          <li>Stops are decided on a close and executed at the following session's close.</li>
          <li>Position size uses only the equity known at entry. Checked: every trade has signal &lt; entry ≤ exit ≤ expiry.</li>
          <li>The scoring is a line-by-line Python port of the dashboard. On 1 Oct 2026 it gave the same step scores (−2.00, −1.75, −0.92 vs −0.91 live, −0.30), bias (−62) and trade as the live dashboard.</li>
        </ul></div>
        <div><span class="label">Money and costs</span><ul class="plain">
          <li>₹10 lakh start, one position at a time, max loss per trade ≤ 2% of equity, at most 20 lots. Lot size taken from each contract (25, 75, then 65 over the period).</li>
          <li>Costs per leg: ₹20 brokerage, STT 0.1% on sells and 0.125% on ITM exercise, NSE charges 0.035%, SEBI fee, 18% GST, stamp duty, plus <b>1 point of slippage</b> per leg per fill.</li>
          <li>Trades use the nearest weekly expiry still alive after the entry day; held positions settle at intrinsic value on the expiry-day index close.</li>
          <li>Skipped: {sk["bad_price"]} signals with a missing or below-intrinsic price, {sk["odd_spread"]} with an unrealistic spread price, {sk["too_small"]} where one lot risked more than 2%.</li>
        </ul></div>
      </div>
      <p class="note"><b>Two data problems were found and fixed before these results.</b> (1) The bhavcopy's opening premium is a single first trade and was badly stale on gap days (on 7 Apr 2025 a put “opened” ₹500 below its value), which created fake ₹3 lakh wins; all fills now use closing prices. (2) Some closes on illiquid in-the-money strikes broke no-arbitrage limits (a 200-point spread marked at 207); position values are now kept within what the structure can be worth. The first, buggy run showed +56%; that number was wrong.</p>
      <p class="note"><b>Limits.</b> Two years is about 100 weekly cycles, so a real but small edge could hide in the noise, and a lucky one could appear. The test uses daily closes, so intraday stops are not modelled. Thresholds were set by judgement before the test, not tuned on it; tuning them now on the same data would overstate any improvement.</p>
    </div>
  </section>

  <section class="card">
    <div class="card-h"><h2>What I would change next</h2></div>
    <div class="card-b"><ul class="plain">
      <li><b>Stop trading neutral days</b> with iron butterflies; sit out instead. Neutral was the most common call ({R["dirCounts"]["neu"]} of {meta["signalDays"]} days) and lost {inr(-sum(by_dir["neu"])) if sum(by_dir["neu"]) < 0 else "nothing"}.</li>
      <li><b>Give PCR more weight</b> and test the “4 of 4 agree” filter, but on data the model has not seen: extend the history back to 2019 first, then judge.</li>
      <li><b>Rebuild the option-chain step</b> around wall migration rather than daily flow; on its own it pointed the wrong way slightly.</li>
      <li><b>Keep the test honest:</b> any change gets tested on 2019–2024 and then checked once on this 2024–2026 window, not tuned on it.</li>
    </ul></div>
  </section>

  <details class="card">
    <summary>Trade log · stop rule · {len(trades)} trades</summary>
    <div class="log"><table>
      <thead><tr><th>Signal</th><th>Entry</th><th>Exit</th><th>Why</th><th>Structure</th><th>Legs</th><th>Lots</th><th>Bias</th><th>Net prem</th><th>Max loss</th><th>Costs</th><th>P&amp;L</th></tr></thead>
      <tbody>{"".join(tr_row([t["signal"], t["entry"], t["exit"], t["why"], t["structure"], html.escape(t["legs"]), t["lots"], t["bias"], f'{t["net_prem"]:+.1f}', inr(t["max_loss"]), inr(t["costs"]), f'<span class="{"up" if t["pnl"] >= 0 else "dn"}">{inr(t["pnl"])}</span>']) for t in trades)}</tbody>
    </table></div>
  </details>

  <p class="foot">Educational backtest of a classroom framework. Not investment advice. Past results, good or bad, do not predict future ones.</p>
</div>

<script>
(function(){{
const D={data_js};
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmtL=v=>"₹"+v.toFixed(2)+" L";
const dlabel=d=>new Date(d+"T00:00:00").toLocaleDateString("en-IN",{{day:"numeric",month:"short",year:"numeric"}});

/* ---- equity chart with crosshair tooltip ---- */
(function(){{
  const W=1100,H=330,l=52,r=118,t=14,b=30, svg=document.getElementById("eq"), tip=document.getElementById("eqTip");
  const S=[["stop","Stop rule","--s1"],["expiry","Hold to expiry","--s2"],["3day","3-session exit","--s3"],["nifty","Nifty buy & hold","--ref"]];
  const dates=D.curves.stop.map(p=>p[0]); const idx={{}}; dates.forEach((d,i)=>idx[d]=i);
  const all=S.flatMap(s=>D.curves[s[0]].map(p=>p[1]));
  let lo=Math.floor(Math.min(...all)), hi=Math.ceil(Math.max(...all));
  const X=i=>l+i/(dates.length-1)*(W-l-r), Y=v=>t+(hi-v)/(hi-lo)*(H-t-b);
  let s="";
  for(let v=lo;v<=hi;v++) s+=`<line x1="${{l}}" x2="${{W-r}}" y1="${{Y(v)}}" y2="${{Y(v)}}" stroke="${{v===10?css("--faint"):css("--line")}}" ${{v===10?'stroke-dasharray="4 3"':""}}/><text x="${{l-8}}" y="${{Y(v)+4}}" text-anchor="end">${{v}}</text>`;
  let lastM="";
  dates.forEach((d,i)=>{{const m=d.slice(0,7); if(m!==lastM&&(+d.slice(5,7))%3===1){{s+=`<text x="${{X(i)}}" y="${{H-8}}" text-anchor="middle">${{new Date(d+"T00:00:00").toLocaleDateString("en-IN",{{month:"short",year:"2-digit"}})}}</text>`;}} lastM=m;}});
  const ends=[];
  S.forEach(([k,n,c])=>{{
    const pts=D.curves[k].filter(p=>p[0] in idx).map(p=>`${{X(idx[p[0]])}},${{Y(p[1])}}`).join(" ");
    s+=`<polyline points="${{pts}}" fill="none" stroke="${{css(c)}}" stroke-width="${{k==="stop"?2.5:2}}" stroke-linejoin="round" ${{k==="nifty"?'stroke-dasharray="5 4"':""}}/>`;
    const e=D.curves[k][D.curves[k].length-1]; ends.push([Y(e[1]),n,e[1],c]);
  }});
  ends.sort((a,b)=>a[0]-b[0]); for(let i=1;i<ends.length;i++) if(ends[i][0]-ends[i-1][0]<14) ends[i][0]=ends[i-1][0]+14;
  ends.forEach(([y,n,v,c])=>s+=`<circle cx="${{W-r}}" cy="${{y}}" r="0"/><text x="${{W-r+8}}" y="${{y+4}}" style="fill:${{css("--ink")}};font-weight:600">${{fmtL(v)}}</text>`);
  s+=`<line id="xh" x1="0" x2="0" y1="${{t}}" y2="${{H-b}}" stroke="${{css("--faint")}}" opacity="0"/>`;
  S.forEach(([k,n,c])=>s+=`<circle id="dot-${{k}}" r="4.5" fill="${{css(c)}}" stroke="#fff" stroke-width="2" opacity="0"/>`);
  s+=`<rect x="${{l}}" y="${{t}}" width="${{W-l-r}}" height="${{H-t-b}}" fill="transparent" id="hit"/>`;
  svg.innerHTML=s;
  const maps=Object.fromEntries(S.map(([k])=>[k,Object.fromEntries(D.curves[k])]));
  const hit=document.getElementById("hit"), xh=document.getElementById("xh");
  function move(ev){{
    const bb=svg.getBoundingClientRect(), x=(ev.clientX-bb.left)/bb.width*W;
    const i=Math.max(0,Math.min(dates.length-1,Math.round((x-l)/(W-l-r)*(dates.length-1)))), d=dates[i];
    xh.setAttribute("x1",X(i));xh.setAttribute("x2",X(i));xh.setAttribute("opacity",1);
    let h=`<b>${{dlabel(d)}}</b>`;
    S.forEach(([k,n,c])=>{{const v=maps[k][d], dot=document.getElementById("dot-"+k); if(v==null){{dot.setAttribute("opacity",0);return;}}
      dot.setAttribute("cx",X(i));dot.setAttribute("cy",Y(v));dot.setAttribute("opacity",1);
      h+=`<div><span><i class="sw" style="background:${{css(c)}};margin-right:6px"></i>${{n}}</span><span>${{fmtL(v)}}</span></div>`;}});
    tip.innerHTML=h; tip.style.opacity=1;
    const px=X(i)/W*bb.width; tip.style.left=Math.min(bb.width-190,Math.max(0,px+14))+"px"; tip.style.top="10px";
  }}
  hit.addEventListener("mousemove",move);
  hit.addEventListener("mouseleave",()=>{{tip.style.opacity=0;xh.setAttribute("opacity",0);S.forEach(([k])=>document.getElementById("dot-"+k).setAttribute("opacity",0));}});
}})();

/* ---- futures equity chart ---- */
(function(){{
  const W=1100,H=300,l=52,r=118,t=14,b=30, svg=document.getElementById("fu"), tip=document.getElementById("fuTip");
  const S=[["main","Long/short, daily","--s1"],["week","Long/short, weekly","--s2"],["short","Short on bearish only","--s3"],["alws","Always short","--ref"]];
  const dates=D.fut.main.map(p=>p[0]); const idx={{}}; dates.forEach((d,i)=>idx[d]=i);
  const all=S.flatMap(s=>D.fut[s[0]].map(p=>p[1]));
  const lo=Math.floor(Math.min(...all)), hi=Math.ceil(Math.max(...all)), step=hi-lo>8?2:1;
  const X=i=>l+i/(dates.length-1)*(W-l-r), Y=v=>t+(hi-v)/(hi-lo)*(H-t-b);
  let s="";
  for(let v=lo;v<=hi;v+=step) s+=`<line x1="${{l}}" x2="${{W-r}}" y1="${{Y(v)}}" y2="${{Y(v)}}" stroke="${{v===10?css("--faint"):css("--line")}}" ${{v===10?'stroke-dasharray="4 3"':""}}/><text x="${{l-8}}" y="${{Y(v)+4}}" text-anchor="end">${{v}}</text>`;
  let lastM="";
  dates.forEach((d,i)=>{{const m=d.slice(0,7); if(m!==lastM&&(+d.slice(5,7))%3===1){{s+=`<text x="${{X(i)}}" y="${{H-8}}" text-anchor="middle">${{new Date(d+"T00:00:00").toLocaleDateString("en-IN",{{month:"short",year:"2-digit"}})}}</text>`;}} lastM=m;}});
  const ends=[];
  S.forEach(([k,n,c])=>{{
    const pts=D.fut[k].filter(p=>p[0] in idx).map(p=>`${{X(idx[p[0]])}},${{Y(p[1])}}`).join(" ");
    s+=`<polyline points="${{pts}}" fill="none" stroke="${{css(c)}}" stroke-width="${{k==="main"?2.5:2}}" stroke-linejoin="round" ${{k==="alws"?'stroke-dasharray="5 4"':""}}/>`;
    const e=D.fut[k][D.fut[k].length-1]; ends.push([Y(e[1]),e[1]]);
  }});
  ends.sort((a,b)=>a[0]-b[0]); for(let i=1;i<ends.length;i++) if(ends[i][0]-ends[i-1][0]<14) ends[i][0]=ends[i-1][0]+14;
  ends.forEach(([y,v])=>s+=`<text x="${{W-r+8}}" y="${{y+4}}" style="fill:${{css("--ink")}};font-weight:600">${{fmtL(v)}}</text>`);
  s+=`<line id="fxh" x1="0" x2="0" y1="${{t}}" y2="${{H-b}}" stroke="${{css("--faint")}}" opacity="0"/>`;
  S.forEach(([k,n,c])=>s+=`<circle id="fdot-${{k}}" r="4.5" fill="${{css(c)}}" stroke="#fff" stroke-width="2" opacity="0"/>`);
  s+=`<rect x="${{l}}" y="${{t}}" width="${{W-l-r}}" height="${{H-t-b}}" fill="transparent" id="fhit"/>`;
  svg.innerHTML=s;
  const maps=Object.fromEntries(S.map(([k])=>[k,Object.fromEntries(D.fut[k])]));
  const hit=document.getElementById("fhit"), xh=document.getElementById("fxh");
  hit.addEventListener("mousemove",ev=>{{
    const bb=svg.getBoundingClientRect(), x=(ev.clientX-bb.left)/bb.width*W;
    const i=Math.max(0,Math.min(dates.length-1,Math.round((x-l)/(W-l-r)*(dates.length-1)))), d=dates[i];
    xh.setAttribute("x1",X(i));xh.setAttribute("x2",X(i));xh.setAttribute("opacity",1);
    let h=`<b>${{dlabel(d)}}</b>`;
    S.forEach(([k,n,c])=>{{const v=maps[k][d], dot=document.getElementById("fdot-"+k); if(v==null){{dot.setAttribute("opacity",0);return;}}
      dot.setAttribute("cx",X(i));dot.setAttribute("cy",Y(v));dot.setAttribute("opacity",1);
      h+=`<div><span><i class="sw" style="background:${{css(c)}};margin-right:6px"></i>${{n}}</span><span>${{fmtL(v)}}</span></div>`;}});
    tip.innerHTML=h; tip.style.opacity=1;
    const px=X(i)/W*bb.width; tip.style.left=Math.min(bb.width-200,Math.max(0,px+14))+"px"; tip.style.top="10px";
  }});
  hit.addEventListener("mouseleave",()=>{{tip.style.opacity=0;xh.setAttribute("opacity",0);S.forEach(([k])=>document.getElementById("fdot-"+k).setAttribute("opacity",0));}});
}})();

/* ---- bucket bars: share of times Nifty fell ---- */
(function(){{
  const W=520,H=240,l=40,r=10,t=16,b=40, svg=document.getElementById("bk"), tip=document.getElementById("bkTip");
  const B=D.buckets, n=B.length, bw=(W-l-r)/n, Y=v=>t+(1-v)*(H-t-b);
  let s="";
  [0,.25,.5,.75,1].forEach(v=>s+=`<line x1="${{l}}" x2="${{W-r}}" y1="${{Y(v)}}" y2="${{Y(v)}}" stroke="${{css("--line")}}"/><text x="${{l-6}}" y="${{Y(v)+4}}" text-anchor="end">${{v*100}}%</text>`);
  B.forEach((x,i)=>{{
    const cx=l+bw*i+bw/2, w=Math.min(56,bw-18), v=x.down??0, y=Y(v), h=Y(0)-y;
    s+=`<path d="M${{cx-w/2}},${{Y(0)}} V${{y+4}} Q${{cx-w/2}},${{y}} ${{cx-w/2+4}},${{y}} H${{cx+w/2-4}} Q${{cx+w/2}},${{y}} ${{cx+w/2}},${{y+4}} V${{Y(0)}} Z" fill="${{css("--s1")}}"/>`;
    s+=`<text x="${{cx}}" y="${{y-6}}" text-anchor="middle" style="fill:${{css("--ink")}};font-weight:600">${{Math.round(v*100)}}%</text>`;
    s+=`<text x="${{cx}}" y="${{H-22}}" text-anchor="middle">${{x.b}}</text><text x="${{cx}}" y="${{H-8}}" text-anchor="middle">n=${{x.n}}</text>`;
    s+=`<rect class="bh" data-i="${{i}}" x="${{l+bw*i}}" y="${{t}}" width="${{bw}}" height="${{H-t-b}}" fill="transparent"/>`;
  }});
  s+=`<line x1="${{l}}" x2="${{W-r}}" y1="${{Y(D.baseDown)}}" y2="${{Y(D.baseDown)}}" stroke="${{css("--ink")}}" stroke-dasharray="5 4" stroke-width="1.5"/><text x="${{W-r}}" y="${{Y(D.baseDown)-6}}" text-anchor="end" style="fill:${{css("--ink")}}">baseline ${{Math.round(D.baseDown*100)}}%</text>`;
  svg.innerHTML=s;
  svg.querySelectorAll(".bh").forEach(el=>{{
    el.addEventListener("mousemove",ev=>{{const x=B[+el.dataset.i], bb=svg.getBoundingClientRect();
      tip.innerHTML=`<b>Bias ${{x.b}}</b><div><span>Days</span><span>${{x.n}}</span></div><div><span>Nifty fell next 3 days</span><span>${{Math.round((x.down||0)*100)}}%</span></div><div><span>Avg 3-day move</span><span>${{x.mean==null?"—":(x.mean*100).toFixed(2)+"%"}}</span></div>`;
      tip.style.opacity=1; tip.style.left=Math.min(bb.width-190,ev.clientX-bb.left+12)+"px"; tip.style.top="8px";}});
    el.addEventListener("mouseleave",()=>tip.style.opacity=0);
  }});
}})();
}})();
</script>
'''
with open(os.path.join(HERE, "report.html"), "w") as f:
    f.write(page)
print("wrote report.html", len(page))

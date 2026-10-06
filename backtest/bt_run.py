"""Two-year walk-forward backtest of the Nifty Positioning Desk.

No look-ahead, by construction:
  - The signal for day t uses only files NSE published by the evening of t
    (bhavcopy t, participant OI t, index and VIX closes up to t).
  - Trades are entered at the CLOSE of the next session, t+1, plus slippage.
    (Bhavcopy opening premiums are single first trades and proved unreliable.)
  - Stops are checked on a close and executed at the following session's close.
  - Fills are rejected if a premium is below intrinsic value or the strike traded
    under 500 contracts that day.
  - Position size uses only equity known at entry.
"""
import csv, json, math, os, random, statistics, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_model as M
import bt_data as D
import desk_server as ds

START, END = "2024-10-01", "2026-09-30"
CAPITAL = 1_000_000
RISK = 0.02            # max loss per trade as a share of equity at entry
SLIP = 1.0             # points per leg per side, on every non-expiry fill
BROKERAGE = 20.0       # per order
STT_SELL = 0.001       # on option sell premium
STT_EXERCISE = 0.00125 # on intrinsic value of long ITM options at expiry
EXCH = 0.0003503       # NSE transaction charge on premium
SEBI = 0.000001
GST = 0.18
STAMP = 0.00003        # on buy premium


# ---------------------------------------------------------------- data
def load():
    nifty = D.index_hist("nifty", date(2023, 6, 1), date(2026, 10, 1))
    vix = D.index_hist("vix", date(2023, 6, 1), date(2026, 10, 1))
    days = {}
    for f in sorted(os.listdir(D.DAYS)):
        if f[0].isdigit():
            with open(os.path.join(D.DAYS, f)) as fh:
                j = json.load(fh)
            if j:
                days[j["d"]] = j
    parts = {}
    for d in days:
        p = ds.read_cache(ds.cache_path("part", d.replace("-", "") + ".json"))
        if p and "FII" in p:
            parts[d] = p
    return nifty, vix, days, parts


# ---------------------------------------------------------------- signals
def build_signals(nifty, vix, days, parts):
    sess = sorted(days)
    nbars = {b["d"]: b for b in nifty}
    sigs = {}
    for i, t in enumerate(sess):
        if t < START or i == 0:
            continue
        pv = sess[i - 1]
        if t not in parts or pv not in parts or t not in nbars or pv not in nbars:
            continue
        bars = [b for b in nifty if b["d"] <= t]
        vx = [v["c"] for v in vix if v["d"] <= t]
        day, prev = days[t], days[pv]
        spot = bars[-1]["c"]
        s1, x1 = M.step1(bars)
        s2, x2 = M.step2(nbars[pv]["c"], spot, day["futOi"], day["futChg"], parts[t], parts[pv])
        exp, rows = M.chain_rows(day, spot)
        mkt = M.add_iv_pressure(rows, exp, day, prev, spot)
        s3, x3 = M.step3(rows, spot)
        pcrs = [days[s]["pcr"] for s in sess[max(0, i - 9):i + 1] if days[s].get("pcr")]
        s4, x4 = M.step4(pcrs)
        reg, x5 = M.step5(vx)
        bias, d, agree = M.combine([s1, s2, s3, s4])
        sigs[t] = {"d": t, "spot": spot, "s": [s1, s2, s3, s4], "bias": bias, "dir": d, "agree": agree,
                   "reg": reg, "res": x3["res"], "sup": x3["sup"], "ivMkt": mkt, "x": {**x1, **x2, **x4, **x5}}
    return sigs


# ---------------------------------------------------------------- pricing helpers
def px(day, exp, k, typ, field):
    try:
        v = day["opt"][exp]["k"][str(int(k))][typ][field]
    except (KeyError, TypeError):
        return None
    return v if v and v > 0 else None


def payoff_unit(legs, S):
    return sum(q * (max(0, S - k) if t == "CE" else max(0, k - S)) for t, k, q in legs)


def max_loss_unit(legs, net_debit):
    ks = [k for _, k, _ in legs]
    worst = min(payoff_unit(legs, S) for S in range(int(min(ks) - 3000), int(max(ks) + 3000), 10))
    return net_debit - worst  # positive number


def fill_costs(fills):
    """fills: list of (side +1 buy / -1 sell, premium, units)."""
    c = 0.0
    for side, p, u in fills:
        turn = p * u
        brk, exch, sebi = BROKERAGE, turn * EXCH, turn * SEBI
        c += brk + exch + sebi + GST * (brk + exch + sebi)
        c += turn * STT_SELL if side < 0 else turn * STAMP
    return c


# ---------------------------------------------------------------- trading engine
MAX_LOTS = 20
MIN_VOL = 500  # contracts traded that day, per leg


def leg_price(day, exp, t, k, field=3):
    """Closing premium if it is sane (traded, and not below intrinsic value); else None."""
    try:
        v = day["opt"][exp]["k"][str(int(k))][t]
    except (KeyError, TypeError):
        return None, 0
    p, vol = v[field], v[4]
    S = day["und"]
    intrinsic = max(0.0, S - k) if t == "CE" else max(0.0, k - S)
    if not p or p <= 0 or p < intrinsic - 1.0:
        return None, vol
    return p, vol


def mark(day, pos, t, k):
    p, _ = leg_price(day, pos["exp"], t, k)
    S = day["und"]
    intrinsic = max(0.0, S - k) if t == "CE" else max(0.0, k - S)
    if p is None:
        p = max(intrinsic, pos["last"][(t, k)] if intrinsic == 0 else intrinsic)
    pos["last"][(t, k)] = p
    return p


def value_bounds(legs):
    """A European options structure is always worth between its lowest and highest
    expiry payoff. Stale closes on illiquid ITM strikes can break that; clamp to it."""
    ks = [k for _, k, _ in legs]
    grid = range(int(min(ks) - 3000), int(max(ks) + 3000), 10)
    vals = [payoff_unit(legs, S) for S in grid]
    hi = max(vals)
    open_up = payoff_unit(legs, max(ks) + 6000) > hi + 1  # unbounded on the upside (long calls)
    return min(vals), (float("inf") if open_up else hi)


def run(sigs, days, exit_rule="stop", force_dir=None, rng=None):
    """Signal on day t's close -> enter at the close of t+1. Exit decisions taken on a
    close are executed at the next session's close. Expiry settles at intrinsic value
    against the index close on expiry day."""
    sess = [d for d in sorted(days)]
    i0, i1 = sess.index(START), sess.index(END)
    cash, equity, trades = float(CAPITAL), [], []
    pos, queued = None, None
    skipped = {"bad_price": 0, "illiquid": 0, "too_small": 0, "odd_spread": 0}
    for i in range(i0, i1 + 1):
        d = sess[i]
        day = days[d]
        # 1. manage the open position
        if pos:
            if d == pos["exp"]:
                S = day["und"]
                val = payoff_unit(pos["legs"], S) * pos["units"]
                stt = sum(STT_EXERCISE * (max(0, S - k) if t == "CE" else max(0, k - S)) * pos["units"]
                          for t, k, q in pos["legs"] if q > 0)
                cash += val - stt
                close_trade(pos, d, val, stt, "expiry", trades)
                pos = None
            elif pos["pending_exit"]:
                fills, vu = [], 0.0
                for t, k, q in pos["legs"]:
                    p = mark(day, pos, t, k)
                    p = max(0.05, p - SLIP) if q > 0 else p + SLIP
                    vu += q * p
                    fills.append((-q, p, pos["units"]))
                lo, hi = pos["bounds"]
                val = min(max(vu, lo - SLIP * len(pos["legs"])), hi) * pos["units"]
                costs = fill_costs(fills)
                cash += val - costs
                close_trade(pos, d, val, costs, pos["pending_exit"], trades)
                pos = None
        # 2. execute an entry queued from yesterday's signal, at today's close
        if queued and not pos:
            sig, queued = queued, None
            exp = M.nearest_expiry(day["opt"], d)
            direction = force_dir or sig["dir"]
            if direction == "random":
                direction = rng.choice(["bull", "bear", "neu"])
            name, legs, sup, res = M.legs(direction, sig["reg"], sig["spot"], sig["sup"], sig["res"])
            quotes = [leg_price(day, exp, t, k) if exp else (None, 0) for t, k, q in legs]
            if not all(p for p, v in quotes):
                skipped["bad_price"] += 1
            elif any(v < MIN_VOL for p, v in quotes):
                skipped["illiquid"] += 1
            else:
                fill_px = [max(0.05, p + SLIP) if q > 0 else max(0.05, p - SLIP) for (p, v), (t, k, q) in zip(quotes, legs)]
                net = sum(q * p for p, (t, k, q) in zip(fill_px, legs))  # >0 debit, <0 credit, per unit
                ml = max_loss_unit(legs, net)
                width = max(k for _, k, _ in legs) - min(k for _, k, _ in legs)
                odd = width and len(legs) > 1 and (ml < 0.1 * width or ml <= 0)
                lot = day["opt"][exp]["lot"]
                eq_now = equity[-1]["eq"] if equity else cash
                lots = min(MAX_LOTS, int(RISK * eq_now // (ml * lot))) if ml > 0 else 0
                while lots > 0 and (net if net > 0 else ml) * lot * lots > 0.9 * eq_now:
                    lots -= 1
                if odd:
                    skipped["odd_spread"] += 1
                elif lots < 1:
                    skipped["too_small"] += 1
                else:
                    units = lot * lots
                    costs = fill_costs([(q, p, units) for p, (t, k, q) in zip(fill_px, legs)])
                    cash -= net * units + costs
                    pos = {"sig": sig["d"], "entry": d, "exp": exp, "name": name, "dir": direction, "reg": sig["reg"],
                           "legs": legs, "units": units, "lots": lots, "lot": lot, "net": net, "maxloss": ml * units,
                           "res": sig["res"] or res, "sup": sig["sup"] or sup, "entry_cost": costs, "held": 0,
                           "pending_exit": None, "last": {(t, k): p for p, (t, k, q) in zip(fill_px, legs)},
                           "bias": sig["bias"], "agree": sig["agree"], "spot": sig["spot"],
                           "bounds": value_bounds(legs)}
        # 3. mark to market at the close, and decide exits for the next close
        mtm = 0.0
        if pos:
            vu = sum(q * mark(day, pos, t, k) for t, k, q in pos["legs"])
            lo, hi = pos["bounds"]
            mtm = min(max(vu, lo), hi) * pos["units"]
            pos["held"] += 1
            S = day["und"]
            if exit_rule == "stop":
                dn = pos["dir"]
                if (dn == "bear" and S > pos["res"]) or (dn == "bull" and S < pos["sup"]) or \
                   (dn == "neu" and (S > pos["res"] or S < pos["sup"])):
                    pos["pending_exit"] = "stop"
            elif exit_rule == "3day" and pos["held"] >= 3:
                pos["pending_exit"] = "time"
        equity.append({"d": d, "eq": cash + mtm})
        # 4. flat and no entry queued: today's signal queues an entry for tomorrow's close
        if not pos and not queued and d in sigs and i < i1:
            queued = sigs[d]
    if pos:
        val = sum(q * pos["last"][(t, k)] for t, k, q in pos["legs"]) * pos["units"]
        cash += val
        close_trade(pos, sess[i1], val, 0.0, "end", trades)
        equity[-1]["eq"] = cash
    return {"trades": trades, "equity": equity, "skipped": skipped}


def close_trade(pos, d, exit_val, exit_cost, why, trades):
    pnl = exit_val - pos["net"] * pos["units"] - pos["entry_cost"] - exit_cost
    trades.append({"signal": pos["sig"], "entry": pos["entry"], "exit": d, "expiry": pos["exp"], "why": why,
                   "structure": pos["name"], "dir": pos["dir"], "reg": pos["reg"], "lots": pos["lots"],
                   "legs": " / ".join(f"{'B' if q > 0 else 'S'} {k} {t}" for t, k, q in pos["legs"]),
                   "net_prem": round(pos["net"], 2), "max_loss": round(pos["maxloss"]),
                   "costs": round(pos["entry_cost"] + exit_cost), "pnl": round(pnl),
                   "bias": round(pos["bias"]), "agree": pos["agree"], "spot": pos["spot"]})


# ---------------------------------------------------------------- statistics
def perf(res):
    eq = [e["eq"] for e in res["equity"]]
    tr = res["trades"]
    peak, mdd = eq[0], 0
    for v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq))]
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0
    sharpe = (statistics.mean(rets) / sd * math.sqrt(250)) if sd else 0
    wins = [t["pnl"] for t in tr if t["pnl"] > 0]
    losses = [t["pnl"] for t in tr if t["pnl"] <= 0]
    years = len(eq) / 250
    return {"final": round(eq[-1]), "ret": eq[-1] / CAPITAL - 1, "cagr": (eq[-1] / CAPITAL) ** (1 / years) - 1 if eq[-1] > 0 else -1,
            "mdd": mdd, "sharpe": sharpe, "n": len(tr), "win": len(wins) / len(tr) if tr else 0,
            "avgWin": statistics.mean(wins) if wins else 0, "avgLoss": statistics.mean(losses) if losses else 0,
            "pf": (sum(wins) / -sum(losses)) if losses and sum(losses) else None,
            "costs": sum(t["costs"] for t in tr)}


def signal_stats(sigs, nifty):
    closes = {b["d"]: b["c"] for b in nifty}
    ds_ = sorted(d for d in closes if d >= START)
    pos = {d: i for i, d in enumerate(ds_)}
    rows = []
    for d, s in sorted(sigs.items()):
        if d not in pos:
            continue
        i = pos[d]
        f = {}
        for n in (1, 3, 5):
            if i + n < len(ds_):
                f[n] = closes[ds_[i + n]] / closes[d] - 1
        rows.append({**s, "fwd": f})
    return rows


def bucket_table(rows, n=3):
    bk = [("≤ −50", lambda b: b <= -50), ("−50 to −20", lambda b: -50 < b <= -20), ("−20 to +20", lambda b: -20 < b < 20),
          ("+20 to +50", lambda b: 20 <= b < 50), ("≥ +50", lambda b: b >= 50)]
    out = []
    for name, f in bk:
        r = [x["fwd"][n] for x in rows if n in x["fwd"] and f(x["bias"])]
        out.append({"bucket": name, "n": len(r), "mean": statistics.mean(r) if r else None,
                    "up": sum(1 for v in r if v > 0) / len(r) if r else None})
    return out


def hit_rate(rows, n=3, key=lambda x: x["dir"], filt=lambda x: True):
    res = {}
    for dname, sg in (("bear", -1), ("bull", 1)):
        r = [x["fwd"][n] for x in rows if n in x["fwd"] and key(x) == dname and filt(x)]
        res[dname] = {"n": len(r), "hit": sum(1 for v in r if v * sg > 0) / len(r) if r else None,
                      "mean": statistics.mean(r) if r else None}
    return res


def spearman(a, b):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
        for pos, i in enumerate(o):
            r[i] = pos
        return r
    ra, rb = rank(a), rank(b)
    return statistics.correlation(ra, rb) if len(a) > 2 else None


def main():
    nifty, vix, days, parts = load()
    sigs = build_signals(nifty, vix, days, parts)
    print(f"{len(days)} sessions loaded, {len(sigs)} signal days ({min(sigs)} → {max(sigs)})")
    rows = signal_stats(sigs, nifty)
    base3 = [x["fwd"][3] for x in rows if 3 in x["fwd"]]
    out = {"meta": {"start": START, "end": END, "capital": CAPITAL, "risk": RISK, "slip": SLIP,
                    "sessions": len([d for d in days if START <= d <= END]), "signalDays": len(sigs)}}
    out["dirCounts"] = {k: sum(1 for s in sigs.values() if s["dir"] == k) for k in ("bull", "neu", "bear")}
    out["regCounts"] = {k: sum(1 for s in sigs.values() if s["reg"] == k) for k in ("low", "mid", "high")}
    out["baseUp3"] = sum(1 for v in base3 if v > 0) / len(base3)
    out["buckets"] = {n: bucket_table(rows, n) for n in (1, 3, 5)}
    out["hit"] = {n: hit_rate(rows, n) for n in (1, 3, 5)}
    out["hitByAgree"] = {a: hit_rate(rows, 3, filt=lambda x, a=a: (x["agree"] >= 4) if a == "4" else (x["agree"] == 3) if a == "3" else (x["agree"] <= 2))
                         for a in ("4", "3", "≤2")}
    # each step on its own, and the combined score without it
    names = ["Price trend", "OI & FII", "Option chain", "PCR"]
    steps = []
    for j, nm in enumerate(names):
        alone = hit_rate(rows, 3, key=lambda x, j=j: "bull" if x["s"][j] >= 0.35 else "bear" if x["s"][j] <= -0.35 else "neu")
        def without(x, j=j):
            b = (sum(x["s"]) - x["s"][j]) / 6 * 100
            return "bull" if b >= 20 else "bear" if b <= -20 else "neu"
        wo = hit_rate(rows, 3, key=without)
        r = [x for x in rows if 3 in x["fwd"]]
        steps.append({"step": nm, "alone": alone, "without": wo,
                      "ic": spearman([x["s"][j] for x in r], [x["fwd"][3] for x in r])})
    out["steps"] = steps
    r = [x for x in rows if 3 in x["fwd"]]
    out["icBias"] = {n: spearman([x["bias"] for x in rows if n in x["fwd"]], [x["fwd"][n] for x in rows if n in x["fwd"]]) for n in (1, 3, 5)}
    halves = [("Oct 2024 – Sep 2025", "2024-10-01", "2025-09-30"), ("Oct 2025 – Sep 2026", "2025-10-01", "2026-09-30")]
    out["halves"] = [{"name": nm, "hit": hit_rate([x for x in rows if a <= x["d"] <= b], 3),
                      "ic": spearman([x["bias"] for x in rows if a <= x["d"] <= b and 3 in x["fwd"]],
                                     [x["fwd"][3] for x in rows if a <= x["d"] <= b and 3 in x["fwd"]])} for nm, a, b in halves]

    # trading
    runs = {}
    for rule in ("stop", "expiry", "3day"):
        res = run(sigs, days, exit_rule=rule)
        runs[rule] = {"perf": perf(res), "equity": res["equity"], "trades": res["trades"], "skipped": res["skipped"]}
        print(rule, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in runs[rule]["perf"].items()}, res["skipped"])
    bench = {}
    for fd in ("bear", "bull"):
        res = run(sigs, days, exit_rule="stop", force_dir=fd)
        bench["always_" + fd] = {"perf": perf(res), "equity": res["equity"]}
    rnd = []
    for seed in range(100):
        res = run(sigs, days, exit_rule="stop", force_dir="random", rng=random.Random(seed))
        rnd.append(perf(res)["ret"])
    rnd.sort()
    bench["random"] = {"median": rnd[50], "p5": rnd[5], "p95": rnd[94], "beat": None}
    n0 = next(b for b in nifty if b["d"] >= START)
    n1 = [b for b in nifty if b["d"] <= END][-1]
    bench["nifty"] = {"ret": n1["c"] / n0["c"] - 1, "from": n0, "to": n1}
    bench["random"]["modelPctile"] = sum(1 for v in rnd if v < runs["stop"]["perf"]["ret"]) / len(rnd)
    out["runs"] = runs
    out["bench"] = bench
    out["niftyCurve"] = [{"d": b["d"], "c": b["c"]} for b in nifty if START <= b["d"] <= END]
    out["signals"] = [{"d": x["d"], "bias": round(x["bias"], 1), "dir": x["dir"], "agree": x["agree"], "reg": x["reg"],
                       "s": [round(v, 2) for v in x["s"]], "spot": x["spot"], "f3": x["fwd"].get(3)} for x in rows]
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, default=str)
    with open(os.path.join(HERE, "trades.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(runs["stop"]["trades"][0].keys()))
        w.writeheader()
        w.writerows(runs["stop"]["trades"])
    print("bias IC", out["icBias"], "hit3", out["hit"][3], "base up", out["baseUp3"])
    print("random", bench["random"], "nifty", round(bench["nifty"]["ret"], 4))


if __name__ == "__main__":
    main()

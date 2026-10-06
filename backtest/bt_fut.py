"""Nifty futures backtest of the desk signal: long on bullish, short on bearish, flat on neutral.

No look-ahead: the view at day t's close is executed at day t+1's futures close.
Real near-month futures closes from the bhavcopy; the position rolls to the next
month two sessions before expiry. Daily mark-to-market, ₹10 lakh, whole lots
sized to about 1.5x exposure, full Indian futures charges and 1 point of slippage.
"""
import datetime as dt, json, os, random, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_run as B
import desk_server as ds

CAPITAL = 1_000_000
LEVERAGE = 1.5        # target exposure / equity, rounded to whole lots (min 1)
MARGIN = 0.15         # approximate SPAN + exposure margin, share of notional
ROLL_SESSIONS = 2     # roll when this many sessions or fewer remain to expiry
SLIP = 1.0            # index points per side
BROK, STT, EXCH, SEBI, STAMP, GST = 20.0, 0.0002, 0.0000173, 0.000001, 0.00002, 0.18


def side_cost(price, units, buy):
    v = price * units
    exch, sebi = v * EXCH, v * SEBI
    c = BROK + exch + sebi + GST * (BROK + exch + sebi) + SLIP * units
    return c + (v * STAMP if buy else v * STT)


def load_fut(sessions):
    out = {}
    for d in sessions:
        p = os.path.join(ds.DATA, "btfut", d.replace("-", "") + ".json")
        out[d] = json.load(open(p))
    return out


class Market:
    def __init__(self, sessions, fut, closes):
        self.s, self.fut, self.close = sessions, fut, closes
        self.i = {d: k for k, d in enumerate(sessions)}

    def contract(self, d):
        """Near month, or the next one once ROLL_SESSIONS or fewer sessions remain."""
        exps = sorted(e for e in self.fut[d] if e > d)
        for e in exps:
            left = sum(1 for s in self.s[self.i[d] + 1:self.i[d] + 12] if s <= e)
            if left > ROLL_SESSIONS:
                return e
        return exps[-1]

    def px(self, d, e):
        return self.fut[d][e]["c"]


def run(mkt, sigs, target_of, decide_days, start, end, stop=False):
    S = mkt.s
    i0, i1 = S.index(start), S.index(end)
    cash = float(CAPITAL)
    pos = {"dir": 0}
    pending, blocked = None, None
    eq, trades, costs, switches, rolls = [], [], 0.0, 0, 0
    for i in range(i0, i1 + 1):
        d = S[i]
        # 1. mark the open position to today's close
        if pos["dir"]:
            p = mkt.px(d, pos["exp"])
            cash += pos["dir"] * pos["units"] * (p - pos["last"])
            pos["last"] = p
            # 2. roll to the next contract when expiry is near
            ne = mkt.contract(d)
            if ne != pos["exp"]:
                c = side_cost(p, pos["units"], buy=pos["dir"] < 0) + side_cost(mkt.px(d, ne), pos["units"], buy=pos["dir"] > 0)
                cash -= c
                costs += c
                pos["cost"] += c
                pos["exp"], pos["last"] = ne, mkt.px(d, ne)
                rolls += 1
        # 3. execute yesterday's decision at today's close
        if pending is not None and pending != pos["dir"]:
            if pos["dir"]:
                p = mkt.px(d, pos["exp"])
                c = side_cost(p, pos["units"], buy=pos["dir"] < 0)
                cash -= c
                costs += c
                pos["cost"] += c
                trades.append({"entry": pos["entry"], "exit": d, "dir": pos["dir"], "lots": pos["lots"],
                               "pnl": round(cash - pos["cash0"]), "why": pos.get("why", "signal")})
                pos = {"dir": 0}
                switches += 1
            if pending:
                e = mkt.contract(d)
                p = mkt.px(d, e)
                lot = mkt.fut[d][e]["lot"]
                lots = max(1, round(cash * LEVERAGE / (p * lot)))
                while lots > 0 and MARGIN * p * lot * lots > cash:
                    lots -= 1
                if lots:
                    units = lots * lot
                    c = side_cost(p, units, buy=pending > 0)
                    cash0 = cash
                    cash -= c
                    costs += c
                    sig = sigs.get(S[i - 1], {})
                    pos = {"dir": pending, "exp": e, "last": p, "units": units, "lots": lots, "entry": d,
                           "cash0": cash0, "cost": c, "res": sig.get("res"), "sup": sig.get("sup")}
                    switches += 1
        pending = None
        # 4. stop: the view is wrong once the index closes through the wall it relied on
        u = mkt.close[d]
        if stop and pos["dir"]:
            if (pos["dir"] > 0 and pos["sup"] and u < pos["sup"]) or (pos["dir"] < 0 and pos["res"] and u > pos["res"]):
                pending, blocked = 0, pos["dir"]
                pos["why"] = "stop"
        eq.append({"d": d, "eq": cash})
        # 5. today's view sets tomorrow's position
        if pending is None and d in sigs and d in decide_days and i < i1:
            t = target_of(sigs[d])
            if blocked is not None:
                if t == blocked:
                    t = 0
                else:
                    blocked = None
            pending = t
    if pos["dir"]:
        trades.append({"entry": pos["entry"], "exit": S[i1], "dir": pos["dir"], "lots": pos["lots"],
                       "pnl": round(cash - pos["cash0"]), "why": "end"})
    return {"equity": eq, "trades": trades, "costs": costs, "switches": switches, "rolls": rolls}


def perf(r):
    v = [e["eq"] for e in r["equity"]]
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    rets = [v[k] / v[k - 1] - 1 for k in range(1, len(v))]
    sd = statistics.pstdev(rets)
    tr = r["trades"]
    wins = [t["pnl"] for t in tr if t["pnl"] > 0]
    loss = [t["pnl"] for t in tr if t["pnl"] <= 0]
    return {"final": v[-1], "ret": v[-1] / CAPITAL - 1, "mdd": mdd, "sharpe": statistics.mean(rets) / sd * 250 ** 0.5 if sd else 0,
            "n": len(tr), "win": len(wins) / len(tr) if tr else 0, "avgWin": statistics.mean(wins) if wins else 0,
            "avgLoss": statistics.mean(loss) if loss else 0, "costs": r["costs"], "rolls": r["rolls"],
            "worstDay": min(v[k] - v[k - 1] for k in range(1, len(v)))}


def null_targets(model_tgt, days_, rng):
    """Random long/flat/short schedule with the model's state mix and switch rate."""
    seq = [model_tgt[d] for d in days_]
    freq = {s: seq.count(s) / len(seq) for s in (-1, 0, 1)}
    sw = sum(1 for a, b in zip(seq, seq[1:]) if a != b) / max(1, len(seq) - 1)
    st = rng.choices([-1, 0, 1], weights=[freq[-1], freq[0], freq[1]])[0]
    out = {}
    for d in days_:
        if rng.random() < sw:
            others = [s for s in (-1, 0, 1) if s != st]
            w = [freq[s] for s in others]
            st = rng.choices(others, weights=w if sum(w) else None)[0]
        out[d] = st
    return out


def main():
    nifty, vix, days, parts = B.load()
    sigs = B.build_signals(nifty, vix, days, parts)
    sessions = sorted(days)
    fut = load_fut(sessions)
    closes = {b["d"]: b["c"] for b in nifty}
    mkt = Market(sessions, fut, closes)
    start, end = B.START, B.END
    sig_days = [d for d in sessions if start <= d <= end and d in sigs]
    wk = {}
    for d in sig_days:
        wk[dt.date.fromisoformat(d).isocalendar()[:2]] = d
    weekly = set(wk.values())
    daily = set(sig_days)
    maps = {"ls": lambda s: {"bull": 1, "bear": -1, "neu": 0}[s["dir"]],
            "short": lambda s: -1 if s["dir"] == "bear" else 0,
            "long": lambda s: 1 if s["dir"] == "bull" else 0}
    names = {"ls": "Long bullish / short bearish / flat neutral", "short": "Short on bearish only", "long": "Long on bullish only"}
    configs = [("ls", "daily", False), ("ls", "weekly", False), ("ls", "daily", True),
               ("short", "daily", False), ("short", "weekly", False), ("long", "daily", False), ("long", "weekly", False)]
    out = {"meta": {"start": start, "end": end, "lev": LEVERAGE, "roll": ROLL_SESSIONS, "slip": SLIP}, "runs": []}
    rng = random.Random(21)
    for key, freq, stop in configs:
        dd = daily if freq == "daily" else weekly
        r = run(mkt, sigs, maps[key], dd, start, end, stop)
        p = perf(r)
        tgt = {d: maps[key](sigs[d]) for d in sorted(dd)}
        nulls = []
        for _ in range(300):
            nt = null_targets(tgt, sorted(dd), rng)
            rr = run(mkt, sigs, lambda s, nt=nt: nt[s["d"]], dd, start, end, stop)
            nulls.append(perf(rr)["ret"])
        nulls.sort()
        p["null"] = {"median": nulls[150], "p5": nulls[15], "p95": nulls[284], "pctile": sum(1 for v in nulls if v < p["ret"]) / 300}
        name = names[key] + (" · weekly" if freq == "weekly" else " · daily") + (" · with stop" if stop else "")
        out["runs"].append({"key": f"{key}-{freq}-{int(stop)}", "name": name, "perf": p, "switches": r["switches"],
                            "equity": [{"d": e["d"], "eq": round(e["eq"])} for e in r["equity"]], "trades": r["trades"]})
        print(f"{name:62s} ret {p['ret']:+6.1%}  mdd {p['mdd']:6.1%}  trades {p['n']:3d} win {p['win']:.0%}  costs ₹{p['costs']:,.0f}  rolls {p['rolls']}"
              f"  worst day ₹{p['worstDay']:,.0f} | random median {p['null']['median']:+.1%} (5–95% {p['null']['p5']:+.1%}..{p['null']['p95']:+.1%}) beat {p['null']['pctile']:.0%}")
    for nm, f in (("Always long (futures buy and hold)", lambda s: 1), ("Always short", lambda s: -1)):
        r = run(mkt, sigs, f, daily, start, end)
        p = perf(r)
        out.setdefault("bench", []).append({"name": nm, "perf": p, "equity": [{"d": e["d"], "eq": round(e["eq"])} for e in r["equity"]]})
        print(f"{nm:62s} ret {p['ret']:+6.1%}  mdd {p['mdd']:6.1%}  costs ₹{p['costs']:,.0f} rolls {p['rolls']}")
    # halves for the main rule
    for a, b in (("2024-10-01", "2025-09-30"), ("2025-10-01", "2026-09-30")):
        bb = max(d for d in sessions if d <= b)
        aa = min(d for d in sessions if d >= a)
        r = run(mkt, sigs, maps["ls"], daily, aa, bb)
        p = perf(r)
        al = run(mkt, sigs, lambda s: 1, daily, aa, bb)
        out.setdefault("halves", []).append({"name": f"{aa[:7]} to {bb[:7]}", "ret": p["ret"], "mdd": p["mdd"], "long": perf(al)["ret"],
                                              "nifty": closes[bb] / closes[aa] - 1})
        print(f"half {aa}..{bb}: long/short {p['ret']:+.1%} (mdd {p['mdd']:.1%}), always long {perf(al)['ret']:+.1%}, Nifty {closes[bb] / closes[aa] - 1:+.1%}")
    with open(os.path.join(HERE, "results_fut.json"), "w") as f:
        json.dump(out, f)


if __name__ == "__main__":
    main()

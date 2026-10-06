"""Signal-only and Nifty-ETF timing backtest. No options.

The ETF is modelled by the Nifty 50 index itself (a Nifty ETF tracks it closely;
dividends of roughly 1.2% a year are left out of every line, buy-and-hold included).

No look-ahead: the model's view at day t's close sets the target position, which
is executed at the NEXT session (close by default; the open variant uses the
index open). Costs are charged on every switch.
"""
import json, os, random, statistics, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_run as B

CAPITAL = 1_000_000
# Delivery costs per switch, as a share of the amount traded (assumptions; see report)
BUY_COST = 0.00015 + 0.0000297 * 1.18 + 0.000001 + 0.0005   # stamp duty, exchange+GST, SEBI, half-spread
SELL_COST = 0.00001 + 0.0000297 * 1.18 + 0.000001 + 0.0005  # STT on ETF units, exchange+GST, SEBI, half-spread
DP_CHARGE = 15.93                                            # flat per sell, ₹
CASH_YIELD = 0.0                                             # idle cash earns nothing in the main runs


def simulate(days, closes, opens, target, execute="close", cash_yield=CASH_YIELD):
    """target[d] = 1 (invested) or 0 (cash), decided at d's close."""
    eq, units, cash = [], 0.0, float(CAPITAL)
    pos = 0
    switches, costs = 0, 0.0
    pending = None
    daily_cash = (1 + cash_yield) ** (1 / 250) - 1
    for i, d in enumerate(days):
        c, o = closes[d], opens[d]
        if pending is not None and pending != pos:
            px = c if execute == "close" else o
            if pending == 1:
                fee = cash * BUY_COST
                units = (cash - fee) / px
                costs += fee
                cash = 0.0
            else:
                gross = units * px
                fee = gross * SELL_COST + DP_CHARGE
                cash = gross - fee
                costs += fee
                units = 0.0
            pos = pending
            switches += 1
        pending = None
        cash *= 1 + daily_cash
        eq.append({"d": d, "eq": cash + units * c})
        if d in target:
            pending = target[d]
    return eq, switches, costs


def stats(eq, invested_days=None):
    v = [e["eq"] for e in eq]
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    r = [v[i] / v[i - 1] - 1 for i in range(1, len(v))]
    sd = statistics.pstdev(r)
    yrs = len(v) / 250
    return {"final": v[-1], "ret": v[-1] / CAPITAL - 1, "cagr": (v[-1] / CAPITAL) ** (1 / yrs) - 1, "mdd": mdd,
            "vol": sd * 250 ** 0.5, "sharpe": statistics.mean(r) / sd * 250 ** 0.5 if sd else 0}


def main():
    nifty, vix, days, parts = B.load()
    sigs = B.build_signals(nifty, vix, days, parts)
    bars = {b["d"]: b for b in nifty}
    tdays = [d for d in sorted(bars) if B.START <= d <= B.END]
    closes = {d: bars[d]["c"] for d in tdays}
    opens = {d: bars[d]["o"] for d in tdays}
    S = {d: s for d, s in sigs.items() if d in closes}

    rules = {
        "bull_only": ("Invested only on bullish days", lambda s: 1 if s["dir"] == "bull" else 0),
        "not_bear": ("Invested unless bearish", lambda s: 0 if s["dir"] == "bear" else 1),
        "agree3": ("Out only on strong bearish (3+ steps agree)", lambda s: 0 if s["dir"] == "bear" and s["agree"] >= 3 else 1),
        "pcr": ("PCR step only: out when PCR is bearish", lambda s: 0 if s["s"][3] <= -0.35 else 1),
    }
    out = {"rules": {}, "meta": {"start": tdays[0], "end": tdays[-1], "days": len(tdays), "buy": BUY_COST, "sell": SELL_COST, "dp": DP_CHARGE}}
    # buy and hold: buy at the first close
    bh_eq, _, bh_cost = simulate(tdays, closes, opens, {d: 1 for d in tdays[:1]}, "close")
    out["bh"] = {**stats(bh_eq), "costs": bh_cost, "equity": bh_eq}
    rng = random.Random(7)
    for key, (name, f) in rules.items():
        tgt = {d: f(s) for d, s in S.items()}
        res = {}
        for ex in ("close", "open"):
            eq, sw, cost = simulate(tdays, closes, opens, tgt, ex)
            res[ex] = {**stats(eq), "switches": sw, "costs": cost}
            if ex == "close":
                res["equity"] = eq
        eq6, _, _ = simulate(tdays, closes, opens, tgt, "close", cash_yield=0.065)
        res["withYield"] = stats(eq6)
        frac = sum(tgt.values()) / len(tgt)
        # null model: random daily in/out with the same share of days invested and the same average holding run
        runs_ = []
        flips = res["close"]["switches"] / len(tgt)
        for _ in range(300):
            st, rt = (1 if rng.random() < frac else 0), {}
            for d in tdays:
                # two-state chain with the same time invested (frac) and switch rate (flips)
                p_flip = flips * (0.5 / (1 - frac) if st == 0 else 0.5 / frac) if 0 < frac < 1 else 0
                if rng.random() < p_flip:
                    st = 1 - st
                rt[d] = st
            e, _, _ = simulate(tdays, closes, opens, rt, "close")
            runs_.append(e[-1]["eq"] / CAPITAL - 1)
        runs_.sort()
        res["random"] = {"median": runs_[150], "p5": runs_[15], "p95": runs_[284],
                         "pctile": sum(1 for v in runs_ if v < res["close"]["ret"]) / len(runs_)}
        res["name"], res["invested"] = name, frac
        out["rules"][key] = res
        print(f"{name:45s} ret {res['close']['ret']:+.1%} (open-exec {res['open']['ret']:+.1%}, +6.5% cash {res['withYield']['ret']:+.1%})"
              f"  mdd {res['close']['mdd']:.1%}  invested {frac:.0%}  switches {res['close']['switches']}  costs ₹{res['close']['costs']:,.0f}"
              f"  random median {res['random']['median']:+.1%}  pctile {res['random']['pctile']:.0%}")
    print(f"{'Buy and hold':45s} ret {out['bh']['ret']:+.1%}  mdd {out['bh']['mdd']:.1%}")

    # signal-only: longer horizons, relevant to an ETF holder
    ds_ = tdays
    pos = {d: i for i, d in enumerate(ds_)}
    sig_tab = {}
    for n in (1, 3, 5, 10, 20):
        rows = [(s, closes[ds_[pos[d] + n]] / closes[d] - 1) for d, s in S.items() if pos[d] + n < len(ds_)]
        base_up = sum(1 for _, r in rows if r > 0) / len(rows)
        t = {"n": n, "baseUp": base_up}
        for k, sg in (("bull", 1), ("bear", -1), ("neu", 0)):
            rr = [r for s, r in rows if s["dir"] == k]
            t[k] = {"n": len(rr), "mean": statistics.mean(rr) if rr else None,
                    "hit": (sum(1 for r in rr if r * sg > 0) / len(rr)) if rr and sg else None}
        t["ic"] = B.spearman([s["bias"] for s, _ in rows], [r for _, r in rows])
        allr = [r for _, r in rows]
        t["allMean"] = statistics.mean(allr)
        sig_tab[n] = t
        print(f"{n:2d}d  base up {base_up:.0%}  bull: n={t['bull']['n']} hit {t['bull']['hit']:.0%} avg {t['bull']['mean']:+.2%} | "
              f"bear: n={t['bear']['n']} hit {t['bear']['hit']:.0%} avg {t['bear']['mean']:+.2%} | neutral avg {t['neu']['mean']:+.2%} | all {t['allMean']:+.2%} | IC {t['ic']:+.3f}")
    out["signal"] = sig_tab
    with open(os.path.join(HERE, "results_etf.json"), "w") as f:
        json.dump(out, f)


if __name__ == "__main__":
    main()

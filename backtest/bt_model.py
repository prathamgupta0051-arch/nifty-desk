"""Python port of the dashboard's six-step scoring (nifty-desk.html, compute()).

Every function takes only data dated on or before the signal day, so nothing
from the future can leak in. Rules and thresholds are copied from the dashboard;
see NIFTY_POSITIONING_DESK.md section 5.
"""
import math
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import desk_server as ds


def clamp(v, a, b):
    return max(a, min(b, v))


def sgn(x):
    return (x > 0) - (x < 0)


def jsround(x):  # JavaScript Math.round (half up), not Python's banker's rounding
    return math.floor(x + 0.5)


# ---------------------------------------------------------------- step 1
def step1(bars):
    closes = [b["c"] for b in bars]
    spot = closes[-1]
    mas = [ds.sma(closes, n) for n in (20, 50, 200)]
    ma_s = sum(sgn(spot - m) for m in mas) / 3
    structure, _, _ = ds.swing_structure(bars)
    st = {"hhhl": 1, "range": 0, "lhll": -1}[structure]
    return clamp(ma_s + st, -2, 2), {"dma": mas, "structure": structure}


# ---------------------------------------------------------------- step 2
def step2(price0, price1, oi1, chg, part_now, part_prev):
    oi0 = oi1 - chg
    pc = (price1 - price0) / (price0 or 1) * 100
    oc = (oi1 - oi0) / (oi0 or 1) * 100
    if pc >= 0 and oc >= 0:
        q = "lb"
    elif pc < 0 and oc >= 0:
        q = "sb"
    elif pc >= 0:
        q = "sc"
    else:
        q = "lu"
    qs = {"lb": 1.25, "sb": -1.25, "sc": 0.5, "lu": -0.5}[q]
    if abs(oc) < 1:
        qs *= 0.5
    f, fp = part_now["FII"], part_prev["FII"]
    lp = f["l"] / ((f["l"] + f["s"]) or 1) * 100
    plp = fp["l"] / ((fp["l"] + fp["s"]) or 1) * 100
    dlp = lp - plp
    if dlp >= 3:
        fs = 0.75
    elif dlp <= -3:
        fs = -0.75
    elif lp < 15:
        fs = -0.5
    elif lp > 70:
        fs = 0.5
    else:
        fs = 0
    return clamp(qs + fs, -2, 2), {"quad": q, "pc": pc, "oc": oc, "fiiLong": lp, "fiiChg": dlp}


# ---------------------------------------------------------------- step 3
IV_EDGE = 0.1
FLOW = {
    "C": {"write": {"otm": ("bear", 1.0), "itm": ("bear", 0.5)},
          "buy": {"otm": ("bull", 0.5), "itm": ("bull", 0.3)},
          "cover": {"otm": ("bull", 0.7), "itm": ("bull", 0.5)},
          "exit": {"otm": ("bear", 0.3), "itm": ("bear", 0.3)}},
    "P": {"write": {"otm": ("bull", 1.0), "itm": ("bull", 0.5)},
          "buy": {"otm": ("bear", 0.5), "itm": ("bear", 0.3)},
          "cover": {"otm": ("bear", 0.7), "itm": ("bear", 0.5)},
          "exit": {"otm": ("bull", 0.3), "itm": ("bull", 0.3)}},
}


def nearest_expiry(opt, d_iso):
    xs = sorted(x for x in opt if x > d_iso)
    return xs[0] if xs else None


def chain_rows(day, spot):
    exp = nearest_expiry(day["opt"], day["d"])
    if not exp:
        return None, []
    rows = []
    for k, v in day["opt"][exp]["k"].items():
        k = int(k)
        if k % 100 or abs(k - spot) > 600:
            continue
        c, p = v.get("CE"), v.get("PE")
        if not c or not p:
            continue
        rows.append({"k": k, "ce": c[0], "dce": c[1], "cp": c[3], "cvol": c[4],
                     "pe": p[0], "dpe": p[1], "pp": p[3], "pvol": p[4]})
    rows.sort(key=lambda r: r["k"])
    return exp, rows


def add_iv_pressure(rows, exp, day, prev_day, spot_now):
    """Same method as desk_server.enrich_chain: Black-76 IV off the parity forward,
    compared with yesterday's smile at the same moneyness, minus the market-wide shift."""
    if not prev_day or exp not in prev_day["opt"]:
        return None
    xd, td, pd = date.fromisoformat(exp), date.fromisoformat(day["d"]), date.fromisoformat(prev_day["d"])
    t_now, t_prev = max((xd - td).days, 1 / 24) / 365, max((xd - pd).days, 1 / 24) / 365
    prev = prev_day["opt"][exp]["k"]
    prev_px = {int(k): ((v.get("CE") or [0, 0, 0, None])[3], (v.get("PE") or [0, 0, 0, None])[3]) for k, v in prev.items()}
    f_now = ds.implied_forward({r["k"]: (r["cp"], r["pp"]) for r in rows}, spot_now, t_now)
    f_prev = ds.implied_forward(prev_px, prev_day["und"], t_prev)
    smile = []
    for k, (c, p) in prev_px.items():
        cp = "CE" if k >= f_prev else "PE"
        iv = ds.implied_vol(cp, c if cp == "CE" else p, f_prev, k, t_prev)
        if iv and abs(k - f_prev) <= 2000:
            smile.append((k, iv))
    smile.sort()

    def at(x):
        for (a, ia), (b, ib) in zip(smile, smile[1:]):
            if a <= x <= b:
                return ia + (ib - ia) * (x - a) / (b - a)
        return None

    res = []
    for r in rows:
        otm = "CE" if r["k"] >= f_now else "PE"
        iv_now = ds.implied_vol(otm, r["cp"] if otm == "CE" else r["pp"], f_now, r["k"], t_now)
        iv_exp = at(r["k"] * f_prev / f_now)
        r["ivRes"] = round(iv_now - iv_exp, 2) if iv_now and iv_exp else None
        if r["ivRes"] is not None:
            res.append(r["ivRes"])
    mkt = sorted(res)[len(res) // 2] if res else None
    for r in rows:
        r["ivS"] = round(r["ivRes"] - mkt, 2) if r["ivRes"] is not None and mkt is not None else None
    return mkt


def step3(rows, spot):
    if not rows:
        return 0.0, {"res": None, "sup": None, "net": 0}
    mx = max(1, max(max(r["ce"], r["pe"]) for r in rows))
    mxd = max(1, max(max(abs(r["dce"]), abs(r["dpe"])) for r in rows))
    scores = []
    for r in rows:
        ivs = r.get("ivS")
        for sd in ("C", "P"):
            oi, d, vol, other = (r["ce"], r["dce"], r["cvol"], r["dpe"]) if sd == "C" else (r["pe"], r["dpe"], r["pvol"], r["dce"])
            if not d:
                continue
            itm_pts = spot - r["k"] if sd == "C" else r["k"] - spot
            zone = "ATM" if abs(r["k"] - spot) <= 50 else "ITM" if itm_pts > 0 else "OTM"
            if ivs is not None:
                act = ("write" if d > 0 else "exit") if ivs <= -IV_EDGE else ("buy" if d > 0 else "cover") if ivs >= IV_EDGE else None
            else:
                act = "write" if d > 0 else "cover"
            view, w = ("neu", 0.0)
            if act:
                view, w = FLOW[sd][act]["itm" if zone == "ITM" else "otm"]
            if zone == "ITM" and itm_pts > 200:
                w *= 0.5
            if vol and abs(d) / vol < 0.01:
                w *= 0.5
            if ivs is not None and abs(other) > abs(d):
                w *= 0.6
            scores.append((1 if view == "bull" else -1 if view == "bear" else 0) * w * abs(d) / mxd)
    tot = sum(abs(s) for s in scores) or 1
    net = sum(scores) / tot

    def wall(key, ok):
        best = None
        for r in rows:
            if ok(r["k"]) and (best is None or r[key] > best[1]):
                best = (r["k"], r[key])
        return best[0] if best else None

    res = wall("ce", lambda k: k >= spot - 50)
    sup = wall("pe", lambda k: k <= spot + 50)
    s3 = 1.5 * net
    if res and spot > res:
        s3 += 0.5
    elif sup and spot < sup:
        s3 -= 0.5
    return clamp(s3, -2, 2), {"res": res, "sup": sup, "net": net}


# ---------------------------------------------------------------- step 4
def step4(pcr_hist, hi=1.5, lo=0.7):
    h = [round(x, 2) for x in pcr_hist][-10:]
    p = h[-1]
    ref = h[-6] if len(h) > 5 else h[0]
    d = p - ref
    if p >= hi:
        s = -1
    elif p <= lo:
        s = 1
    elif d <= -0.15:
        s = -1
    elif d >= 0.15:
        s = 1
    else:
        s = 0.3 if p > 1.1 else -0.3 if p < 0.85 else 0
    return s, {"pcr": p, "pcrChg": d}


# ---------------------------------------------------------------- step 5
def step5(vix_closes):
    v = vix_closes[-250:]
    iv = v[-1]
    ivp = round(sum(1 for x in v if x < iv) / len(v) * 100)
    reg = "low" if ivp < 30 else "high" if ivp > 70 else "mid"
    return reg, {"vix": iv, "ivp": ivp}


# ---------------------------------------------------------------- combine + step 6
def combine(s):
    bias = sum(s) / 8 * 100
    d = "bull" if bias >= 20 else "bear" if bias <= -20 else "neu"
    sg = 1 if d == "bull" else -1 if d == "bear" else 0
    if sg == 0:
        agree = sum(1 for x in s if abs(x) < 0.35)
    else:
        agree = sum(1 for x in s if sgn(x) == sg and abs(x) >= 0.35)
    return bias, d, agree


NAMES = {"bull-low": "Long call", "bull-mid": "Bull call spread", "bull-high": "Bull put spread",
         "neu-low": "Long straddle", "neu-mid": "Iron butterfly", "neu-high": "Iron condor",
         "bear-low": "Long put", "bear-mid": "Bear put spread", "bear-high": "Bear call spread"}


def legs(direction, reg, spot, sup_wall, res_wall, w=200):
    atm = jsround(spot / 50) * 50
    sup = sup_wall if (sup_wall and sup_wall < spot) else atm - w / 2
    res = res_wall if (res_wall and res_wall > spot) else atm + w / 2
    L = lambda t, k, q: (t, jsround(k / 50) * 50, q)
    book = {
        "bull-low": [L("CE", atm, 1)],
        "bull-mid": [L("CE", atm, 1), L("CE", atm + w, -1)],
        "bull-high": [L("PE", sup, -1), L("PE", sup - w, 1)],
        "neu-low": [L("CE", atm, 1), L("PE", atm, 1)],
        "neu-mid": [L("CE", atm, -1), L("PE", atm, -1), L("CE", atm + w, 1), L("PE", atm - w, 1)],
        "neu-high": [L("PE", sup, -1), L("PE", sup - w, 1), L("CE", res, -1), L("CE", res + w, 1)],
        "bear-low": [L("PE", atm, 1)],
        "bear-mid": [L("PE", atm, 1), L("PE", atm - w, -1)],
        "bear-high": [L("CE", res, -1), L("CE", res + w, 1)],
    }
    key = f"{direction}-{reg}"
    return NAMES[key], book[key], sup, res

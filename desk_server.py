#!/usr/bin/env python3
"""Nifty Positioning Desk - live data server.

Pulls Nifty data from NSE (option chain, futures, participant OI, bhavcopy,
index and India VIX history), computes the inputs for the six-step desk
framework, and serves the dashboard at http://127.0.0.1:8765

Run:  python3 desk_server.py          (stdlib only, no installs needed)
"""
import csv, io, json, math, os, ssl, sys, threading, time, traceback, webbrowser, zipfile
from datetime import datetime, timedelta, timezone, date
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPSHandler
from urllib.error import HTTPError, URLError

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DESK_DATA") or os.path.join(HERE, "data")  # the Mac service sets DESK_DATA to keep its files out of the repo
PAGE = os.path.join(HERE, "nifty-desk.html")
PORT = int(os.environ.get("DESK_PORT", "8765"))
IST = timezone(timedelta(hours=5, minutes=30))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

LIVE_EVERY_OPEN = 60        # seconds between live pulls while the market is open
LIVE_EVERY_CLOSED = 15 * 60 # ... and while it is closed
HIST_DAYS = 11              # trading days of bhavcopy / participant history


def now_ist():
    return datetime.now(IST)


def market_open(t=None):
    t = t or now_ist()
    if t.weekday() >= 5:
        return False
    m = t.hour * 60 + t.minute
    return 9 * 60 + 15 <= m <= 15 * 60 + 30


def log(*a):
    print(now_ist().strftime("%H:%M:%S"), *a, flush=True)


def ssl_context():
    """python.org builds on macOS ship without CA certs; fall back to the system bundle."""
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        for f in ("/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem", "/opt/homebrew/etc/openssl@3/cert.pem"):
            if os.path.exists(f):
                ctx.load_verify_locations(cafile=f)
                break
    return ctx


# ---------------------------------------------------------------- NSE session
class NSE:
    def __init__(self):
        self.jar = CookieJar()
        self.op = build_opener(HTTPCookieProcessor(self.jar), HTTPSHandler(context=ssl_context()))
        self.warm_at = 0
        self.lock = threading.Lock()

    def _open(self, url, accept, referer=None, timeout=25):
        h = {"User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"}
        if referer:
            h["Referer"] = referer
        with self.op.open(Request(url, headers=h), timeout=timeout) as r:
            return r.read()

    def warm(self):
        self._open("https://www.nseindia.com/option-chain", "text/html,application/xhtml+xml")
        self.warm_at = time.time()

    def json(self, path, referer="https://www.nseindia.com/option-chain"):
        url = "https://www.nseindia.com" + path
        with self.lock:
            for attempt in range(3):
                try:
                    if time.time() - self.warm_at > 240 or attempt:
                        self.warm()
                    time.sleep(0.35)
                    return json.loads(self._open(url, "application/json, text/plain, */*", referer))
                except (HTTPError, URLError, ValueError, TimeoutError) as e:
                    last = e
                    time.sleep(1.5 * (attempt + 1))
            raise RuntimeError(f"NSE {path}: {last}")

    def archive(self, url):
        """Returns bytes, or None when the file doesn't exist (holiday / not published yet)."""
        try:
            time.sleep(0.25)
            return self._open(url, "*/*", timeout=40)
        except HTTPError as e:
            if e.code in (403, 404):
                return None
            raise


nse = NSE()


def cache_path(*p):
    path = os.path.join(DATA, *p)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def read_cache(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_cache(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def weekdays_back(start, n_max=30):
    d = start
    for _ in range(n_max):
        if d.weekday() < 5:
            yield d
        d -= timedelta(days=1)


# ---------------------------------------------------------------- end-of-day history
def bhavcopy(d):
    """Aggregates for NIFTY from the F&O bhavcopy of date d, cached on disk."""
    path = cache_path("bhav", d.strftime("%Y%m%d") + ".json")
    c = read_cache(path)
    if c is not None and (c == {} or c.get("ver") == 3):
        return c or None
    raw = nse.archive("https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_"
                      f"{d.strftime('%Y%m%d')}_F_0000.csv.zip")
    if raw is None:
        if d < now_ist().date():  # past day with no file = holiday; remember that
            write_cache(path, {})
        return None
    z = zipfile.ZipFile(io.BytesIO(raw))
    text = z.read(z.namelist()[0]).decode("utf-8", "replace")
    fut_oi = fut_chg = ce = pe = 0.0
    near = None
    lot = None
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("TckrSymb") != "NIFTY":
            continue
        tp, xp, td = r["FinInstrmTp"], r["XpryDt"], r["TradDt"]
        if tp == "IDF":  # daily change counts every contract, so a roll nets out
            fut_chg += float(r["ChngInOpnIntrst"] or 0)
        if xp <= td:  # contract expiring today won't exist tomorrow; leave it out
            continue
        oi = float(r["OpnIntrst"] or 0)
        lot = lot or int(float(r["NewBrdLotQty"] or 0) or 0) or None
        if tp == "IDF":
            fut_oi += oi
            if near is None or xp < near[0]:
                near = (xp, float(r["ClsPric"] or 0))
        elif tp == "IDO":
            if r["OptnTp"] == "CE":
                ce += oi
            elif r["OptnTp"] == "PE":
                pe += oi
    lot = lot or 65
    out = {"d": d.isoformat(), "close": near[1] if near else None,
           "oi": round(fut_oi / lot), "chg": round(fut_chg / lot), "ver": 3, "pcr": round(pe / ce, 3) if ce else None, "lot": lot}
    write_cache(path, out)
    return out


def bhav_options(d):
    """Closing price of every NIFTY option (expiries within 45 days) from the bhavcopy of date d."""
    path = cache_path("bhavopt", d.strftime("%Y%m%d") + ".json")
    c = read_cache(path)
    if c is not None:
        return c or None
    raw = nse.archive("https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_"
                      f"{d.strftime('%Y%m%d')}_F_0000.csv.zip")
    if raw is None:
        return None
    z = zipfile.ZipFile(io.BytesIO(raw))
    text = z.read(z.namelist()[0]).decode("utf-8", "replace")
    out, und, horizon = {}, None, (d + timedelta(days=45)).isoformat()
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("TckrSymb") != "NIFTY" or r["FinInstrmTp"] != "IDO" or r["XpryDt"] > horizon:
            continue
        und = und or float(r["UndrlygPric"])
        k = str(int(float(r["StrkPric"])))
        out.setdefault(r["XpryDt"], {}).setdefault(k, {})[r["OptnTp"]] = float(r["ClsPric"] or 0)
    res = {"d": d.isoformat(), "und": und, "x": out}
    write_cache(path, res)
    return res


RATE = 0.065


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def b76_price(cp, F, K, T, v, r=RATE):
    """Black-76 on the forward: pricing off the parity-implied forward removes the
    timing gap between the index close and the option closes."""
    sq = math.sqrt(T)
    d1 = (math.log(F / K) + v * v / 2 * T) / (v * sq)
    d2 = d1 - v * sq
    df = math.exp(-r * T)
    if cp == "CE":
        return df * (F * _ncdf(d1) - K * _ncdf(d2))
    return df * (K * _ncdf(-d2) - F * _ncdf(-d1))


def implied_forward(prices, S, T, r=RATE):
    """Median of K + e^rT (C - P) over strikes near spot. prices: {strike: (call, put)}."""
    near = sorted((abs(k - S), k) for k, (c, p) in prices.items() if c and p)[:3]
    fs = sorted(k + math.exp(r * T) * (prices[k][0] - prices[k][1]) for _, k in near)
    return fs[len(fs) // 2] if fs else S


def implied_vol(cp, price, F, K, T):
    """Black-76 IV by bisection. None when the price is mostly intrinsic (IV is unreliable)."""
    if not price or price <= 0 or T <= 0:
        return None
    intrinsic = max(0.0, F - K) if cp == "CE" else max(0.0, K - F)
    if price - intrinsic < 3:  # under 3 points of time value: too little to read IV from
        return None
    lo, hi = 0.005, 3.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if b76_price(cp, F, K, T, mid) > price:
            hi = mid
        else:
            lo = mid
    return round(mid * 100, 2)


def participant(d):
    """Index-futures long/short contracts by participant for date d."""
    path = cache_path("part", d.strftime("%Y%m%d") + ".json")
    c = read_cache(path)
    if c is not None:
        return c or None
    raw = nse.archive("https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_"
                      f"{d.strftime('%d%m%Y')}.csv")
    if raw is None or b"Client Type" not in raw:
        if d < now_ist().date():
            write_cache(path, {})
        return None
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8", "replace"))))
    hdr = next(i for i, r in enumerate(rows) if r and r[0].strip() == "Client Type")
    cols = [h.strip() for h in rows[hdr]]
    il, ish = cols.index("Future Index Long"), cols.index("Future Index Short")
    out = {"d": d.isoformat()}
    for r in rows[hdr + 1:]:
        name = r[0].strip() if r else ""
        if name in ("Client", "DII", "FII", "Pro"):
            out[name] = {"l": int(float(r[il])), "s": int(float(r[ish]))}
    write_cache(path, out)
    return out


def collect(fn, today, n):
    got = []
    for d in weekdays_back(today, 40):
        try:
            r = fn(d)
        except Exception as e:  # network hiccup on one file shouldn't sink the rest
            log("skip", fn.__name__, d, e)
            r = None
        if r:
            got.append(r)
        if len(got) >= n:
            break
    return list(reversed(got))


def index_history(kind, days):
    """kind 'nifty' or 'vix'. Daily OHLC, oldest first; cached per day."""
    today = now_ist().date()
    path = cache_path("hist", f"{kind}_{today.isoformat()}.json")
    c = read_cache(path)
    if c:
        return c
    rows = {}
    end = today
    start_all = today - timedelta(days=days)
    while end > start_all:
        start = max(start_all, end - timedelta(days=85))
        q = f"from={start.strftime('%d-%m-%Y')}&to={end.strftime('%d-%m-%Y')}"
        if kind == "nifty":
            j = nse.json("/api/historicalOR/indicesHistory?indexType=NIFTY%2050&" + q,
                         "https://www.nseindia.com/reports-indices-historical-index-data")
        else:
            j = nse.json("/api/historicalOR/vixhistory?" + q,
                         "https://www.nseindia.com/reports-indices-historical-vix")
        for x in j.get("data", []):
            d = datetime.strptime(x["EOD_TIMESTAMP"].title(), "%d-%b-%Y").date().isoformat()
            rows[d] = {"d": d, "h": float(x["EOD_HIGH_INDEX_VAL"]),
                       "l": float(x["EOD_LOW_INDEX_VAL"]), "c": float(x["EOD_CLOSE_INDEX_VAL"])}
        end = start - timedelta(days=1)
    out = [rows[k] for k in sorted(rows)]
    if out:
        write_cache(path, out)
    return out


# ---------------------------------------------------------------- analytics
def sma(xs, n):
    return round(sum(xs[-n:]) / n, 2) if len(xs) >= n else None


def swing_structure(bars, look=90, k=3):
    """Compare the last two pivot highs and lows (k-bar fractals)."""
    b = bars[-look:]
    hs, ls = [], []
    for i in range(k, len(b) - k):
        win = b[i - k:i + k + 1]
        if b[i]["h"] == max(x["h"] for x in win):
            hs.append(b[i]["h"])
        if b[i]["l"] == min(x["l"] for x in win):
            ls.append(b[i]["l"])
    if len(hs) < 2 or len(ls) < 2:
        return "range", hs[-2:], ls[-2:]
    hh, hl = hs[-1] > hs[-2], ls[-1] > ls[-2]
    lh, ll = hs[-1] < hs[-2], ls[-1] < ls[-2]
    s = "hhhl" if hh and hl else "lhll" if lh and ll else "range"
    return s, hs[-2:], ls[-2:]


# ---------------------------------------------------------------- state
STATE = {"loading": True, "errors": []}
DAILY = {}
state_lock = threading.Lock()


def refresh_daily():
    today = now_ist().date()
    log("pulling end-of-day history …")
    nifty = index_history("nifty", 430)
    vix = index_history("vix", 370)
    bh = collect(bhavcopy, today, HIST_DAYS)
    pt = collect(participant, today, HIST_DAYS)
    DAILY.update({"nifty": nifty, "vix": vix, "bhav": bh, "part": pt,
                  "day": today.isoformat(), "at": time.time()})
    log(f"history ok: {len(nifty)} Nifty days, {len(vix)} VIX days, "
        f"{len(bh)} bhavcopies (last {bh[-1]['d'] if bh else '-'}), "
        f"{len(pt)} participant files (last {pt[-1]['d'] if pt else '-'})")


def daily_stale():
    if not DAILY:
        return True
    t = now_ist()
    if DAILY["day"] != t.date().isoformat():
        return True
    # after the close NSE publishes today's files in the evening; re-check every 30 min
    have_today = DAILY["bhav"] and DAILY["bhav"][-1]["d"] == t.date().isoformat() \
        and DAILY["part"] and DAILY["part"][-1]["d"] == t.date().isoformat()
    return t.weekday() < 5 and t.hour >= 16 and not have_today and time.time() - DAILY["at"] > 1800


def refresh_live():
    t = now_ist()
    errs = []
    out = {}

    # Spot + India VIX
    try:
        ai = nse.json("/api/allIndices", "https://www.nseindia.com/market-data/live-market-indices")
        for x in ai["data"]:
            if x["index"] == "NIFTY 50":
                out["spot"] = float(x["last"])
                out["spotPrev"] = float(x.get("previousClose") or 0)
            elif x["index"] == "INDIA VIX":
                out["vix"] = float(x["last"])
    except Exception as e:
        errs.append(f"index quote: {e}")

    # Nifty futures (all expiries)
    try:
        fj = nse.json("/api/liveEquity-derivatives?index=nse50_fut",
                      "https://www.nseindia.com/market-data/equity-derivatives-watch")
        futs = [x for x in fj["data"] if x.get("underlying") == "NIFTY"]
        futs.sort(key=lambda x: datetime.strptime(x["expiryDate"], "%d-%b-%Y"))
        out["futLive"] = {"d": t.date().isoformat(), "close": float(futs[0]["lastPrice"]),
                          "oi": int(sum(float(x["openInterest"]) for x in futs)),
                          "contract": futs[0]["contract"]}
    except Exception as e:
        errs.append(f"futures: {e}")

    # Option chain, nearest expiry
    try:
        info = nse.json("/api/option-chain-contract-info?symbol=NIFTY")
        exps = [datetime.strptime(x, "%d-%b-%Y").date() for x in info["expiryDates"]]
        exps = [e for e in exps if e > t.date() or (e == t.date() and t.hour * 60 + t.minute < 15 * 60 + 30)]
        exp = exps[0]
        oc = nse.json(f"/api/option-chain-v3?type=Indices&symbol=NIFTY&expiry={exp.strftime('%d-%b-%Y')}")
        spot = out.get("spot") or float(oc["records"]["underlyingValue"])
        out.setdefault("spot", spot)
        rows, tce, tpe = [], 0.0, 0.0
        atm = round(spot / 50) * 50
        atm_iv = []
        for r in oc["records"]["data"]:
            k = float(r["strikePrice"])
            ce, pe = r.get("CE") or {}, r.get("PE") or {}
            tce += ce.get("openInterest", 0) or 0
            tpe += pe.get("openInterest", 0) or 0
            if k == atm:
                atm_iv = [v for v in (ce.get("impliedVolatility"), pe.get("impliedVolatility")) if v]
            if abs(k - spot) <= 600 and k % 100 == 0:
                rows.append({"k": int(k), "ce": int(ce.get("openInterest", 0) or 0),
                             "dce": int(ce.get("changeinOpenInterest", 0) or 0),
                             "pe": int(pe.get("openInterest", 0) or 0),
                             "dpe": int(pe.get("changeinOpenInterest", 0) or 0),
                             "cp": ce.get("lastPrice"), "cchg": ce.get("change"), "cvol": ce.get("totalTradedVolume"),
                             "pp": pe.get("lastPrice"), "pchg": pe.get("change"), "pvol": pe.get("totalTradedVolume")})
        rows.sort(key=lambda r: r["k"])
        out.update({"chain": rows, "expiry": exp.isoformat(),
                    "dte": max(1, (exp - t.date()).days),
                    "pcrLive": round(tpe / tce, 3) if tce else None,
                    "atmIv": round(sum(atm_iv) / len(atm_iv), 2) if atm_iv else None,
                    "chainTime": oc["records"].get("timestamp")})
    except Exception as e:
        errs.append(f"option chain: {e}")
    return out, errs


def build_payload(live, errs):
    t = now_ist()
    # live prints only count as "today" once today's session has started
    traded_today = t.weekday() < 5 and t.hour * 60 + t.minute >= 9 * 60 + 15
    p = {"live": True, "marketOpen": market_open(t), "updated": t.strftime("%d %b %Y, %H:%M:%S IST"),
         "asof": t.date().isoformat(), "errors": errs}
    p.update({k: v for k, v in live.items() if k in ("spot", "spotPrev", "chain", "expiry", "dte", "pcrLive", "atmIv", "chainTime")})

    # Step 3: per-strike IV today vs the previous session's close (backfilled from bhavcopy),
    # so we can tell writers from buyers: IV falling while OI rises = writing, etc.
    try:
        enrich_chain(p, live)
    except Exception as e:
        errs.append(f"strike IV: {e}")

    # Step 1: moving averages + structure from daily closes (+ today's live print)
    bars = list(DAILY.get("nifty") or [])
    spot = live.get("spot")
    if spot and traded_today and (not bars or bars[-1]["d"] < t.date().isoformat()):
        bars.append({"d": t.date().isoformat(), "h": spot, "l": spot, "c": spot})
    closes = [b["c"] for b in bars]
    if closes:
        p.update({"dma20": sma(closes, 20), "dma50": sma(closes, 50), "dma200": sma(closes, 200)})
        s, hs, ls = swing_structure(bars)
        p.update({"structure": s, "swingHighs": hs, "swingLows": ls,
                  "closes": [round(c, 2) for c in closes[-120:]]})

    # Step 2: futures price/OI series (EOD bhavcopy + live), participant OI
    # OI is chained from each day's reported change, so an expiring contract
    # dropping out of the file doesn't read as unwinding. Price uses the spot close,
    # which avoids the basis jump when the near-month contract rolls.
    bh = [b for b in DAILY.get("bhav", []) if b.get("close")]
    spot_close = {b["d"]: b["c"] for b in DAILY.get("nifty") or []}
    fut = []
    if bh:
        adj = [0] * len(bh)
        adj[-1] = bh[-1]["oi"]
        for i in range(len(bh) - 1, 0, -1):
            adj[i - 1] = adj[i] - bh[i]["chg"]
        fut = [{"d": b["d"], "close": spot_close.get(b["d"], b["close"]), "oi": adj[i]} for i, b in enumerate(bh)]
    fl = live.get("futLive")
    if fl and traded_today and (not fut or fl["d"] > fut[-1]["d"]):
        fut.append({"d": fl["d"], "close": spot or fl["close"], "oi": fl["oi"]})
    p["futHist"] = fut
    pt = DAILY.get("part") or []
    if len(pt) >= 2:
        a, b = pt[-1], pt[-2]
        p["part"] = {n: {"l": a[n]["l"], "s": a[n]["s"], "pl": b[n]["l"], "ps": b[n]["s"]}
                     for n in ("FII", "DII", "Pro", "Client") if n in a and n in b}
        p["partDate"] = a["d"]
        p["fiiHist"] = [{"d": x["d"], "lp": round(x["FII"]["l"] / (x["FII"]["l"] + x["FII"]["s"]) * 100, 2)}
                        for x in pt if "FII" in x]
    bh = DAILY.get("bhav") or []
    if bh:
        p["lot"] = bh[-1]["lot"]
        p["pcrHist"] = ", ".join(f"{b['pcr']:.2f}" for b in bh if b.get("pcr"))
        p["pcrDates"] = [b["d"] for b in bh if b.get("pcr")]

    # Step 5: India VIX as the IV gauge
    vix = [v["c"] for v in (DAILY.get("vix") or [])][-250:]
    iv = live.get("vix") or (vix[-1] if vix else None)
    if iv and vix:
        p.update({"iv": round(iv, 2), "ivLo": round(min(vix + [iv]), 2), "ivHi": round(max(vix + [iv]), 2),
                  "ivp": round(sum(1 for v in vix if v < iv) / len(vix) * 100),
                  "vixHist": vix[-60:]})
        ref = vix[-5] if len(vix) >= 5 else vix[0]
        ch = (iv - ref) / ref * 100
        p["ivTrend"] = "falling" if ch < -5 else "rising" if ch > 5 else "flat"
    return p


def enrich_chain(p, live):
    chain, exp, ct = live.get("chain"), live.get("expiry"), live.get("chainTime")
    if not chain or not exp or not ct:
        return
    cdt = datetime.strptime(ct, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    prev_days = [b["d"] for b in DAILY.get("bhav", []) if b["d"] < cdt.date().isoformat()]
    if not prev_days:
        return
    pd = date.fromisoformat(prev_days[-1])
    bo = bhav_options(pd)
    if not bo or exp not in bo["x"]:
        return
    xd = date.fromisoformat(exp)
    exp_close = datetime(xd.year, xd.month, xd.day, 15, 30, tzinfo=IST)
    t_now = max((exp_close - cdt).total_seconds() / 86400, 1 / 24) / 365
    t_prev = max((xd - pd).days, 1 / 24) / 365
    s_now, s_prev = live.get("spot"), bo["und"]
    prev = bo["x"][exp]
    f_now = implied_forward({r["k"]: (r.get("cp"), r.get("pp")) for r in chain}, s_now, t_now)
    f_prev = implied_forward({int(k): (v.get("CE"), v.get("PE")) for k, v in prev.items()}, s_prev, t_prev)
    # Yesterday's smile from out-of-the-money options (their prices carry the IV information)
    smile = []
    for k, v in prev.items():
        k = int(k)
        cp = "CE" if k >= f_prev else "PE"
        iv = implied_vol(cp, v.get(cp), f_prev, k, t_prev)
        if iv and abs(k - f_prev) <= 2000:
            smile.append((k, iv))
    smile.sort()

    def smile_at(x):
        for (a, ia), (b, ib) in zip(smile, smile[1:]):
            if a <= x <= b:
                return ia + (ib - ia) * (x - a) / (b - a)
        return None

    res = []
    for r in chain:
        k = r["k"]
        q = prev.get(str(k), {})
        r["cp0"], r["pp0"] = q.get("CE"), q.get("PE")
        otm = "CE" if k >= f_now else "PE"
        iv_now = implied_vol(otm, r.get("cp" if otm == "CE" else "pp"), f_now, k, t_now)
        # Sticky moneyness: with no trading, today's IV at K should equal yesterday's IV
        # at the same distance from the forward, i.e. at K * F_prev / F_now.
        iv_exp = smile_at(k * f_prev / f_now)
        r["ivNow"] = iv_now
        r["ivExp"] = round(iv_exp, 2) if iv_exp else None
        r["ivRes"] = round(iv_now - iv_exp, 2) if iv_now and iv_exp else None
        if r["ivRes"] is not None:
            res.append(r["ivRes"])
    mkt = sorted(res)[len(res) // 2] if res else None
    for r in chain:
        # strike-specific pressure = residual after the market-wide vol shift
        r["ivS"] = round(r["ivRes"] - mkt, 2) if r["ivRes"] is not None and mkt is not None else None
    p.update({"chain": chain, "chainPrevDate": pd.isoformat(), "chainSpotPrev": s_prev,
              "fwdNow": round(f_now, 2), "fwdPrev": round(f_prev, 2),
              "ivMkt": round(mkt, 2) if mkt is not None else None})


def worker():
    last_live = 0
    while True:
        try:
            if daily_stale():
                refresh_daily()
            gap = LIVE_EVERY_OPEN if market_open() else LIVE_EVERY_CLOSED
            if time.time() - last_live >= gap or STATE.get("loading") or STATE.get("force"):
                live, errs = refresh_live()
                payload = build_payload(live, errs)
                with state_lock:
                    STATE.clear()
                    STATE.update(payload)
                last_live = time.time()
                log(f"live ok: Nifty {payload.get('spot')}  VIX {payload.get('iv')}  "
                    f"PCR(live) {payload.get('pcrLive')}" + (f"  errors: {errs}" if errs else ""))
        except Exception as e:
            traceback.print_exc()
            with state_lock:
                STATE.setdefault("errors", []).append(str(e))
            time.sleep(20)
        time.sleep(5)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html", "/nifty-desk.html"):
            with open(PAGE, "rb") as f:
                html = f.read()
            with open(os.path.join(HERE, "brand", "head.html"), "rb") as f:
                head = f.read()
            self.send(200, head + html + b"</body></html>", "text/html; charset=utf-8")
        elif path.startswith("/brand/") and "/.." not in path and os.path.isfile(os.path.join(HERE, path.lstrip("/"))):
            ext = path.rsplit(".", 1)[-1]
            ctype = {"png": "image/png", "webmanifest": "application/manifest+json", "html": "text/html"}.get(ext, "application/octet-stream")
            with open(os.path.join(HERE, path.lstrip("/")), "rb") as f:
                self.send(200, f.read(), ctype)
        elif path == "/api/data":
            with state_lock:
                body = json.dumps(STATE).encode()
            self.send(200, body, "application/json")
        elif path == "/api/refresh":
            STATE["force"] = True
            self.send(200, b'{"ok":true}', "application/json")
        elif path == "/api/context":
            import context_feeds
            self.send(200, context_feeds.snapshot(), "application/json")
        elif path == "/api/context/refresh":
            import context_feeds
            context_feeds.CTX["force"] = True
            self.send(200, b'{"ok":true}', "application/json")
        else:
            self.send(404, b"not found", "text/plain")


def main():
    os.makedirs(DATA, exist_ok=True)
    threading.Thread(target=worker, daemon=True).start()
    import context_feeds  # macro, FII/DII flows and quarterly results
    context_feeds.start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    log(f"Nifty Positioning Desk running at {url}  (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("stopped")


if __name__ == "__main__":
    main()

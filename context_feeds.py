"""Market-context feeds for the desk: global macro, FII/DII flows, quarterly results.

Sources (all free, no keys):
  - CNBC public quote + chart feeds: Brent, WTI, gold, US/India 10Y yields, DXY,
    USD/INR, S&P 500, US VIX
  - New York Fed: effective Fed funds rate and target range
  - NSE: FII/DII cash-market flows, participant-wise OI, integrated financial-results
    filings (XBRL), board-meeting calendar, Nifty 50 constituents
"""
import csv, io, json, os, re, threading, time, traceback
from datetime import date, datetime, timedelta
from urllib.request import Request

import desk_server as ds

DATA = ds.DATA
CTX = {"macro": None, "flows": None, "results": None, "events": None, "errors": {}, "updated": {}}
LOCK = threading.Lock()


def _get(url, accept="application/json", timeout=25):
    h = {"User-Agent": ds.UA, "Accept": accept}
    with ds.nse.op.open(Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def _num(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").replace("+", ""))
    except ValueError:
        return None


# ================================================================ global macro
MACRO = [
    # key, CNBC symbol, label, unit, how a RISE affects Indian equities, 1-month threshold, kind of threshold
    ("brent", "@LCO.1", "Brent crude", "$/bbl", -1, 5.0, "pct"),
    ("wti", "@CL.1", "WTI crude", "$/bbl", -1, 5.0, "pct"),
    ("gold", "@GC.1", "Gold", "$/oz", -1, 5.0, "pct"),
    ("us10y", "US10Y", "US 10-year yield", "%", -1, 0.20, "abs"),
    ("dxy", ".DXY", "US dollar index", "", -1, 2.0, "pct"),
    ("usdinr", "INR=", "USD / INR", "₹", -1, 1.0, "pct"),
    ("in10y", "IN10Y", "India 10-year yield", "%", -1, 0.15, "abs"),
    ("spx", ".SPX", "S&P 500", "", 1, 3.0, "pct"),
    ("vix", ".VIX", "US VIX (fear gauge)", "", -1, 20.0, "pct"),
]
WHY = {
    "brent": ("India imports about 85% of its oil. Costlier crude widens the trade deficit, weakens the rupee, lifts inflation and hurts oil marketing, paint, airline and chemical companies.",
              "Cheaper crude eases inflation and the trade deficit and helps oil importers, OMCs, paints and airlines."),
    "wti": ("Moves with Brent; a rise adds to India's import bill.", "A fall lowers India's import bill."),
    "gold": ("Gold rallies when investors want safety, so a sharp rise often signals risk-off globally. India is also a big gold importer.",
             "Falling gold usually means investors are comfortable taking risk."),
    "us10y": ("Higher US yields make US bonds more attractive than emerging-market stocks, which tends to pull FII money out of India.",
              "Lower US yields push investors toward higher-return markets like India."),
    "dxy": ("A stronger dollar usually means money flowing out of emerging markets, including India.",
            "A weaker dollar supports emerging-market flows."),
    "usdinr": ("A weaker rupee (higher USD/INR) cuts FII returns in dollar terms and makes imports costlier. It helps IT and pharma exporters.",
               "A stronger rupee makes Indian assets more attractive to foreign investors."),
    "in10y": ("Rising Indian yields raise borrowing costs and compete with equities, especially for banks' bond books and rate-sensitive sectors.",
              "Falling yields support valuations and rate-sensitive sectors like banks, autos and real estate."),
    "spx": ("Global risk appetite is improving; Indian markets usually follow over time.",
            "A falling US market tends to spill over into risk-off selling in India."),
    "vix": ("Rising fear in the US often triggers global selling, including FII outflows from India.",
            "Calm US markets support risk-taking globally."),
}


def cnbc_quotes(symbols):
    url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
           + "%7C".join(s.replace("=", "%3D") for s in symbols)
           + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json")
    j = json.loads(_get(url))
    out = {}
    for q in j["FormattedQuoteResult"]["FormattedQuote"]:
        out[q["symbol"]] = {"last": _num(q.get("last")), "chg": _num(q.get("change")), "chgPct": _num(q.get("change_pct")),
                            "time": q.get("last_time"), "name": q.get("name")}
    return out


def cnbc_history(sym):
    path = ds.cache_path("macro", f"{sym.replace('.', '_').replace('@', 'F_').replace('=', 'X')}_{date.today().isoformat()}.json")
    c = ds.read_cache(path)
    if c:
        return c
    j = json.loads(_get(f"https://ts-api.cnbc.com/harmony/app/charts/1Y.json?symbol={sym}"))
    bars = [{"d": f"{b['tradeTime'][:4]}-{b['tradeTime'][4:6]}-{b['tradeTime'][6:8]}", "c": _num(b["close"])}
            for b in j["barData"]["priceBars"] if _num(b.get("close"))]
    bars = bars[-260:]
    if bars:
        ds.write_cache(path, bars)
    return bars


def fed_funds_targets():
    """(date, upper target) for recent days, newest first."""
    j = json.loads(_get("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/30.json"))
    return [(x["effectiveDate"], x["targetRateTo"]) for x in j["refRates"]]


def fed_funds():
    j = json.loads(_get("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/130.json"))
    r = j["refRates"]
    now, old = r[0], r[-1]
    return {"effr": now["percentRate"], "lo": now["targetRateFrom"], "hi": now["targetRateTo"], "date": now["effectiveDate"],
            "lo6m": old["targetRateFrom"], "hi6m": old["targetRateTo"], "date6m": old["effectiveDate"],
            "hist": [{"d": x["effectiveDate"], "c": x["percentRate"]} for x in reversed(r)]}


def treasury():
    """US Treasury daily yield curve (official CSV), oldest first."""
    path = ds.cache_path("macro", f"treasury_{ds.now_ist():%Y-%m-%d_%H}.json")
    c = ds.read_cache(path)
    if c:
        return c
    rows = []
    yr = date.today().year
    for y in ((yr - 1, yr) if date.today().month <= 2 else (yr,)):
        raw = _get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                   f"{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv", accept="text/csv").decode()
        for r in csv.DictReader(io.StringIO(raw)):
            m, d_, y_ = r["Date"].split("/")
            rows.append({"d": f"{y_}-{m}-{d_}", "m3": _num(r.get("3 Mo")), "m6": _num(r.get("6 Mo")), "y1": _num(r.get("1 Yr")),
                         "y2": _num(r.get("2 Yr")), "y10": _num(r.get("10 Yr"))})
    rows.sort(key=lambda r: r["d"])
    if rows:
        ds.write_cache(path, rows)
    return rows


def fed_expectations(fed):
    """What traders expect from the Fed, read from 6-month Treasury bills vs the actual Fed rate.
    Bills well above the Fed rate = hikes priced in; well below = cuts priced in."""
    tr = [r for r in treasury() if r["m6"] is not None]
    effr = {x["d"]: x["c"] for x in fed["hist"]}
    def spread(i):
        r = tr[i]
        e = effr.get(r["d"]) or next((effr[d] for d in sorted(effr, reverse=True) if d <= r["d"]), None)
        return None if e is None else round(r["m6"] - e, 2)
    now = spread(-1)
    week = spread(-6) if len(tr) > 6 else None
    view = "hike" if now is not None and now >= 0.15 else "cut" if now is not None and now <= -0.15 else "hold"
    return {"spread": now, "spreadWeekAgo": week, "shift": None if week is None or now is None else round(now - week, 2),
            "view": view, "bill6m": tr[-1]["m6"], "y2": tr[-1]["y2"], "date": tr[-1]["d"]}


def _flag(level, title, detail):
    return {"level": level, "title": title, "detail": detail}


def macro_flags(items, fed, events):
    """Red = a change that is bad for Indian stocks; amber = a big change worth watching."""
    state_path = os.path.join(DATA, "macro_state.json")
    state = ds.read_cache(state_path) or {}
    today = ds.now_ist().date().isoformat()
    prev_day = max((d for d in state if d < today), default=None)
    prev_views = state.get(prev_day, {}) if prev_day else {}
    for i in items:
        fl = []
        h = [c for _, c in i["hist"]]
        if len(h) > 30:
            diffs = [(h[k] - h[k - 1]) if i["kind"] == "abs" else (h[k] / h[k - 1] - 1) * 100 for k in range(1, len(h))]
            mean = sum(abs(x) for x in diffs) / len(diffs)
            today_move = i["chg"] if i["kind"] == "abs" else i["chgPct"]
            if today_move is not None and mean and abs(today_move) >= 2.5 * mean:
                bad = (today_move > 0) == (i["sign"] < 0)
                unit = " pts" if i["kind"] == "abs" else "%"
                fl.append(_flag("red" if bad else "amber", f"Big move today: {'+' if today_move > 0 else '−'}{abs(today_move):.2f}{unit}",
                                f"About {abs(today_move) / mean:.0f}× its normal daily move."))
            past = h[:-1] if i["hist"][-1][0] == today else h
            if past and i["last"] > max(past):
                fl.append(_flag("red" if i["sign"] < 0 else "amber", "New 1-year high", "Highest level in the past year."))
            elif past and i["last"] < min(past):
                fl.append(_flag("red" if i["sign"] > 0 else "amber", "New 1-year low", "Lowest level in the past year."))
        if i["key"] == "us10y" and i.get("c1w") is not None and abs(i["c1w"]) >= 0.15:
            fl.append(_flag("red" if i["c1w"] > 0 else "amber", f"US 10-year moved {'+' if i['c1w'] > 0 else '−'}{abs(i['c1w']):.2f} pts this week",
                            "A fast change in US bond rates usually moves FII money within days."))
        pv = prev_views.get(i["key"])
        if pv and pv != i["view"] and i["view"] == "head":
            fl.append(_flag("red", "Turned bad for India today", f"Was {'good' if pv == 'tail' else 'neutral'} on {prev_day}."))
        i["flags"] = fl
        i["sign"] = i["sign"]
    fflags = []
    if fed:
        if fed.get("changedDays") is not None:
            up = fed["changedDir"] > 0
            fflags.append(_flag("red" if up else "amber", f"Fed {'raised' if up else 'cut'} rates {fed['changedDays']} days ago",
                                f"Target range now {fed['lo']:.2f}–{fed['hi']:.2f}%."))
        ex = fed.get("expect")
        if ex and ex["view"] != "hold":
            fflags.append(_flag("red" if ex["view"] == "hike" else "amber",
                                f"Market expects a Fed rate {ex['view'].upper()}",
                                f"6-month US Treasury bills pay {ex['bill6m']:.2f}%, {abs(ex['spread']):.2f}% {'above' if ex['spread'] > 0 else 'below'} the Fed rate of {fed['effr']:.2f}%."))
        if ex and ex.get("shift") is not None and abs(ex["shift"]) >= 0.10:
            fflags.append(_flag("red" if ex["shift"] > 0 else "amber",
                                f"Fed expectations shifted toward a {'hike' if ex['shift'] > 0 else 'cut'} this week",
                                f"The bills-vs-Fed gap moved {ex['shift']:+.2f}% in 5 sessions."))
        nxt = next((e for e in (events or []) if e.get("cat") == "Fed"), None)
        if nxt:
            dd = (date.fromisoformat(nxt["d"]) - ds.now_ist().date()).days
            if 0 <= dd <= 7:
                fflags.append(_flag("amber", f"Fed decision {'tonight' if dd == 0 else f'in {dd} day' + ('s' if dd > 1 else '')}",
                                    "Expect big swings in US bond rates, the dollar and FII flows around it."))
        fed["flags"] = fflags
    state[today] = {i["key"]: i["view"] for i in items}
    for d in sorted(state)[:-10]:
        state.pop(d)
    ds.write_cache(state_path, state)
    out = []
    for i in items:
        out += [dict(f, key=i["key"], label=i["label"]) for f in i["flags"]]
    out += [dict(f, key="fed", label="US Fed") for f in fflags]
    out.sort(key=lambda f: f["level"] != "red")
    return out


def build_macro():
    quotes = cnbc_quotes([m[1] for m in MACRO])
    items = []
    for key, sym, label, unit, sign, thr, kind in MACRO:
        q = quotes.get(sym, {})
        try:
            h = cnbc_history(sym)
        except Exception:
            h = []
        last = q.get("last") or (h[-1]["c"] if h else None)
        if last is None:
            continue
        closes = [b["c"] for b in h]

        def ago(n):
            return closes[-1 - n] if len(closes) > n else None

        def change(ref):
            if ref is None:
                return None
            return (last - ref) if kind == "abs" else (last / ref - 1) * 100

        c1w, c1m, c3m = change(ago(5)), change(ago(21)), change(ago(63))
        pctl = round(sum(1 for c in closes if c < last) / len(closes) * 100) if closes else None
        if key == "vix":
            # the VIX is read by level, not by its monthly change
            view = "head" if last >= 25 else "tail" if last <= 15 else "neutral"
        elif c1m is None:
            view = "neutral"
        else:
            effect = sign * c1m
            view = "tail" if effect >= thr else "head" if effect <= -thr else "neutral"
        rise_txt, fall_txt = WHY[key]
        items.append({"sign": sign, "key": key, "label": label, "unit": unit, "last": last, "chg": q.get("chg"), "chgPct": q.get("chgPct"),
                      "time": q.get("time"), "c1w": c1w, "c1m": c1m, "c3m": c3m, "kind": kind, "pctl": pctl, "view": view,
                      "why": rise_txt if (c1m or 0) * (1 if key != "vix" else 1) >= 0 else fall_txt,
                      "hist": [[b["d"], b["c"]] for b in h]})
    try:
        fed = fed_funds()
        hist_rates = fed_funds_targets()
        ch = next(((k, hist_rates[k][1] - hist_rates[k + 1][1]) for k in range(len(hist_rates) - 1)
                   if hist_rates[k][1] != hist_rates[k + 1][1]), None)
        if ch:
            days_since = (ds.now_ist().date() - date.fromisoformat(hist_rates[ch[0]][0])).days
            if days_since <= 7:
                fed["changedDays"], fed["changedDir"] = days_since, ch[1]
        try:
            fed["expect"] = fed_expectations(fed)
        except Exception as e:
            CTX["errors"]["treasury"] = str(e)
        moved = (fed["hi"] - fed["hi6m"])
        fed["view"] = "tail" if moved < 0 else "head" if moved > 0 else "neutral"
        fed["why"] = ("The Fed has cut rates over the last six months, which tends to push global money toward emerging markets like India."
                      if moved < 0 else "The Fed has raised rates over the last six months, which tends to pull money back to the US."
                      if moved > 0 else "The Fed has held rates steady over the last six months.")
    except Exception as e:
        fed = None
        CTX["errors"]["fed"] = str(e)
    flags = macro_flags(items, fed, (CTX.get("events") or {}).get("events"))
    heads = sum(1 for i in items if i["view"] == "head") + (1 if fed and fed["view"] == "head" else 0)
    tails = sum(1 for i in items if i["view"] == "tail") + (1 if fed and fed["view"] == "tail" else 0)
    total = len(items) + (1 if fed else 0)
    score = round((tails - heads) / (total or 1) * 100)
    verdict = "Headwinds" if score <= -20 else "Tailwinds" if score >= 20 else "Mixed"
    return {"flags": flags, "items": items, "fed": fed, "heads": heads, "tails": tails, "total": total, "score": score, "verdict": verdict,
            "updated": ds.now_ist().strftime("%d %b %Y, %H:%M IST")}


# ================================================================ FII / DII flows
FLOW_DIR = os.path.join(DATA, "flows")


def fetch_cash_flows():
    os.makedirs(FLOW_DIR, exist_ok=True)
    j = ds.nse.json("/api/fiidiiTradeReact", "https://www.nseindia.com/reports/fii-dii")
    rows = {r["category"]: r for r in j}
    d = datetime.strptime(j[0]["date"], "%d-%b-%Y").date().isoformat()
    rec = {"d": d}
    for cat, k in (("FII/FPI", "fii"), ("DII", "dii")):
        r = rows.get(cat)
        if r:
            rec[k] = {"buy": _num(r["buyValue"]), "sell": _num(r["sellValue"]), "net": _num(r["netValue"])}
    ds.write_cache(os.path.join(FLOW_DIR, d + ".json"), rec)
    return rec


def participant_full(d):
    """Every column of the participant-wise OI file, for the derivatives table."""
    raw = ds.nse.archive("https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_" + d.strftime("%d%m%Y") + ".csv")
    if not raw or b"Client Type" not in raw:
        return None
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8", "replace"))))
    h = next(i for i, r in enumerate(rows) if r and r[0].strip() == "Client Type")
    cols = [c.strip() for c in rows[h]]
    out = {"d": d.isoformat()}
    for r in rows[h + 1:]:
        if r and r[0].strip() in ("FII", "DII", "Pro", "Client"):
            out[r[0].strip()] = {c: int(float(v)) for c, v in zip(cols[1:], r[1:]) if v.strip()}
    return out


def build_flows():
    try:
        fetch_cash_flows()
    except Exception as e:
        CTX["errors"]["fiidii"] = str(e)
    hist = []
    if os.path.isdir(FLOW_DIR):
        for f in sorted(os.listdir(FLOW_DIR)):
            if f.endswith(".json"):
                r = ds.read_cache(os.path.join(FLOW_DIR, f))
                if r and "fii" in r:
                    hist.append(r)
    out = {"hist": hist[-60:]}
    if hist:
        t = hist[-1]
        f, di = t["fii"], t.get("dii", {})
        gross = (f["buy"] or 0) + (f["sell"] or 0)
        prev = hist[-2] if len(hist) > 1 else None
        past = [abs(h["fii"]["net"]) for h in hist[-21:-1]]
        avg = sum(past) / len(past) if past else None
        streak, sgn = 0, (f["net"] > 0) - (f["net"] < 0)
        for h in reversed(hist):
            s = (h["fii"]["net"] > 0) - (h["fii"]["net"] < 0)
            if s != sgn or s == 0:
                break
            streak += 1
        month = t["d"][:7]
        mtd = sum(h["fii"]["net"] for h in hist if h["d"][:7] == month)
        mtd_dii = sum(h.get("dii", {}).get("net", 0) for h in hist if h["d"][:7] == month)
        big = abs(f["net"]) >= 3000 or (avg and len(past) >= 5 and abs(f["net"]) >= 1.5 * avg)
        out["today"] = {"d": t["d"], "fii": f, "dii": di, "fiiNetPct": f["net"] / gross * 100 if gross else None,
                        "prevNet": prev["fii"]["net"] if prev else None, "prevD": prev["d"] if prev else None,
                        "avgAbs": avg, "days": len(past), "streak": streak, "sign": sgn, "mtd": mtd, "mtdDii": mtd_dii,
                        "big": bool(big),
                        "absorb": (di.get("net", 0) / -f["net"] * 100) if f["net"] < 0 and di.get("net") else None}
    # derivatives: FII long % in index futures for the last two years (from the backtest cache + live cache)
    pts = {}
    for sub in ("part",):
        p = os.path.join(DATA, sub)
        if os.path.isdir(p):
            for fn in os.listdir(p):
                r = ds.read_cache(os.path.join(p, fn))
                if r and "FII" in r:
                    l, s = r["FII"]["l"], r["FII"]["s"]
                    pts[r["d"]] = round(l / ((l + s) or 1) * 100, 2)
    out["fiiLongHist"] = sorted(pts.items())[-500:]
    # today's full derivatives picture vs the previous file
    try:
        got = []
        for d in ds.weekdays_back(ds.now_ist().date(), 15):
            r = participant_full(d)
            if r:
                got.append(r)
            if len(got) == 2:
                break
        if len(got) == 2:
            now, prv = got
            rows = []
            for lab, a, b in (("Index futures", "Future Index Long", "Future Index Short"),
                              ("Stock futures", "Future Stock Long", "Future Stock Short"),
                              ("Index calls", "Option Index Call Long", "Option Index Call Short"),
                              ("Index puts", "Option Index Put Long", "Option Index Put Short")):
                L, S_ = now["FII"][a], now["FII"][b]
                pL, pS = prv["FII"][a], prv["FII"][b]
                rows.append({"name": lab, "long": L, "short": S_, "net": L - S_, "dNet": (L - S_) - (pL - pS),
                             "longPct": L / ((L + S_) or 1) * 100, "dLongPct": L / ((L + S_) or 1) * 100 - pL / ((pL + pS) or 1) * 100})
            out["deriv"] = {"d": now["d"], "prev": prv["d"], "rows": rows}
    except Exception as e:
        CTX["errors"]["participant"] = str(e)
    try:
        out["sectors"] = build_sectors()
    except Exception as e:
        CTX["errors"]["sectors"] = str(e)
    out["updated"] = ds.now_ist().strftime("%d %b %Y, %H:%M IST")
    return out


# ================================================================ FII flows by sector (NSDL)
NSDL = "https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_{}.html"


def _month_end(y, m):
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return nxt - timedelta(days=1)


def nsdl_file(d):
    """Parsed NSDL sector file for period-end date d, cached; None if not published."""
    path = ds.cache_path("sectors", d.isoformat() + ".json")
    c = ds.read_cache(path)
    if c is not None:
        return c or None
    try:
        raw = _get(NSDL.format(d.strftime("%b%d%Y")), accept="text/html", timeout=40)
    except Exception:
        return None
    h = raw.decode("utf-8", "replace")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S | re.I)
    import html as _html
    cells = lambda r: [_html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S | re.I)]
    head = [cells(r) for r in rows[:4]]
    periods = head[0][2:6] if head and len(head[0]) >= 6 else []
    cat = next((c for c in head if c and c[0] == "Sr. No."), None)
    if not cat or len(periods) != 4:
        return None
    width = (len(cat) - 2) // 8          # categories per currency block
    eq = [2 + k * 2 * width for k in range(4)]  # Equity, INR, in each of the 4 blocks
    if any(cat[i] != "Equity" for i in eq):
        return None
    num = lambda v: float(v.replace(",", "")) if re.match(r"^-?[\d,.]+$", v or "") else 0.0
    sectors = []
    for r in rows[4:]:
        c = cells(r)
        if len(c) == len(cat) and c[0].isdigit():
            sectors.append({"name": c[1], "aucStart": num(c[eq[0]]), "net1": num(c[eq[1]]), "net2": num(c[eq[2]]), "aucEnd": num(c[eq[3]])})
    if not sectors:
        return None
    out = {"d": d.isoformat(), "periods": periods, "sectors": sectors}
    ds.write_cache(path, out)
    return out


def build_sectors(months=6):
    today = ds.now_ist().date()
    files = []
    y, m = today.year, today.month
    for _ in range(months + 2):
        f = nsdl_file(_month_end(y, m))
        if f:
            files.append(f)
        if len(files) >= months:
            break
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    files.sort(key=lambda f: f["d"])
    if not files:
        return None
    # the newest half-month file (the 15th) can be more recent than the last month-end file
    mid = nsdl_file(date(today.year, today.month, 15)) if today.day > 15 else None
    latest = files[-1]
    names = [s["name"] for s in latest["sectors"]]
    by = {n: {"name": n} for n in names}
    hist_periods = []
    for f in files:
        hist_periods += [f["periods"][1].replace("Net Investment ", ""), f["periods"][2].replace("Net Investment ", "")]
        for s_ in f["sectors"]:
            if s_["name"] in by:
                by[s_["name"]].setdefault("flows", []).extend([s_["net1"], s_["net2"]])
    tot_end = sum(s_["aucEnd"] for s_ in latest["sectors"]) or 1
    first = files[0]
    tot_start = sum(s_["aucStart"] for s_ in first["sectors"]) or 1
    start_map = {s_["name"]: s_["aucStart"] for s_ in first["sectors"]}
    for s_ in latest["sectors"]:
        b = by[s_["name"]]
        b["auc"] = s_["aucEnd"]
        b["weight"] = s_["aucEnd"] / tot_end * 100
        b["weightChg"] = b["weight"] - start_map.get(s_["name"], 0) / tot_start * 100
        b["lastFortnight"] = s_["net2"]
        b["lastMonth"] = s_["net1"] + s_["net2"]
        b["total"] = sum(b.get("flows", []))
        b["last3m"] = sum(b.get("flows", [])[-6:])
    rows = sorted(by.values(), key=lambda r: r.get("lastMonth", 0))
    return {"asof": latest["periods"][3].replace("AUC as on ", ""), "periods": hist_periods, "rows": rows,
            "months": len(files), "monthNet": sum(r.get("lastMonth", 0) for r in rows),
            "mid": None if not mid or mid["d"] <= latest["d"] else {"period": mid["periods"][2], "net": sum(s_["net2"] for s_ in mid["sectors"])}}


# ================================================================ event calendar
def fomc_dates():
    path = ds.cache_path("events", f"fomc_{date.today():%Y-%m}.json")
    c = ds.read_cache(path)
    if c:
        return c
    h = _get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", accept="text/html").decode("utf-8", "replace")
    out = []
    for yr in (date.today().year, date.today().year + 1):
        m = re.search(r">%d FOMC Meetings<(.*?)(?:>%d FOMC Meetings<|$)" % (yr, yr - 1), h, re.S)
        if not m:
            continue
        for mon, dd in re.findall(r'fomc-meeting__month[^>]*><strong>([A-Za-z/]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<', m.group(1), re.S):
            day = re.findall(r"\d+", dd)
            if not day:
                continue
            mon1 = mon.split("/")[-1]
            try:
                dt_ = datetime.strptime(f"{day[-1]} {mon1[:3]} {yr}", "%d %b %Y").date()
            except ValueError:
                continue
            out.append({"d": dt_.isoformat(), "sep": "*" in dd})
    out = sorted({x["d"]: x for x in out}.values(), key=lambda x: x["d"])
    if out:
        ds.write_cache(path, out)
    return out


def ff_events():
    out = []
    for wk in ("thisweek", "nextweek"):
        try:
            j = json.loads(_get(f"https://nfs.faireconomy.media/ff_calendar_{wk}.json"))
        except Exception:
            continue
        for x in j:
            if x.get("impact") not in ("High", "Medium") or x.get("country") not in ("USD", "CNY", "EUR", "JPY", "All"):
                continue
            try:
                t = datetime.fromisoformat(x["date"]).astimezone(ds.IST)
            except ValueError:
                continue
            out.append({"t": t.isoformat(), "d": t.date().isoformat(), "time": t.strftime("%H:%M"), "title": f"{x['country']} {x['title']}",
                        "cat": "Global data", "impact": x["impact"], "forecast": x.get("forecast"), "previous": x.get("previous")})
    return out


WHY_EV = {
    "RBI": "Repo rate and liquidity decision. Moves banks, NBFCs, rate-sensitive sectors and the rupee.",
    "Fed": "US rate decision. Shifts US yields and the dollar, which drive FII flows into India.",
    "CPI": "Inflation sets the path for RBI rates.",
    "GDP": "Growth print for the quarter; big surprises re-rate the whole market.",
    "IIP": "Industrial output, a monthly read on manufacturing and capex.",
    "Expiry": "F&O expiry: open interest unwinds and rolls, so the index can swing sharply into the close.",
    "Holiday": "Markets shut. Global moves pile up for the next session's open.",
    "Results": "A Nifty 50 company reports. Big names can move the index and their sector.",
}


def _next_weekday(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def build_events(days=45):
    today = ds.now_ist().date()
    end = today + timedelta(days=days)
    ev = []

    def add(d, title, cat, impact, time_="", note=""):
        if today <= d <= end:
            ev.append({"d": d.isoformat(), "time": time_, "title": title, "cat": cat, "impact": impact, "why": note or WHY_EV.get(cat, "")})

    man = ds.read_cache(os.path.join(DATA, "events_manual.json")) or {}
    for d in man.get("rbi_mpc_decisions", []):
        add(date.fromisoformat(d), "RBI monetary policy decision", "RBI", "High", "10:00")
    try:
        for f in fomc_dates():
            d = date.fromisoformat(f["d"]) + timedelta(days=1)  # 2 pm ET decision lands at about 23:30-00:30 IST, so the next Indian session reacts
            add(d, "US Fed rate decision" + (" + projections" if f["sep"] else "") + " (overnight)", "Fed", "High", "≈00:00")
    except Exception as e:
        CTX["errors"]["fomc"] = str(e)
    # India data on MOSPI's usual schedule
    for k in range(0, 3):
        y, m = today.year + (today.month + k - 1) // 12, (today.month + k - 1) % 12 + 1
        add(_next_weekday(date(y, m, 12)), "India CPI inflation", "CPI", "High", "16:00", "Usual MOSPI schedule: the 12th, 4 pm. " + WHY_EV["CPI"])
        add(_next_weekday(date(y, m, 28)) if date(y, m, 28) <= _month_end(y, m) else _month_end(y, m), "India industrial output (IIP)", "IIP", "Medium", "16:00")
        if m in (2, 5, 8, 11):
            me = _month_end(y, m)
            while me.weekday() >= 5:
                me -= timedelta(days=1)
            add(me, "India quarterly GDP", "GDP", "High", "16:00", "Usual MOSPI schedule: last working day of Feb, May, Aug, Nov. " + WHY_EV["GDP"])
    # Nifty expiries
    try:
        info = ds.nse.json("/api/option-chain-contract-info?symbol=NIFTY")
        exps = sorted(datetime.strptime(x, "%d-%b-%Y").date() for x in info["expiryDates"])
        months_last = {}
        for e in exps:
            months_last[(e.year, e.month)] = max(months_last.get((e.year, e.month), e), e)
        for e in exps:
            monthly = months_last[(e.year, e.month)] == e
            add(e, "Nifty monthly expiry" if monthly else "Nifty weekly expiry", "Expiry", "Medium" if monthly else "Low", "15:30")
    except Exception as ex:
        CTX["errors"]["expiry"] = str(ex)
    # NSE trading holidays
    try:
        h = ds.nse.json("/api/holiday-master?type=trading", "https://www.nseindia.com/resources/exchange-communication-holidays")
        for x in h.get("CM", []):
            add(datetime.strptime(x["tradingDate"], "%d-%b-%Y").date(), "Market holiday: " + x["description"].replace("*", ""), "Holiday", "Info")
    except Exception as ex:
        CTX["errors"]["holidays"] = str(ex)
    # Nifty 50 results (from the results feed's calendar)
    res = CTX.get("results") or {}
    for c in res.get("calendar", []):
        if c.get("n50"):
            add(date.fromisoformat(c["d"]), f"{c['sym']} quarterly results", "Results", "Medium")
    # global releases from Forex Factory (this week and next)
    ev += [dict(x, why="") for x in ff_events() if today.isoformat() <= x["d"] <= end.isoformat()]
    rank = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}
    ev.sort(key=lambda e: (e["d"], rank.get(e["impact"], 4), e["time"]))
    nxt = lambda cat: next((e for e in ev if e["cat"] == cat), None)
    return {"events": ev, "next": {k: nxt(k) for k in ("RBI", "Fed", "CPI", "Holiday")},
            "nextMonthly": next((e for e in ev if e["title"] == "Nifty monthly expiry"), None),
            "rbiSource": man.get("rbi_source"), "updated": ds.now_ist().strftime("%d %b %Y, %H:%M IST")}


# ================================================================ quarterly results
RES_DIR = os.path.join(DATA, "results")
REF_IF = "https://www.nseindia.com/companies-listing/corporate-integrated-filing"


def nifty50():
    path = ds.cache_path("results", f"nifty50_{date.today().isoformat()}.json")
    c = ds.read_cache(path)
    if c:
        return c
    raw = ds.nse.archive("https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv")
    syms = [r["Symbol"].strip() for r in csv.DictReader(io.StringIO(raw.decode("utf-8", "replace")))] if raw else []
    if syms:
        ds.write_cache(path, syms)
    return syms


TAGS = {"rev": ["RevenueFromOperations", "InterestEarned", "TotalRevenueFromOperations", "Revenue"],
        "inc": ["Income", "TotalIncome"],
        "pbt": ["ProfitBeforeTax", "ProfitLossBeforeTax"],
        "pat": ["ProfitLossForPeriod", "ProfitLossForThePeriod", "NetProfitLossForThePeriod", "ProfitLossForPeriodFromContinuingOperations"]}


def parse_xbrl(url):
    """Quarter figures (rupees) from a results XBRL file, cached forever by URL."""
    key = re.sub(r"[^A-Za-z0-9]", "_", url.split("/")[-1])[-90:]
    path = ds.cache_path("results", "xbrl2", key + ".json")
    c = ds.read_cache(path)
    if c is not None:
        return c
    raw = ds.nse.archive(url)
    if not raw:
        return {}
    x = raw.decode("utf-8", "replace")
    # the quarter context: a duration of roughly three months
    # quarter contexts for the company as a whole: ~3-month duration and no dimension
    # (dimensional contexts hold segment, associate or other breakdowns)
    ctx = {}
    for cid, body in re.findall(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', x, re.S):
        m = re.search(r'<xbrli:startDate>([^<]+)</xbrli:startDate>\s*<xbrli:endDate>([^<]+)</xbrli:endDate>', body)
        if not m or "explicitMember" in body or "typedMember" in body:
            continue
        a, b = m.group(1)[:10], m.group(2)[:10]
        ctx[cid] = (a, b, (date.fromisoformat(b) - date.fromisoformat(a)).days)
    qctx = [c for c, (a, b, n) in ctx.items() if 80 <= n <= 100]
    out = {}
    for k, names in TAGS.items():
        for nm in names:
            vals = re.findall(r'<[a-z-]+:%s\b[^>]*contextRef="([^"]+)"[^>]*>([^<]+)<' % nm, x)
            q = [float(v) for cid, v in vals if cid in qctx and re.match(r"^-?[\d.]+$", v.strip())]
            if q:
                out[k] = q[0]
                break
    if qctx:
        out["from"], out["to"] = ctx[qctx[0]][0], ctx[qctx[0]][1]
    ds.write_cache(path, out)
    return out


def filings(from_d, to_d):
    rows, page = [], 0
    while True:
        j = ds.nse.json(f"/api/integrated-filing-results?index=equities&from_date={from_d:%d-%m-%Y}&to_date={to_d:%d-%m-%Y}&page={page}&size=100", REF_IF)
        data = j.get("data", [])
        rows += data
        if not data or len(rows) >= (j.get("totalCount") or 0) or page > 30:
            break
        page += 1
    return [r for r in rows if r.get("type") == "Integrated Filing- Financials"]


def year_ago(symbol, qe, consolidated):
    """Same quarter last year for this company, from its own filing history."""
    path = ds.cache_path("results", "sym", symbol + ".json")
    c = ds.read_cache(path)
    if c is None or time.time() - c.get("t", 0) > 7 * 86400:
        j = ds.nse.json(f"/api/integrated-filing-results?index=equities&symbol={symbol}&page=0&size=60", REF_IF)
        c = {"t": time.time(), "rows": [{"qe": r["qe_Date"], "cons": r.get("consolidated"), "xbrl": r.get("xbrl")}
                                        for r in j.get("data", []) if r.get("type") == "Integrated Filing- Financials"]}
        ds.write_cache(path, c)
    target = (datetime.strptime(qe, "%d-%b-%Y").date().replace(year=datetime.strptime(qe, "%d-%b-%Y").year - 1)).strftime("%d-%b-%Y").upper()
    for r in c["rows"]:
        if r["qe"].upper() == target and r["cons"] == consolidated and (r["xbrl"] or "").endswith(".xml"):
            return parse_xbrl(r["xbrl"])
    return None


def _real_url(u):
    """NSE fills missing attachments with '.../null' or '-'; treat those as no link."""
    if not u or u.rstrip("/").split("/")[-1] in ("null", "-", "", "None"):
        return None
    return u


def results_pdf(sym, filed):
    """The company's own results PDF from its NSE announcements around the filing date, cached."""
    path = ds.cache_path("results", "pdf", f"{sym}_{filed:%Y%m%d}.json")
    c = ds.read_cache(path)
    if c is not None:
        return c.get("url")
    url = None
    try:
        j = ds.nse.json(f"/api/corporate-announcements?index=equities&symbol={sym}&from_date={filed - timedelta(days=1):%d-%m-%Y}"
                        f"&to_date={filed + timedelta(days=1):%d-%m-%Y}", "https://www.nseindia.com/companies-listing/corporate-filings-announcements")
        best = 0
        for a in j if isinstance(j, list) else []:
            f = _real_url(a.get("attchmntFile"))
            if not f or not f.lower().endswith(".pdf"):
                continue
            txt = (a.get("desc", "") + " " + a.get("attchmntText", "") + " " + f).lower()
            score = 3 if "financial result" in txt else 2 if "result" in txt else 1 if "outcome of board meeting" in txt else 0
            if score > best:
                best, url = score, f
    except Exception:
        return None  # don't cache failures
    ds.write_cache(path, {"url": url})
    return url


def build_results(days=7):
    today = ds.now_ist().date()
    n50 = set(nifty50())
    rows = filings(today - timedelta(days=days - 1), today)
    # one row per company and quarter, preferring consolidated figures
    best = {}
    for r in rows:
        key = (r["symbol"], r["qe_Date"])
        if key not in best or (r.get("consolidated") == "Consolidated" and best[key].get("consolidated") != "Consolidated"):
            best[key] = r
    out = []
    def filed_at(r):
        try:
            return datetime.strptime(r["creation_Date"], "%d-%b-%Y %H:%M:%S")
        except (ValueError, TypeError):
            return datetime.min

    for (sym, qe), r in sorted(best.items(), key=lambda kv: filed_at(kv[1]), reverse=True):
        x = (r.get("xbrl") or "")
        f = parse_xbrl(x) if x.endswith(".xml") else {}
        ya = None
        try:
            ya = year_ago(sym, qe, r.get("consolidated"))
        except Exception:
            pass

        def yoy(k):
            a, b = f.get(k), (ya or {}).get(k)
            if a is None or not b:
                return None
            if b < 0 and k == "pat":
                return None  # growth from a loss isn't meaningful as a percentage
            return (a / b - 1) * 100

        rev = f.get("rev") or f.get("inc")
        out.append({"t": r["creation_Date"], "sym": sym, "name": r.get("cmName") or r.get("smName"), "qe": qe.title(),
                    "cons": r.get("consolidated"), "n50": sym in n50, "rev": rev, "pat": f.get("pat"), "pbt": f.get("pbt"),
                    "revYoY": yoy("rev") if f.get("rev") else yoy("inc"), "patYoY": yoy("pat"),
                    "margin": (f["pat"] / rev * 100) if f.get("pat") is not None and rev else None,
                    "patPrev": (ya or {}).get("pat"), "ixbrl": _real_url(r.get("ixbrl")),
                    "pdf": _real_url(r.get("pdf_attach")) or results_pdf(sym, filed_at(r).date()),
                    "screener": f"https://www.screener.in/company/{sym}/{'consolidated/' if r.get('consolidated') == 'Consolidated' else ''}#quarters"})
    cal = []
    try:
        e = ds.nse.json("/api/event-calendar?index=equities", "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar")
        for x in e:
            if "result" in (x.get("purpose", "") + x.get("bm_desc", "")).lower():
                dd = datetime.strptime(x["date"], "%d-%b-%Y").date()
                if today <= dd <= today + timedelta(days=14):
                    cal.append({"d": dd.isoformat(), "sym": x.get("symbol"), "name": x.get("company"), "n50": x.get("symbol") in n50,
                                "purpose": x.get("purpose")})
        cal.sort(key=lambda c: (c["d"], not c["n50"], c["sym"] or ""))
    except Exception as ex:
        CTX["errors"]["calendar"] = str(ex)
    return {"rows": out, "calendar": cal, "days": days, "updated": ds.now_ist().strftime("%d %b %Y, %H:%M IST")}


# ================================================================ refresh loop
EVERY = {"macro": 15 * 60, "flows": 30 * 60, "results": 30 * 60, "events": 30 * 60}


def notify_new_flags(m):
    """Show a macOS notification once per new flag, so alerts arrive even with the dashboard closed."""
    import subprocess
    path = os.path.join(DATA, "alerts_seen.json")
    seen = ds.read_cache(path) or {}
    today = ds.now_ist().date().isoformat()
    for f in (m or {}).get("flags", []):
        fid = f"{today}|{f['key']}|{f['title'].split(':')[0]}"
        if fid in seen:
            continue
        seen[fid] = time.time()
        msg = f"{f['title']}. {f['detail']}".replace('"', "'")
        try:
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Nifty Desk alert" subtitle "{f["label"]}"'],
                           timeout=10, check=False)
        except Exception:
            pass
    cutoff = time.time() - 14 * 86400
    ds.write_cache(path, {k: v for k, v in seen.items() if v > cutoff})


def worker():
    last = {k: 0 for k in EVERY}
    builders = {"macro": build_macro, "flows": build_flows, "results": build_results, "events": build_events}
    while True:
        for k, fn in builders.items():
            if time.time() - last[k] >= EVERY[k] or CTX.get("force"):
                try:
                    v = fn()
                    if k == "macro":
                        notify_new_flags(v)
                    with LOCK:
                        CTX[k] = v
                        CTX["errors"].pop(k, None)
                        CTX["updated"][k] = ds.now_ist().strftime("%H:%M")
                    ds.log(f"context {k} ok")
                except Exception as e:
                    traceback.print_exc()
                    with LOCK:
                        CTX["errors"][k] = str(e)
                last[k] = time.time()
        CTX.pop("force", None)
        time.sleep(20)


def start():
    threading.Thread(target=worker, daemon=True).start()


def snapshot():
    with LOCK:
        return json.dumps({k: CTX[k] for k in ("macro", "flows", "results", "events", "errors", "updated")}).encode()

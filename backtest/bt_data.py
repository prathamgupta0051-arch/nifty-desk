"""Download and cache the point-in-time end-of-day data the backtest needs.

Everything comes from NSE's public end-of-day archives, each file published the
evening of the day it describes:
  - F&O bhavcopy (UDiFF): futures OI, every NIFTY option's OI, change in OI,
    open/close price and volume
  - Participant-wise OI: FII / DII / Pro / Client index-futures longs and shorts
  - Nifty 50 and India VIX daily OHLC
"""
import csv, io, json, os, sys, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import desk_server as ds  # reuse the NSE session, cache helpers and participant parser

DAYS = os.path.join(ds.DATA, "bt")
os.makedirs(DAYS, exist_ok=True)


def parse_bhav(d):
    """Compact record of one session's NIFTY F&O data, or None on a holiday."""
    path = os.path.join(DAYS, d.strftime("%Y%m%d") + ".json")
    if os.path.exists(path):
        with open(path) as f:
            c = json.load(f)
        return c or None
    raw = ds.nse.archive("https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_"
                         f"{d.strftime('%Y%m%d')}_F_0000.csv.zip")
    if raw is None:
        with open(path, "w") as f:
            json.dump({}, f)
        return None
    z = zipfile.ZipFile(io.BytesIO(raw))
    rows = csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode("utf-8", "replace")))
    td = d.isoformat()
    horizon = (d + timedelta(days=45)).isoformat()
    und = None
    fut_oi = fut_chg = ce_all = pe_all = 0.0
    fut_lot = None
    opt = {}
    for r in rows:
        if r.get("TckrSymb") != "NIFTY":
            continue
        tp, xp = r["FinInstrmTp"], r["XpryDt"]
        lot = int(float(r["NewBrdLotQty"] or 0)) or None
        oi = float(r["OpnIntrst"] or 0)
        if tp == "IDF":
            fut_chg += float(r["ChngInOpnIntrst"] or 0) / (lot or 1)
            if xp > td:
                fut_oi += oi / (lot or 1)
                fut_lot = fut_lot or lot
            continue
        if tp != "IDO":
            continue
        und = und or float(r["UndrlygPric"])
        if xp > td:
            if r["OptnTp"] == "CE":
                ce_all += oi
            else:
                pe_all += oi
        if xp > horizon:
            continue
        k = int(float(r["StrkPric"]))
        if und and abs(k - und) > 3000:
            continue
        e = opt.setdefault(xp, {"lot": lot, "k": {}})
        # [OI, chgOI (contracts), open, close, volume (contracts)]
        e["k"].setdefault(str(k), {})[r["OptnTp"]] = [
            round(oi / (lot or 1)), round(float(r["ChngInOpnIntrst"] or 0) / (lot or 1)),
            float(r["OpnPric"] or 0), float(r["ClsPric"] or 0), int(float(r["TtlTradgVol"] or 0))]
    out = {"d": td, "und": und, "lot": fut_lot, "futOi": round(fut_oi), "futChg": round(fut_chg),
           "pcr": round(pe_all / ce_all, 4) if ce_all else None, "opt": opt}
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    return out


def index_hist(kind, start, end):
    path = os.path.join(DAYS, f"_{kind}_{start}_{end}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows = {}
    e = end
    while e > start:
        s = max(start, e - timedelta(days=85))
        q = f"from={s.strftime('%d-%m-%Y')}&to={e.strftime('%d-%m-%Y')}"
        if kind == "nifty":
            j = ds.nse.json("/api/historicalOR/indicesHistory?indexType=NIFTY%2050&" + q,
                            "https://www.nseindia.com/reports-indices-historical-index-data")
        else:
            j = ds.nse.json("/api/historicalOR/vixhistory?" + q,
                            "https://www.nseindia.com/reports-indices-historical-vix")
        for x in j.get("data", []):
            dd = datetime.strptime(x["EOD_TIMESTAMP"].title(), "%d-%b-%Y").date().isoformat()
            rows[dd] = {"d": dd, "o": float(x["EOD_OPEN_INDEX_VAL"]), "h": float(x["EOD_HIGH_INDEX_VAL"]),
                        "l": float(x["EOD_LOW_INDEX_VAL"]), "c": float(x["EOD_CLOSE_INDEX_VAL"])}
        e = s - timedelta(days=1)
    out = [rows[k] for k in sorted(rows)]
    with open(path, "w") as f:
        json.dump(out, f)
    return out


def weekdays(a, b):
    d = a
    while d <= b:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def main(start=date(2024, 9, 16), end=date(2026, 10, 1)):
    t0 = time.time()
    nifty = index_hist("nifty", date(2023, 6, 1), end)
    vix = index_hist("vix", date(2023, 6, 1), end)
    print(f"index history: {len(nifty)} Nifty, {len(vix)} VIX sessions", flush=True)
    days = list(weekdays(start, end))
    done = [0]

    def job(d):
        for attempt in range(4):
            try:
                b = parse_bhav(d)
                p = ds.participant(d)
                break
            except Exception as e:
                if attempt == 3:
                    print("FAILED", d, e, flush=True)
                    return d, None, None
                time.sleep(3 * (attempt + 1))
        done[0] += 1
        if done[0] % 50 == 0:
            print(f"  {done[0]}/{len(days)} days  ({time.time() - t0:.0f}s)", flush=True)
        return d, b, p

    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(job, days))

    # A throttled request (403) looks like a missing file. Any real trading day
    # (per the index history) without data gets its cache cleared and retried slowly.
    trading = {x["d"] for x in nifty}
    for rnd in range(3):
        gaps = [d for d, b, p in res if d.isoformat() in trading and (not b or not p)]
        if not gaps:
            break
        print(f"retrying {len(gaps)} trading days with missing files (round {rnd + 1})", flush=True)
        time.sleep(20)
        for d in gaps:
            for sub, name in (("bt", d.strftime("%Y%m%d") + ".json"), ("part", d.strftime("%Y%m%d") + ".json")):
                fp = os.path.join(ds.DATA, sub, name)
                try:
                    with open(fp) as f:
                        if json.load(f) == {}:
                            os.remove(fp)
                except (OSError, ValueError):
                    pass
        res = [r if r[0] not in gaps else job(r[0]) for r in res]
        for d in gaps:
            time.sleep(1)
    sessions = [d.isoformat() for d, b, p in res if b]
    missing_part = [d.isoformat() for d, b, p in res if b and not p]
    print(f"done: {len(sessions)} sessions with bhavcopy, {len(missing_part)} missing participant files "
          f"{missing_part[:5]}  in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

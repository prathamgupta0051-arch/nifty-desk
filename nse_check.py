#!/usr/bin/env python3
"""Call every NSE source the dashboard uses, fresh (no cache), and report what worked.
Run by the "NSE connection check" workflow on GitHub, or locally: python3 nse_check.py"""
import json, sys, time
from datetime import timedelta

import desk_server as ds

checks = []


def check(name, fn):
    t = time.time()
    try:
        detail = fn()
        checks.append((name, "OK", detail, time.time() - t))
    except Exception as e:
        checks.append((name, "FAILED", str(e)[:120], time.time() - t))


def last_file(url_fmt, fmt):
    for d in ds.weekdays_back(ds.now_ist().date(), 10):
        raw = ds.nse.archive(url_fmt.format(d.strftime(fmt)))
        if raw:
            return f"{d:%d %b}: {len(raw):,} bytes"
    raise RuntimeError("no file in the last 10 weekdays")


check("Nifty & India VIX quote", lambda: "Nifty " + str(next(x["last"] for x in ds.nse.json("/api/allIndices")["data"] if x["index"] == "NIFTY 50")))
check("Nifty futures (live)", lambda: f"{len(ds.nse.json('/api/liveEquity-derivatives?index=nse50_fut')['data'])} contracts")
def chain():
    e = ds.nse.json("/api/option-chain-contract-info?symbol=NIFTY")["expiryDates"][0]
    j = ds.nse.json(f"/api/option-chain-v3?type=Indices&symbol=NIFTY&expiry={e}")
    return f"expiry {e}, {len(j['records']['data'])} strikes"
check("Option chain", chain)
check("Nifty history", lambda: f"{len(ds.nse.json('/api/historicalOR/indicesHistory?indexType=NIFTY%2050&from=01-09-2026&to=30-09-2026', 'https://www.nseindia.com/reports-indices-historical-index-data')['data'])} days (Sep)")
check("India VIX history", lambda: f"{len(ds.nse.json('/api/historicalOR/vixhistory?from=01-09-2026&to=30-09-2026', 'https://www.nseindia.com/reports-indices-historical-vix')['data'])} days (Sep)")
check("FII/DII cash flows", lambda: "; ".join(f"{r['category']} net {r['netValue']} cr ({r['date']})" for r in ds.nse.json("/api/fiidiiTradeReact", "https://www.nseindia.com/reports/fii-dii")))
check("Participant OI file", lambda: last_file("https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{}.csv", "%d%m%Y"))
check("F&O bhavcopy", lambda: last_file("https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{}_F_0000.csv.zip", "%Y%m%d"))
def filings():
    t = ds.now_ist().date()
    j = ds.nse.json(f"/api/integrated-filing-results?index=equities&from_date={t - timedelta(days=6):%d-%m-%Y}&to_date={t:%d-%m-%Y}&page=0&size=20",
                    "https://www.nseindia.com/companies-listing/corporate-integrated-filing")
    return f"{j.get('totalCount')} filings in 7 days"
check("Quarterly results filings", filings)
check("Results calendar", lambda: f"{len(ds.nse.json('/api/event-calendar?index=equities', 'https://www.nseindia.com/companies-listing/corporate-filings-event-calendar'))} board meetings")
check("Market holidays", lambda: f"{len(ds.nse.json('/api/holiday-master?type=trading', 'https://www.nseindia.com/resources/exchange-communication-holidays')['CM'])} holidays")
check("Nifty 50 list", lambda: f"{ds.nse.archive('https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv').count(b'EQ,')} stocks")

ok = sum(1 for c in checks if c[1] == "OK")
print(f"\nNSE connection check · {ds.now_ist():%d %b %Y %H:%M IST} · {ok}/{len(checks)} sources OK\n")
for name, st, detail, sec in checks:
    print(f"{'✓' if st == 'OK' else '✗'} {name:28s} {st:7s} {sec:5.1f}s  {detail}")
sys.exit(0 if ok == len(checks) else 1)

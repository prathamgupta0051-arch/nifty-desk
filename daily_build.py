#!/usr/bin/env python3
"""Once-a-day build of the hosted dashboard (run by GitHub Actions after market close).

Collects everything the live server collects, then writes a static site:
  site/index.html        the dashboard
  site/api/data          six-step framework data   (the page fetches these two
  site/api/context       macro, flows, results, events  paths, same as the live server)
  site/backtest.html     the backtest report
History that NSE doesn't keep for us (daily FII/DII cash flows, macro state)
lives in data/ and is committed back to the repository by the workflow.
"""
import json, os, shutil, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import desk_server as ds
import context_feeds as cf

SITE = os.path.join(HERE, "site")


def main():
    t0 = time.time()
    os.makedirs(os.path.join(SITE, "api"), exist_ok=True)
    status = {"nse": "ok", "steps": {}}

    # 1. six-step framework (NSE)
    try:
        ds.refresh_daily()
        live, errs = ds.refresh_live()
        payload = ds.build_payload(live, errs)
        payload["static"] = True
        status["steps"]["framework"] = "ok" if payload.get("spot") and payload.get("chain") else f"partial: {errs}"
    except Exception as e:
        traceback.print_exc()
        payload = None
        status["steps"]["framework"] = f"failed: {e}"
        status["nse"] = "failed"

    # 2. market context. Results first (events use its calendar), events before macro (Fed flags use events).
    for key, fn in (("results", cf.build_results), ("events", cf.build_events), ("macro", cf.build_macro), ("flows", cf.build_flows)):
        try:
            cf.CTX[key] = fn()
            status["steps"][key] = "ok"
        except Exception as e:
            traceback.print_exc()
            cf.CTX["errors"][key] = str(e)
            status["steps"][key] = f"failed: {e}"
    cf.CTX["updated"] = {k: ds.now_ist().strftime("%H:%M") for k in ("macro", "flows", "results", "events")}

    # 3. write the site. If NSE failed, keep yesterday's framework data rather than publishing nothing.
    data_path = os.path.join(SITE, "api", "data")
    last_good = os.path.join(ds.DATA, "published_data.json")  # committed, so it survives between runs
    if payload and payload.get("spot"):
        with open(last_good, "w") as f:
            json.dump(payload, f)
    elif os.path.exists(last_good):
        with open(last_good) as f:
            payload = json.load(f)
        payload.setdefault("errors", []).append("NSE data could not be refreshed today; showing the last successful update.")
        status["steps"]["framework"] += " (showing last good data)"
    with open(data_path, "w") as f:
        json.dump(payload or {"loading": True, "errors": [status["steps"]["framework"]]}, f)
    ctx = cf.snapshot()
    with open(os.path.join(SITE, "api", "context"), "wb") as f:
        f.write(ctx)
    # committed copy, so the morning-note routine can read every tab straight from the repository
    with open(os.path.join(ds.DATA, "published_context.json"), "wb") as f:
        f.write(ctx)
    with open(os.path.join(HERE, "nifty-desk.html"), "rb") as f:
        page = f.read()
    head = (b"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            b"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
            b"<style>body{margin:0}[hidden]{display:none!important}</style></head><body>")
    with open(os.path.join(SITE, "index.html"), "wb") as f:
        f.write(head + page + b"</body></html>")
    rep = os.path.join(HERE, "backtest", "report.html")
    if os.path.exists(rep):
        with open(rep, "rb") as f:
            body = f.read()
        with open(os.path.join(SITE, "backtest.html"), "wb") as f:
            f.write(head + body + b"</body></html>")
    open(os.path.join(SITE, ".nojekyll"), "w").close()
    status["built"] = ds.now_ist().strftime("%d %b %Y, %H:%M IST")
    status["seconds"] = round(time.time() - t0)
    with open(os.path.join(SITE, "api", "status.json"), "w") as f:
        json.dump(status, f, indent=1)
    print(json.dumps(status, indent=1))


if __name__ == "__main__":
    main()

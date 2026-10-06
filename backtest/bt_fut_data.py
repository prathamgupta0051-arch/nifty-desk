"""Cache every NIFTY futures contract's daily prices from the F&O bhavcopy."""
import csv, io, json, os, sys, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_data as D
import desk_server as ds

OUT = os.path.join(ds.DATA, "btfut")
os.makedirs(OUT, exist_ok=True)


def fut_day(d):
    path = os.path.join(OUT, d.replace("-", "") + ".json")
    if os.path.exists(path):
        return json.load(open(path))
    raw = ds.nse.archive("https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_"
                         f"{d.replace('-', '')}_F_0000.csv.zip")
    if raw is None:
        raise RuntimeError(f"missing bhavcopy {d}")  # every requested day is a known session
    z = zipfile.ZipFile(io.BytesIO(raw))
    out = {}
    for r in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode("utf-8", "replace"))):
        if r.get("TckrSymb") == "NIFTY" and r["FinInstrmTp"] == "IDF":
            out[r["XpryDt"]] = {"o": float(r["OpnPric"] or 0), "c": float(r["ClsPric"] or 0),
                                "s": float(r["SttlmPric"] or 0), "lot": int(float(r["NewBrdLotQty"] or 0)),
                                "vol": int(float(r["TtlTradgVol"] or 0))}
    with open(path, "w") as f:
        json.dump(out, f)
    return out


def main():
    sessions = sorted(f[:4] + "-" + f[4:6] + "-" + f[6:8] for f in os.listdir(D.DAYS)
                      if f[0].isdigit() and json.load(open(os.path.join(D.DAYS, f))))
    t0 = time.time()

    def job(d):
        for a in range(5):
            try:
                return d, fut_day(d)
            except Exception as e:
                time.sleep(3 * (a + 1))
        print("FAILED", d, flush=True)
        return d, None

    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(job, sessions))
    bad = [d for d, r in res if not r]
    print(f"{len(res)} sessions, {len(bad)} failed {bad[:5]}, {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

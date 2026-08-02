"""Refresh OHLCV for symbols in divs_past_week.csv (1y window, parallel)."""
import sys, csv, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
sys.path.insert(0, r"C:\Users\adars\sss\scripts")
import fetch_yahoo_ohlcv as yh

ROOT = Path(r"C:\Users\adars\sss\data")
OUT  = ROOT / "ohlcv"
OUT.mkdir(parents=True, exist_ok=True)
TODAY = date.today()
START = TODAY - timedelta(days=400)

def work(sym):
    try:
        payload = yh.fetch_chart(f"{sym}.NS", START, TODAY, 30)
        rows = yh.extract_rows(payload)
        rows.sort(key=lambda r: r["date"])
        yh.write_csv(rows, str(OUT / f"{sym}.csv"))
        return sym, len(rows)
    except Exception as e:
        return sym, f"ERR: {e!r}"

def main():
    syms = sorted({r["symbol"].strip() for r in csv.DictReader(open(ROOT/"divs_past_week.csv", encoding="utf-8")) if r.get("symbol")})
    print(f"[refresh] {len(syms)} symbols, range {START}..{TODAY}", flush=True)
    t0 = time.time(); ok = err = 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(work, s): s for s in syms}
        for f in as_completed(futs):
            sym, n = f.result()
            if isinstance(n, str): err += 1; print(f"  {sym}: {n}", flush=True)
            else: ok += 1
    print(f"[done] {time.time()-t0:.1f}s  ok={ok}  err={err}", flush=True)

if __name__ == "__main__": main()

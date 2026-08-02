"""Re-fetch full 10y OHLCV for symbols whose file got truncated by refresh_div_ohlcv."""
import sys, csv, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
sys.path.insert(0, r"C:\Users\adars\sss\scripts")
import fetch_yahoo_ohlcv as yh
import pandas as pd

ROOT = Path(r"C:\Users\adars\sss\data")
OUT  = ROOT / "ohlcv"
TODAY = date.today()
START = TODAY.replace(year=TODAY.year - 10)

# Symbols affected by refresh_div_ohlcv.py: those in divs_past_week.csv
syms = sorted({r["symbol"].strip() for r in csv.DictReader(open(ROOT/"divs_past_week.csv", encoding="utf-8")) if r.get("symbol")})

def work(sym):
    p = OUT / f"{sym}.csv"
    # Check if file is truncated
    if p.exists():
        df = pd.read_csv(p, usecols=["date"])
        if len(df):
            mn = pd.to_datetime(df["date"]).min()
            if mn <= pd.Timestamp("2017-01-01"):
                return sym, -1  # already has 10y
    try:
        payload = yh.fetch_chart(f"{sym}.NS", START, TODAY, 30)
        rows = yh.extract_rows(payload)
        rows.sort(key=lambda r: r["date"])
        yh.write_csv(rows, str(p))
        return sym, len(rows)
    except Exception as e:
        return sym, f"ERR: {e!r}"

print(f"Checking/refetching {len(syms)} symbols, range {START}..{TODAY}", flush=True)
t0 = time.time(); ok = skip = err = 0
with ThreadPoolExecutor(max_workers=16) as ex:
    futs = {ex.submit(work, s): s for s in syms}
    for f in as_completed(futs):
        sym, n = f.result()
        if isinstance(n, str): err += 1; print(f"  {sym}: {n}", flush=True)
        elif n == -1: skip += 1
        else: ok += 1
print(f"[done] {time.time()-t0:.1f}s  refetched={ok} already_full={skip} err={err}", flush=True)

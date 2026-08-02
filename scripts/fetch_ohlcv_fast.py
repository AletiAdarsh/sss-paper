"""Fast parallel OHLCV fetch — 755 stocks in ~3 min using 32 workers."""
import sys, time, csv
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
sys.path.insert(0, r"C:\Users\adars\sss\scripts")
import fetch_yahoo_ohlcv as yh

ROOT = Path(r"C:\Users\adars\sss\data")
OUT  = ROOT / "ohlcv"
OUT.mkdir(parents=True, exist_ok=True)
TODAY = date.today()
START = TODAY.replace(year=TODAY.year - 10)
N_WORKERS = 32

def work(sym):
    out = OUT / f"{sym}.csv"
    if out.exists() and out.stat().st_size > 200: return sym, -1
    try:
        payload = yh.fetch_chart(f"{sym}.NS", START, TODAY, 30)
        rows = yh.extract_rows(payload)
        rows.sort(key=lambda r: r["date"])
        yh.write_csv(rows, str(out))
        return sym, len(rows)
    except Exception as e:
        return sym, f"ERR: {e!r}"

def main():
    consts = list(csv.DictReader(open(ROOT/"nifty_total_market_constituents.csv", encoding="utf-8")))
    syms = [c["Symbol"].strip() for c in consts]
    print(f"[ohlcv-fast] {len(syms)} symbols, {N_WORKERS} workers", flush=True)
    t0 = time.time()
    done = err = 0
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futs = {ex.submit(work, s): s for s in syms}
        for i, f in enumerate(as_completed(futs), 1):
            sym, n = f.result()
            if isinstance(n, str): err += 1
            else: done += 1
            if i % 50 == 0 or i == len(syms):
                print(f"[{i}/{len(syms)}] ok={done} err={err} elapsed={(time.time()-t0):.1f}s", flush=True)
    print(f"[done] {(time.time()-t0):.1f}s  ok={done}  err={err}", flush=True)

if __name__ == "__main__": main()

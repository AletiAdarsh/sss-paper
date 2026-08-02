"""Batch-fetch full history from Fyers for the declaration stocks -> data/ohlcv_fyers/.
Rate-limited to stay under Fyers' 200 req/min data cap."""
import sys, csv, time, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
sys.path.insert(0, r"C:\Users\adars\sss\scripts")
import fyers_client as fy

ROOT = Path(r"C:\Users\adars\sss\data")
OUT  = ROOT / "ohlcv_fyers"; OUT.mkdir(exist_ok=True)
SRC  = ROOT / "dividend_declarations_apr.csv"
START = "2015-01-01"
END   = date.today().isoformat()

# global rate limiter: >= 0.32s between any two API requests (~3/s, < 200/min)
_lock = threading.Lock(); _last = [0.0]
def throttle():
    with _lock:
        dt = time.time() - _last[0]
        if dt < 0.32: time.sleep(0.32 - dt)
        _last[0] = time.time()

_orig = fy.fetch_history
def rl_fetch(*a, **k):
    throttle(); return _orig(*a, **k)
fy.fetch_history = rl_fetch

def work(sym):
    fsym = f"NSE:{sym}-EQ"
    p_exist = OUT / f"{sym}.csv"
    if p_exist.exists() and p_exist.stat().st_size > 2000:   # already have a good file
        return sym, "skip"
    try:
        candles = fy.fetch_history_range(fsym, START, END, sleep=0.0)
    except Exception as e:
        return sym, f"ERR {str(e)[:60]}"
    if not candles:
        return sym, "empty"
    p = OUT / f"{sym}.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["date","open","high","low","close","volume"])
        for c in candles:
            d = datetime.fromtimestamp(c[0], timezone.utc).date().isoformat()
            w.writerow([d, c[1], c[2], c[3], c[4], c[5]])
    return sym, len(candles)

def main():
    syms = sorted({r["symbol"].strip() for r in csv.DictReader(open(SRC, encoding="utf-8")) if r.get("symbol")})
    print(f"[fyers] {len(syms)} symbols, {START}..{END}", flush=True)
    t0 = time.time(); ok = err = 0; errs = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(work, s): s for s in syms}
        for i, f in enumerate(as_completed(futs), 1):
            sym, n = f.result()
            if n == "skip": ok += 1
            elif isinstance(n, str): err += 1; errs.append(f"{sym}:{n}")
            else: ok += 1
            if i % 50 == 0 or i == len(syms):
                print(f"  [{i}/{len(syms)}] ok={ok} err={err} {time.time()-t0:.0f}s", flush=True)
    print(f"[done] {time.time()-t0:.0f}s ok={ok} err={err}", flush=True)
    if errs: print("errors:", "; ".join(errs[:40]), flush=True)

if __name__ == "__main__": main()

"""Parallel fetcher for dividend filings — 750 stocks, 10 years.

Reuses cached OHLCV. Filters NSE filings for event_type='dividend'.
Output: data/dividend_filings/<SYMBOL>.csv
"""
from __future__ import annotations
import csv, json, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, r"C:\Users\adars\sss\scripts")
import fetch_corporate_filings as cf

ROOT     = Path(r"C:\Users\adars\sss\data")
CONST    = ROOT / "nifty_total_market_constituents.csv"
OUT_DIR  = ROOT / "dividend_filings"
PROG     = ROOT / "dividend_fetch_progress.json"
ERR      = ROOT / "dividend_fetch_errors.csv"
OUT_DIR.mkdir(parents=True, exist_ok=True)

N_WORKERS  = 32
TODAY      = date.today()
START_DATE = TODAY.replace(year=TODAY.year - 10)
TIMEOUT    = 30
NSE_SLEEP  = 0.20

_LOCK = threading.Lock()
_progress: dict = {}

def load_progress():
    if PROG.exists():
        try: return json.loads(PROG.read_text())
        except: return {}
    return {}

def save_progress():
    with _LOCK: PROG.write_text(json.dumps(_progress, indent=2, default=str))

def log_error(sym, stage, msg):
    with _LOCK:
        new = not ERR.exists()
        with ERR.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if new: w.writerow(["timestamp","symbol","stage","error"])
            w.writerow([datetime.now().isoformat(timespec="seconds"), sym, stage, msg[:500]])

def fetch_dividends(symbol: str):
    out = OUT_DIR / f"{symbol}.csv"
    if out.exists() and out.stat().st_size > 100:
        return -1, "skipped"
    client = cf.HttpJsonClient(timeout=TIMEOUT, sleep_seconds=NSE_SLEEP)
    all_rows = cf.fetch_nse(client, symbol, START_DATE, TODAY, 90)
    deduped = cf.dedupe_rows(all_rows)
    divs = [r for r in deduped if r.get("event_type") == "dividend"]
    divs.sort(key=lambda r: r.get("event_datetime") or "")
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cf.CSV_FIELDS)
        w.writeheader()
        for r in divs:
            w.writerow({k: r.get(k, "") for k in cf.CSV_FIELDS})
    return len(divs), f"{len(deduped)}->{len(divs)} divs"

def process(sym):
    rec = {}
    try:
        n, msg = fetch_dividends(sym)
        rec["dividends"] = {"status":"ok","rows":n,"msg":msg,"ts":datetime.now().isoformat()}
    except Exception as e:
        log_error(sym, "dividends", repr(e))
        rec["dividends"] = {"status":"error","err":repr(e)[:200],"ts":datetime.now().isoformat()}
    return sym, rec

def main():
    global _progress
    _progress = load_progress()
    syms = [c["Symbol"].strip() for c in csv.DictReader(open(CONST, encoding="utf-8"))]
    print(f"[start] {len(syms)} symbols, {N_WORKERS} workers, range {START_DATE}..{TODAY}", flush=True)
    t0 = time.time(); done = err = completed = 0
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futs = {ex.submit(process, s): s for s in syms}
        for f in as_completed(futs):
            sym, rec = f.result()
            _progress[sym] = rec
            completed += 1
            if rec["dividends"]["status"] == "ok": done += 1
            else: err += 1
            if completed % 20 == 0 or completed == len(syms):
                save_progress()
                elapsed = (time.time()-t0)/60
                rate = completed / max(elapsed, 0.01)
                eta = (len(syms)-completed) / max(rate, 0.01)
                print(f"[{completed}/{len(syms)}] last={sym:<14} ok={done} err={err} "
                      f"elapsed={elapsed:.1f}m rate={rate:.1f}/m eta={eta:.0f}m", flush=True)
    save_progress()
    print(f"[done] {(time.time()-t0)/60:.1f}m", flush=True)

if __name__ == "__main__":
    main()

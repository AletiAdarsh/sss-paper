"""Refresh dividend filings for past 60 days (all symbols), append+dedupe."""
import sys, csv, time, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
sys.path.insert(0, r"C:\Users\adars\sss\scripts")
import fetch_corporate_filings as cf

ROOT  = Path(r"C:\Users\adars\sss\data")
CONST = ROOT / "nifty_total_market_constituents.csv"
OUT   = ROOT / "dividend_filings"
TODAY = date.today()
START = TODAY - timedelta(days=60)
N_WORKERS = 16

_LOCK = threading.Lock()

def refresh(symbol: str):
    out = OUT / f"{symbol}.csv"
    client = cf.HttpJsonClient(timeout=30, sleep_seconds=0.25)
    fresh = cf.fetch_nse(client, symbol, START, TODAY, 60)
    fresh = [r for r in fresh if r.get("event_type") == "dividend"]
    if not fresh and not out.exists(): return symbol, 0
    # Load existing rows
    existing = []
    if out.exists():
        with out.open("r", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    # Merge by dedupe_key
    seen = {r.get("dedupe_key") for r in existing if r.get("dedupe_key")}
    added = 0
    for r in fresh:
        k = r.get("dedupe_key")
        if k and k not in seen:
            existing.append({k2: r.get(k2, "") for k2 in cf.CSV_FIELDS})
            seen.add(k); added += 1
    existing.sort(key=lambda r: r.get("event_datetime") or "")
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cf.CSV_FIELDS); w.writeheader()
        for r in existing:
            w.writerow({k: r.get(k, "") for k in cf.CSV_FIELDS})
    return symbol, added

def main():
    syms = [c["Symbol"].strip() for c in csv.DictReader(open(CONST, encoding="utf-8"))]
    print(f"[refresh] {len(syms)} symbols, range {START}..{TODAY}", flush=True)
    t0 = time.time(); ok = err = total_added = 0
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futs = {ex.submit(refresh, s): s for s in syms}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                sym, added = f.result()
                ok += 1; total_added += added
            except Exception as e:
                err += 1
            if i % 100 == 0 or i == len(syms):
                print(f"  [{i}/{len(syms)}] ok={ok} err={err} added={total_added} {time.time()-t0:.0f}s", flush=True)
    print(f"[done] {time.time()-t0:.0f}s  added={total_added}", flush=True)

if __name__ == "__main__": main()

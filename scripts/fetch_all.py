"""Parallel driver: fetch OHLCV + earnings-only NSE filings for the NIFTY
Total Market (~755 stocks), last 10 years.

Speedup vs the serial version:
  - ThreadPoolExecutor with N_WORKERS threads
  - Each thread builds its own HttpJsonClient (own cookie jar) -> no shared
    state, no contention.
  - Per-symbol output files; driver skips already-finished symbols.
  - Progress JSON + error CSV are written under a lock.

Run:
    python C:\\Users\\adars\\sss\\scripts\\fetch_all.py
"""
from __future__ import annotations
import csv
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

SCRIPTS = Path(r"C:\Users\adars\sss\scripts")
sys.path.insert(0, str(SCRIPTS))

import fetch_yahoo_ohlcv as yh         # noqa: E402
import fetch_corporate_filings as cf   # noqa: E402

ROOT       = Path(r"C:\Users\adars\sss\data")
CONST_FILE = ROOT / "nifty_total_market_constituents.csv"
OHLCV_DIR  = ROOT / "ohlcv"
FILE_DIR   = ROOT / "filings"
PROG_FILE  = ROOT / "fetch_progress.json"
ERR_FILE   = ROOT / "fetch_errors.csv"
OHLCV_DIR.mkdir(parents=True, exist_ok=True)
FILE_DIR.mkdir(parents=True, exist_ok=True)

N_WORKERS  = 32
TODAY      = date.today()
START_DATE = TODAY.replace(year=TODAY.year - 10)
TIMEOUT    = 30
NSE_SLEEP  = 0.20    # per-chunk wait inside a worker

_LOCK = threading.Lock()
_progress: dict = {}

def load_constituents() -> list[dict]:
    with open(CONST_FILE, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def load_progress() -> dict:
    if PROG_FILE.exists():
        try: return json.loads(PROG_FILE.read_text())
        except Exception: return {}
    return {}

def save_progress():
    with _LOCK:
        PROG_FILE.write_text(json.dumps(_progress, indent=2, default=str))

def log_error(symbol: str, stage: str, msg: str):
    with _LOCK:
        new = not ERR_FILE.exists()
        with ERR_FILE.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if new: w.writerow(["timestamp","symbol","stage","error"])
            w.writerow([datetime.now().isoformat(timespec="seconds"), symbol, stage, msg[:500]])

def fetch_ohlcv(symbol: str) -> tuple[int, str]:
    out = OHLCV_DIR / f"{symbol}.csv"
    if out.exists() and out.stat().st_size > 200:
        return -1, "skipped"
    payload = yh.fetch_chart(f"{symbol}.NS", START_DATE, TODAY, TIMEOUT)
    rows = yh.extract_rows(payload)
    rows.sort(key=lambda r: r["date"])
    yh.write_csv(rows, str(out))
    return len(rows), (f"{rows[0]['date']} -> {rows[-1]['date']}" if rows else "no data")

def fetch_filings_earnings(symbol: str) -> tuple[int, str]:
    out = FILE_DIR / f"{symbol}.csv"
    if out.exists() and out.stat().st_size > 100:
        return -1, "skipped"
    client = cf.HttpJsonClient(timeout=TIMEOUT, sleep_seconds=NSE_SLEEP)
    all_rows = cf.fetch_nse(client, symbol, START_DATE, TODAY, 90)
    deduped = cf.dedupe_rows(all_rows)
    earnings = [r for r in deduped if r.get("event_type") == "earnings_results"]
    earnings.sort(key=lambda r: r.get("event_datetime") or "")
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cf.CSV_FIELDS)
        w.writeheader()
        for r in earnings:
            w.writerow({k: r.get(k, "") for k in cf.CSV_FIELDS})
    return len(earnings), f"{len(deduped)}->{len(earnings)} earnings"

def process_symbol(symbol: str) -> tuple[str, dict]:
    rec = {}
    try:
        n, msg = fetch_ohlcv(symbol)
        rec["ohlcv"] = {"status":"ok", "rows": n, "msg": msg, "ts": datetime.now().isoformat()}
    except Exception as e:
        log_error(symbol, "ohlcv", repr(e))
        rec["ohlcv"] = {"status":"error", "err": repr(e)[:200], "ts": datetime.now().isoformat()}
    try:
        n, msg = fetch_filings_earnings(symbol)
        rec["filings"] = {"status":"ok", "rows": n, "msg": msg, "ts": datetime.now().isoformat()}
    except Exception as e:
        log_error(symbol, "filings", repr(e))
        rec["filings"] = {"status":"error", "err": repr(e)[:200], "ts": datetime.now().isoformat()}
    return symbol, rec

def main():
    global _progress
    consts = load_constituents()
    _progress = load_progress()
    symbols = [c["Symbol"].strip() for c in consts]
    print(f"[start] {len(symbols)} symbols  range={START_DATE}..{TODAY}  workers={N_WORKERS}", flush=True)
    t0 = time.time()
    completed = 0
    done_o = done_f = err_o = err_f = 0
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futures = {ex.submit(process_symbol, sym): sym for sym in symbols}
        for fut in as_completed(futures):
            sym, rec = fut.result()
            _progress[sym] = rec
            completed += 1
            if rec.get("ohlcv",{}).get("status") == "ok":   done_o += 1
            else:                                           err_o += 1
            if rec.get("filings",{}).get("status") == "ok": done_f += 1
            else:                                           err_f += 1
            if completed % 20 == 0 or completed == len(symbols):
                save_progress()
                elapsed = (time.time() - t0) / 60
                rate    = completed / max(elapsed, 0.01)
                eta     = (len(symbols) - completed) / max(rate, 0.01)
                print(f"[{completed:>3}/{len(symbols)}] last={sym:<14} "
                      f"ohlcv_ok={done_o} err={err_o} | filings_ok={done_f} err={err_f} | "
                      f"elapsed={elapsed:.1f}m rate={rate:.1f}/m eta={eta:.0f}m",
                      flush=True)
    save_progress()
    print(f"[done] total time {(time.time()-t0)/60:.1f}m", flush=True)

if __name__ == "__main__":
    main()

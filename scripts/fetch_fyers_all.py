"""Fetch Fyers OHLCV for ALL constituents we don't already have (skips existing)."""
import sys, csv, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, r"C:\Users\adars\sss\scripts")
import fetch_fyers_ohlcv as bf   # reuses work() (skip-existing + throttle)

ROOT=Path(r"C:\Users\adars\sss\data")
syms=sorted({c["Symbol"].strip() for c in csv.DictReader(open(ROOT/"nifty_total_market_constituents.csv",encoding="utf-8"))})
have={p.stem for p in (ROOT/"ohlcv_fyers").glob("*.csv")}
todo=[s for s in syms if s not in have]
print(f"[fyers-all] {len(syms)} constituents, {len(have)} already, fetching {len(todo)}", flush=True)
t0=time.time(); ok=err=0; errs=[]
with ThreadPoolExecutor(max_workers=4) as ex:
    futs={ex.submit(bf.work,s):s for s in todo}
    for i,f in enumerate(as_completed(futs),1):
        sym,n=f.result()
        if n=="skip": ok+=1
        elif isinstance(n,str): err+=1; errs.append(f"{sym}:{n[:30]}")
        else: ok+=1
        if i%50==0 or i==len(todo):
            print(f"  [{i}/{len(todo)}] ok={ok} err={err} {time.time()-t0:.0f}s", flush=True)
print(f"[done] {time.time()-t0:.0f}s ok={ok} err={err}", flush=True)
if errs: print("errs:", "; ".join(errs[:40]), flush=True)

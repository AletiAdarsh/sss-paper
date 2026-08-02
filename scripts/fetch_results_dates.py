"""Fetch quarterly/annual RESULTS announcement dates for ALL constituents, last 5y.
Anchor = earnings_results filings (financial results). -> data/results_dates.csv"""
import sys, csv, time
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, r"C:\Users\adars\sss\scripts")
import fetch_corporate_filings as cf

ROOT=r"C:\Users\adars\sss\data"
CONST=ROOT+r"\nifty_total_market_constituents.csv"
OUT=ROOT+r"\results_dates.csv"
START=date(2021,1,1); TODAY=date.today(); N=16

def work(sym):
    try:
        cl=cf.HttpJsonClient(timeout=30, sleep_seconds=0.15)
        rows=cf.fetch_nse(cl, sym, START, TODAY, 90)
    except Exception as e:
        return sym, None, f"ERR {str(e)[:40]}"
    seen={}
    for r in rows:
        if r.get("event_type")!="earnings_results": continue
        text=(r.get("headline") or "")+" "+(r.get("description") or "")
        tl=text.lower()
        # keep genuine results filings; skip investor-call/presentation noise
        if not any(k in tl for k in ("financial result","quarterly result","audited","unaudited","standalone","consolidated result","integrated filing")):
            continue
        dt=(r.get("event_datetime") or "")[:10]
        if dt and dt not in seen:
            seen[dt]={"symbol":sym,"result_dt":(r.get("event_datetime") or "")[:19],
                      "headline":(r.get("headline") or "")[:120]}
    return sym, list(seen.values()), "ok"

def main():
    syms=[c["Symbol"].strip() for c in csv.DictReader(open(CONST, encoding="utf-8"))]
    print(f"[results] {len(syms)} symbols {START}..{TODAY}", flush=True)
    t0=time.time(); allrows=[]; ok=err=0; errs=[]
    with ThreadPoolExecutor(max_workers=N) as ex:
        futs={ex.submit(work,s):s for s in syms}
        for i,f in enumerate(as_completed(futs),1):
            sym,evs,st=f.result()
            if st!="ok": err+=1; errs.append(sym)
            else: ok+=1; allrows.extend(evs or [])
            if i%100==0 or i==len(syms):
                print(f"  [{i}/{len(syms)}] events={len(allrows)} err={err} {time.time()-t0:.0f}s", flush=True)
    allrows.sort(key=lambda r:(r["symbol"],r["result_dt"]))
    with open(OUT,"w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=["symbol","result_dt","headline"]); w.writeheader(); w.writerows(allrows)
    print(f"[done] {time.time()-t0:.0f}s  {len(allrows)} results across {len({r['symbol'] for r in allrows})} stocks -> {OUT}", flush=True)
    if errs: print("errs:", ",".join(errs[:30]), flush=True)

if __name__=="__main__": main()

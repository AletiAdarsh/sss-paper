"""Full dividend-announcement history (declaration date + amount + type) for each
Fyers stock, last 5y. Keeps ALL declarations per symbol (not just latest), from NSE
corporate-announcements board_meeting/dividend filings. -> data/dividend_declarations_history.csv"""
import sys, csv, re, time
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, r"C:\Users\adars\sss\scripts")
import fetch_corporate_filings as cf

ROOT  = r"C:\Users\adars\sss\data"
SRC   = ROOT + r"\dividend_declarations_apr.csv"      # the Fyers stock universe (441)
OUT   = ROOT + r"\dividend_declarations_history.csv"
START = date(2021, 1, 1)
TODAY = date.today()
N = 16

amt_per = re.compile(r"(?:Rs\.?|Re\.?|INR|₹)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/-)?\s*per\s+(?:equity\s+)?share", re.I)

def parse_amt(text):
    ms = amt_per.findall(text)
    if ms:
        try: return round(sum(float(x) for x in ms), 4)
        except: pass
    return None

def dtype(t):
    t = t.lower()
    return "interim" if "interim" in t else "final" if "final" in t else "special" if "special" in t else "dividend"

def work(sym):
    try:
        cl = cf.HttpJsonClient(timeout=30, sleep_seconds=0.15)
        rows = cf.fetch_nse(cl, sym, START, TODAY, 90)
    except Exception as e:
        return sym, None, f"ERR {str(e)[:50]}"
    # capture board-meeting DECLARATION DATES that concern a dividend (amount optional);
    # prefer the outcome filing. dedupe by day.
    events = {}
    for r in rows:
        et = r.get("event_type")
        if et not in ("board_meeting", "earnings_results"): continue
        text = (r.get("headline") or "") + " " + (r.get("description") or "")
        tl = text.lower()
        if "dividend" not in tl: continue
        # skip pure "meeting will be held" pre-intimations without an outcome verb
        is_outcome = bool(re.search(r"recommend|declar|approv|outcome|considered|meeting held", tl))
        dt = (r.get("event_datetime") or "")[:10]
        if not dt: continue
        amt = parse_amt(text)
        prev = events.get(dt)
        # keep one row per day; prefer the row that has an amount / is an outcome
        if prev is None or (amt is not None and prev.get("amount_rs") is None) or (is_outcome and not prev.get("_out")):
            events[dt] = {"symbol": sym, "declare_dt": (r.get("event_datetime") or "")[:19],
                          "amount_rs": amt, "dividend_type": dtype(text),
                          "_out": is_outcome, "headline": (r.get("headline") or "")[:140]}
    for e in events.values(): e.pop("_out", None)
    return sym, list(events.values()), "ok"

def main():
    syms = sorted({r["symbol"].strip() for r in csv.DictReader(open(SRC, encoding="utf-8")) if r.get("symbol")})
    print(f"[decl-hist] {len(syms)} symbols {START}..{TODAY}", flush=True)
    t0 = time.time(); allrows = []; ok = err = 0; errs = []
    with ThreadPoolExecutor(max_workers=N) as ex:
        futs = {ex.submit(work, s): s for s in syms}
        for i, f in enumerate(as_completed(futs), 1):
            sym, evs, status = f.result()
            if status != "ok": err += 1; errs.append(sym)
            else: ok += 1; allrows.extend(evs or [])
            if i % 50 == 0 or i == len(syms):
                print(f"  [{i}/{len(syms)}] events={len(allrows)} err={err} {time.time()-t0:.0f}s", flush=True)
    allrows.sort(key=lambda r: (r["symbol"], r["declare_dt"]))
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["symbol","declare_dt","amount_rs","dividend_type","headline"])
        w.writeheader(); w.writerows(allrows)
    n_syms = len({r["symbol"] for r in allrows})
    print(f"[done] {time.time()-t0:.0f}s  {len(allrows)} declarations across {n_syms} stocks -> {OUT}", flush=True)
    if errs: print("errs:", ",".join(errs[:40]), flush=True)

if __name__ == "__main__": main()

"""Pull dividend records from NSE's Corporate Actions API.

Endpoint: https://www.nseindia.com/api/corporates-corporateActions
Returns per record: symbol, series, subject (e.g. 'Interim Dividend - Rs 4.50 Per Share'),
ex_date, record_date, etc. Across ALL companies in one call per date range.
"""
import csv, json, re, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import date, timedelta
from http.cookiejar import CookieJar
from pathlib import Path

OUT  = Path(r"C:\Users\adars\sss\data\corporate_actions_raw.csv")
DIV  = Path(r"C:\Users\adars\sss\data\dividends_official.csv")
URL  = "https://www.nseindia.com/api/corporates-corporateActions"
BOOT = "https://www.nseindia.com/companies-listing/corporate-filings-actions"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
           "Accept-Language":"en-US,en;q=0.9", "Referer": BOOT}
TODAY = date.today()
START = TODAY.replace(year=TODAY.year - 10)
CHUNK = 60   # days per request

def build_opener():
    jar = CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.open(urllib.request.Request(BOOT, headers=HEADERS), timeout=30).read()
    time.sleep(0.5)
    return op

def fetch_chunk(op, frm, to):
    params = {"index":"equities",
              "from_date": frm.strftime("%d-%m-%Y"),
              "to_date":   to.strftime("%d-%m-%Y")}
    url = f"{URL}?{urllib.parse.urlencode(params)}"
    last = None
    for k in range(4):
        try:
            with op.open(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
                body = r.read().decode("utf-8", errors="replace")
            d = json.loads(body)
            return d if isinstance(d, list) else d.get("data", [])
        except Exception as e:
            last = e; time.sleep(1 + k)
    print(f"  fail {frm}..{to}: {last!r}", flush=True)
    return []

def iter_chunks():
    cur = START
    while cur <= TODAY:
        nxt = min(TODAY, cur + timedelta(days=CHUNK-1))
        yield cur, nxt
        cur = nxt + timedelta(days=1)

def main():
    op = build_opener()
    chunks = list(iter_chunks())
    print(f"{len(chunks)} chunks of {CHUNK}d  range={START}..{TODAY}", flush=True)
    all_rows = []
    t0 = time.time()
    for i, (frm, to) in enumerate(chunks, 1):
        data = fetch_chunk(op, frm, to)
        for d in data:
            all_rows.append(d)
        if i % 5 == 0 or i == len(chunks):
            print(f"  [{i}/{len(chunks)}] {frm}..{to}  +{len(data)}  cum={len(all_rows)}  {time.time()-t0:.1f}s", flush=True)
        time.sleep(0.30)

    # save raw
    if all_rows:
        keys = sorted({k for r in all_rows for k in r.keys()})
        with OUT.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader()
            for r in all_rows: w.writerow({k: r.get(k,"") for k in keys})
        print(f"\nRaw corporate actions: {len(all_rows):,} rows -> {OUT}")

    # filter to dividends and extract amount
    p_rs = re.compile(r"(?:Rs\.?|INR|₹)\s*([0-9]+(?:\.[0-9]+)?)", re.I)
    p_pct = re.compile(r"([0-9]{1,4}(?:\.[0-9]+)?)\s*%")
    p_fv  = re.compile(r"face\s+value\s+(?:of\s+)?(?:Rs\.?|INR|₹)?\s*([0-9]+(?:\.[0-9]+)?)", re.I)
    div_rows = []
    seen = set()
    for r in all_rows:
        subj = (r.get("subject") or r.get("purpose") or "").strip()
        if "dividend" not in subj.lower(): continue
        sym = (r.get("symbol") or "").strip()
        exd = r.get("exDate") or r.get("ex_date") or ""
        rec = r.get("recDate") or r.get("record_date") or ""
        key = (sym, exd, subj)
        if key in seen: continue
        seen.add(key)
        amt = None; src = ""
        m = p_rs.search(subj)
        if m:
            try: amt = float(m.group(1)); src = "Rs_in_subject"
            except: pass
        if amt is None:
            mp = p_pct.search(subj)
            if mp:
                pct = float(mp.group(1))
                fv = 10.0
                mf = p_fv.search(subj)
                if mf:
                    try: fv = float(mf.group(1))
                    except: pass
                if 5 <= pct <= 2000:
                    amt = pct/100.0 * fv; src = "pct_of_fv"
        # classify dividend type
        sl = subj.lower()
        if "interim" in sl: dtype = "interim"
        elif "final" in sl: dtype = "final"
        elif "special" in sl: dtype = "special"
        else: dtype = "other"
        div_rows.append({"symbol":sym, "subject":subj, "dividend_type":dtype,
                         "amount_rs": amt, "amount_source": src,
                         "ex_date":exd, "record_date":rec,
                         "broadcast_date": r.get("bcastdt") or r.get("an_dt") or ""})
    print(f"\nDividend records: {len(div_rows):,}   with amount: {sum(1 for r in div_rows if r['amount_rs']):,}")
    with DIV.open("w", encoding="utf-8", newline="") as f:
        keys = ["symbol","dividend_type","amount_rs","amount_source","subject","ex_date","record_date","broadcast_date"]
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader()
        for r in div_rows: w.writerow({k: r.get(k,"") for k in keys})
    print(f"Wrote: {DIV}")
    print(f"Total: {(time.time()-t0):.1f}s")

if __name__ == "__main__": main()

"""Pull OFFICIAL earnings filing dates from NSE's bulk financial-results
endpoint.

Endpoint: https://www.nseindia.com/api/corporates-financial-results
Params:
    index=equities
    period=Quarterly
    from_date=DD-MM-YYYY
    to_date=DD-MM-YYYY

Returns every quarterly filing across ALL listed companies in the window.
We iterate in 60-day chunks across 10 years -> ~60 API calls total.

Output: data/earnings_dates.csv (replaces the volume-spike file).
"""
from __future__ import annotations
import csv
import json
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, timedelta
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(r"C:\Users\adars\sss\data")
OUT  = ROOT / "earnings_dates.csv"

URL  = "https://www.nseindia.com/api/corporates-financial-results"
BOOT = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept":     "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":    BOOT,
}

TODAY = date.today()
START = TODAY.replace(year=TODAY.year - 10)
CHUNK = 60   # days

def build_opener():
    jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def bootstrap(opener):
    req = urllib.request.Request(BOOT, headers=HEADERS)
    with opener.open(req, timeout=30) as r:
        r.read()
    time.sleep(0.5)

def fetch_chunk(opener, frm: date, to: date) -> list[dict]:
    params = {
        "index": "equities",
        "period": "Quarterly",
        "from_date": frm.strftime("%d-%m-%Y"),
        "to_date":   to.strftime("%d-%m-%Y"),
    }
    url = f"{URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    last = None
    for attempt in range(4):
        try:
            with opener.open(req, timeout=30) as r:
                body = r.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            return data if isinstance(data, list) else data.get("data", [])
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            last = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"failed chunk {frm}..{to}: {last!r}")

def iter_chunks(start: date, end: date):
    cur = start
    while cur <= end:
        nxt = min(end, cur + timedelta(days=CHUNK-1))
        yield cur, nxt
        cur = nxt + timedelta(days=1)

def main():
    opener = build_opener()
    bootstrap(opener)
    all_rows = []
    chunks = list(iter_chunks(START, TODAY))
    print(f"Pulling {len(chunks)} chunks of {CHUNK} days each across {START}..{TODAY}", flush=True)
    t0 = time.time()
    for i, (frm, to) in enumerate(chunks, 1):
        try:
            data = fetch_chunk(opener, frm, to)
            for d in data:
                all_rows.append({
                    "symbol":          (d.get("symbol") or "").strip(),
                    "company_name":    (d.get("companyName") or d.get("companyname") or "").strip(),
                    "isin":            (d.get("isin") or "").strip(),
                    "broadcast_dt":    d.get("broadcastDate") or d.get("broadcastDt") or d.get("relDt"),
                    "period_ended":    d.get("toDate") or d.get("period") or "",
                    "raw":             "",
                })
            print(f"  [{i}/{len(chunks)}] {frm}..{to} -> {len(data)} filings (cum={len(all_rows)})  elapsed={time.time()-t0:.1f}s", flush=True)
        except Exception as e:
            print(f"  [{i}/{len(chunks)}] ERROR {frm}..{to}: {e!r}", flush=True)
        time.sleep(0.4)
    # de-dupe by (symbol, broadcast_dt)
    seen = set(); out = []
    for r in all_rows:
        key = (r["symbol"], r["broadcast_dt"])
        if key in seen or not r["symbol"]: continue
        seen.add(key); out.append(r)
    # write
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["symbol","company_name","isin","broadcast_dt","period_ended"])
        w.writeheader()
        for r in out:
            w.writerow({k: r.get(k, "") for k in w.fieldnames})
    print(f"\n{len(out):,} unique earnings filings across {len(set(r['symbol'] for r in out))} symbols")
    print(f"Wrote: {OUT}")
    print(f"Total time: {(time.time()-t0):.1f}s")

if __name__ == "__main__": main()

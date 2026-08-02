"""Try NSE corporate-announcements endpoint with subject filter (no symbol).
Returns all companies' filings matching subject in a date range."""
import csv, json, time, urllib.request, urllib.parse
from datetime import date, timedelta
from http.cookiejar import CookieJar
from pathlib import Path

OUT = Path(r"C:\Users\adars\sss\data\earnings_dates.csv")
URL  = "https://www.nseindia.com/api/corporate-announcements"
BOOT = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
HEADERS = {"User-Agent":"Mozilla/5.0", "Accept":"application/json","Referer":BOOT}
TODAY = date.today()
START = TODAY.replace(year=TODAY.year-10)
CHUNK = 45

jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
opener.open(urllib.request.Request(BOOT, headers=HEADERS), timeout=30).read()
time.sleep(0.5)

def fetch(frm, to):
    params = {"index":"equities","subject":"Financial Results",
              "from_date":frm.strftime("%d-%m-%Y"),"to_date":to.strftime("%d-%m-%Y")}
    url = f"{URL}?{urllib.parse.urlencode(params)}"
    for k in range(3):
        try:
            r = opener.open(urllib.request.Request(url, headers=HEADERS), timeout=30)
            body = r.read().decode("utf-8","replace")
            d = json.loads(body)
            return d if isinstance(d, list) else d.get("data", [])
        except Exception as e:
            if k == 2: print(f"  fail {frm}..{to}: {e!r}"); return []
            time.sleep(1+k)

cur, t0, all_rows = START, time.time(), []
chunks = []
while cur <= TODAY:
    nxt = min(TODAY, cur + timedelta(days=CHUNK-1))
    chunks.append((cur, nxt)); cur = nxt + timedelta(days=1)
print(f"{len(chunks)} chunks of {CHUNK}d")
for i,(frm,to) in enumerate(chunks,1):
    data = fetch(frm, to)
    for d in data:
        all_rows.append({
            "symbol":(d.get("symbol") or "").strip(),
            "an_dt": d.get("an_dt") or d.get("sort_date") or d.get("dt") or "",
            "desc":  d.get("desc") or d.get("attchmntText") or "",
        })
    if i % 5 == 0 or i == len(chunks):
        print(f"  [{i}/{len(chunks)}] {frm}..{to}  +{len(data)}  cum={len(all_rows)}  {time.time()-t0:.1f}s", flush=True)
    time.sleep(0.30)

# parse dates and dedupe
import re
def parse_dt(s):
    m = re.match(r"(\d{2})-(\w{3})-(\d{4})", str(s))
    if not m: return None
    try:
        from datetime import datetime
        return datetime.strptime(s[:11], "%d-%b-%Y").date()
    except: return None

for r in all_rows:
    r["event_date"] = parse_dt(r["an_dt"])
seen = set(); deduped = []
for r in all_rows:
    if not r["symbol"] or not r["event_date"]: continue
    key = (r["symbol"], r["event_date"])
    if key in seen: continue
    seen.add(key); deduped.append(r)

# also drop "schedule of" / "intimation" type filings — keep only the actual result publishing
keep = []
for r in deduped:
    desc = (r["desc"] or "").lower()
    if "schedule" in desc or "intimation" in desc: continue
    keep.append(r)

with OUT.open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f); w.writerow(["symbol","event_date","desc"])
    for r in keep: w.writerow([r["symbol"], r["event_date"], r["desc"][:120]])

print(f"\n{len(deduped):,} unique (symbol,date) filings; {len(keep):,} after dropping schedules/intimations")
print(f"Symbols: {len(set(r['symbol'] for r in keep))}")
print(f"Wrote: {OUT}")
print(f"Total: {time.time()-t0:.1f}s")

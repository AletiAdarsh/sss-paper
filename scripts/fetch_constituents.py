"""Fetch the official NIFTY Total Market (~750) constituent list from NSE."""
import csv
import urllib.request
import os

URL = "https://archives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv"
OUT = r"C:\Users\adars\sss\data\nifty_total_market_constituents.csv"

req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=30) as resp:
    text = resp.read().decode("utf-8")

# Save raw
with open(OUT, "w", encoding="utf-8", newline="") as f:
    f.write(text)

# Quick parse
rows = list(csv.DictReader(text.splitlines()))
print(f"Wrote {len(rows)} constituents to {OUT}")
print("Columns:", list(rows[0].keys()) if rows else "(empty)")
print("\nFirst 5 rows:")
for r in rows[:5]:
    print(" ", r)

# Industry breakdown
if rows:
    from collections import Counter
    industries = Counter(r.get("Industry","") for r in rows)
    print(f"\nUnique industries: {len(industries)}")
    for ind, n in industries.most_common(15):
        print(f"  {ind:<40} {n}")

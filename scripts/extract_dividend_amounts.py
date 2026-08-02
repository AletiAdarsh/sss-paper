"""Extract dividend amount from filing text and compute dividend yield.

Sources in NSE filings (in priority order):
  1. Headline / description fields, e.g.
     - "Interim Dividend of Rs. 2.50 per share"
     - "Final Dividend of Rs. 8/- per equity share of face value of Rs. 10/-"
     - "dividend of 200% (Rs. 20 per share of Rs. 10 face value)"
  2. raw_category if it contains "Dividend"

Rules:
  - Prefer absolute "Rs. X" or "INR X" per share amount.
  - If only "X%" is found AND face value (FV) is captured, amount = X% * FV.
  - Yield = amount / reaction_close (close on event day from metrics).

Output: data/metrics/all_dividend_metrics_with_amount.csv
"""
import re
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:\Users\adars\sss\data")
M = ROOT / "metrics" / "all_dividend_metrics.csv"
F = ROOT / "dividend_filings"
OUT = ROOT / "metrics" / "all_dividend_metrics_with_amount.csv"

# regex patterns
P_RS_PER = re.compile(
    r"(?:Rs\.?|INR|₹)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/-)?\s*(?:per\s+(?:equity\s+)?share)",
    re.IGNORECASE)
P_RS_OF_RS = re.compile(  # "dividend of Rs. 2.50" without 'per share' but next "of Rs"
    r"(?:dividend|div)[^.]*?(?:Rs\.?|INR|₹)\s*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE)
P_PCT = re.compile(r"([0-9]{1,4}(?:\.[0-9]+)?)\s*%", re.IGNORECASE)
P_FV  = re.compile(
    r"face\s+value\s+(?:of\s+)?(?:Rs\.?|INR|₹)\s*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE)

def parse_amount(text: str) -> tuple[float|None, str]:
    if not isinstance(text, str): return None, ""
    m = P_RS_PER.search(text)
    if m:
        try: return float(m.group(1)), "Rs_per_share"
        except: pass
    m = P_PCT.search(text)
    if m:
        pct = float(m.group(1))
        # extract face value
        fv_m = P_FV.search(text)
        fv = 10.0  # default for most Indian stocks
        if fv_m:
            try: fv = float(fv_m.group(1))
            except: pass
        # only use % path if it's a reasonable dividend % (10..1000)
        if 5 <= pct <= 2000:
            return pct/100.0 * fv, "pct_of_fv"
    m = P_RS_OF_RS.search(text)
    if m:
        try:
            v = float(m.group(1))
            if 0.1 <= v <= 500: return v, "Rs_in_dividend_text"
        except: pass
    return None, ""

# load metrics
df = pd.read_csv(M)
df["filing_date"] = pd.to_datetime(df["filing_date"])
print(f"Loaded {len(df):,} dividend events")

# scan filings per symbol — combine headline+description+raw_category for parsing
# we need to merge by (symbol, filing_date) but the metrics already has these
amounts = []
sources = []
checked = []

# pre-load all filings once
filing_text: dict[tuple[str,str], str] = {}
for fp in F.glob("*.csv"):
    sym = fp.stem
    try:
        d = pd.read_csv(fp)
    except: continue
    if "event_date" not in d.columns: continue
    d["event_date"] = pd.to_datetime(d["event_date"], errors="coerce")
    for _, r in d.iterrows():
        if pd.isna(r["event_date"]): continue
        key = (sym, r["event_date"].date().isoformat())
        existing = filing_text.get(key, "")
        text = " | ".join(str(r.get(c,"")) for c in ["headline","description","raw_category"])
        filing_text[key] = (existing + " | " + text) if existing else text

for _, r in df.iterrows():
    key = (r["symbol"], pd.to_datetime(r["filing_date"]).date().isoformat())
    txt = filing_text.get(key, "")
    amt, src = parse_amount(txt)
    amounts.append(amt); sources.append(src)

df["dividend_amount_rs"] = amounts
df["dividend_amount_source"] = sources

# Pull reaction_close from OHLCV per symbol+reaction_date
print("Looking up reaction_close from OHLCV...")
_o_cache: dict[str, pd.DataFrame] = {}
def get_close(sym, dt):
    if sym not in _o_cache:
        p = ROOT/"ohlcv"/f"{sym}.csv"
        if not p.exists():
            _o_cache[sym] = None; return None
        o = pd.read_csv(p)
        o["date"] = pd.to_datetime(o["date"])
        o["adj_close"] = pd.to_numeric(o["adj_close"], errors="coerce")
        _o_cache[sym] = o
    o = _o_cache[sym]
    if o is None: return None
    row = o.loc[o["date"] == pd.to_datetime(dt), "adj_close"]
    return float(row.iloc[0]) if len(row) else None

closes = [get_close(r["symbol"], r["reaction_date"]) for _, r in df.iterrows()]
df["reaction_close"] = closes
df["dividend_yield_pct"] = (df["dividend_amount_rs"] / df["reaction_close"]) * 100.0

# Buckets
def yield_bucket(y):
    if pd.isna(y): return "unknown"
    if y < 0.25: return "<0.25%"
    if y < 0.5:  return "0.25-0.5%"
    if y < 1.0:  return "0.5-1%"
    if y < 2.0:  return "1-2%"
    if y < 3.0:  return "2-3%"
    if y < 5.0:  return "3-5%"
    return ">=5%"
df["yield_bucket"] = df["dividend_yield_pct"].apply(yield_bucket)

# also amount buckets (absolute Rs)
def amt_bucket(a):
    if pd.isna(a): return "unknown"
    if a < 1: return "<Rs 1"
    if a < 2: return "Rs 1-2"
    if a < 5: return "Rs 2-5"
    if a < 10: return "Rs 5-10"
    if a < 25: return "Rs 10-25"
    if a < 100: return "Rs 25-100"
    return ">=Rs 100"
df["amount_bucket"] = df["dividend_amount_rs"].apply(amt_bucket)

print(f"  parsed amount: {df['dividend_amount_rs'].notna().sum():,}/{len(df):,} "
      f"({df['dividend_amount_rs'].notna().mean():.1%})")
print(f"  parsed by source:")
print(df["dividend_amount_source"].value_counts().to_string())
print(f"\n  amount stats (Rs/share): "
      f"median={df['dividend_amount_rs'].median():.2f}  "
      f"p10={df['dividend_amount_rs'].quantile(.1):.2f}  "
      f"p90={df['dividend_amount_rs'].quantile(.9):.2f}")
print(f"  yield stats (%): "
      f"median={df['dividend_yield_pct'].median():.3f}%  "
      f"p10={df['dividend_yield_pct'].quantile(.1):.3f}%  "
      f"p90={df['dividend_yield_pct'].quantile(.9):.3f}%")
print(f"\n  yield bucket distribution:")
print(df["yield_bucket"].value_counts().to_string())
df.to_csv(OUT, index=False)
print(f"\nWrote: {OUT}")

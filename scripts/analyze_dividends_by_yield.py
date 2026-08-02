"""Dividend pattern analysis bucketed by YIELD (amount / price).

Uses NSE official corporate-actions data (dividends_official.csv) joined
with OHLCV. Anchor date = broadcast_date if available else ex_date.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"C:\Users\adars\sss\data")
RPT  = Path(r"C:\Users\adars\sss\reports")
RPT.mkdir(parents=True, exist_ok=True)
OUT  = RPT / "dividend_by_yield.txt"

PRE_W  = [1, 3, 5, 7, 14, 21]
POST_W = [1, 3, 5, 7, 14, 21, 30, 45, 60]

lines = []
def p(*a): s = " ".join(str(x) for x in a); lines.append(s); print(s)

# Load dividends + constituents
divs = pd.read_csv(ROOT/"dividends_official.csv")
print(f"Raw dividend records: {len(divs):,}")

# parse dates
def pd_date(s):
    if pd.isna(s) or s == "": return pd.NaT
    try: return pd.to_datetime(s, dayfirst=True, errors="coerce")
    except: return pd.NaT
divs["ex_date"]        = divs["ex_date"].apply(pd_date)
divs["record_date"]    = divs["record_date"].apply(pd_date)
divs["broadcast_date"] = divs["broadcast_date"].apply(pd_date)
# anchor for our event = broadcast_date (announcement) if present else ex_date
divs["anchor_date"]    = divs["broadcast_date"].fillna(divs["ex_date"])
divs = divs.dropna(subset=["anchor_date","symbol"])
divs = divs[divs["amount_rs"].notna() & (divs["amount_rs"] > 0)]
print(f"Records with amount + anchor: {len(divs):,}")

consts = pd.read_csv(ROOT/"nifty_total_market_constituents.csv")
consts.columns = [c.strip() for c in consts.columns]
INDUSTRY = dict(zip(consts["Symbol"].str.strip(), consts["Industry"].fillna("")))
universe = set(consts["Symbol"].str.strip())
divs = divs[divs["symbol"].isin(universe)]
print(f"After restricting to NIFTY-750 universe: {len(divs):,}")

# Load OHLCV per symbol on demand
_o_cache: dict[str, pd.DataFrame] = {}
def load_o(sym):
    if sym in _o_cache: return _o_cache[sym]
    p_ = ROOT/"ohlcv"/f"{sym}.csv"
    if not p_.exists(): _o_cache[sym]=None; return None
    d = pd.read_csv(p_)
    d["date"] = pd.to_datetime(d["date"])
    for c in ["adj_close","volume"]: d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["adj_close","volume"]).sort_values("date").reset_index(drop=True)
    _o_cache[sym] = d
    return d

# Build event-window metrics
rows = []
for _, r in divs.iterrows():
    sym = r["symbol"]; anchor = r["anchor_date"]
    d = load_o(sym)
    if d is None: continue
    arr = d["date"].values
    pos = arr.searchsorted(np.datetime64(anchor))
    if pos >= len(d) or pos == 0: continue
    ev_close = d["adj_close"].iat[pos]
    prev = d["adj_close"].iat[pos-1]
    if prev <= 0 or pd.isna(prev) or pd.isna(ev_close): continue
    rec = {"symbol":sym, "industry": INDUSTRY.get(sym,""),
           "anchor_date": d["date"].iat[pos].date(),
           "dividend_type": r["dividend_type"],
           "amount_rs": float(r["amount_rs"]),
           "reaction_close": float(ev_close),
           "dividend_yield_pct": float(r["amount_rs"]/ev_close*100),
           "event_day_price_chg_pct": (ev_close/prev - 1)*100}
    # vol ratio
    ev_vol = d["volume"].iat[pos]
    bv = d["volume"].iloc[max(0,pos-20):pos].mean()
    rec["event_day_volume_vs_prev20x"] = float(ev_vol/bv) if bv and bv>0 else np.nan
    # pre/post
    for w in PRE_W:
        s = pos-w
        if s < 0: rec[f"pre_{w}d_price_chg_pct"]=np.nan; continue
        sc = d["adj_close"].iat[s]
        rec[f"pre_{w}d_price_chg_pct"] = (prev/sc - 1)*100 if sc>0 else np.nan
    for w in POST_W:
        t = pos + w
        rec[f"post_{w}d_price_chg_pct"] = (d["adj_close"].iat[t]/ev_close - 1)*100 if t < len(d) else np.nan
    rows.append(rec)

df = pd.DataFrame(rows)
df["anchor_date"] = pd.to_datetime(df["anchor_date"])
df["year"] = df["anchor_date"].dt.year
print(f"\nFinal event rows: {len(df):,}")

# Yield buckets
def yb(y):
    if pd.isna(y): return "?"
    if y < 0.25: return "0_under_0.25%"
    if y < 0.5:  return "1_0.25-0.5%"
    if y < 1.0:  return "2_0.5-1%"
    if y < 2.0:  return "3_1-2%"
    if y < 3.0:  return "4_2-3%"
    if y < 5.0:  return "5_3-5%"
    return "6_above_5%"
df["yield_bucket"] = df["dividend_yield_pct"].apply(yb)

# Amount buckets
def ab(a):
    if pd.isna(a): return "?"
    if a < 1: return "1_<Rs1"
    if a < 2: return "2_Rs1-2"
    if a < 5: return "3_Rs2-5"
    if a < 10: return "4_Rs5-10"
    if a < 25: return "5_Rs10-25"
    if a < 100: return "6_Rs25-100"
    return "7_>=Rs100"
df["amount_bucket"] = df["amount_rs"].apply(ab)

df.to_csv(ROOT/"metrics"/"all_dividend_metrics_official.csv", index=False)

# ----- Reporting -----
p("="*100); p(f"DIVIDEND ANALYSIS BY YIELD — {len(df):,} events, {df['symbol'].nunique()} stocks"); p("="*100)
p(f"date range: {df['anchor_date'].min().date()} -> {df['anchor_date'].max().date()}")
p(f"\nDividend type distribution:")
p(df["dividend_type"].value_counts().to_string())

p(f"\nYield stats (%): median={df['dividend_yield_pct'].median():.2f}  "
  f"p25={df['dividend_yield_pct'].quantile(.25):.2f}  "
  f"p75={df['dividend_yield_pct'].quantile(.75):.2f}  "
  f"p90={df['dividend_yield_pct'].quantile(.9):.2f}")
p(f"Amount stats (Rs/share): median={df['amount_rs'].median():.2f}  "
  f"p25={df['amount_rs'].quantile(.25):.2f}  "
  f"p75={df['amount_rs'].quantile(.75):.2f}  "
  f"p90={df['amount_rs'].quantile(.9):.2f}")

# ---- 1. BY YIELD BUCKET ----
p("\n" + "="*100); p("PATTERN 1 — Price action grouped by DIVIDEND YIELD bucket"); p("="*100)
p(f"  {'bucket':<18}{'n':>7}{'event-day':>12}{'p7':>10}{'p21':>10}{'p45':>10}{'p60':>10}{'p45_hit':>10}")
for b in sorted(df["yield_bucket"].dropna().unique()):
    sub = df[df["yield_bucket"]==b]
    if len(sub)<30: continue
    p(f"  {b:<18}{len(sub):>7}{sub['event_day_price_chg_pct'].mean():>+11.2f}%"
      f"{sub['post_7d_price_chg_pct'].mean():>+9.2f}%"
      f"{sub['post_21d_price_chg_pct'].mean():>+9.2f}%"
      f"{sub['post_45d_price_chg_pct'].mean():>+9.2f}%"
      f"{sub['post_60d_price_chg_pct'].mean():>+9.2f}%"
      f"{(sub['post_45d_price_chg_pct']>0).mean():>9.1%}")

# ---- 2. BY DIVIDEND TYPE ----
p("\n" + "="*100); p("PATTERN 2 — Interim vs Final vs Special"); p("="*100)
p(f"  {'type':<12}{'n':>7}{'med_yield':>12}{'event-day':>12}{'p21':>10}{'p45':>10}{'p60':>10}{'p45_hit':>10}")
for t in sorted(df["dividend_type"].unique()):
    sub = df[df["dividend_type"]==t]
    if len(sub)<30: continue
    p(f"  {t:<12}{len(sub):>7}{sub['dividend_yield_pct'].median():>+11.2f}%"
      f"{sub['event_day_price_chg_pct'].mean():>+11.2f}%"
      f"{sub['post_21d_price_chg_pct'].mean():>+9.2f}%"
      f"{sub['post_45d_price_chg_pct'].mean():>+9.2f}%"
      f"{sub['post_60d_price_chg_pct'].mean():>+9.2f}%"
      f"{(sub['post_45d_price_chg_pct']>0).mean():>9.1%}")

# ---- 3. HIGH-YIELD (>=2%) deep dive across horizons ----
p("\n" + "="*100); p("PATTERN 3 — HIGH-YIELD (>=2%) dividends only"); p("="*100)
high = df[df["dividend_yield_pct"]>=2.0]
p(f"n={len(high):,}  median yield = {high['dividend_yield_pct'].median():.2f}%  "
  f"median amount = Rs.{high['amount_rs'].median():.2f}/share")
p(f"\n  {'horizon':>10}{'mean':>10}{'med':>10}{'std':>10}{'hit+':>10}")
for w in POST_W:
    s = high[f"post_{w}d_price_chg_pct"].dropna()
    if len(s)<30: continue
    p(f"  post-{w:>2}d  {s.mean():>+9.2f}%{s.median():>+9.2f}%{s.std():>9.2f}{(s>0).mean():>9.1%}")
# split by event-day direction
p("\n  Same but split by event-day direction (PEAD for high-yield):")
p(f"  {'horizon':>10}{'UP mean':>11}{'UP hit':>9}{'DN mean':>11}{'DN hit':>9}{'gap':>10}")
for w in POST_W:
    u = high.loc[high["event_day_price_chg_pct"]>0, f"post_{w}d_price_chg_pct"].dropna()
    d_ = high.loc[high["event_day_price_chg_pct"]<0, f"post_{w}d_price_chg_pct"].dropna()
    if len(u)<10 or len(d_)<10: continue
    p(f"  post-{w:>2}d  {u.mean():>+10.2f}%{(u>0).mean():>8.1%}"
      f"{d_.mean():>+10.2f}%{(d_>0).mean():>8.1%}{(u.mean()-d_.mean()):>+9.2f}%")

# ---- 4. LOW-YIELD (<0.5%) for contrast ----
p("\n" + "="*100); p("PATTERN 4 — LOW-YIELD (<0.5%) dividends for contrast"); p("="*100)
low = df[df["dividend_yield_pct"]<0.5]
p(f"n={len(low):,}  median yield = {low['dividend_yield_pct'].median():.2f}%  "
  f"median amount = Rs.{low['amount_rs'].median():.2f}/share")
p(f"\n  {'horizon':>10}{'mean':>10}{'med':>10}{'hit+':>10}")
for w in POST_W:
    s = low[f"post_{w}d_price_chg_pct"].dropna()
    if len(s)<30: continue
    p(f"  post-{w:>2}d  {s.mean():>+9.2f}%{s.median():>+9.2f}%{(s>0).mean():>9.1%}")

# ---- 5. By Year ----
p("\n" + "="*100); p("PATTERN 5 — High-yield (>=2%) by year"); p("="*100)
y = (high.groupby("year")
     .agg(n=("symbol","size"),
          ed=("event_day_price_chg_pct","mean"),
          p21=("post_21d_price_chg_pct","mean"),
          p45=("post_45d_price_chg_pct","mean"),
          p60=("post_60d_price_chg_pct","mean"),
          p45_hit=("post_45d_price_chg_pct", lambda s:(s>0).mean()))
     .round(2))
p(y.to_string())

# ---- 6. By Industry ----
p("\n" + "="*100); p("PATTERN 6 — High-yield (>=2%) by industry"); p("="*100)
ind = (high.groupby("industry")
       .agg(n=("symbol","size"),
            med_yield=("dividend_yield_pct","median"),
            ed=("event_day_price_chg_pct","mean"),
            p21=("post_21d_price_chg_pct","mean"),
            p45=("post_45d_price_chg_pct","mean"),
            p60=("post_60d_price_chg_pct","mean"),
            p45_hit=("post_45d_price_chg_pct", lambda s:(s>0).mean()))
       .round(2))
ind = ind[ind["n"]>=30].sort_values("p45", ascending=False)
p(ind.to_string())

# ---- 7. Bear regime cut ----
p("\n" + "="*100); p("PATTERN 7 — Yield-bucketed patterns in CURRENT BEAR (2025-26)"); p("="*100)
cb = df[df["anchor_date"]>=pd.Timestamp("2025-01-01")]
p(f"Total events in bear: {len(cb):,}")
p(f"\n  {'bucket':<18}{'n':>7}{'event-day':>12}{'p21':>10}{'p45':>10}{'p60':>10}{'p45_hit':>10}")
for b in sorted(cb["yield_bucket"].dropna().unique()):
    sub = cb[cb["yield_bucket"]==b]
    if len(sub)<10: continue
    p(f"  {b:<18}{len(sub):>7}{sub['event_day_price_chg_pct'].mean():>+11.2f}%"
      f"{sub['post_21d_price_chg_pct'].mean():>+9.2f}%"
      f"{sub['post_45d_price_chg_pct'].mean():>+9.2f}%"
      f"{sub['post_60d_price_chg_pct'].mean():>+9.2f}%"
      f"{(sub['post_45d_price_chg_pct']>0).mean():>9.1%}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"\nReport: {OUT}")
print(f"Metrics CSV: {ROOT}\\metrics\\all_dividend_metrics_official.csv")

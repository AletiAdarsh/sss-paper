"""Identify earnings dates from OHLCV using a domain-specific heuristic:

Every Indian listed company must announce quarterly results within fixed
windows per SEBI LODR Reg 33:
  Q1 (Jun-end)  -> announced Jul 15 to Aug 14
  Q2 (Sep-end)  -> announced Oct 15 to Nov 14
  Q3 (Dec-end)  -> announced Jan 15 to Feb 14
  Q4 (Mar-end)  -> announced Apr 15 to May 30  (audited, 60-day window)

Inside each window, the earnings day is the trading day with the
highest volume / 20-day-prior-avg ratio AND a vol_spike >= 1.5x.
Quarterly results are typically the single biggest volume event in the
window (mandatory disclosure + analyst reactions).

Outputs:
  data/earnings_dates.csv with columns: symbol, year, quarter, earnings_date,
                                        volume_ratio, abs_price_move_pct
"""
from __future__ import annotations
import pandas as pd
from pathlib import Path

ROOT  = Path(r"C:\Users\adars\sss\data")
O_DIR = ROOT / "ohlcv"
OUT   = ROOT / "earnings_dates.csv"

# (quarter_label, start_month, start_day, end_month, end_day)
WINDOWS = [
    ("Q1", 7, 15, 8, 14),
    ("Q2", 10, 15, 11, 14),
    ("Q3", 1, 15, 2, 14),
    ("Q4", 4, 15, 5, 30),
]

def find_dates(symbol: str) -> list[dict]:
    p = O_DIR / f"{symbol}.csv"
    if not p.exists(): return []
    d = pd.read_csv(p)
    if "date" not in d.columns: return []
    d["date"] = pd.to_datetime(d["date"])
    d["adj_close"] = pd.to_numeric(d["adj_close"], errors="coerce")
    d["close"]     = pd.to_numeric(d["close"], errors="coerce")
    d["volume"]    = pd.to_numeric(d["volume"], errors="coerce")
    d = d.dropna(subset=["adj_close","volume"]).sort_values("date").reset_index(drop=True)
    d["vol_avg20"] = d["volume"].rolling(20).mean().shift(1)
    d["vol_ratio"] = d["volume"] / d["vol_avg20"]
    d["ret_pct"]   = d["adj_close"].pct_change() * 100.0

    out = []
    years = range(d["date"].dt.year.min(), d["date"].dt.year.max()+1)
    for y in years:
        for q, sm, sd, em, ed_ in WINDOWS:
            # Q3 spans Jan-Feb of fiscal-following calendar year — keep simple:
            # use calendar-year buckets. (Q3 of FY23 = Jan-Feb 2023)
            start = pd.Timestamp(year=y, month=sm, day=sd)
            end   = pd.Timestamp(year=y, month=em, day=ed_)
            mask = (d["date"] >= start) & (d["date"] <= end)
            sub = d[mask]
            if len(sub) == 0: continue
            sub = sub[sub["vol_ratio"] >= 1.5]
            if len(sub) == 0: continue
            best = sub.loc[sub["vol_ratio"].idxmax()]
            out.append({"symbol": symbol, "year": y, "quarter": q,
                        "earnings_date": best["date"].date(),
                        "volume_ratio": round(best["vol_ratio"], 2),
                        "abs_price_move_pct": round(abs(best["ret_pct"]), 2)})
    return out

def main():
    import csv
    consts = list(csv.DictReader(open(ROOT/"nifty_total_market_constituents.csv", encoding="utf-8")))
    rows = []
    for i, c in enumerate(consts, 1):
        sym = c["Symbol"].strip()
        rows.extend(find_dates(sym))
        if i % 100 == 0: print(f"  scanned {i}/{len(consts)}  events={len(rows)}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)
    print(f"\n{len(df):,} probable earnings dates across {df['symbol'].nunique()} symbols")
    print(f"By quarter:\n{df['quarter'].value_counts().to_string()}")
    print(f"Wrote: {OUT}")

if __name__ == "__main__": main()

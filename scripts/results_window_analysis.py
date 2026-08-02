"""Same windowed-return analysis as dividends, but for RESULTS announcements.
- Source: data/filings/*.csv where event_type='earnings_results'
- Dedupe: at most one event per (symbol, 80-day window) — keep earliest per quarter
- Anchor at event_datetime
- Output: data/results_event_returns.csv
"""
import glob, sys
import pandas as pd
import numpy as np
from pathlib import Path

ROOT  = Path(r"C:\Users\adars\sss\data")
OUT_E = ROOT/"results_event_returns.csv"
OFFSETS = [-10,-7,-5,-3,-1, 0, 1,3,5,7,10,14,21,30,45,60]

_OHLCV = {}
def ohlcv(sym):
    if sym in _OHLCV: return _OHLCV[sym]
    p = ROOT/"ohlcv"/f"{sym}.csv"
    if not p.exists():
        _OHLCV[sym] = None; return None
    o = pd.read_csv(p)
    o["date"] = pd.to_datetime(o["date"])
    o["adj_close"] = pd.to_numeric(o["adj_close"], errors="coerce")
    o = o.dropna(subset=["adj_close"]).sort_values("date").reset_index(drop=True)
    _OHLCV[sym] = o
    return o

def trading_close(sym, target_date, offset_td):
    o = ohlcv(sym)
    if o is None or not len(o): return np.nan
    t = pd.Timestamp(target_date).normalize()
    if t < o["date"].iloc[0] or t > o["date"].iloc[-1]: return np.nan
    idx = int(o["date"].searchsorted(t))
    if idx >= len(o): return np.nan
    tgt = idx + offset_td
    if tgt < 0 or tgt >= len(o): return np.nan
    return float(o.iloc[tgt]["adj_close"])

def main():
    # 1) Build results event list with quarter-level dedupe
    print("Loading filings...", flush=True)
    events = []
    files = list(glob.glob(str(ROOT/"filings"/"*.csv")))
    for i, f in enumerate(files, 1):
        df = pd.read_csv(f)
        if not len(df): continue
        df = df[df["event_type"]=="earnings_results"].copy()
        if not len(df): continue
        df["event_datetime"] = pd.to_datetime(df["event_datetime"], errors="coerce")
        df = df.dropna(subset=["event_datetime"]).sort_values("event_datetime")
        # Dedupe: keep earliest event per 80-day window
        last_dt = None
        for _, r in df.iterrows():
            if last_dt is None or (r["event_datetime"]-last_dt).days > 80:
                events.append({"symbol":r["symbol"], "event_dt":r["event_datetime"],
                               "headline":r.get("headline","")[:100]})
                last_dt = r["event_datetime"]
        if i % 200 == 0: print(f"  {i}/{len(files)}", flush=True)
    e = pd.DataFrame(events)
    print(f"Deduped results events: {len(e):,}")

    # Industry
    consts = pd.read_csv(ROOT/"nifty_total_market_constituents.csv")
    consts.columns = [c.strip() for c in consts.columns]
    ind = dict(zip(consts["Symbol"].str.strip(), consts["Industry"].fillna("")))
    e["industry"] = e["symbol"].map(ind).fillna("")

    # 2) Compute returns
    print("Computing windowed returns...", flush=True)
    rows = []
    for i, r in e.iterrows():
        sym = r["symbol"]; dt = r["event_dt"]
        c0 = trading_close(sym, dt, 0)
        if pd.isna(c0) or c0 <= 0: continue
        rec = {"symbol":sym, "industry":r["industry"], "event_dt":dt,
               "close_at_event":c0}
        for off in OFFSETS:
            c = trading_close(sym, dt, off)
            rec[f"ret_{off:+d}"] = (c/c0 - 1)*100 if pd.notna(c) else np.nan
        rows.append(rec)
        if (i+1) % 5000 == 0:
            print(f"  {i+1}/{len(e)}", flush=True)
    er = pd.DataFrame(rows)
    er.to_csv(OUT_E, index=False)
    print(f"Saved: {OUT_E}  ({len(er):,} events)")

if __name__ == "__main__":
    main()

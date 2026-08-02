"""Same as dividend_window_analysis.py but expanded to ALL 12,711 dividends.
- Match announcement date if any filing in [ex_date-60d, ex_date]; else anchor at ex_date.
- Skip only when no OHLCV available for the symbol.
- Output: data/dividend_event_returns_all.csv
"""
from __future__ import annotations
import glob, re
import pandas as pd
import numpy as np
from pathlib import Path

ROOT  = Path(r"C:\Users\adars\sss\data")
OUT_E = ROOT/"dividend_event_returns_all.csv"
OUT_A = ROOT/"dividend_window_aggregates_all.csv"
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
    div = pd.read_csv(ROOT/"dividends_official.csv")
    div["ex_date"] = pd.to_datetime(div["ex_date"], format="%d-%b-%Y", errors="coerce")
    div = div.dropna(subset=["ex_date"]).copy()
    p_re = re.compile(r"\bRe\.?\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
    def reparse(row):
        if pd.notna(row["amount_rs"]) and row["amount_rs"]>0: return row["amount_rs"]
        m = p_re.search(str(row["subject"]))
        return float(m.group(1)) if m else np.nan
    div["amount_rs"] = div.apply(reparse, axis=1)
    print(f"Total dividend rows (valid ex_date): {len(div):,}")

    # Load filings
    print("Loading filings...", flush=True)
    all_filings = []
    for f in glob.glob(str(ROOT/"dividend_filings"/"*.csv")):
        df = pd.read_csv(f)
        if len(df):
            df["event_datetime"] = pd.to_datetime(df["event_datetime"], errors="coerce")
            all_filings.append(df[["symbol","event_datetime"]])
    filings = pd.concat(all_filings, ignore_index=True).dropna(subset=["event_datetime"]).sort_values("event_datetime")
    by_sym = dict(tuple(filings.groupby("symbol")))

    # Build events
    events = []
    have_ohlcv = no_ohlcv = ann_anchored = ex_anchored = 0
    for _, r in div.iterrows():
        sym = r["symbol"]; ex = r["ex_date"]
        if ohlcv(sym) is None:
            no_ohlcv += 1; continue
        have_ohlcv += 1
        anchor_type = "ex_date"; anchor = ex
        if sym in by_sym:
            ff = by_sym[sym]
            win = ff[(ff["event_datetime"]>=ex-pd.Timedelta(days=60)) & (ff["event_datetime"]<=ex)]
            if len(win):
                anchor = win.iloc[0]["event_datetime"]
                anchor_type = "announce"
                ann_anchored += 1
        if anchor_type == "ex_date": ex_anchored += 1
        events.append({"symbol":sym, "anchor":anchor, "anchor_type":anchor_type,
                       "ex_date":ex, "amount_rs":r["amount_rs"], "dividend_type":r["dividend_type"],
                       "subject":r["subject"]})
    e = pd.DataFrame(events)
    print(f"Events: {len(e):,}   ann-anchored: {ann_anchored:,}   ex-anchored: {ex_anchored:,}   skipped (no ohlcv): {no_ohlcv:,}")

    # Industry
    consts = pd.read_csv(ROOT/"nifty_total_market_constituents.csv")
    consts.columns = [c.strip() for c in consts.columns]
    ind = dict(zip(consts["Symbol"].str.strip(), consts["Industry"].fillna("")))
    e["industry"] = e["symbol"].map(ind).fillna("")

    # Compute returns
    print("Computing windowed returns...", flush=True)
    rows = []
    for i, r in e.iterrows():
        sym = r["symbol"]; ann = r["anchor"]
        c0 = trading_close(sym, ann, 0)
        if pd.isna(c0) or c0 <= 0: continue
        rec = {"symbol":sym, "industry":r["industry"], "anchor_dt":pd.Timestamp(ann).date(),
               "anchor_type":r["anchor_type"], "ex_date":r["ex_date"].date(),
               "amount_rs":r["amount_rs"], "dividend_type":r["dividend_type"],
               "close_at_anchor":c0,
               "yield_pct": (r["amount_rs"]/c0*100) if pd.notna(r["amount_rs"]) else np.nan}
        for off in OFFSETS:
            c = trading_close(sym, ann, off)
            rec[f"ret_{off:+d}"] = (c/c0 - 1)*100 if pd.notna(c) else np.nan
        rows.append(rec)
        if (i+1) % 1500 == 0:
            print(f"  {i+1}/{len(e)}", flush=True)
    er = pd.DataFrame(rows)
    er.to_csv(OUT_E, index=False)
    print(f"Saved: {OUT_E}  ({len(er):,} events)")
    return er

if __name__ == "__main__":
    main()

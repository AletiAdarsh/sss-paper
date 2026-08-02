"""Build event-window metrics for every quarterly-results event in every stock.

For each (symbol, earnings event_date):
  - pre  windows: 1/3/5/7/14/21/30/45/60d -> price chg %, vol avg, vol/prior20x
  - event-day:    price chg vs prev close, volume / prev-20d avg
  - post windows: 1/3/5/7/14/21/30/45/60d -> price chg % from event-day close

Inputs:
  data/filings/<SYMBOL>.csv   (earnings_results only)
  data/ohlcv/<SYMBOL>.csv     (Yahoo daily OHLCV)

Output:
  data/metrics/all_event_metrics.csv     (one row per filing event)
  data/metrics/coverage_summary.csv      (per-symbol counts)
"""
from __future__ import annotations
import csv
import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT     = Path(r"C:\Users\adars\sss\data")
F_DIR    = ROOT / "filings"
O_DIR    = ROOT / "ohlcv"
M_DIR    = ROOT / "metrics"
M_DIR.mkdir(parents=True, exist_ok=True)

PRE_W  = [1, 3, 5, 7, 14, 21, 30, 45, 60]
POST_W = [1, 3, 5, 7, 14, 21, 30, 45, 60]

def load_ohlcv(symbol: str) -> pd.DataFrame | None:
    p = O_DIR / f"{symbol}.csv"
    if not p.exists() or p.stat().st_size < 200: return None
    d = pd.read_csv(p)
    if "date" not in d.columns or "adj_close" not in d.columns: return None
    d["date"] = pd.to_datetime(d["date"])
    for c in ["open","high","low","close","adj_close","volume"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.sort_values("date").reset_index(drop=True)
    d = d.dropna(subset=["adj_close"])
    return d

def metrics_for_event(ohlcv: pd.DataFrame, event_dt: pd.Timestamp) -> dict | None:
    """Compute pre/event/post metrics. Uses next trading day on/after event_dt."""
    arr = ohlcv["date"]
    pos = arr.searchsorted(event_dt)
    if pos >= len(arr) or pos == 0: return None
    ev_close = ohlcv["adj_close"].iloc[pos]
    prev_close = ohlcv["adj_close"].iloc[pos-1]
    ev_vol = ohlcv["volume"].iloc[pos]
    if prev_close <= 0 or pd.isna(prev_close) or pd.isna(ev_close): return None

    out = {"reaction_date": ohlcv["date"].iloc[pos].date(),
           "reaction_idx": int(pos),
           "reaction_close": float(ev_close),
           "event_day_price_chg_pct": (ev_close/prev_close - 1) * 100.0}
    # event-day volume vs prior 20d
    base_start = max(0, pos-20)
    base_vol = ohlcv["volume"].iloc[base_start:pos].mean()
    out["event_day_volume_vs_prev20x"] = float(ev_vol/base_vol) if base_vol and base_vol>0 else np.nan

    # pre windows
    for w in PRE_W:
        start = pos - w
        end   = pos - 1
        if start < 0:
            out[f"pre_{w}d_price_chg_pct"] = np.nan
            out[f"pre_{w}d_volume_vs_prior20x"] = np.nan
            continue
        start_close = ohlcv["adj_close"].iloc[start]
        if start_close <= 0 or pd.isna(start_close):
            out[f"pre_{w}d_price_chg_pct"] = np.nan
        else:
            out[f"pre_{w}d_price_chg_pct"] = (prev_close/start_close - 1) * 100.0
        win_vol = ohlcv["volume"].iloc[start:end+1].mean()
        prior_start = max(0, start-20); prior_end = start
        prior_vol = ohlcv["volume"].iloc[prior_start:prior_end].mean() if prior_end > prior_start else np.nan
        out[f"pre_{w}d_volume_vs_prior20x"] = float(win_vol/prior_vol) if prior_vol and prior_vol>0 else np.nan

    # post windows
    for w in POST_W:
        tgt = pos + w
        if tgt >= len(ohlcv):
            out[f"post_{w}d_price_chg_pct"] = np.nan; continue
        out[f"post_{w}d_price_chg_pct"] = (ohlcv["adj_close"].iloc[tgt]/ev_close - 1) * 100.0
    return out

def main():
    consts = pd.read_csv(ROOT/"nifty_total_market_constituents.csv")
    consts.columns = [c.strip() for c in consts.columns]
    rows = []
    cover = []
    n_done = 0
    for _, c in consts.iterrows():
        sym = str(c["Symbol"]).strip()
        ohlcv = load_ohlcv(sym)
        f = F_DIR / f"{sym}.csv"
        if ohlcv is None or not f.exists() or f.stat().st_size < 200:
            cover.append({"symbol":sym,"industry":c.get("Industry",""),
                          "ohlcv_rows":0 if ohlcv is None else len(ohlcv),
                          "earnings_events":0, "metrics_rows":0})
            continue
        ev = pd.read_csv(f)
        ev["event_date"] = pd.to_datetime(ev["event_date"], errors="coerce")
        # de-dupe by date (some quarters have multiple filings on same day)
        ev = ev.dropna(subset=["event_date"]).drop_duplicates(subset=["event_date","headline"])
        nev = len(ev)
        nm = 0
        for _, e in ev.iterrows():
            m = metrics_for_event(ohlcv, e["event_date"])
            if m is None: continue
            m.update({"symbol": sym,
                      "industry": c.get("Industry",""),
                      "company_name": c.get("Company Name",""),
                      "isin": c.get("ISIN Code",""),
                      "filing_date": e["event_date"].date(),
                      "headline": str(e.get("headline",""))[:200],
                      "raw_category": str(e.get("raw_category",""))[:80]})
            rows.append(m); nm += 1
        cover.append({"symbol":sym,"industry":c.get("Industry",""),
                      "ohlcv_rows":len(ohlcv),"earnings_events":nev,"metrics_rows":nm})
        n_done += 1
        if n_done % 50 == 0:
            print(f"  processed {n_done} symbols ... metrics rows so far={len(rows)}")

    df = pd.DataFrame(rows)
    # reorder columns
    front = ["symbol","industry","company_name","filing_date","reaction_date",
             "event_day_price_chg_pct","event_day_volume_vs_prev20x"]
    rest = [c for c in df.columns if c not in front]
    df = df[front + rest]
    out = M_DIR / "all_event_metrics.csv"
    df.to_csv(out, index=False)
    pd.DataFrame(cover).to_csv(M_DIR/"coverage_summary.csv", index=False)
    print(f"\nWrote {len(df):,} events from {n_done} symbols -> {out}")
    print(f"Coverage summary -> {M_DIR/'coverage_summary.csv'}")

if __name__ == "__main__":
    main()

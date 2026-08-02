"""For every NIFTY-750 dividend in last 10y, compute pre/post returns around the
ANNOUNCEMENT date at windows: -10,-7,-5,-3,-1,0,+1,+3,+5,+7,+10,+14,+21,+30,+45,+60 trading days.

Inputs:
  data/dividend_filings/{SYMBOL}.csv   (event_datetime = announcement broadcast time)
  data/dividends_official.csv          (amount_rs, ex_date)
  data/ohlcv/{SYMBOL}.csv              (daily OHLCV)

Outputs:
  data/dividend_event_returns.csv      (one row per event with returns at each offset)
  data/dividend_window_aggregates.csv  (mean/median/n at each offset, overall and by buckets)

Plus a printed SBIN deep-dive and summary.
"""
from __future__ import annotations
import glob, sys, re, json
import pandas as pd
import numpy as np
from pathlib import Path

ROOT  = Path(r"C:\Users\adars\sss\data")
OUT_E = ROOT/"dividend_event_returns.csv"
OUT_A = ROOT/"dividend_window_aggregates.csv"

OFFSETS = [-10,-7,-5,-3,-1, 0, 1,3,5,7,10,14,21,30,45,60]

# --- 1) Load + cache OHLCV per symbol on demand ----------------------------
_OHLCV_CACHE = {}
def ohlcv(sym):
    if sym in _OHLCV_CACHE: return _OHLCV_CACHE[sym]
    p = ROOT/"ohlcv"/f"{sym}.csv"
    if not p.exists():
        _OHLCV_CACHE[sym] = None; return None
    o = pd.read_csv(p)
    o["date"] = pd.to_datetime(o["date"])
    o["adj_close"] = pd.to_numeric(o["adj_close"], errors="coerce")
    o = o.dropna(subset=["adj_close"]).sort_values("date").reset_index(drop=True)
    _OHLCV_CACHE[sym] = o
    return o

def trading_close(sym, target_date, offset_td):
    """Close on the trading day at index_of(target_date)+offset_td. Returns float or NaN."""
    o = ohlcv(sym)
    if o is None or not len(o): return np.nan
    t = pd.Timestamp(target_date).normalize()
    # Guard: target outside file's date range
    if t < o["date"].iloc[0] or t > o["date"].iloc[-1]: return np.nan
    idx = int(o["date"].searchsorted(t))
    if idx >= len(o): return np.nan
    tgt = idx + offset_td
    if tgt < 0 or tgt >= len(o): return np.nan
    return float(o.iloc[tgt]["adj_close"])

# --- 2) Build event list: one ANNOUNCEMENT per (symbol, dividend) ---------
def build_events():
    div = pd.read_csv(ROOT/"dividends_official.csv")
    div["ex_date"] = pd.to_datetime(div["ex_date"], format="%d-%b-%Y", errors="coerce")
    div = div.dropna(subset=["ex_date"]).copy()
    # Parse Re-amounts as fallback
    p_re = re.compile(r"\bRe\.?\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
    def reparse(row):
        if pd.notna(row["amount_rs"]) and row["amount_rs"]>0: return row["amount_rs"]
        m = p_re.search(str(row["subject"]))
        return float(m.group(1)) if m else np.nan
    div["amount_rs"] = div.apply(reparse, axis=1)

    # Load all filings to find earliest announcement <= ex_date for each dividend
    print(f"Loading dividend_filings...", flush=True)
    all_filings = []
    for f in glob.glob(str(ROOT/"dividend_filings"/"*.csv")):
        df = pd.read_csv(f)
        if len(df):
            df["event_datetime"] = pd.to_datetime(df["event_datetime"], errors="coerce")
            all_filings.append(df[["symbol","event_datetime","headline","description","raw_category"]])
    filings = pd.concat(all_filings, ignore_index=True).dropna(subset=["event_datetime"])
    filings = filings.sort_values("event_datetime")

    # For each (symbol, ex_date) in div, find earliest filing in [ex_date - 45d, ex_date]
    events = []
    print(f"Matching {len(div):,} dividend rows to announcements...", flush=True)
    by_sym = dict(tuple(filings.groupby("symbol")))
    for _, r in div.iterrows():
        sym = r["symbol"]; ex = r["ex_date"]
        if sym not in by_sym: continue
        ff = by_sym[sym]
        win = ff[(ff["event_datetime"]>=ex-pd.Timedelta(days=45)) & (ff["event_datetime"]<=ex)]
        if not len(win): continue
        ann = win.iloc[0]["event_datetime"]
        events.append({"symbol":sym, "announce_dt":ann, "ex_date":ex,
                       "amount_rs":r["amount_rs"], "dividend_type":r["dividend_type"],
                       "subject":r["subject"]})
    e = pd.DataFrame(events)
    print(f"Matched {len(e):,} announcement events", flush=True)
    return e

# --- 3) Compute returns at each offset --------------------------------------
def compute_returns(events):
    consts = pd.read_csv(ROOT/"nifty_total_market_constituents.csv")
    consts.columns = [c.strip() for c in consts.columns]
    ind = dict(zip(consts["Symbol"].str.strip(), consts["Industry"].fillna("")))

    rows = []
    for i, r in events.iterrows():
        sym = r["symbol"]; ann = r["announce_dt"]
        c0 = trading_close(sym, ann, 0)
        if pd.isna(c0) or c0 <= 0: continue
        rec = {"symbol":sym, "industry":ind.get(sym,""), "announce_dt":ann.date(),
               "ex_date": r["ex_date"].date(), "amount_rs":r["amount_rs"],
               "dividend_type":r["dividend_type"], "close_at_announce":c0,
               "yield_pct": (r["amount_rs"]/c0*100) if pd.notna(r["amount_rs"]) else np.nan}
        for off in OFFSETS:
            c = trading_close(sym, ann, off)
            rec[f"ret_{off:+d}"] = (c/c0 - 1)*100 if pd.notna(c) else np.nan
        rows.append(rec)
        if (i+1) % 1000 == 0:
            print(f"  {i+1}/{len(events)}", flush=True)
    return pd.DataFrame(rows)

# --- 4) Aggregates ---------------------------------------------------------
def aggregate(df):
    ret_cols = [f"ret_{o:+d}" for o in OFFSETS]
    out = []
    def add_group(name, sub):
        for c in ret_cols:
            s = sub[c].dropna()
            out.append({"group":name, "offset":c, "n":len(s),
                        "mean_pct": s.mean() if len(s) else np.nan,
                        "median_pct": s.median() if len(s) else np.nan,
                        "p25": s.quantile(0.25) if len(s) else np.nan,
                        "p75": s.quantile(0.75) if len(s) else np.nan,
                        "pct_positive": (s>0).mean()*100 if len(s) else np.nan})
    add_group("ALL", df)
    df_y = df.dropna(subset=["yield_pct"]).copy()
    df_y["yld_bucket"] = pd.cut(df_y["yield_pct"], [0,0.25,0.5,1,2,5,100],
                                labels=["<0.25","0.25-0.5","0.5-1","1-2","2-5",">5"])
    for b, sub in df_y.groupby("yld_bucket", observed=True):
        add_group(f"yield {b}%", sub)
    for t, sub in df.groupby("dividend_type"):
        if len(sub) >= 50: add_group(f"type={t}", sub)
    # Sector
    for ind, sub in df.groupby("industry"):
        if len(sub) >= 200: add_group(f"ind={ind}", sub)
    return pd.DataFrame(out)

# --- 5) SBIN deep-dive -----------------------------------------------------
def sbin_walkthrough(events_df):
    sb = events_df[events_df["symbol"]=="SBIN"].sort_values("announce_dt")
    print("\n=== SBIN — all announcement events found ===")
    print(sb[["announce_dt","ex_date","amount_rs","dividend_type"]].to_string(index=False))

def main():
    events = build_events()
    sbin_walkthrough(events)
    print("\nComputing windowed returns...", flush=True)
    er = compute_returns(events)
    er.to_csv(OUT_E, index=False)
    print(f"Saved per-event returns: {OUT_E}  ({len(er):,} events)", flush=True)

    # SBIN with returns
    sb = er[er["symbol"]=="SBIN"].sort_values("announce_dt")
    print("\n=== SBIN — windowed returns (% vs close@announce) ===")
    cols = ["announce_dt","amount_rs","yield_pct","close_at_announce"] + [f"ret_{o:+d}" for o in OFFSETS]
    pd.set_option("display.width", 260)
    pd.set_option("display.float_format", lambda x: f"{x:.2f}" if pd.notna(x) else "n/a")
    print(sb[cols].to_string(index=False))

    agg = aggregate(er)
    agg.to_csv(OUT_A, index=False)
    print(f"\nSaved aggregates: {OUT_A}")

    print("\n=== ALL EVENTS — mean / median % return relative to announcement close ===")
    a = agg[agg["group"]=="ALL"].copy()
    a["offset_n"] = a["offset"].str.extract(r"([-+]\d+)").astype(int)
    a = a.sort_values("offset_n")
    print(a[["offset","n","mean_pct","median_pct","pct_positive","p25","p75"]].to_string(index=False))

    print("\n=== BY YIELD BUCKET — mean % return at key offsets ===")
    key_offs = ["ret_-5","ret_-1","ret_+1","ret_+5","ret_+10","ret_+30","ret_+60"]
    pivot = agg[agg["group"].str.startswith("yield ")].pivot(index="group", columns="offset", values="mean_pct")
    pivot = pivot[[c for c in key_offs if c in pivot.columns]]
    print(pivot.to_string())

    print("\n=== BY DIVIDEND TYPE — mean % return at key offsets ===")
    pivot2 = agg[agg["group"].str.startswith("type=")].pivot(index="group", columns="offset", values="mean_pct")
    pivot2 = pivot2[[c for c in key_offs if c in pivot2.columns]]
    print(pivot2.to_string())

if __name__ == "__main__":
    main()

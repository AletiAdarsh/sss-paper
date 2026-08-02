"""Build event-window metrics from earnings_dates.csv + per-symbol OHLCV.
Reads earnings_dates.csv, computes pre/event/post windows. Outputs single CSV."""
from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(r"C:\Users\adars\sss\data")
O_DIR = ROOT / "ohlcv"
M_DIR = ROOT / "metrics"
M_DIR.mkdir(parents=True, exist_ok=True)

PRE_W  = [1, 3, 5, 7, 14, 21, 30, 45, 60]
POST_W = [1, 3, 5, 7, 14, 21, 30, 45, 60]

# load constituents for industry mapping
consts = pd.read_csv(ROOT/"nifty_total_market_constituents.csv")
consts.columns = [c.strip() for c in consts.columns]
INDUSTRY = dict(zip(consts["Symbol"].str.strip(), consts["Industry"].fillna("")))
CNAME    = dict(zip(consts["Symbol"].str.strip(), consts["Company Name"].fillna("")))

ed_df = pd.read_csv(ROOT/"earnings_dates.csv")
ed_df["earnings_date"] = pd.to_datetime(ed_df["earnings_date"])

# cache ohlcv per symbol
_cache: dict[str, pd.DataFrame] = {}

def load_o(sym: str):
    if sym in _cache: return _cache[sym]
    p = O_DIR / f"{sym}.csv"
    if not p.exists(): return None
    d = pd.read_csv(p)
    d["date"] = pd.to_datetime(d["date"])
    for c in ["adj_close","volume"]: d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["adj_close","volume"]).sort_values("date").reset_index(drop=True)
    _cache[sym] = d
    return d

def metrics(d, ev_date):
    arr = d["date"].values
    pos = arr.searchsorted(np.datetime64(ev_date))
    if pos >= len(d) or pos == 0: return None
    ev_close = d["adj_close"].iat[pos]
    prev_close = d["adj_close"].iat[pos-1]
    if prev_close <= 0 or pd.isna(prev_close) or pd.isna(ev_close): return None
    out = {"reaction_date": d["date"].iat[pos].date(),
           "event_day_price_chg_pct": (ev_close/prev_close - 1) * 100.0}
    ev_vol = d["volume"].iat[pos]
    base_vol = d["volume"].iloc[max(0,pos-20):pos].mean()
    out["event_day_volume_vs_prev20x"] = float(ev_vol/base_vol) if base_vol and base_vol>0 else np.nan
    for w in PRE_W:
        s_idx = pos - w
        if s_idx < 0:
            out[f"pre_{w}d_price_chg_pct"] = np.nan
            out[f"pre_{w}d_volume_vs_prior20x"] = np.nan; continue
        start_close = d["adj_close"].iat[s_idx]
        out[f"pre_{w}d_price_chg_pct"] = (prev_close/start_close - 1)*100.0 if start_close>0 else np.nan
        win_vol = d["volume"].iloc[s_idx:pos].mean()
        ps = max(0, s_idx-20)
        prior = d["volume"].iloc[ps:s_idx].mean() if s_idx > ps else np.nan
        out[f"pre_{w}d_volume_vs_prior20x"] = float(win_vol/prior) if prior and prior>0 else np.nan
    for w in POST_W:
        t = pos + w
        out[f"post_{w}d_price_chg_pct"] = (d["adj_close"].iat[t]/ev_close - 1)*100.0 if t < len(d) else np.nan
    return out

rows = []
for sym, g in ed_df.groupby("symbol"):
    d = load_o(sym)
    if d is None: continue
    for _, e in g.iterrows():
        m = metrics(d, e["earnings_date"])
        if m is None: continue
        m["symbol"] = sym
        m["industry"] = INDUSTRY.get(sym, "")
        m["company_name"] = CNAME.get(sym, "")
        m["year"] = e["year"]
        m["quarter"] = e["quarter"]
        m["filing_date"] = e["earnings_date"].date()
        m["volume_ratio_at_id"] = e.get("volume_ratio")
        rows.append(m)

df = pd.DataFrame(rows)
front = ["symbol","industry","company_name","year","quarter","filing_date",
         "reaction_date","event_day_price_chg_pct","event_day_volume_vs_prev20x"]
rest = [c for c in df.columns if c not in front]
df = df[front + rest]
out = M_DIR/"all_event_metrics.csv"
df.to_csv(out, index=False)
print(f"Wrote {len(df):,} events from {df['symbol'].nunique()} symbols -> {out}")

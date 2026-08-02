"""Build event-window metrics for every dividend announcement.

Multiple filings on the same date for the same symbol (e.g. "Dividend",
"Board Meeting Outcome", "Record Date" filings) are de-duplicated so each
dividend event appears once.

Output: data/metrics/all_dividend_metrics.csv
"""
from __future__ import annotations
import csv
from pathlib import Path
import pandas as pd
import numpy as np

ROOT   = Path(r"C:\Users\adars\sss\data")
O_DIR  = ROOT / "ohlcv"
F_DIR  = ROOT / "dividend_filings"
M_DIR  = ROOT / "metrics"
M_DIR.mkdir(parents=True, exist_ok=True)
OUT    = M_DIR / "all_dividend_metrics.csv"

PRE_W  = [1, 3, 5, 7, 14, 21, 30, 45, 60]
POST_W = [1, 3, 5, 7, 14, 21, 30, 45, 60]

consts = pd.read_csv(ROOT/"nifty_total_market_constituents.csv")
consts.columns = [c.strip() for c in consts.columns]
INDUSTRY = dict(zip(consts["Symbol"].str.strip(), consts["Industry"].fillna("")))
CNAME    = dict(zip(consts["Symbol"].str.strip(), consts["Company Name"].fillna("")))

_cache: dict[str, pd.DataFrame] = {}
def load_o(sym):
    if sym in _cache: return _cache[sym]
    p = O_DIR/f"{sym}.csv"
    if not p.exists(): return None
    d = pd.read_csv(p)
    if "date" not in d.columns: return None
    d["date"] = pd.to_datetime(d["date"])
    for c in ["adj_close","volume"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["adj_close","volume"]).sort_values("date").reset_index(drop=True)
    _cache[sym] = d
    return d

def metrics(d, ev_date):
    arr = d["date"].values
    pos = arr.searchsorted(np.datetime64(ev_date))
    if pos >= len(d) or pos == 0: return None
    ev_close = d["adj_close"].iat[pos]
    prev = d["adj_close"].iat[pos-1]
    if prev<=0 or pd.isna(prev) or pd.isna(ev_close): return None
    out = {"reaction_date": d["date"].iat[pos].date(),
           "event_day_price_chg_pct": (ev_close/prev - 1)*100}
    ev_vol = d["volume"].iat[pos]
    bv = d["volume"].iloc[max(0,pos-20):pos].mean()
    out["event_day_volume_vs_prev20x"] = float(ev_vol/bv) if bv and bv>0 else np.nan
    for w in PRE_W:
        s = pos - w
        if s < 0:
            out[f"pre_{w}d_price_chg_pct"] = np.nan
            out[f"pre_{w}d_volume_vs_prior20x"] = np.nan; continue
        sc = d["adj_close"].iat[s]
        out[f"pre_{w}d_price_chg_pct"] = (prev/sc - 1)*100 if sc>0 else np.nan
        wv = d["volume"].iloc[s:pos].mean()
        ps = max(0, s-20)
        pv = d["volume"].iloc[ps:s].mean() if s > ps else np.nan
        out[f"pre_{w}d_volume_vs_prior20x"] = float(wv/pv) if pv and pv>0 else np.nan
    for w in POST_W:
        t = pos + w
        out[f"post_{w}d_price_chg_pct"] = (d["adj_close"].iat[t]/ev_close - 1)*100 if t < len(d) else np.nan
    return out

rows = []
n_syms_with_data = 0
for _, c in consts.iterrows():
    sym = c["Symbol"].strip()
    o = load_o(sym)
    fp = F_DIR/f"{sym}.csv"
    if o is None or not fp.exists() or fp.stat().st_size < 200: continue
    ev = pd.read_csv(fp)
    if "event_date" not in ev.columns or len(ev)==0: continue
    ev["event_date"] = pd.to_datetime(ev["event_date"], errors="coerce")
    ev = ev.dropna(subset=["event_date"])
    # de-dupe to one row per (date) — first filing of day = announcement
    ev = ev.sort_values("event_datetime").drop_duplicates(subset=["event_date"], keep="first")
    if len(ev)==0: continue
    n_syms_with_data += 1
    for _, e in ev.iterrows():
        m = metrics(o, e["event_date"])
        if m is None: continue
        m.update({
            "symbol": sym, "industry": INDUSTRY.get(sym,""),
            "company_name": CNAME.get(sym,""),
            "filing_date": e["event_date"].date(),
            "headline": str(e.get("headline",""))[:200],
            "raw_category": str(e.get("raw_category",""))[:80],
        })
        rows.append(m)

df = pd.DataFrame(rows)
front = ["symbol","industry","company_name","filing_date","reaction_date",
         "event_day_price_chg_pct","event_day_volume_vs_prev20x"]
rest  = [c for c in df.columns if c not in front]
df = df[front + rest]
df.to_csv(OUT, index=False)
print(f"Wrote {len(df):,} dividend events from {n_syms_with_data} symbols -> {OUT}")

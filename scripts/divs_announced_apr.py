"""List dividends ANNOUNCED Apr 1 -> today, mapped to amount + OHLCV."""
import re, glob
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"C:\Users\adars\sss\data")
TODAY = pd.Timestamp("2026-07-09")
START = pd.Timestamp("2026-04-01")

# 1) Load all announcements
rows = []
for f in glob.glob(str(ROOT/"dividend_filings"/"*.csv")):
    df = pd.read_csv(f)
    if len(df): rows.append(df)
a = pd.concat(rows, ignore_index=True)
a["event_datetime"] = pd.to_datetime(a["event_datetime"], errors="coerce")
a = a[(a["event_datetime"]>=START) & (a["event_datetime"]<=TODAY+pd.Timedelta(days=1))].copy()

# Earliest announcement per symbol (first filing in the window = the declaration)
a = a.sort_values("event_datetime")
first = a.groupby("symbol", as_index=False).first()
first = first.rename(columns={"event_datetime":"announce_dt"})

# 2) Match to dividends_official.csv (amount + ex_date) by symbol with closest ex_date >= announce_dt
d = pd.read_csv(ROOT/"dividends_official.csv")
for c in ["ex_date","record_date"]:
    d[c] = pd.to_datetime(d[c], dayfirst=True, errors="coerce")

def best_match(row):
    sym = row["symbol"]; adt = row["announce_dt"]
    cand = d[(d["symbol"]==sym) & (d["ex_date"]>=adt-pd.Timedelta(days=2))]
    if not len(cand): return pd.Series([np.nan, pd.NaT, pd.NaT, np.nan, ""])
    cand = cand.assign(gap=(cand["ex_date"]-adt).abs()).sort_values("gap")
    r = cand.iloc[0]
    return pd.Series([r["amount_rs"], r["ex_date"], r["record_date"], r.get("dividend_type",""), r.get("subject","")])

first[["amount_rs","ex_date","record_date","dividend_type","subject"]] = first.apply(best_match, axis=1)

# Parse Re X if amount missing
p_re = re.compile(r"\bRe\.?\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
def reparse(row):
    if pd.notna(row["amount_rs"]) and row["amount_rs"]>0: return row["amount_rs"]
    s = str(row["subject"]) + " " + str(row.get("headline",""))
    m = p_re.search(s)
    return float(m.group(1)) if m else np.nan
first["amount_rs"] = first.apply(reparse, axis=1)

# 3) Industry / company name
consts = pd.read_csv(ROOT/"nifty_total_market_constituents.csv")
consts.columns = [c.strip() for c in consts.columns]
ind  = dict(zip(consts["Symbol"].str.strip(), consts["Industry"].fillna("")))
cn   = dict(zip(consts["Symbol"].str.strip(), consts["Company Name"].fillna("")))
first["industry"]     = first["symbol"].map(ind).fillna("(non-NIFTY750)")
first["company_name"] = first["symbol"].map(cn).fillna("")

# 4) OHLCV: close on announce date and close now
def get_close(sym, dt):
    p = ROOT/"ohlcv"/f"{sym}.csv"
    if not p.exists(): return np.nan
    o = pd.read_csv(p)
    o["date"] = pd.to_datetime(o["date"])
    o["adj_close"] = pd.to_numeric(o["adj_close"], errors="coerce")
    o = o.dropna(subset=["adj_close"])
    if not len(o): return np.nan
    # find <= dt
    ok = o[o["date"]<=dt]
    return float(ok.iloc[-1]["adj_close"]) if len(ok) else np.nan

def get_last(sym):
    p = ROOT/"ohlcv"/f"{sym}.csv"
    if not p.exists(): return np.nan, None
    o = pd.read_csv(p)
    o["date"] = pd.to_datetime(o["date"])
    o["adj_close"] = pd.to_numeric(o["adj_close"], errors="coerce")
    o = o.dropna(subset=["adj_close"])
    if not len(o): return np.nan, None
    last = o.iloc[-1]
    return float(last["adj_close"]), last["date"].date()

closes_ann, closes_now, dts_now = [], [], []
for _, r in first.iterrows():
    adt = r["announce_dt"]
    closes_ann.append(get_close(r["symbol"], adt))
    lp, ld = get_last(r["symbol"])
    closes_now.append(lp); dts_now.append(ld)
first["close_on_announce"] = closes_ann
first["close_now"]         = closes_now
first["close_now_date"]    = dts_now
first["dividend_yield_pct"]= (first["amount_rs"]/first["close_on_announce"])*100
first["chg_since_announce_pct"] = (first["close_now"]/first["close_on_announce"] - 1) * 100
first["days_since_announce"] = (TODAY - first["announce_dt"]).dt.days

out = first[["symbol","company_name","industry","dividend_type","amount_rs",
             "dividend_yield_pct","announce_dt","ex_date","record_date",
             "close_on_announce","close_now","close_now_date",
             "days_since_announce","chg_since_announce_pct","headline","subject"]].sort_values("announce_dt", ascending=False)
out.to_csv(ROOT/"divs_announced_apr.csv", index=False)
print(f"Total: {len(out)}  with amount: {out['amount_rs'].notna().sum()}\n")

disp = out.copy()
disp["announce_dt"] = disp["announce_dt"].dt.strftime("%Y-%m-%d")
disp["ex_date"] = disp["ex_date"].dt.strftime("%Y-%m-%d")
disp = disp[["symbol","industry","dividend_type","amount_rs","dividend_yield_pct",
             "announce_dt","ex_date","close_on_announce","close_now",
             "chg_since_announce_pct","days_since_announce"]]
disp.columns = ["Symbol","Industry","Type","Div Rs","Yield %","Announced",
                "Ex-Date","Close@Ann","Close Now","%Chg","Days"]
pd.set_option("display.max_rows", None)
pd.set_option("display.width", 240)
pd.set_option("display.float_format", lambda x: f"{x:.2f}" if pd.notna(x) else "n/a")
print(disp.to_string(index=False))
print(f"\nWrote: data/divs_announced_apr.csv")

"""List stocks that went ex-dividend in the past 7 days, with enriched data."""
import re
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"C:\Users\adars\sss\data")
TODAY = pd.Timestamp("2026-07-09")
WEEK  = pd.Timestamp("2026-04-01")

d = pd.read_csv(ROOT/"dividends_official.csv")
for c in ["ex_date","record_date","broadcast_date"]:
    d[c] = pd.to_datetime(d[c], dayfirst=True, errors="coerce")
sub = d[(d["ex_date"]>=WEEK) & (d["ex_date"]<=TODAY)].copy()
print(f"Total dividends in past week: {len(sub)}")

# Fix Re (paise) parsing — original parser only catches "Rs X", miss "Re 0.75"
p_re = re.compile(r"\bRe\.?\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
def reparse(row):
    if pd.notna(row["amount_rs"]) and row["amount_rs"] > 0: return row["amount_rs"]
    m = p_re.search(str(row["subject"]))
    if m:
        try: return float(m.group(1))
        except: pass
    return np.nan
sub["amount_rs"] = sub.apply(reparse, axis=1)

# Industry
consts = pd.read_csv(ROOT/"nifty_total_market_constituents.csv")
consts.columns = [c.strip() for c in consts.columns]
ind   = dict(zip(consts["Symbol"].str.strip(), consts["Industry"].fillna("")))
cname = dict(zip(consts["Symbol"].str.strip(), consts["Company Name"].fillna("")))
sub["industry"]     = sub["symbol"].map(ind).fillna("(non-NIFTY750)")
sub["company_name"] = sub["symbol"].map(cname).fillna("")

# Pull close on ex-date and most recent close from OHLCV
def get_price(sym, dt):
    p = ROOT/"ohlcv"/f"{sym}.csv"
    if not p.exists(): return np.nan
    o = pd.read_csv(p)
    o["date"] = pd.to_datetime(o["date"])
    o["adj_close"] = pd.to_numeric(o["adj_close"], errors="coerce")
    row = o.loc[o["date"]==dt, "adj_close"]
    return float(row.iloc[0]) if len(row) else np.nan

def get_last(sym):
    p = ROOT/"ohlcv"/f"{sym}.csv"
    if not p.exists(): return np.nan, None
    o = pd.read_csv(p)
    o["date"] = pd.to_datetime(o["date"])
    o["adj_close"] = pd.to_numeric(o["adj_close"], errors="coerce")
    last = o.dropna(subset=["adj_close"]).iloc[-1]
    return float(last["adj_close"]), last["date"].date()

prices_ex, prices_now, dates_now = [], [], []
for _, r in sub.iterrows():
    prices_ex.append(get_price(r["symbol"], r["ex_date"]))
    lp, ld = get_last(r["symbol"])
    prices_now.append(lp); dates_now.append(ld)
sub["close_on_ex"]   = prices_ex
sub["close_now"]     = prices_now
sub["close_now_date"]= dates_now
sub["days_since_ex"] = (TODAY - sub["ex_date"]).dt.days
sub["chg_since_ex_pct"] = (sub["close_now"]/sub["close_on_ex"] - 1) * 100.0
sub["dividend_yield_pct"] = (sub["amount_rs"] / sub["close_on_ex"]) * 100.0

# Final display
cols = ["symbol","company_name","industry","dividend_type","amount_rs",
        "dividend_yield_pct","ex_date","record_date","close_on_ex",
        "close_now","close_now_date","days_since_ex","chg_since_ex_pct","subject"]
out = sub[cols].sort_values("ex_date", ascending=False)
out.to_csv(ROOT/"divs_past_week.csv", index=False)
print("\nWrote: data/divs_past_week.csv\n")
# also print a friendlier view
display = out[["symbol","industry","dividend_type","amount_rs","dividend_yield_pct",
               "ex_date","close_on_ex","close_now","chg_since_ex_pct","days_since_ex"]]
display.columns = ["Symbol","Industry","Type","Div Rs","Yield %","Ex-Date",
                   "Close@Ex","Close Now","%Chg since Ex","Days since Ex"]
pd.set_option("display.max_rows", None)
pd.set_option("display.width", 220)
pd.set_option("display.float_format", lambda x: f"{x:.2f}" if pd.notna(x) else "n/a")
print(display.to_string(index=False))

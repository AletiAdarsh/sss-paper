"""Sector breakdown + backtest for RESULTS events (18,145 events, 10y)."""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"C:\Users\adars\sss\data")
e = pd.read_csv(ROOT/"results_event_returns.csv")
e["event_dt"] = pd.to_datetime(e["event_dt"])
e["year"] = e["event_dt"].dt.year

OFFSETS = [-10,-7,-5,-3,-1, 0, 1,3,5,7,10,14,21,30,45,60]
key_offs = ["ret_-5","ret_-1","ret_+1","ret_+5","ret_+10","ret_+30","ret_+45","ret_+60"]
pd.set_option("display.width", 260)
pd.set_option("display.float_format", lambda x: f"{x:.2f}" if pd.notna(x) else "n/a")

def stats(r, label):
    r = r.dropna()
    if not len(r): return None
    return {"label":label, "n":len(r), "mean":r.mean(), "median":r.median(),
            "std":r.std(), "win_pct":(r>0).mean()*100,
            "best":r.max(), "worst":r.min(),
            "sharpe":r.mean()/r.std() if r.std() else np.nan}

print(f"Total results events: {len(e):,}\n")

print("=== ALL EVENTS — mean / median % return ===")
hdr = [stats(e[f"ret_{o:+d}"], f"T{o:+d}") for o in OFFSETS]
print(pd.DataFrame([h for h in hdr if h]).to_string(index=False))

print("\n"+"="*100)
print("SECTOR BREAKDOWN (>=300 events, sorted by T+60)")
print("="*100)
sec = e[e["industry"]!=""].copy()
g = sec.groupby("industry")
summary = g[key_offs].mean()
summary["n"] = g.size()
summary["win60"] = (sec.assign(w=sec["ret_+60"]>0).groupby("industry")["w"].mean()*100)
summary = summary[summary["n"]>=300].sort_values("ret_+60", ascending=False)
print(summary.to_string())

print("\n"+"="*100)
print("BACKTEST — buy at results-event close, hold N days")
print("="*100)
print("\n--- Overall by holding period ---")
hp = [stats(e[f"ret_+{h}"], f"hold_{h}d") for h in [5,10,14,21,30,45,60]]
print(pd.DataFrame([h for h in hp if h]).to_string(index=False))

print("\n--- Year-by-year (hold 60d) ---")
yr_rows = [stats(sub["ret_+60"], yr) for yr, sub in e.groupby("year")]
print(pd.DataFrame([y for y in yr_rows if y]).to_string(index=False))

print("\n--- By sector (hold 60d, >=300 events) ---")
sb = []
for ind, sub in sec.groupby("industry"):
    if len(sub) >= 300:
        s = stats(sub["ret_+60"], ind)
        if s: sb.append(s)
print(pd.DataFrame(sb).sort_values("mean", ascending=False).to_string(index=False))

print("\n"+"="*100)
print("PORTFOLIO SIMULATION — $1000, 5%/trade, recycle cash, hold 60d")
print("="*100)
e2 = e.dropna(subset=["ret_+60"]).copy()
e2["exit_dt"] = e2["event_dt"] + pd.Timedelta(days=84)
e2_s = e2.sort_values("event_dt").reset_index(drop=True)

cash = 1000.0; positions = []; nav_hist = []
for _, t in e2_s.iterrows():
    matured = [p for p in positions if p[0] <= t["event_dt"]]
    for p in matured: cash += p[1]
    positions = [p for p in positions if p[0] > t["event_dt"]]
    nav = cash + sum(p[1] for p in positions)
    alloc = min(cash, nav*0.05)
    if alloc > 0.5:
        cash -= alloc
        positions.append((t["exit_dt"], alloc*(1+t["ret_+60"]/100)))
    nav_hist.append({"date":t["event_dt"], "nav":nav})
final = cash + sum(p[1] for p in positions)
nh = pd.DataFrame(nav_hist)
years = (e2_s["event_dt"].max()-e2_s["event_dt"].min()).days/365.25
cagr = (final/1000)**(1/years)-1
print(f"Starting:  $1,000")
print(f"Final NAV: ${final:,.2f}")
print(f"Span:      {years:.1f} years")
print(f"CAGR:      {cagr*100:.2f}%")
print(f"Trades:    {len(e2_s):,}")
nh["year"]=nh["date"].dt.year
print("\nNAV by year (last NAV per year):")
print(nh.groupby("year").last()[["nav"]].to_string())

# Variants
def sim(df, label, slot=0.05):
    df = df.dropna(subset=["ret_+60"]).sort_values("event_dt").reset_index(drop=True)
    df["exit_dt"] = df["event_dt"] + pd.Timedelta(days=84)
    cash = 1000.0; positions = []
    for _, t in df.iterrows():
        matured = [p for p in positions if p[0] <= t["event_dt"]]
        for p in matured: cash += p[1]
        positions = [p for p in positions if p[0] > t["event_dt"]]
        nav = cash + sum(p[1] for p in positions)
        alloc = min(cash, nav*slot)
        if alloc > 0.5:
            cash -= alloc
            positions.append((t["exit_dt"], alloc*(1+t["ret_+60"]/100)))
    final = cash + sum(p[1] for p in positions)
    yrs = (df["event_dt"].max()-df["event_dt"].min()).days/365.25
    return final, yrs, len(df)

print("\n--- Sector-filtered variants ---")
top_sectors_60d = summary.head(6).index.tolist()
for ind in top_sectors_60d:
    f, y, n = sim(sec[sec["industry"]==ind], ind, slot=0.10)
    print(f"  {ind:32s} trades={n:5d}  NAV=${f:8,.0f}  CAGR={((f/1000)**(1/y)-1)*100:6.2f}%")

print("\n--- All vs filtered events ---")
f, y, n = sim(e, "ALL"); print(f"  ALL events:            trades={n:5d}  NAV=${f:8,.0f}  CAGR={((f/1000)**(1/y)-1)*100:6.2f}%")
top_inds = set(summary.head(6).index)
f, y, n = sim(e[e["industry"].isin(top_inds)], "TOP6")
print(f"  Top-6 sectors only:    trades={n:5d}  NAV=${f:8,.0f}  CAGR={((f/1000)**(1/y)-1)*100:6.2f}%")

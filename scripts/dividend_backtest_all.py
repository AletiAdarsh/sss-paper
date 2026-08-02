"""Sector breakdown + backtest on the FULL panel of 6,342 events."""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"C:\Users\adars\sss\data")
e = pd.read_csv(ROOT/"dividend_event_returns_all.csv")
e["anchor_dt"] = pd.to_datetime(e["anchor_dt"])
e["year"] = e["anchor_dt"].dt.year

OFFSETS = [-10,-7,-5,-3,-1, 0, 1,3,5,7,10,14,21,30,45,60]
key_offs = ["ret_-5","ret_-1","ret_+1","ret_+5","ret_+10","ret_+30","ret_+45","ret_+60"]

pd.set_option("display.width", 260)
pd.set_option("display.float_format", lambda x: f"{x:.2f}" if pd.notna(x) else "n/a")

print(f"Total events: {len(e):,}")
print(f"  ann-anchored: {(e['anchor_type']=='announce').sum():,}")
print(f"  ex-anchored:  {(e['anchor_type']=='ex_date').sum():,}")

def stats(rets, label):
    r = rets.dropna()
    if not len(r): return None
    return {"label":label, "n":len(r), "mean":r.mean(), "median":r.median(),
            "std":r.std(), "win_pct":(r>0).mean()*100,
            "best":r.max(), "worst":r.min(),
            "sharpe":r.mean()/r.std() if r.std() else np.nan}

# ============ HEADLINE ALL OFFSETS ============
print("\n=== ALL EVENTS — mean / median % return ===")
hdr = []
for o in OFFSETS:
    s = stats(e[f"ret_{o:+d}"], f"T{o:+d}")
    if s: hdr.append(s)
print(pd.DataFrame(hdr).to_string(index=False))

# Same, split by anchor type
print("\n=== Split: announcement-anchored vs ex-date-anchored ===")
for at in ["announce","ex_date"]:
    sub = e[e["anchor_type"]==at]
    print(f"\n--- {at} (N={len(sub)}) ---")
    rows = []
    for o in [-5,-1,1,5,10,30,60]:
        s = stats(sub[f"ret_{o:+d}"], f"T{o:+d}")
        if s: rows.append(s)
    print(pd.DataFrame(rows).to_string(index=False))

# ============ SECTOR BREAKDOWN ============
print("\n"+"="*100)
print("SECTOR BREAKDOWN — mean % at key offsets, sectors with ≥100 events")
print("="*100)
sec = e[e["industry"] != ""].copy()
g = sec.groupby("industry")
summary = g[key_offs].mean()
summary["n"] = g.size()
summary["win60"] = (sec.assign(w=sec["ret_+60"]>0).groupby("industry")["w"].mean()*100)
summary = summary[summary["n"]>=100].sort_values("ret_+60", ascending=False)
print(summary.to_string())

# ============ BACKTEST ============
print("\n"+"="*100)
print("BACKTEST — buy at anchor close, hold N days")
print("="*100)
print("\n--- Overall by holding period ---")
hp = [stats(e[f"ret_+{h}"], f"hold_{h}d") for h in [5,10,14,21,30,45,60]]
print(pd.DataFrame([h for h in hp if h]).to_string(index=False))

print("\n--- Year-by-year (hold 60d) ---")
yr = [stats(sub["ret_+60"], yr) for yr, sub in e.groupby("year")]
print(pd.DataFrame([y for y in yr if y]).to_string(index=False))

print("\n--- By yield bucket (hold 60d) ---")
ey = e.dropna(subset=["yield_pct"]).copy()
ey["yb"] = pd.cut(ey["yield_pct"], [0,0.25,0.5,1,2,5,100],
                  labels=["<0.25","0.25-0.5","0.5-1","1-2","2-5",">5"])
print(pd.DataFrame([stats(sub["ret_+60"], f"yld_{b}") for b, sub in ey.groupby("yb", observed=True) if stats(sub["ret_+60"], "_")]).to_string(index=False))

print("\n--- By sector (hold 60d, ≥100 events) ---")
sb = []
for ind, sub in sec.groupby("industry"):
    if len(sub) >= 100:
        s = stats(sub["ret_+60"], ind)
        if s: sb.append(s)
print(pd.DataFrame(sb).sort_values("mean", ascending=False).to_string(index=False))

# ============ PORTFOLIO SIM ============
print("\n"+"="*100)
print("PORTFOLIO SIMULATION — $1000, 5% per trade, recycle cash, hold 60d")
print("="*100)
e2 = e.dropna(subset=["ret_+60"]).copy()
e2["exit_dt"] = e2["anchor_dt"] + pd.Timedelta(days=84)
e2_s = e2.sort_values("anchor_dt").reset_index(drop=True)

cash = 1000.0
positions = []
nav_hist = []
for _, t in e2_s.iterrows():
    matured = [p for p in positions if p[0] <= t["anchor_dt"]]
    for p in matured: cash += p[1]
    positions = [p for p in positions if p[0] > t["anchor_dt"]]
    nav = cash + sum(p[1] for p in positions)
    alloc = min(cash, nav*0.05)
    if alloc > 0.5:
        cash -= alloc
        positions.append((t["exit_dt"], alloc*(1+t["ret_+60"]/100)))
    nav_hist.append({"date":t["anchor_dt"], "nav":nav})

final = cash + sum(p[1] for p in positions)
nh = pd.DataFrame(nav_hist)
years = (e2_s["anchor_dt"].max()-e2_s["anchor_dt"].min()).days/365.25
cagr = (final/1000)**(1/years)-1
print(f"Starting:  $1,000")
print(f"Final NAV: ${final:.2f}")
print(f"Span:      {years:.1f} years")
print(f"CAGR:      {cagr*100:.2f}%")
print(f"Trades:    {len(e2_s):,}")

nh["year"] = nh["date"].dt.year
print("\nNAV by year (last NAV per year):")
print(nh.groupby("year").last()[["nav"]].to_string())

# Compare: ann-only vs ex-only sim
print("\n--- Split sim: announcement-anchored events only ---")
def sim(df, label):
    df = df.dropna(subset=["ret_+60"]).sort_values("anchor_dt").reset_index(drop=True)
    df["exit_dt"] = df["anchor_dt"] + pd.Timedelta(days=84)
    cash = 1000.0; positions = []
    for _, t in df.iterrows():
        matured = [p for p in positions if p[0] <= t["anchor_dt"]]
        for p in matured: cash += p[1]
        positions = [p for p in positions if p[0] > t["anchor_dt"]]
        nav = cash + sum(p[1] for p in positions)
        alloc = min(cash, nav*0.05)
        if alloc > 0.5:
            cash -= alloc
            positions.append((t["exit_dt"], alloc*(1+t["ret_+60"]/100)))
    final = cash + sum(p[1] for p in positions)
    yrs = (df["anchor_dt"].max()-df["anchor_dt"].min()).days/365.25
    print(f"  {label}: trades={len(df):,}  final=${final:,.0f}  CAGR={((final/1000)**(1/yrs)-1)*100:.2f}%")

sim(e2[e2["anchor_type"]=="announce"], "ann-only")
sim(e2[e2["anchor_type"]=="ex_date"],  "ex-only")
sim(e2[e2["yield_pct"]>=1],            "yield>=1%")
sim(e2[e2["yield_pct"]>=2],            "yield>=2%")

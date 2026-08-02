"""Sector breakdown + backtest of 'buy at announcement, hold N days' strategy."""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"C:\Users\adars\sss\data")
e = pd.read_csv(ROOT/"dividend_event_returns.csv")
e["announce_dt"] = pd.to_datetime(e["announce_dt"])
e["year"] = e["announce_dt"].dt.year

OFFSETS = [-10,-7,-5,-3,-1, 0, 1,3,5,7,10,14,21,30,45,60]
ret_cols = [f"ret_{o:+d}" for o in OFFSETS]
key_offs = ["ret_-5","ret_-1","ret_+1","ret_+5","ret_+10","ret_+30","ret_+45","ret_+60"]

pd.set_option("display.width", 260)
pd.set_option("display.float_format", lambda x: f"{x:.2f}" if pd.notna(x) else "n/a")

# ============= 1) SECTOR BREAKDOWN ==============================
print("="*100)
print("SECTOR BREAKDOWN — mean % return at each offset (sectors with >=80 events)")
print("="*100)
sectors = e[e["industry"] != ""].copy()
g = sectors.groupby("industry")
sec_summary = g[key_offs].mean()
sec_summary["n_events"] = g.size()
sec_summary["win_rate_60d"] = (sectors.assign(w=sectors["ret_+60"]>0).groupby("industry")["w"].mean()*100)
sec_summary = sec_summary[sec_summary["n_events"]>=80].sort_values("ret_+60", ascending=False)
print(sec_summary.to_string())

# ============= 2) BACKTEST ==============================
print("\n"+"="*100)
print("BACKTEST — buy at announcement close, hold N days, exit at close")
print("="*100)

def stats(rets, label):
    r = rets.dropna()
    if not len(r): return None
    return {
        "label": label,
        "n_trades": len(r),
        "mean_pct": r.mean(),
        "median_pct": r.median(),
        "std_pct": r.std(),
        "win_rate_pct": (r>0).mean()*100,
        "best_pct": r.max(),
        "worst_pct": r.min(),
        "sharpe_per_trade": r.mean()/r.std() if r.std() else np.nan,
    }

# Overall by holding period
print("\n--- Overall, by holding period ---")
hold_results = []
for h in [5,10,14,21,30,45,60]:
    s = stats(e[f"ret_+{h}"], f"hold_{h}d")
    if s: hold_results.append(s)
hp = pd.DataFrame(hold_results)
print(hp.to_string(index=False))

# Year by year (hold 60d)
print("\n--- Year-by-year (hold 60d) ---")
yr_rows = []
for yr, sub in e.groupby("year"):
    s = stats(sub["ret_+60"], f"{yr}")
    if s: yr_rows.append(s)
yr = pd.DataFrame(yr_rows)
print(yr.to_string(index=False))

# By yield bucket (hold 60d)
print("\n--- By yield bucket (hold 60d) ---")
e_y = e.dropna(subset=["yield_pct"]).copy()
e_y["yld_bucket"] = pd.cut(e_y["yield_pct"], [0,0.25,0.5,1,2,5,100],
                            labels=["<0.25","0.25-0.5","0.5-1","1-2","2-5",">5"])
yld_rows = []
for b, sub in e_y.groupby("yld_bucket", observed=True):
    s = stats(sub["ret_+60"], f"yld_{b}")
    if s: yld_rows.append(s)
print(pd.DataFrame(yld_rows).to_string(index=False))

# By sector (hold 60d)
print("\n--- By sector (hold 60d, >=80 events) ---")
sec_rows = []
for ind, sub in sectors.groupby("industry"):
    if len(sub) < 80: continue
    s = stats(sub["ret_+60"], ind)
    if s: sec_rows.append(s)
sec_bt = pd.DataFrame(sec_rows).sort_values("mean_pct", ascending=False)
print(sec_bt.to_string(index=False))

# ============= 3) PORTFOLIO SIMULATION ==============================
print("\n"+"="*100)
print("PORTFOLIO SIMULATION — equal allocation per trade, hold 60 days")
print("="*100)

# Approach: each event = $1 invested at announce, redeemed at T+60.
# Aggregate by EXIT year for an investor's PnL view.
e2 = e.dropna(subset=["ret_+60"]).copy()
e2["exit_dt"] = e2["announce_dt"] + pd.Timedelta(days=84)  # ~60 trading days ≈ 84 cal days
e2["exit_yr"] = e2["exit_dt"].dt.year

# Year-level PnL: assume $1 per trade equally distributed
print("\n--- Per-year P&L (assume $1 capital deployed per trade, exit year) ---")
yr_pnl = []
for yr, sub in e2.groupby("exit_yr"):
    capital_deployed = len(sub) * 1.0
    pnl = (sub["ret_+60"]/100).sum()
    yr_pnl.append({
        "exit_year": yr, "trades": len(sub),
        "capital_$": capital_deployed,
        "total_pnl_$": pnl,
        "return_on_deployed_pct": pnl/capital_deployed*100,
        "win_rate_pct": (sub["ret_+60"]>0).mean()*100,
    })
print(pd.DataFrame(yr_pnl).to_string(index=False))

# Realistic capital recycling: bucket capital, deploy only what's free
print("\n--- Capital-recycling simulation: fixed $1000 portfolio, equal-weight slots ---")
# Each trade holds for 60 cal days approx 84 cal days. Time-overlapping trades compete for slots.
# Simple cash sim: walk trades by announce date; deploy 10% of available cash to each, recover at exit.
e2_sorted = e2.sort_values("announce_dt").reset_index(drop=True)
cash = 1000.0
open_positions = []  # list of (exit_dt, value)
nav_history = []
for _, t in e2_sorted.iterrows():
    # Close out matured positions
    matured = [p for p in open_positions if p[0] <= t["announce_dt"]]
    for p in matured: cash += p[1]
    open_positions = [p for p in open_positions if p[0] > t["announce_dt"]]
    # Try to deploy: allocate up to 5% of NAV per trade
    nav = cash + sum(p[1] for p in open_positions)
    alloc = min(cash, nav*0.05)
    if alloc > 0.5:
        ret = t["ret_+60"]/100
        cash -= alloc
        open_positions.append((t["exit_dt"], alloc*(1+ret)))
    nav_history.append({"date": t["announce_dt"], "nav": nav, "cash": cash, "n_open": len(open_positions)})

# Close all remaining
final_nav = cash + sum(p[1] for p in open_positions)
nh = pd.DataFrame(nav_history)
print(f"Starting capital: $1000")
print(f"Final NAV (after all positions close at modeled exits): ${final_nav:.2f}")
years = (e2_sorted["announce_dt"].max() - e2_sorted["announce_dt"].min()).days / 365.25
cagr = (final_nav/1000)**(1/years) - 1
print(f"Span: {years:.1f} years   CAGR: {cagr*100:.2f}%")
print(f"Total trades: {len(e2_sorted)}")

# Yearly NAV snapshot
nh["year"] = nh["date"].dt.year
yr_nav = nh.groupby("year").last()[["nav","cash","n_open"]]
print("\nNAV by year (sampled at last trade of each year):")
print(yr_nav.to_string())

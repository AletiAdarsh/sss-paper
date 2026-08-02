"""Walk-forward, out-of-sample validation with RULE-BASED stock selection.

The honest test: at the start of each test quarter, rank candidate movers using
ONLY the prior 6 months of ORB results, pick the top-K, then trade those K FORWARD
into the unseen quarter. One position at a time (the <50k reality). Aggregate all
out-of-sample trades. If past rank predicts future performance, the edge is real.

Baseline for comparison: trade ALL candidates each quarter (no selection).
"""
import pandas as pd, numpy as np
from pathlib import Path
import orb_backtest as ob

ROOT = Path(r"C:\Users\adars\sss\data")
ob.SLIPPAGE = 0.0005
ob.TRAIL = True; ob.TRAIL_R = 1.0          # trailing variant from prior step

TRAIN_Q   = 2      # quarters of lookback for selection (=6 months)
TOP_K     = 5      # trade the top-K ranked movers each quarter
MIN_TR    = 8      # need >=8 in-sample trades to rank a stock
RISK_RS   = 500.0  # risk per trade for the equity curve (1% of 50k)

# ---- candidate pool: most LIQUID screened movers (slippage stays realistic) ----
movers = pd.read_csv(ROOT / "tradeable_movers.csv")
pool = movers[movers["turn_cr"] >= 40].sort_values("turn_cr", ascending=False)
SYMS = [s for s in pool["sym"].tolist() if "&" not in s][:30]
print(f"Candidate pool ({len(SYMS)} liquid movers): {', '.join(SYMS)}\n")

# ---- fetch + precompute each symbol's daily ORB trades ----
trades = {}
for s in SYMS:
    df = ob.fetch_symbol(s)
    if df.empty or len(df) < 1000:
        continue
    dfp = ob.prep(df)
    rows = []
    for day, dd in dfp.groupby("day"):
        t = ob.simulate_day(dd, 200000)
        if t:
            rows.append(t)
    if rows:
        tr = pd.DataFrame(rows)
        tr["day"] = pd.to_datetime(tr["day"])
        tr["rmult"] = tr["net"] / tr["R"]      # size-independent net (after costs)
        trades[s] = tr

alldays = pd.to_datetime(sorted({d for tr in trades.values() for d in tr["day"]}))
qs = pd.period_range(alldays.min(), alldays.max(), freq="Q")
print(f"Data spans {alldays.min().date()} .. {alldays.max().date()}  ({len(qs)} quarters)\n")


def one_position_per_day(cands, days_trades):
    """Given selected symbols and their trades in a window, keep only the FIRST
    signal each day (earliest entry time) -> models a single-position account."""
    frames = [days_trades[s].assign(sym=s) for s in cands if s in days_trades]
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True)
    d = d.sort_values(["day", "entry_hm"])
    return d.groupby("day", as_index=False).first()


def in_window(tr, q_start, q_end):
    return tr[(tr["day"] >= q_start) & (tr["day"] < q_end)]


def _max_streak(mask):
    """Longest run of True in a boolean Series."""
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


oos_sel, oos_all = [], []
per_q = []
for i in range(TRAIN_Q, len(qs)):
    test_q = qs[i]
    test_start = test_q.start_time
    test_end   = test_q.end_time
    train_start = qs[i - TRAIN_Q].start_time
    train_end   = test_start

    # rank candidates by in-sample mean R-multiple over the train window
    ranks = []
    for s, tr in trades.items():
        insamp = in_window(tr, train_start, train_end)
        if len(insamp) >= MIN_TR:
            ranks.append((s, insamp["rmult"].mean(), len(insamp)))
    if not ranks:
        continue
    ranks.sort(key=lambda x: x[1], reverse=True)
    selected = [r[0] for r in ranks[:TOP_K]]
    allcand  = [r[0] for r in ranks]

    # trade forward (out-of-sample), one position/day
    sel_fwd = one_position_per_day(selected, {s: in_window(trades[s], test_start, test_end) for s in selected})
    all_fwd = one_position_per_day(allcand,  {s: in_window(trades[s], test_start, test_end) for s in allcand})
    if not sel_fwd.empty:
        sel_fwd["q"] = str(test_q); oos_sel.append(sel_fwd)
    if not all_fwd.empty:
        all_fwd["q"] = str(test_q); oos_all.append(all_fwd)

    per_q.append({
        "quarter": str(test_q),
        "picks": ",".join(selected),
        "sel_n": len(sel_fwd), "sel_R": sel_fwd["rmult"].mean() if len(sel_fwd) else np.nan,
        "sel_win%": (sel_fwd["net"] > 0).mean() * 100 if len(sel_fwd) else np.nan,
        "all_R": all_fwd["rmult"].mean() if len(all_fwd) else np.nan,
    })

pd.set_option("display.width", 240)
pd.set_option("display.float_format", lambda x: f"{x:,.3f}" if abs(x) < 100 else f"{x:,.1f}")

print("=" * 120)
print("PER-QUARTER OUT-OF-SAMPLE (picks chosen from prior 6mo only, traded forward)")
print("=" * 120)
pq = pd.DataFrame(per_q)
print(pq.to_string(index=False))

sel = pd.concat(oos_sel, ignore_index=True)
alc = pd.concat(oos_all, ignore_index=True)

def report(name, d):
    net, r = d["net"], d["rmult"]
    win = net > 0
    # risk-sized equity on 50k: each trade risks RISK_RS, pnl = rmult * RISK_RS
    pnl = r * RISK_RS
    eq = 50000 + pnl.cumsum()
    peak = eq.cummax(); dd = (eq - peak)
    print(f"\n[{name}]  OOS trades={len(d):,}  win%={win.mean()*100:.1f}")
    print(f"   mean net R-multiple = {r.mean():.4f}   (>0 => edge persists out-of-sample)")
    print(f"   median R = {r.median():.4f}   std R = {r.std():.3f}")
    print(f"   risk-sized on 50k (risk Rs{RISK_RS:.0f}/trade): "
          f"final equity Rs{eq.iloc[-1]:,.0f}  ({(eq.iloc[-1]/50000-1)*100:+.1f}%), "
          f"max drawdown Rs{dd.min():,.0f} ({dd.min()/50000*100:+.1f}%)")

print("\n" + "=" * 120)
print("POOLED OUT-OF-SAMPLE RESULTS")
print("=" * 120)
report("SELECTED top-5 (the rule-based algo)", sel)
report("ALL candidates (no selection, baseline)", alc)

print("\nVERDICT:",
      "OOS EDGE PERSISTS -- selection carries forward" if sel["rmult"].mean() > 0
      else "OOS edge does NOT persist -- prior in-sample result was optimistic")
print("Does selection beat no-selection? sel R=%.4f vs all R=%.4f"
      % (sel["rmult"].mean(), alc["rmult"].mean()))

# ------------------------------------------------------------------ FULL STATS
print("\n" + "#" * 78)
print("# FULL STATS  --  the rule-based algo, out-of-sample (unseen data)")
print("#" * 78)
d = sel.copy()
n = len(d)
net = d["net"]                       # rupees on ~200k notional per trade
r   = d["rmult"]                     # net after costs, per rupee of risk
wins = d[net > 0]; losses = d[net < 0]; flat = d[net == 0]
gross = d["gross"]; cost = d["cost"]

print(f"\nTOTAL TRADES TAKEN (out-of-sample): {n}")
print(f"  winners : {len(wins):4d}   ({len(wins)/n*100:5.1f}%)")
print(f"  losers  : {len(losses):4d}   ({len(losses)/n*100:5.1f}%)")
print(f"  flat    : {len(flat):4d}   ({len(flat)/n*100:5.1f}%)")

print(f"\nMONEY (per trade on ~Rs2L notional, then risk-sized to Rs500/trade):")
print(f"  gross P&L per trade (before costs): Rs {gross.mean():+.1f}")
print(f"  cost  per trade                   : Rs {cost.mean():.1f}")
print(f"  NET   P&L per trade (after costs) : Rs {net.mean():+.1f}   <-- the number that matters")
print(f"  total gross over all {n} trades   : Rs {gross.sum():+,.0f}")
print(f"  total costs paid                  : Rs {cost.sum():,.0f}")
print(f"  total NET                         : Rs {net.sum():+,.0f}")

print(f"\nWIN / LOSS SIZE:")
print(f"  average WIN  : Rs {wins['net'].mean():+,.0f}   (best  Rs {net.max():+,.0f})")
print(f"  average LOSS : Rs {losses['net'].mean():+,.0f}   (worst Rs {net.min():+,.0f})")
print(f"  win/loss ratio (avg win / avg loss): {abs(wins['net'].mean()/losses['net'].mean()):.2f}")
pf = wins['net'].sum() / -losses['net'].sum()
print(f"  profit factor (gross wins / gross losses): {pf:.2f}   (need >1.0 to make money)")

print(f"\nEXPECTANCY (size-independent, in units of risk R):")
print(f"  mean   net R/trade : {r.mean():+.4f}   (0 = breakeven; need clearly >0)")
print(f"  median net R/trade : {r.median():+.4f}")
print(f"  std of R           : {r.std():.3f}")

# risk-sized equity curve on 50k
pnl = r * RISK_RS
eq = 50000 + pnl.cumsum()
peak = eq.cummax(); ddser = eq - peak
print(f"\nACCOUNT SIMULATION (start Rs50,000, risk Rs500 = 1% per trade):")
print(f"  ending equity : Rs {eq.iloc[-1]:,.0f}   ({(eq.iloc[-1]/50000-1)*100:+.1f}% over ~1.75 yrs)")
print(f"  peak equity   : Rs {eq.max():,.0f}")
print(f"  worst drawdown: Rs {ddser.min():,.0f}   ({ddser.min()/50000*100:.1f}% of account)")
print(f"  longest losing streak: {_max_streak(net<0)} trades in a row")

print(f"\nPER-QUARTER NET R (out-of-sample):")
qstats = d.groupby("q").apply(lambda g: pd.Series({
    "trades": len(g), "win%": (g['net']>0).mean()*100,
    "net_R": g['rmult'].mean(), "net_Rs": g['net'].sum()})).reset_index()
print(qstats.to_string(index=False))
print(f"\n  quarters profitable: {(qstats['net_R']>0).sum()} of {len(qstats)}")

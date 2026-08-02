"""How sensitive is the out-of-sample result to the SLIPPAGE assumption?
Reruns the same walk-forward OOS test at several slippage levels and also shows
the exact cost breakdown for one representative trade. Brokerage is tiny; the
question is whether slippage sinks it.
"""
import pandas as pd, numpy as np
from pathlib import Path
import orb_backtest as ob

ROOT = Path(r"C:\Users\adars\sss\data")
ob.TRAIL = True; ob.TRAIL_R = 1.0
TRAIN_Q, TOP_K, MIN_TR = 2, 5, 8

movers = pd.read_csv(ROOT / "tradeable_movers.csv")
pool = movers[movers["turn_cr"] >= 40].sort_values("turn_cr", ascending=False)
SYMS = [s for s in pool["sym"].tolist() if "&" not in s][:30]

# cache prepped data once
prepped = {}
for s in SYMS:
    df = ob.fetch_symbol(s)
    if not df.empty and len(df) >= 1000:
        prepped[s] = ob.prep(df)


def build_and_validate(slip):
    ob.SLIPPAGE = slip
    trades = {}
    for s, dfp in prepped.items():
        rows = [ob.simulate_day(dd, 200000) for _, dd in dfp.groupby("day")]
        rows = [t for t in rows if t]
        if rows:
            tr = pd.DataFrame(rows); tr["day"] = pd.to_datetime(tr["day"])
            tr["rmult"] = tr["net"] / tr["R"]; trades[s] = tr
    qs = pd.period_range(
        min(tr["day"].min() for tr in trades.values()),
        max(tr["day"].max() for tr in trades.values()), freq="Q")

    def win(tr, a, b): return tr[(tr["day"] >= a) & (tr["day"] < b)]
    oos = []
    for i in range(TRAIN_Q, len(qs)):
        ts, te = qs[i].start_time, qs[i].end_time
        tr_s = qs[i - TRAIN_Q].start_time
        ranks = [(s, win(tr, tr_s, ts)["rmult"].mean(), len(win(tr, tr_s, ts)))
                 for s, tr in trades.items() if len(win(tr, tr_s, ts)) >= MIN_TR]
        if not ranks: continue
        ranks.sort(key=lambda x: x[1], reverse=True)
        sel = [r[0] for r in ranks[:TOP_K]]
        frames = [win(trades[s], ts, te).assign(sym=s) for s in sel if s in trades]
        if not frames: continue
        d = pd.concat(frames, ignore_index=True).sort_values(["day", "entry_hm"])
        d = d.groupby("day", as_index=False).first()
        oos.append(d)
    o = pd.concat(oos, ignore_index=True)
    return o


print("Measuring slippage sensitivity (out-of-sample, rule-based algo)...\n")
print(f"{'slip/side':>10} {'cost/trade':>11} {'gross/trade':>12} {'NET/trade':>11} "
      f"{'win%':>6} {'PF':>5} {'on Rs50k':>10}")
print("-" * 72)
RISK = 500.0
for slip in [0.0, 0.0001, 0.0002, 0.0003, 0.0004, 0.0005]:
    o = build_and_validate(slip)
    net, gross, cost = o["net"], o["gross"], o["cost"]
    pf = net[net > 0].sum() / -net[net < 0].sum() if (net < 0).any() else np.inf
    eq_end = 50000 + (o["rmult"] * RISK).sum()
    tag = "  <-- I used this" if abs(slip - 0.0005) < 1e-9 else \
          ("  BREAKEVEN-ish" if abs(net.mean()) < 15 else "")
    print(f"{slip*100:9.2f}% {cost.mean():10.0f} {gross.mean():+11.0f} {net.mean():+10.0f} "
          f"{(net>0).mean()*100:5.1f} {pf:5.2f} {(eq_end/50000-1)*100:+8.1f}%{tag}")

print("\nReading it: find the slippage where NET/trade crosses 0. Below that = profitable,")
print("above = losing. That single assumption decides whether this algo is viable.")

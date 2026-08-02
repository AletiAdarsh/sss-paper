"""Test: on TRENDING movers only, does letting winners run (trailing stop) beat
the fixed 1.5R target? Compares both exits on the gross-positive subset.
Data already cached -> fast.
"""
import pandas as pd, numpy as np
import orb_backtest as ob

# the movers that showed a GROSS edge in orb_movers (dropped the choppy ones:
# RPOWER, TARIL, CUPID, SYRMA, MRPL, IDEA, NETWEB)
TREND = ["OLAELEC","APOLLO","CARTRADE","GMDCLTD","DATAPATTNS",
         "CHENNPETRO","PARADEEP","TDPOWERSYS"]
ob.SLIPPAGE = 0.0005
data = {s: ob.fetch_symbol(s) for s in TREND}

def runall(label):
    all_tr = []
    for sym in TREND:
        tr = ob.backtest(sym, data[sym])
        if not tr.empty:
            tr["sym"] = sym; all_tr.append(tr)
    agg = pd.concat(all_tr, ignore_index=True)
    net, gross = agg["net"], agg["gross"]
    wins = net > 0
    print(f"\n[{label}]  trades={len(agg):,}  win%={wins.mean()*100:.1f}")
    print(f"   GROSS/trade=Rs{gross.mean():,.1f}  cost/trade=Rs{agg['cost'].mean():,.1f}  "
          f"NET/trade=Rs{net.mean():,.1f}   NET total=Rs{net.sum():,.0f}")
    print(f"   exits: {agg['reason'].value_counts().to_dict()}")
    # per symbol net expectancy
    per = agg.groupby("sym")["net"].agg(["mean","sum","count"]).sort_values("mean", ascending=False)
    per.columns = ["net/trade","net_total","n"]
    print(per.to_string())
    return agg

print("="*90)
print("TRENDING MOVERS SUBSET:", ", ".join(TREND))
print("="*90)

ob.TRAIL = False
fixed = runall("FIXED 1.5R target")

ob.TRAIL = True
ob.TRAIL_R = 1.0
trail = runall("TRAILING 1.0R (let winners run)")

ob.TRAIL_R = 1.5
trail15 = runall("TRAILING 1.5R (looser trail)")

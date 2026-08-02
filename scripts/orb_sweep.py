"""Sweep ORB params to test whether ANY regime has a GROSS edge (costs aside).
If gross expectancy is ~0 across the board, the template is dead regardless of costs.
Reuses cached data + logic from orb_backtest.
"""
import pandas as pd, numpy as np
import orb_backtest as ob

data = {s: ob.fetch_symbol(s) for s in ob.UNIVERSE}
prepped = {s: ob.prep(df) for s, df in data.items()}

def run(or_bars, buf, tgt_r, vol_mult):
    ob.OR_BARS, ob.BUF, ob.TGT_R, ob.VOL_MULT = or_bars, buf, tgt_r, vol_mult
    all_net, all_gross, all_R = [], [], []
    n = 0
    for s, df in prepped.items():
        for day, dd in df.groupby("day"):
            t = ob.simulate_day(dd, 200000)
            if t:
                all_net.append(t["net"]); all_gross.append(t["gross"]); all_R.append(t["R"]); n += 1
    if n == 0: return None
    g = np.array(all_gross); net = np.array(all_net)
    return {"OR": or_bars, "buf%": buf*100, "tgtR": tgt_r, "volx": vol_mult,
            "n": n, "gross/t": g.mean(), "net/t": net.mean(),
            "win%": (net > 0).mean()*100}

rows = []
for or_bars in [2, 3, 6]:                    # 10, 15, 30 min opening range
    for buf in [0.0, 0.0005, 0.0015]:        # 0, 0.05%, 0.15% breakout buffer
        for tgt_r in [1.0, 2.0, 3.0]:        # target R multiples
            for vol_mult in [1.0, 1.5, 2.5]: # volume conviction filter
                r = run(or_bars, buf, tgt_r, vol_mult)
                if r: rows.append(r)

res = pd.DataFrame(rows)
pd.set_option("display.width", 200)
pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
print("=== ORB PARAM SWEEP (gross = costs-aside edge) ===")
print("Sorted by gross expectancy per trade (best first):")
print(res.sort_values("gross/t", ascending=False).head(15).to_string(index=False))
print("\nBest GROSS/trade:  Rs%.1f" % res["gross/t"].max())
print("Median GROSS/trade across regimes: Rs%.1f" % res["gross/t"].median())
print("Regimes with gross/trade > Rs50 (needed just to beat costs): %d of %d"
      % ((res["gross/t"] > 50).sum(), len(res)))

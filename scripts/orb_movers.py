"""Re-run the SAME ORB backtest, but on the screened high-range movers instead of
sleepy large-caps. Honest slippage bumped to 0.05%/side (mid-caps = wider spreads).
"""
import pandas as pd, numpy as np
import orb_backtest as ob

# liquid movers (turnover >= ~60cr/day) from range_screener output
ob.UNIVERSE = ["OLAELEC","NETWEB","APOLLO","CARTRADE","GMDCLTD","TARIL",
               "DATAPATTNS","RPOWER","IDEA","CHENNPETRO","PARADEEP","SYRMA",
               "TDPOWERSYS","MRPL","CUPID"]
ob.SLIPPAGE = 0.0005          # 0.05%/side, more honest for mid-caps

print(f"Pulling/loading {len(ob.UNIVERSE)} MOVERS, 5-min ...")
data = {s: ob.fetch_symbol(s) for s in ob.UNIVERSE}

print("\n" + "=" * 110)
print(f"ORB ON MOVERS | OR={ob.OR_BARS} buf={ob.BUF*100:.2f}% tgt={ob.TGT_R}R "
      f"volx{ob.VOL_MULT} sqoff={ob.SQUAREOFF} | slip={ob.SLIPPAGE*100:.2f}%/side")
print("=" * 110)

rows, all_tr = [], []
for sym in ob.UNIVERSE:
    if data[sym].empty:
        print(f"  {sym}: no data"); continue
    tr = ob.backtest(sym, data[sym])
    if not tr.empty:
        tr["sym"] = sym; all_tr.append(tr)
    r = ob.summarize(sym, tr)
    if r: rows.append(r)

summ = pd.DataFrame(rows)
pd.set_option("display.width", 200)
pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
print(summ.to_string(index=False))

if all_tr:
    agg = pd.concat(all_tr, ignore_index=True)
    net = agg["net"]; wins = net > 0
    print("\n" + "-" * 110)
    print("POOLED (movers):")
    print(f"  trades={len(agg):,}  win%={wins.mean()*100:.1f}  "
          f"gross=Rs{agg['gross'].sum():,.0f}  costs=Rs{agg['cost'].sum():,.0f}  "
          f"NET=Rs{net.sum():,.0f}")
    print(f"  expectancy/trade NET = Rs{net.mean():,.1f}   GROSS = Rs{agg['gross'].mean():,.1f}   "
          f"cost/trade = Rs{agg['cost'].mean():,.1f}")
    print(f"  avg R-multiple(net) = {(net/agg['R']).mean():.3f}")
    print(f"  exit reasons: {agg['reason'].value_counts().to_dict()}")
    print("\nVERDICT:", "GROSS EDGE PRESENT" if agg['gross'].mean() > 0 else "no gross edge",
          "|", "NET POSITIVE after costs" if net.mean() > 0 else "NET NEGATIVE after costs")

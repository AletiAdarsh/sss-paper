"""Is the move 'already made' after a gap up? Measure how far price travels
AFTER the open (where you'd actually enter), by gap-size bucket.

For each gap-up day, entering at the open:
  up_room  = (day_high  - open)/open * 100   -> best-case profit still available
  heat     = (open - day_low)/open  * 100   -> drawdown you must sit through
  to_close = (close     - open)/open * 100   -> result if you just held to close
If up_room is small relative to the gap, the user is right: move already spent.
"""
import pandas as pd, numpy as np
from pathlib import Path
from datetime import timedelta, timezone

CACHE = Path(r"C:\Users\adars\sss\data\intraday_cache")
IST = timezone(timedelta(hours=5, minutes=30))
MIN_GAP = 0.003

rows = []
for f in sorted(CACHE.glob("*_5m.csv")):
    sym = f.stem.replace("_5m", "")
    df = pd.read_csv(f)
    dt = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(IST)
    df["day"] = dt.dt.date
    daily = df.groupby("day").agg(open=("o", "first"), high=("h", "max"),
                                  low=("l", "min"), close=("c", "last")).reset_index()
    daily["prev_close"] = daily["close"].shift(1)
    daily["gap"] = daily["open"] / daily["prev_close"] - 1
    d = daily[daily["gap"] >= MIN_GAP].copy()
    d["up_room"]  = (d["high"] - d["open"]) / d["open"] * 100
    d["heat"]     = (d["open"] - d["low"]) / d["open"] * 100
    d["to_close"] = (d["close"] - d["open"]) / d["open"] * 100
    d["gap_pct"]  = d["gap"] * 100
    rows.append(d[["gap_pct", "up_room", "heat", "to_close"]])

r = pd.concat(rows, ignore_index=True)
pd.set_option("display.float_format", lambda x: f"{x:.2f}")

def show(sub, lab):
    if not len(sub): return
    print(f"{lab:10s} n={len(sub):5d} | up_room(med) {sub['up_room'].median():5.2f}%  "
          f"heat(med) {sub['heat'].median():5.2f}%  toClose(med) {sub['to_close'].median():+5.2f}%  "
          f"| %days close>open {(sub['to_close']>0).mean()*100:4.1f}%")

print(f"Gap-up days: {len(r):,}  (entry assumed at the OPEN)\n")
print("Key: up_room = further upside available AFTER open; heat = drawdown before that.\n")
for lo, hi, lab in [(0.003,0.01,"0.3-1%"),(0.01,0.02,"1-2%"),
                    (0.02,0.03,"2-3%"),(0.03,0.05,"3-5%"),(0.05,1.0,">5%")]:
    show(r[(r["gap_pct"]/100>=lo)&(r["gap_pct"]/100<hi)], lab)

print("\nInterpretation: if up_room is small and heat is large for big gaps,")
print("the overnight move IS mostly spent and buying at the open is a poor bet.")

"""Nifty-50 INDEX gap-UP continuation study (no live token needed — uses the
cached 15-min history in data/intraday_cache/NIFTY50INDEX_15m.csv).

Question (user): when the index gaps UP ~0.7%, does it keep running to +1.5%,
or fade back? Measures, per gap-up day:
    gap        = open/prev_close - 1
    high_vs_pc = day_high/prev_close - 1   -> the best it reached
    reached1.5 = did high_vs_pc hit +1.5%?
    rest_day   = close/open - 1            -> after the gap, did it keep rising?
    close_vs_pc= close/prev_close - 1      -> where it finished vs yesterday
    filled     = did day_low fall back to/under prev_close? (gap filled)
    next_day   = next close / close - 1

Then focuses on the analog band around today's ~0.7% gap.

Run:  py gap_up_continue.py
"""
import pandas as pd, numpy as np
from pathlib import Path
from datetime import timedelta, timezone

CACHE = Path(r"C:\Users\adars\sss\data\intraday_cache\NIFTY50INDEX_15m.csv")
IST = timezone(timedelta(hours=5, minutes=30))

TODAY_GAP = 0.007          # ~0.7% gap up today
TOL       = 0.002          # analog band = today's gap +/- 0.2 pp
REACH     = 0.015          # "continuation" target = +1.5% above prev close


def daily_from_15m():
    df = pd.read_csv(CACHE)
    dt = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(IST)
    df["day"] = dt.dt.date
    d = df.groupby("day").agg(open=("o", "first"), high=("h", "max"),
                              low=("l", "min"), close=("c", "last")).reset_index()
    d["prev_close"] = d["close"].shift(1)
    d = d.dropna(subset=["prev_close"])
    d["gap"]         = d["open"] / d["prev_close"] - 1
    d["high_vs_pc"]  = d["high"] / d["prev_close"] - 1
    d["low_vs_pc"]   = d["low"]  / d["prev_close"] - 1
    d["rest_day"]    = d["close"] / d["open"] - 1
    d["close_vs_pc"] = d["close"] / d["prev_close"] - 1
    d["reached"]     = d["high_vs_pc"] >= REACH
    d["filled"]      = d["low"] <= d["prev_close"]
    d["next_day"]    = d["close"].shift(-1) / d["close"] - 1
    return d


def show(sub, label):
    n = len(sub)
    if n == 0:
        print(f"  {label:16s}: no days"); return
    print(f"  {label:16s}: n={n:4d} | "
          f"reach +1.5% {sub['reached'].mean()*100:4.0f}%  "
          f"| rest-of-day med {sub['rest_day'].median()*100:+.2f}%  "
          f"green {(sub['rest_day']>0).mean()*100:3.0f}%  "
          f"| close vs prevC med {sub['close_vs_pc'].median()*100:+.2f}%  "
          f"| gap filled {sub['filled'].mean()*100:3.0f}%")


d = daily_from_15m()
ups = d[d["gap"] > 0]
print(f"NIFTY 50 gap-UP continuation | {d['day'].min()} -> {d['day'].max()} "
      f"| {len(d):,} sessions, {len(ups):,} gap-ups\n")

# --- the analog band around today's ~0.7% gap ---
lo, hi = TODAY_GAP - TOL, TODAY_GAP + TOL
band = ups[(ups["gap"] >= lo) & (ups["gap"] <= hi)]
print(f"TODAY-LIKE: gap-up between {lo*100:.1f}% and {hi*100:.1f}%  (today ~{TODAY_GAP*100:.1f}%)")
print(f"  sample: {len(band)} days since 2019\n")
print(f"  Of these ~{TODAY_GAP*100:.1f}% gap-up days:")
print(f"    - reached +1.5% (from prev close) intraday : {band['reached'].mean()*100:.0f}%")
print(f"    - closed ABOVE the open (kept rising)      : {(band['rest_day']>0).mean()*100:.0f}%")
print(f"    - closed GREEN vs prev close (held gap)    : {(band['close_vs_pc']>0).mean()*100:.0f}%")
print(f"    - filled the gap (dipped to prev close)    : {band['filled'].mean()*100:.0f}%")
print(f"    - median rest-of-day (open->close)         : {band['rest_day'].median()*100:+.2f}%")
print(f"    - median day close vs prev close           : {band['close_vs_pc'].median()*100:+.2f}%")
print(f"    - median high reached vs prev close        : {band['high_vs_pc'].median()*100:+.2f}%")
print(f"    - next session median                      : {band['next_day'].dropna().median()*100:+.2f}%  "
      f"(green {(band['next_day']>0).mean()*100:.0f}%)")

print("\n" + "="*76)
print("Gap-UP behaviour by size bucket (all history):")
for a, b, lab in [(0.001,0.003,"0.1-0.3%"),(0.003,0.005,"0.3-0.5%"),
                  (0.005,0.007,"0.5-0.7%"),(0.007,0.010,"0.7-1.0%"),
                  (0.010,0.015,"1.0-1.5%"),(0.015,0.05,">1.5%")]:
    show(ups[(ups["gap"] >= a) & (ups["gap"] < b)], lab)
print("\nreach+1.5% = high touched +1.5% above prev close  |  'gap filled' = pulled back to prev close")

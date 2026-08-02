"""Nifty-50 INDEX gap-down scanner + historical-analog predictor.

  1) today's gap = today_open / prev_close - 1   (fresh Fyers OHLC for the index)
  2) if the index GAPPED DOWN, find every prior session in its full history with a
     similar-magnitude gap down (within a tolerance band), and measure what happened NEXT:
        rest_of_day = close/open - 1   (did the gap-down recover intraday or bleed?)
        next_day    = next_close/close - 1
  3) also show base rates for every gap-down severity bucket for context.

The "prediction" is the historical base rate (median move + % green), not a promise.

Run:  py gap_down_predict.py
"""
import numpy as np, pandas as pd
from datetime import date, timedelta
import fyers_client as fy

INDEX  = "NSE:NIFTY50-INDEX"
TODAY  = date.today().isoformat()
START  = "2015-01-01"

GAP_MIN   = 0.003     # ignore gaps < 0.3% (noise)
TOL_FRAC  = 0.30      # analog band = today's gap +/- 30% of its size ...
TOL_FLOOR = 0.0015    # ... but at least +/- 0.15 percentage points


def load_index():
    rows = fy.fetch_history_range(INDEX, START, TODAY, "D")
    if not rows:
        raise SystemExit("No index candles returned (token expired? symbol wrong?)")
    df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume"])
    df["date"] = (pd.to_datetime(df["ts"], unit="s", utc=True)
                    .dt.tz_convert("Asia/Kolkata").dt.date)
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    df["prev_close"] = df["close"].shift(1)
    df["gap"]        = df["open"] / df["prev_close"] - 1
    df["rest_day"]   = df["close"] / df["open"] - 1
    df["next_day"]   = df["close"].shift(-1) / df["close"] - 1
    df["next_hi"]    = df["high"].shift(-1) / df["close"] - 1
    df["next_lo"]    = df["low"].shift(-1) / df["close"] - 1
    return df


def describe(sub, label):
    n = len(sub)
    if n == 0:
        return f"    {label:22s}: no analogs"
    rd = sub["rest_day"].dropna()*100
    nd = sub["next_day"].dropna()*100
    return (f"    {label:22s}: n={n:4d} | "
            f"rest-of-day med {rd.median():+.2f}%  green {(rd>0).mean()*100:3.0f}%  "
            f"|  next-day med {nd.median():+.2f}%  green {(nd>0).mean()*100:3.0f}%")


def main():
    df = load_index()
    last = df.iloc[-1]
    gp   = last["gap"]
    print(f"NIFTY 50 INDEX  |  latest bar {last['date']}  ({len(df):,} sessions of history)")
    print("="*74)
    print(f"prev close {last['prev_close']:.2f}   ->   today open {last['open']:.2f}"
          f"   =   gap {gp*100:+.2f}%")
    if last["date"].isoformat() != TODAY:
        print(f"(note: no bar dated {TODAY} yet — showing the most recent session)")
    print()

    if gp > -GAP_MIN:
        print(f"Not a meaningful gap-DOWN today (gap {gp*100:+.2f}%, threshold -{GAP_MIN*100:.1f}%).")
        print("Showing base rates anyway so you have the map when it does gap down.\n")
    else:
        tol = max(TOL_FLOOR, abs(gp)*TOL_FRAC)
        lo, hi = gp - tol, gp + tol
        analog = df[(df["gap"] >= lo) & (df["gap"] <= hi) & (df["date"] != last["date"])]
        print(f"ANALOGS: prior sessions that gapped down [{lo*100:+.2f}%, {hi*100:+.2f}%]")
        print(describe(analog, "similar gap-downs"))
        if len(analog):
            rd_med = analog["rest_day"].median()
            nd_med = analog["next_day"].dropna().median()
            nd_up  = (analog["next_day"]>0).mean()
            lean = ("REST OF DAY tends to RECOVER (buy-the-dip bias)" if rd_med > 0.0005 else
                    "REST OF DAY tends to keep BLEEDING" if rd_med < -0.0005 else
                    "REST OF DAY roughly flat / no edge")
            print(f"\n   PREDICTION (base rate, n={len(analog)}):")
            print(f"     - {lean}  (median rest-of-day {rd_med*100:+.2f}%)")
            print(f"     - Next session: median {nd_med*100:+.2f}%, closes green {nd_up*100:.0f}% of the time")
            print(f"     - Next-day range: typical high {analog['next_hi'].median()*100:+.2f}%, "
                  f"low {analog['next_lo'].median()*100:+.2f}% vs today's close")
            worst = analog['next_day'].min()*100; best = analog['next_day'].max()*100
            print(f"     - Next-day spread across analogs: worst {worst:+.1f}%  best {best:+.1f}%")
        print()

    print("="*74)
    print("Nifty-50 index gap-DOWN base rates by severity (full history):")
    for lo, hi, lab in [(0.003,0.005,"0.3-0.5%"),(0.005,0.01,"0.5-1%"),
                        (0.01,0.015,"1-1.5%"),(0.015,0.02,"1.5-2%"),
                        (0.02,0.03,"2-3%"),(0.03,1,">3%")]:
        b = df[(df["gap"] <= -lo) & (df["gap"] > -hi)]
        print(describe(b, f"down {lab}"))
    print("\n(rest-of-day = index close vs its own open; next-day = following session close-to-close)")


if __name__ == "__main__":
    main()

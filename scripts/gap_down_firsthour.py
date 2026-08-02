"""Nifty-50 INDEX: on a gap-DOWN day, which way does it go when it breaks the
FIRST HOUR's high vs low?  (opening-range-breakout, conditioned on the gap.)

For every session (2019->today, 15-min bars):
  gap        = day_open / prev_close - 1
  FH_high/lo = high/low of the first hour (09:15-10:15, four 15-min bars)
  after 10:15, whichever of FH_high / FH_low is touched FIRST = the break side
  outcome:
     up-break  -> did it CLOSE above FH_high?  how far did it run from the break?
     dn-break  -> did it CLOSE below FH_low?    how far did it fall from the break?

Then we filter to GAP-DOWN days (and the analog band around today's gap) and
report the base rates:  P(breaks high first) vs P(breaks low first), and given
each break, the continuation odds + typical move.

Run:  py gap_down_firsthour.py
"""
import time
import numpy as np, pandas as pd
from pathlib import Path
from datetime import date, timedelta
import fyers_client as fy

CACHE = Path(r"C:\Users\adars\sss\data\intraday_cache")
CACHE.mkdir(exist_ok=True)
INDEX = "NSE:NIFTY50-INDEX"
TODAY = date.today().isoformat()
START = "2019-01-01"

FH_END    = "10:15"   # first-hour range = bars with time < 10:15 (09:15..10:00)
GAP_MIN   = 0.003
TOL_FRAC  = 0.30
TOL_FLOOR = 0.0015


def load_15m():
    f = CACHE / "NIFTY50INDEX_15m.csv"
    have = pd.read_csv(f) if f.exists() else pd.DataFrame(columns=["ts","o","h","l","c","v"])
    last_cached = (pd.to_datetime(have["ts"].max(), unit="s", utc=True)
                     .tz_convert("Asia/Kolkata").date().isoformat()) if len(have) else START
    s = date.fromisoformat(last_cached if len(have) else START)
    e = date.today()
    rows = []
    cur = s
    while cur <= e:                                   # 90-day chunks for intraday
        nxt = min(e, cur + timedelta(days=90))
        for att in range(3):
            try:
                rows += fy.fetch_history(INDEX, cur.isoformat(), nxt.isoformat(), "15"); break
            except Exception as ex:
                if att == 2: print("  !", cur, ex)
                time.sleep(1+att)
        time.sleep(0.2); cur = nxt + timedelta(days=1)
    new = pd.DataFrame(rows, columns=["ts","o","h","l","c","v"])
    df = (pd.concat([have, new], ignore_index=True)
            .drop_duplicates("ts").sort_values("ts").reset_index(drop=True))
    df.to_csv(f, index=False)
    dt = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    df["date"] = dt.dt.date; df["hm"] = dt.dt.strftime("%H:%M")
    return df


def analyse(df):
    recs = []
    days = sorted(df["date"].unique())
    prev_close = None
    for day in days:
        d = df[df["date"] == day].sort_values("hm").reset_index(drop=True)
        if len(d) < 8:
            prev_close = d["c"].iloc[-1] if len(d) else prev_close; continue
        day_open = d["o"].iloc[0]; day_close = d["c"].iloc[-1]
        fh = d[d["hm"] < FH_END]
        if len(fh) < 3 or prev_close is None:
            prev_close = day_close; continue
        fh_hi = fh["h"].max(); fh_lo = fh["l"].min()
        gap = day_open / prev_close - 1

        post = d[d["hm"] >= FH_END]
        up_i = dn_i = None
        for i, r in post.iterrows():
            if up_i is None and r["h"] >= fh_hi: up_i = i
            if dn_i is None and r["l"] <= fh_lo: dn_i = i
            if up_i is not None or dn_i is not None: break
        # determine first break
        if up_i is None and dn_i is None:
            side = "none"
        elif dn_i is None or (up_i is not None and up_i < dn_i):
            side = "up"
        elif up_i is None or dn_i < up_i:
            side = "down"
        else:
            side = "both"   # same bar broke both extremes -> ambiguous

        recs.append(dict(date=day, gap=gap, fh_hi=fh_hi, fh_lo=fh_lo,
                         day_open=day_open, day_close=day_close, side=side,
                         close_vs_hi=day_close/fh_hi-1, close_vs_lo=day_close/fh_lo-1,
                         close_vs_open=day_close/day_open-1))
        prev_close = day_close
    return pd.DataFrame(recs)


def report(sub, title):
    n = len(sub)
    print(f"\n{title}  (n={n} sessions)")
    if n == 0:
        print("   no sessions"); return
    vc = sub["side"].value_counts()
    up = sub[sub["side"]=="up"]; dn = sub[sub["side"]=="down"]
    none = sub[sub["side"]=="none"]
    print(f"   which side breaks FIRST:  UP-high {len(up)/n*100:4.0f}%   "
          f"DOWN-low {len(dn)/n*100:4.0f}%   neither {len(none)/n*100:4.0f}%   "
          f"both-same-bar {len(sub[sub['side']=='both'])/n*100:.0f}%")
    if len(up):
        held = (up["day_close"] > up["fh_hi"]).mean()
        print(f"   IF breaks FIRST-HOUR HIGH:  closes ABOVE the high {held*100:4.0f}% of days  "
              f"| median close vs high {up['close_vs_hi'].median()*100:+.2f}%  "
              f"| median day (O->C) {up['close_vs_open'].median()*100:+.2f}%")
    if len(dn):
        held = (dn["day_close"] < dn["fh_lo"]).mean()
        print(f"   IF breaks FIRST-HOUR LOW:   closes BELOW the low  {held*100:4.0f}% of days  "
              f"| median close vs low  {dn['close_vs_lo'].median()*100:+.2f}%  "
              f"| median day (O->C) {dn['close_vs_open'].median()*100:+.2f}%")


def main():
    df = load_15m()
    res = analyse(df)
    print(f"NIFTY 50 INDEX first-hour breakout study | {res['date'].min()} -> {res['date'].max()} "
          f"| {len(res):,} sessions")

    today = res.iloc[-1]
    gp = today["gap"]
    print("="*78)
    print(f"TODAY {today['date']}:  gap {gp*100:+.2f}%   "
          f"first-hour HIGH {today['fh_hi']:.2f}   first-hour LOW {today['fh_lo']:.2f}")
    print(f"   -> break {today['fh_hi']:.0f} = bullish trigger; break {today['fh_lo']:.0f} = bearish trigger")
    print(f"   (today so far broke: {today['side'].upper()})")

    # baseline: all sessions
    report(res, "ALL sessions 2019-today")
    # gap-down sessions
    downs = res[res["gap"] <= -GAP_MIN]
    report(downs, f"GAP-DOWN sessions (<= -{GAP_MIN*100:.1f}%)")
    # analog band around today's gap
    if gp <= -GAP_MIN:
        tol = max(TOL_FLOOR, abs(gp)*TOL_FRAC)
        band = res[(res["gap"] >= gp-tol) & (res["gap"] <= gp+tol) & (res["date"] != today["date"])]
        report(band, f"ANALOGS: gap-down like today [{(gp-tol)*100:+.2f}%,{(gp+tol)*100:+.2f}%]")


if __name__ == "__main__":
    main()

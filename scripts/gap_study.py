"""Gap-up fill-and-go study (the user's hypothesis).

For each gap-up day:
  gap up   = today's open > yesterday's close (by >= MIN_GAP)
  fill     = price later trades back DOWN to yesterday's close (fills the gap)
  pre-fill high = the highest point BEFORE the fill happened
  after fill, classify:
     BREAK_HIGH  -> price bounces and exceeds the pre-fill high  (tradeable bounce)
     NO_BREAK    -> filled but never reclaims the pre-fill high  (sideways/fade)
  never fills -> gap held / ran away up (no pullback entry)

Reports probabilities overall and bucketed by gap size, across all cached
5-min symbols.  Run:  py gap_study.py
"""
import pandas as pd, numpy as np
from pathlib import Path
from datetime import timedelta, timezone

CACHE = Path(r"C:\Users\adars\sss\data\intraday_cache")
IST = timezone(timedelta(hours=5, minutes=30))
MIN_GAP = 0.003     # >=0.3% to count as a real gap up


def load(f):
    df = pd.read_csv(f)
    dt = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(IST)
    df["day"] = dt.dt.date
    return df


records = []
for f in sorted(CACHE.glob("*_5m.csv")):
    sym = f.stem.replace("_5m", "")
    df = load(f)
    # daily open/close from intraday
    daily = df.groupby("day").agg(open=("o", "first"), close=("c", "last")).reset_index()
    daily["prev_close"] = daily["close"].shift(1)
    daily["gap"] = daily["open"] / daily["prev_close"] - 1
    gapmap = daily.set_index("day")

    for day, dd in df.groupby("day"):
        if day not in gapmap.index:
            continue
        row = gapmap.loc[day]
        prev_close = row["prev_close"]
        gap = row["gap"]
        if pd.isna(gap) or gap < MIN_GAP:
            continue                       # only gap-UPs of size >= MIN_GAP
        dd = dd.reset_index(drop=True)
        # find first bar whose LOW touches/breaks prev_close  -> gap filled
        fill_idx = None
        for i in range(len(dd)):
            if dd.loc[i, "l"] <= prev_close:
                fill_idx = i
                break
        if fill_idx is None:
            outcome = "NO_FILL"
        else:
            pre_high = dd.loc[:max(0, fill_idx - 1), "h"].max() if fill_idx > 0 else dd.loc[0, "h"]
            after = dd.loc[fill_idx + 1:, "h"]
            if len(after) and after.max() > pre_high:
                outcome = "BREAK_HIGH"
            else:
                outcome = "NO_BREAK"
        records.append({"sym": sym, "day": day, "gap": gap, "outcome": outcome})

r = pd.DataFrame(records)
print(f"Total gap-up days analyzed (gap >= {MIN_GAP*100:.1f}%): {len(r):,}  "
      f"across {r['sym'].nunique()} stocks\n")

def breakdown(sub, label):
    n = len(sub)
    if n == 0:
        print(f"{label:16s}  (no days)"); return
    vc = sub["outcome"].value_counts()
    fill = vc.get("BREAK_HIGH", 0) + vc.get("NO_BREAK", 0)
    nofill = vc.get("NO_FILL", 0)
    bh = vc.get("BREAK_HIGH", 0)
    nb = vc.get("NO_BREAK", 0)
    print(f"{label:16s} n={n:5d} | FILLS gap: {fill/n*100:5.1f}%  "
          f"(never fills/runs up: {nofill/n*100:4.1f}%)")
    if fill:
        print(f"{'':16s}          of the fills -> BREAK pre-fill high: {bh/fill*100:5.1f}%   "
              f"stays below (sideways/fade): {nb/fill*100:5.1f}%")
        print(f"{'':16s}          => P(gap fills AND then breaks high) overall = {bh/n*100:.1f}%")

print("=" * 90)
print("OVERALL")
print("=" * 90)
breakdown(r, "ALL gap-ups")

print("\n" + "=" * 90)
print("BY GAP SIZE")
print("=" * 90)
buckets = [(0.003, 0.01, "0.3-1%"), (0.01, 0.02, "1-2%"),
           (0.02, 0.05, "2-5%"), (0.05, 1.0, ">5%")]
for lo, hi, lab in buckets:
    breakdown(r[(r["gap"] >= lo) & (r["gap"] < hi)], lab)

print("\nNote: 'fill' = price returned to yesterday's close during the day.")
print("Selection isn't the whole story - this is just the raw geometry, before costs.")

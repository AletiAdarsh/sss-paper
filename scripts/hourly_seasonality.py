"""Time-of-day bias in hourly candles: which intraday slots tend to fall, and by how much.

Fetches 60-min candles (cached to data/hourly/{SYM}.csv) and, for each intraday
slot (09:15 ... 15:15), reports how often the candle closes below its open, the
average displacement, and the same conditioned on the day having already surged.

  py scripts/hourly_seasonality.py KALYANKJIL
  py scripts/hourly_seasonality.py KALYANKJIL --start 2021-03-26
  py scripts/hourly_seasonality.py --all --top 20     # scan the whole universe
"""
import sys, time, argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from fyers_client import fetch_history

ROOT = Path(r"C:\Users\adars\sss")
CACHE = ROOT / "data" / "hourly"
CHUNK = 90          # Fyers caps intraday requests at ~100 days
SLOTS = ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]


def fetch_hourly(sym, start, end, sleep=0.35):
    """60-min candles, chunked. Returns DataFrame indexed by IST timestamp."""
    out = []
    cur = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    while cur <= end_d:
        nxt = min(end_d, cur + timedelta(days=CHUNK))
        for attempt in range(3):
            try:
                out += fetch_history(f"NSE:{sym}-EQ", cur.isoformat(), nxt.isoformat(), resolution="60")
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
        time.sleep(sleep)
        cur = nxt + timedelta(days=1)

    if not out:
        return pd.DataFrame()
    d = pd.DataFrame(out, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts")
    d["t"] = pd.to_datetime(d.ts, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    return d.sort_values("t").reset_index(drop=True)


def load(sym, start, end, refresh=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{sym}.csv"
    if f.exists() and not refresh:
        d = pd.read_csv(f, parse_dates=["t"])
        d["t"] = pd.to_datetime(d.t, utc=True).dt.tz_convert("Asia/Kolkata")
        return d
    d = fetch_hourly(sym, start, end)
    if len(d):
        d.to_csv(f, index=False)
    return d


def analyse(d):
    """Per-slot stats. 'Fall' = close < open. Displacement = (close/open - 1)."""
    d = d.copy()
    d["day"] = d.t.dt.date
    d["slot"] = d.t.dt.strftime("%H:%M")
    d["disp"] = (d.close / d.open - 1) * 100
    d["fell"] = d.close < d.open

    # how far the day had already run BEFORE this candle opened:
    # this candle's open vs the day's first candle's open
    day_open = d.groupby("day").open.transform("first")
    d["prior"] = (d.open / day_open - 1) * 100

    rows = []
    for s in SLOTS:
        g = d[d.slot == s]
        if not len(g):
            continue
        up, dn = g[~g.fell], g[g.fell]
        # conditional on the day already being up before this candle
        for label, sub in [("all", g),
                           ("surged >0%", g[g.prior > 0]),
                           ("surged >1%", g[g.prior > 1]),
                           ("surged >2%", g[g.prior > 2])]:
            if label != "all":
                continue
            pass
        rows.append({
            "slot": s,
            "n": len(g),
            "fall%": g.fell.mean() * 100,
            "avg_disp": g.disp.mean(),
            "avg_up": up.disp.mean() if len(up) else np.nan,
            "avg_dn": dn.disp.mean() if len(dn) else np.nan,
            "n_up": len(up),
            "n_dn": len(dn),
            "fall%|>0": g[g.prior > 0].fell.mean() * 100 if (g.prior > 0).sum() else np.nan,
            "n|>0": int((g.prior > 0).sum()),
            "fall%|>1": g[g.prior > 1].fell.mean() * 100 if (g.prior > 1).sum() else np.nan,
            "n|>1": int((g.prior > 1).sum()),
            "fall%|>2": g[g.prior > 2].fell.mean() * 100 if (g.prior > 2).sum() else np.nan,
            "n|>2": int((g.prior > 2).sum()),
        })
    return pd.DataFrame(rows), d


def wilson(k, n, z=1.96):
    """95% CI for a proportion - so we can see if a slot's edge is real or noise."""
    if not n:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return ((c - half) * 100, (c + half) * 100)


def report(sym, start, end, refresh=False):
    d = load(sym, start, end, refresh)
    if not len(d):
        print(f"{sym}: no data")
        return None
    t, dd = analyse(d)
    base_fall = dd.fell.mean() * 100

    print(f"\n{sym}   {dd.t.min():%Y-%m-%d} -> {dd.t.max():%Y-%m-%d}   "
          f"{dd.day.nunique():,} sessions, {len(dd):,} hourly candles")
    print(f"baseline: {base_fall:.1f}% of ALL hourly candles close red\n")

    print(f"{'slot':<7}{'n':>6}{'fall%':>8}{'95% CI':>15}{'avg disp':>10}"
          f"{'avg up':>9}{'avg dn':>9}")
    print("-" * 64)
    for _, r in t.iterrows():
        lo, hi = wilson(r["n_dn"], r["n"])
        flag = ""
        if lo > 50:
            flag = "  <-- bearish, CI clears 50%"
        elif hi < 50:
            flag = "  <-- bullish, CI clears 50%"
        print(f"{r.slot:<7}{int(r.n):>6}{r['fall%']:>7.1f}%{f'[{lo:.0f}-{hi:.0f}]':>15}"
              f"{r.avg_disp:>+9.3f}%{r.avg_up:>+8.2f}%{r.avg_dn:>+8.2f}%{flag}")

    print(f"\nconditioned on the day ALREADY being up when the candle opens:")
    print(f"{'slot':<7}{'fall% all':>11}{'fall%|>0':>11}{'n':>6}{'fall%|>1':>11}{'n':>6}"
          f"{'fall%|>2':>11}{'n':>6}")
    print("-" * 64)
    for _, r in t.iterrows():
        def f(v):
            return f"{v:.1f}%" if pd.notna(v) else "  -  "
        print(f"{r.slot:<7}{r['fall%']:>10.1f}%{f(r['fall%|>0']):>11}{int(r['n|>0']):>6}"
              f"{f(r['fall%|>1']):>11}{int(r['n|>1']):>6}{f(r['fall%|>2']):>11}{int(r['n|>2']):>6}")
    return t


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("symbol", nargs="?", default="KALYANKJIL")
    p.add_argument("--start", default="2021-03-26")
    p.add_argument("--end", default=str(date.today()))
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args()
    report(a.symbol, a.start, a.end, a.refresh)

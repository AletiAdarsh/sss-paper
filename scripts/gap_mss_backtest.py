"""Gap-up FADE with SMC bearish-MSS confirmation (ported from user's EzSMC indicator).

Rule (intraday, 5-min):
  - Only gap-UP days with gap in (GAP_LO, GAP_HI]  (default 0.3% .. 3%)
  - Detect swings via calculate_swing_points(3) exactly like the indicator
  - Track BOS/MSS with the same t_MS state machine
  - Bearish MSS = close crosses UNDER the last swing low, after an up-break (t_MS>0)
  - SHORT on that bar's close, but only while price is still ABOVE prev_close
    (room to fall) and target is >= MIN_ROOM away
  - Stop  = day's high so far (structure invalidation)
  - Target= prev_close (the gap fill);   square off 15:15
  - One trade per symbol per day

Honest cost model reused from orb_backtest (slippage 0.05%/side).
Run:  py gap_mss_backtest.py
"""
import pandas as pd, numpy as np
from pathlib import Path
from datetime import timedelta, timezone
import orb_backtest as ob

CACHE = Path(r"C:\Users\adars\sss\data\intraday_cache")
ROOT  = Path(r"C:\Users\adars\sss\data")
IST = timezone(timedelta(hours=5, minutes=30))

SWING     = 3            # internal swing size (matches indicator's swingSize)
GAP_LO    = 0.003
GAP_HI    = 0.03         # ceiling now 3% (user's change)
SQUAREOFF = "15:15"
MIN_ROOM  = 0.003        # need >=0.3% from entry to gap-fill target to bother
ob.SLIPPAGE = 0.0005
SIGNAL    = "MSS"       # "MSS" (reversal only) or "ANY" (MSS or BOS bearish break)


def calc_swings(h, l, length):
    """Faithful port of calculate_swing_points: returns (swing_high[], swing_low[])
    with a value at the bar where the swing is CONFIRMED (length bars late), else 0."""
    n = len(h)
    sh = [0.0] * n; sl = [0.0] * n
    prev = 0
    for i in range(n):
        if i - length < 0:
            continue
        win_hi = max(h[i - length + 1:i + 1])    # ta.highest(length)
        win_lo = min(l[i - length + 1:i + 1])    # ta.lowest(length)
        h_len = h[i - length]                     # high[length]
        l_len = l[i - length]                     # low[length]
        prev_before = prev
        if h_len > win_hi:
            prev = 0
        elif l_len < win_lo:
            prev = 1
        if prev == 0 and prev_before != 0:
            sh[i] = h_len
        if prev == 1 and prev_before != 1:
            sl[i] = l_len
    return sh, sl


def bearish_signals(o, h, l, c):
    """Return per-bar bearish MSS / BOS flags + running swing-high (for stops),
    replicating the indicator's internal t_MS state machine."""
    n = len(c)
    sh, sl = calc_swings(h, l, SWING)
    dn_broke = up_broke = True
    iy_up = iy_dn = 0.0
    t_ms = 0
    bear_mss = [False] * n; bear_bos = [False] * n
    last_swing_high = [0.0] * n
    for i in range(n):
        if sl[i] != 0: dn_broke = True; iy_dn = sl[i]
        if sh[i] != 0: up_broke = True; iy_up = sh[i]
        # bearish break: close crosses under last swing low
        if i > 0 and iy_dn > 0 and c[i] < iy_dn and c[i - 1] >= iy_dn and dn_broke:
            mss = t_ms > 0            # reversal if prior structure was up
            dn_broke = False; t_ms = -1
            bear_mss[i] = mss; bear_bos[i] = not mss
        # bullish break: close crosses over last swing high (updates state only)
        if i > 0 and iy_up > 0 and c[i] > iy_up and c[i - 1] <= iy_up and up_broke:
            up_broke = False; t_ms = 1
        last_swing_high[i] = iy_up
    return bear_mss, bear_bos, last_swing_high


def simulate_day(day_df, prev_close, cap=200000):
    d = day_df.reset_index(drop=True)
    if len(d) < SWING + 4 or pd.isna(prev_close):
        return None
    o = d["o"].tolist(); h = d["h"].tolist(); l = d["l"].tolist(); c = d["c"].tolist()
    hm = d["hm"].tolist()
    bear_mss, bear_bos, lsh = bearish_signals(o, h, l, c)
    trig = bear_mss if SIGNAL == "MSS" else [bear_mss[i] or bear_bos[i] for i in range(len(c))]

    running_high = o[0]
    for i in range(len(c)):
        running_high = max(running_high, h[i])
        if hm[i] >= SQUAREOFF:
            break
        if not trig[i]:
            continue
        entry = c[i]
        if entry <= prev_close:                       # already filled, no room
            continue
        if (entry - prev_close) / entry < MIN_ROOM:   # not enough meat
            continue
        stop = max(running_high, lsh[i] if lsh[i] > 0 else running_high)
        if stop <= entry:
            stop = entry * 1.004
        target = prev_close
        risk = stop - entry
        qty = max(1, int(cap / entry))

        exit_px, reason = None, None
        for j in range(i + 1, len(c)):
            if h[j] >= stop: exit_px, reason = stop, "stop"; break
            if l[j] <= target: exit_px, reason = target, "target"; break
            if hm[j] >= SQUAREOFF: exit_px, reason = c[j], "squareoff"; break
        if exit_px is None:
            exit_px, reason = c[-1], "eod"

        gross = (entry - exit_px) * qty               # SHORT
        buy_val = exit_px * qty; sell_val = entry * qty
        cost = ob.costs(buy_val, sell_val)
        net = gross - cost
        return {"entry_hm": hm[i], "entry": entry, "exit": exit_px, "qty": qty,
                "stop": stop, "target": target, "reason": reason,
                "gross": gross, "cost": cost, "net": net, "R": risk * qty}
    return None


def prev_closes(df):
    daily = df.groupby("day").agg(open=("o", "first"), close=("c", "last"))
    daily["prev_close"] = daily["close"].shift(1)
    daily["gap"] = daily["open"] / daily["prev_close"] - 1
    return daily


# universe = cached movers (in tradeable_movers list)
movers = set(pd.read_csv(ROOT / "tradeable_movers.csv")["sym"])
files = [f for f in sorted(CACHE.glob("*_5m.csv")) if f.stem.replace("_5m", "") in movers]

all_tr = []
for f in files:
    sym = f.stem.replace("_5m", "")
    df = pd.read_csv(f)
    dt = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(IST)
    df["day"] = dt.dt.date; df["hm"] = dt.dt.strftime("%H:%M")
    daily = prev_closes(df)
    rows = []
    for day, dd in df.groupby("day"):
        g = daily.loc[day, "gap"]; pc = daily.loc[day, "prev_close"]
        if pd.isna(g) or not (GAP_LO < g <= GAP_HI):
            continue
        t = simulate_day(dd, pc)
        if t: t["sym"] = sym; t["day"] = day; rows.append(t)
    if rows:
        all_tr.append(pd.DataFrame(rows))

if not all_tr:
    print("No trades generated."); raise SystemExit

agg = pd.concat(all_tr, ignore_index=True)
net, gross, cost = agg["net"], agg["gross"], agg["cost"]
wins = net > 0
pd.set_option("display.width", 200)
pd.set_option("display.float_format", lambda x: f"{x:,.2f}")

print(f"SIGNAL={SIGNAL}  gap in ({GAP_LO*100:.1f}%,{GAP_HI*100:.1f}%]  slip={ob.SLIPPAGE*100:.2f}%/side")
print(f"Symbols with trades: {agg['sym'].nunique()}   total gap-fade shorts: {len(agg):,}\n")
print(f"win% = {wins.mean()*100:.1f}")
print(f"GROSS/trade = Rs{gross.mean():+.1f}   cost/trade = Rs{cost.mean():.1f}   "
      f"NET/trade = Rs{net.mean():+.1f}")
print(f"total: gross Rs{gross.sum():+,.0f}  costs Rs{cost.sum():,.0f}  NET Rs{net.sum():+,.0f}")
print(f"avg net R-multiple = {(net/agg['R']).mean():+.3f}")
print(f"exit reasons: {agg['reason'].value_counts().to_dict()}")
print("\nper-symbol net expectancy (top/bottom):")
per = agg.groupby("sym")["net"].agg(["mean", "count"]).sort_values("mean", ascending=False)
print(per.head(8).to_string()); print("..."); print(per.tail(5).to_string())
print("\nVERDICT:", "GROSS edge present" if gross.mean() > 0 else "no gross edge",
      "|", "NET POSITIVE" if net.mean() > 0 else "NET NEGATIVE after costs")

"""Same gap-fade + bearish-MSS test, but on 1-MINUTE bars (user request).
1-min fires MSS earlier -> shorts nearer the top -> more room to the gap fill.
Tests whether the finer timeframe creates the gross edge 5-min lacked.
Subset of 8 movers (incl. the two that were net-positive on 5-min).
"""
import sys, time
import pandas as pd, numpy as np
from pathlib import Path
from datetime import date, timedelta, timezone
import orb_backtest as ob
import fyers_client as fy

CACHE = Path(r"C:\Users\adars\sss\data\intraday_cache")
IST = timezone(timedelta(hours=5, minutes=30))

SUBSET = ["PARADEEP", "CHENNPETRO", "OLAELEC", "APOLLO",
          "RPOWER", "GMDCLTD", "CARTRADE", "DATAPATTNS"]
START, END = "2025-01-01", "2026-07-17"     # ~1.5yr of 1-min (keeps pull sane)
SWING, GAP_LO, GAP_HI = 3, 0.003, 0.03
SQUAREOFF, MIN_ROOM = "15:15", 0.003
ob.SLIPPAGE = 0.0005


def fetch_1m(sym):
    f = CACHE / f"{sym}_1m.csv"
    if f.exists():
        return pd.read_csv(f)
    s = date.fromisoformat(START); e = date.fromisoformat(END)
    rows, cur = [], s
    while cur <= e:
        nxt = min(e, cur + timedelta(days=60))
        for attempt in range(3):
            try:
                rows += fy.fetch_history(f"NSE:{sym}-EQ", cur.isoformat(), nxt.isoformat(), "1")
                break
            except Exception as ex:
                if attempt == 2: print(f"  ! {sym} {cur}: {ex}")
                time.sleep(1 + attempt)
        time.sleep(0.25); cur = nxt + timedelta(days=1)
    seen = {r[0]: r for r in rows}
    df = pd.DataFrame([seen[k] for k in sorted(seen)], columns=["ts","o","h","l","c","v"])
    df.to_csv(f, index=False); print(f"  {sym}: {len(df)} 1-min bars cached")
    return df


# --- MSS engine (identical port to the 5-min version) ---
def calc_swings(h, l, length):
    n = len(h); sh = [0.0]*n; sl = [0.0]*n; prev = 0
    for i in range(n):
        if i - length < 0: continue
        win_hi = max(h[i-length+1:i+1]); win_lo = min(l[i-length+1:i+1])
        h_len = h[i-length]; l_len = l[i-length]; pb = prev
        if h_len > win_hi: prev = 0
        elif l_len < win_lo: prev = 1
        if prev == 0 and pb != 0: sh[i] = h_len
        if prev == 1 and pb != 1: sl[i] = l_len
    return sh, sl

def bearish_signals(o, h, l, c):
    n = len(c); sh, sl = calc_swings(h, l, SWING)
    dn_broke = up_broke = True; iy_up = iy_dn = 0.0; t_ms = 0
    bear_mss = [False]*n; lsh = [0.0]*n
    for i in range(n):
        if sl[i] != 0: dn_broke = True; iy_dn = sl[i]
        if sh[i] != 0: up_broke = True; iy_up = sh[i]
        if i>0 and iy_dn>0 and c[i]<iy_dn and c[i-1]>=iy_dn and dn_broke:
            bear_mss[i] = t_ms > 0; dn_broke = False; t_ms = -1
        if i>0 and iy_up>0 and c[i]>iy_up and c[i-1]<=iy_up and up_broke:
            up_broke = False; t_ms = 1
        lsh[i] = iy_up
    return bear_mss, lsh

def simulate_day(d, prev_close, cap=200000):
    d = d.reset_index(drop=True)
    if len(d) < SWING+6 or pd.isna(prev_close): return None
    o=d["o"].tolist(); h=d["h"].tolist(); l=d["l"].tolist(); c=d["c"].tolist(); hm=d["hm"].tolist()
    bear_mss, lsh = bearish_signals(o,h,l,c)
    rh = o[0]
    for i in range(len(c)):
        rh = max(rh, h[i])
        if hm[i] >= SQUAREOFF: break
        if not bear_mss[i]: continue
        entry = c[i]
        if entry <= prev_close or (entry-prev_close)/entry < MIN_ROOM: continue
        stop = max(rh, lsh[i] if lsh[i]>0 else rh)
        if stop <= entry: stop = entry*1.004
        target = prev_close; risk = stop-entry; qty = max(1, int(cap/entry))
        exit_px = reason = None
        for j in range(i+1, len(c)):
            if h[j] >= stop: exit_px, reason = stop, "stop"; break
            if l[j] <= target: exit_px, reason = target, "target"; break
            if hm[j] >= SQUAREOFF: exit_px, reason = c[j], "squareoff"; break
        if exit_px is None: exit_px, reason = c[-1], "eod"
        gross = (entry-exit_px)*qty
        cost = ob.costs(exit_px*qty, entry*qty); net = gross-cost
        return {"entry_hm":hm[i],"reason":reason,"gross":gross,"cost":cost,"net":net,"R":risk*qty}
    return None


all_tr = []
for sym in SUBSET:
    df = fetch_1m(sym)
    if df.empty: continue
    dt = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(IST)
    df["day"] = dt.dt.date; df["hm"] = dt.dt.strftime("%H:%M")
    daily = df.groupby("day").agg(open=("o","first"), close=("c","last"))
    daily["prev_close"] = daily["close"].shift(1)
    daily["gap"] = daily["open"]/daily["prev_close"] - 1
    rows = []
    for day, dd in df.groupby("day"):
        g = daily.loc[day,"gap"]; pc = daily.loc[day,"prev_close"]
        if pd.isna(g) or not (GAP_LO < g <= GAP_HI): continue
        t = simulate_day(dd, pc)
        if t: t["sym"]=sym; rows.append(t)
    if rows: all_tr.append(pd.DataFrame(rows))

agg = pd.concat(all_tr, ignore_index=True)
net, gross, cost = agg["net"], agg["gross"], agg["cost"]
pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
print(f"\n1-MIN gap-fade + MSS | {agg['sym'].nunique()} stocks | trades={len(agg):,}")
print(f"win% = {(net>0).mean()*100:.1f}")
print(f"GROSS/trade = Rs{gross.mean():+.1f}   cost/trade = Rs{cost.mean():.1f}   NET/trade = Rs{net.mean():+.1f}")
print(f"total NET = Rs{net.sum():+,.0f}   avg net R = {(net/agg['R']).mean():+.3f}")
print(f"exits: {agg['reason'].value_counts().to_dict()}")
print("per-symbol NET/trade:")
print(agg.groupby('sym')['net'].agg(['mean','count']).sort_values('mean',ascending=False).to_string())
print("\nVS 5-MIN: gross was +Rs6.6/trade, net -Rs310. Did 1-min change it?")
print("VERDICT:", "GROSS edge present" if gross.mean()>0 else "no gross edge",
      "|", "NET POSITIVE" if net.mean()>0 else "NET NEGATIVE")

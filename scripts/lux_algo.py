"""'Premium Lux Algo' signal engine, ported faithfully, run SIDE-BY-SIDE with the
old 'Signals @Versomil' partial-TP strategy for comparison.

Lux entry signal (the only thing that fires trades in that indicator):
    Supertrend(source=close, ATR len 11, factor 5.5)
    bull = crossover(close, supertrend) AND close >= SMA(close,13)
    bear = crossunder(close, supertrend) AND close <= SMA(close,13)
Lux exit  = its 'Smart Trail' (ATR 13 x factor 4, Wilder-smoothed, 'modified' TR):
    exit long  when Smart-Trail Trend flips to -1,
    exit short when it flips to +1  (also reverse-on-opposite-signal, flat by EOD).

Everything else in that script (SuperIchi, TBO, Range Filter, reversal bands,
S/R, MACD candle color, the 'TP Points' x-marks) is visual overlay, not trades.

Run:  py lux_algo.py            # comparison table, all indices, 1m (where cached) & 5m
      py lux_algo.py save       # also write data/lux_vs_versomil.csv
"""
import sys, csv
from datetime import time
from pathlib import Path
import st_option_backtest as bt
import pine_strategy as ps

LUX_ATR = 11
LUX_FACTOR = 5.5
SMA_LEN = 13
TRAIL_ATR = 13
TRAIL_FACTOR = 4
DAY_OPEN = time(9, 15); NO_NEW = time(15, 0); FORCE_FLAT = time(15, 20)
OUT = Path(r"C:\Users\adars\sss\data\lux_vs_versomil.csv")


def sma(x, n):
    out = [0.0]*len(x); s = 0.0
    for i in range(len(x)):
        s += x[i]
        if i >= n:
            s -= x[i-n]
        out[i] = s/min(i+1, n)
    return out


def lux_supertrend(o, h, l, c, factor=LUX_FACTOR, atrlen=LUX_ATR):
    """Exact port of the Lux `supertrend(close, factor, atrLen)` (close source)."""
    n = len(c)
    atr = bt.wilder_atr(h, l, c, atrlen)
    st = [0.0]*n; direction = [1]*n
    prev_upper = prev_lower = 0.0; prev_st = 0.0
    for i in range(n):
        upper = c[i] + factor*atr[i]
        lower = c[i] - factor*atr[i]
        if i == 0:
            prev_upper, prev_lower = upper, lower
            direction[i] = 1; st[i] = upper; prev_st = st[i]
            continue
        lower = lower if (lower > prev_lower or c[i-1] < prev_lower) else prev_lower
        upper = upper if (upper < prev_upper or c[i-1] > prev_upper) else prev_upper
        if prev_st == prev_upper:
            direction[i] = -1 if c[i] > upper else 1
        else:
            direction[i] = 1 if c[i] < lower else -1
        st[i] = lower if direction[i] == -1 else upper
        prev_upper, prev_lower, prev_st = upper, lower, st[i]
    return st, direction


def smart_trail_trend(h, l, c, period=TRAIL_ATR, factor=TRAIL_FACTOR):
    """Port of the Smart Trail. Returns Trend[] (+1 up, -1 down); flip = exit."""
    n = len(c)
    # sma of (h-l)
    hl = [h[i]-l[i] for i in range(n)]
    hl_sma = sma(hl, period)
    tr = [0.0]*n
    for i in range(n):
        if i == 0:
            tr[i] = h[i]-l[i]; continue
        hilo = min(h[i]-l[i], 1.5*hl_sma[i])
        href = (h[i]-c[i-1]) if l[i] <= h[i-1] else (h[i]-c[i-1]-0.5*(l[i]-h[i-1]))
        lref = (c[i-1]-l[i]) if h[i] >= l[i-1] else (c[i-1]-l[i]-0.5*(l[i-1]-h[i]))
        tr[i] = max(hilo, href, lref)
    # Wilder MA of tr
    wild = [0.0]*n; w = 0.0
    for i in range(n):
        w = w + (tr[i]-w)/period
        wild[i] = w
    trend = [1]*n; tup = [0.0]*n; tdn = [0.0]*n
    for i in range(n):
        loss = factor*wild[i]
        up = c[i]-loss; dn = c[i]+loss
        if i == 0:
            tup[i] = up; tdn[i] = dn; trend[i] = 1; continue
        tup[i] = max(up, tup[i-1]) if c[i-1] > tup[i-1] else up
        tdn[i] = min(dn, tdn[i-1]) if c[i-1] < tdn[i-1] else dn
        trend[i] = 1 if c[i] > tdn[i-1] else (-1 if c[i] < tup[i-1] else trend[i-1])
    return trend


def lux_bt(dts, o, h, l, c, res, intraday=True, long_only=False):
    st, direc = lux_supertrend(o, h, l, c)
    sm = sma(c, SMA_LEN)
    trend = smart_trail_trend(h, l, c)
    trades = []; pos = None
    warm = max(LUX_ATR, TRAIL_ATR, SMA_LEN) + 2
    for i in range(warm, len(dts)):
        dt = dts[i]; tod = dt.time()
        bull = c[i] > st[i] and c[i-1] <= st[i-1] and c[i] >= sm[i]
        bear = c[i] < st[i] and c[i-1] >= st[i-1] and c[i] <= sm[i]
        if pos:
            newday = dt.date() != dts[pos["i"]].date()
            exitpx = None; why = None
            if intraday and (tod >= FORCE_FLAT or newday):
                exitpx = o[i] if newday else c[i]; why = "eod"
            elif pos["side"] == "L" and trend[i] == -1:
                exitpx = c[i]; why = "trail"
            elif pos["side"] == "S" and trend[i] == 1:
                exitpx = c[i]; why = "trail"
            elif pos["side"] == "L" and bear:
                exitpx = c[i]; why = "reverse"
            elif pos["side"] == "S" and bull:
                exitpx = c[i]; why = "reverse"
            if exitpx is not None:
                d = (exitpx-pos["e"]) if pos["side"] == "L" else (pos["e"]-exitpx)
                trades.append({"pts": d, "entry": pos["e"], "why": why}); pos = None
        if not pos and (not intraday or DAY_OPEN <= tod < NO_NEW):
            if bull: pos = {"side": "L", "e": c[i], "i": i}
            elif bear and not long_only: pos = {"side": "S", "e": c[i], "i": i}
    if pos:
        d = (c[-1]-pos["e"]) if pos["side"] == "L" else (pos["e"]-c[-1])
        trades.append({"pts": d, "entry": pos["e"], "why": "eod"})
    n = len(trades)
    if n == 0:
        return None
    rp = [t["pts"]/t["entry"]*100 for t in trades]
    pts = [t["pts"] for t in trades]
    wins = [x for x in rp if x > 0]; losses = [x for x in rp if x <= 0]
    pf = sum(wins)/-sum(losses) if losses and sum(losses) < 0 else 99.0
    return {"n": n, "wr": len(wins)/n*100, "pf": pf, "avg_pct": sum(rp)/n,
            "tot_pct": sum(rp), "tot_pts": sum(pts), "avg_pts": sum(pts)/n,
            "avgW": sum(wins)/len(wins) if wins else 0,
            "avgL": sum(losses)/len(losses) if losses else 0, "_trades": trades}


def agg_stats(trades):
    """Aggregate a raw list of {'pts','entry'} trades into the same stat dict."""
    n = len(trades)
    if n == 0:
        return None
    rp = [t["pts"]/t["entry"]*100 for t in trades]
    pts = [t["pts"] for t in trades]
    wins = [x for x in rp if x > 0]; losses = [x for x in rp if x <= 0]
    pf = sum(wins)/-sum(losses) if losses and sum(losses) < 0 else 99.0
    return {"n": n, "wr": len(wins)/n*100, "pf": pf, "avg_pct": sum(rp)/n,
            "tot_pct": sum(rp), "tot_pts": sum(pts), "avg_pts": sum(pts)/n,
            "avgW": sum(wins)/len(wins) if wins else 0,
            "avgL": sum(losses)/len(losses) if losses else 0}


def lux_run(res, idx):
    b = bt.load_bars(idx, res)
    return lux_bt([x[0] for x in b], [x[1] for x in b], [x[2] for x in b],
                  [x[3] for x in b], [x[4] for x in b], res, intraday=True)


def compare(save=False):
    import os
    idxs = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
    rows = []
    print(f"\n{'index':10} {'tf':>3} | {'strategy':16} {'n':>4} {'win%':>5} {'PF':>5} "
          f"{'avg%':>7} {'tot%':>8} {'totpts':>9}")
    print("-"*82)
    for idx in idxs:
        for res in ("1", "5"):
            path = bt.cache_path(idx, res) if hasattr(bt, "cache_path") else None
            try:
                v = ps.run(res, idx, intraday=True)     # old Versomil (primary)
            except SystemExit:
                print(f"{idx:10} {res:>3} | (no {res}m cache -- skip)")
                continue
            lx = lux_run(res, idx)                       # new Lux (comparison)
            for label, s in (("Versomil(TP1-4)", v), ("LuxAlgo", lx)):
                if not s:
                    print(f"{idx:10} {res:>3} | {label:16}  0 trades"); continue
                print(f"{idx:10} {res:>3} | {label:16} {s['n']:4d} {s['wr']:4.0f}% "
                      f"{s['pf']:5.2f} {s['avg_pct']:+6.3f} {s['tot_pct']:+7.1f} {s['tot_pts']:+9.0f}")
                rows.append({"index": idx, "tf": f"{res}m", "strategy": label,
                             "trades": s["n"], "win%": f"{s['wr']:.0f}", "PF": f"{s['pf']:.2f}",
                             "avg%": f"{s['avg_pct']:.3f}", "tot%": f"{s['tot_pct']:.1f}",
                             "tot_pts": f"{s['tot_pts']:.0f}", "avg_pts": f"{s['avg_pts']:.2f}"})
        print("-"*82)
    if save and rows:
        with OUT.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        print(f"saved -> {OUT}")


if __name__ == "__main__":
    compare(save=(len(sys.argv) > 1 and sys.argv[1] == "save"))

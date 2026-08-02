"""Faithful Pine strategy (Supertrend 15/5 flip entry + partial TPs at ATR
multiples + ATR SL). Runs on ANY price series -- index (from cache) or a real
option strike (fetched live).

Defaults from the Pine (ATR-based, et=ex2):
    TP1=1.5xATR(30%) TP2=3xATR(30%) TP3=5xATR(30%) TP4=9xATR(10%), SL=6xATR.

Usage:
    py pine_strategy.py            # print TP1 timing table (indices)
    py pine_strategy.py save       # write data/pine_all_indices_stats.csv
    py pine_strategy.py option     # apply directly on real 24000 CE/PE, 1m & 5m
"""
import sys, csv, statistics as sstat
from datetime import time
from pathlib import Path
import st_option_backtest as bt

TP_MULT = [1.5, 3.0, 5.0, 9.0]
TP_QTY  = [0.30, 0.30, 0.30, 0.10]
SL_MULT = 6.0
DAY_OPEN = time(9, 15); FORCE_FLAT = time(15, 20); NO_NEW = time(15, 0)
OUT = Path(r"C:\Users\adars\sss\data\pine_all_indices_stats.csv")


def _bt(dts, o, h, l, c, res, intraday=True, long_only=False):
    st, tr = bt.supertrend(h, l, c)
    atr = bt.wilder_atr(h, l, c, 14)
    trades = []; pos = None
    tp_hits = [0, 0, 0, 0]; sl_hits = 0
    t1_bars = []; t1_pts = []; t1_pct = []

    def open_pos(side, i):
        e = c[i]; a = atr[i]
        tps = [e + m*a for m in TP_MULT] if side == "L" else [e - m*a for m in TP_MULT]
        sl = e - SL_MULT*a if side == "L" else e + SL_MULT*a
        return {"side": side, "entry": e, "rem": 1.0, "tps": tps, "sl": sl, "i": i,
                "done": [False]*4, "pts": 0.0}

    def book(p, price, qty):
        d = (price - p["entry"]) if p["side"] == "L" else (p["entry"] - price)
        p["pts"] += d*qty; p["rem"] -= qty

    def close(p, dt, reason):
        trades.append({"pts": p["pts"], "entry": p["entry"], "reason": reason, "bars": None})

    for i in range(bt.ST_ATR_LEN+2, len(dts)):
        dt = dts[i]; tod = dt.time()
        fu = tr[i] == 1 and tr[i-1] == -1; fd = tr[i] == -1 and tr[i-1] == 1
        if pos:
            newday = dt.date() != dts[pos["i"]].date()
            if intraday and (tod >= FORCE_FLAT or newday):
                book(pos, o[i] if newday else c[i], pos["rem"]); close(pos, dt, "eod"); pos = None
            else:
                for k in range(4):
                    if pos and not pos["done"][k] and pos["rem"] > 1e-9:
                        hit = (pos["side"] == "L" and h[i] >= pos["tps"][k]) or \
                              (pos["side"] == "S" and l[i] <= pos["tps"][k])
                        if hit:
                            if k == 0:
                                t1_bars.append(i - pos["i"]); disp = abs(pos["tps"][0]-pos["entry"])
                                t1_pts.append(disp); t1_pct.append(disp/pos["entry"]*100)
                            book(pos, pos["tps"][k], TP_QTY[k]); pos["done"][k] = True; tp_hits[k] += 1
                if pos and pos["rem"] <= 1e-9:
                    close(pos, dt, "tp-all"); pos = None
                if pos:
                    slhit = (pos["side"] == "L" and l[i] <= pos["sl"]) or \
                            (pos["side"] == "S" and h[i] >= pos["sl"])
                    if slhit:
                        book(pos, pos["sl"], pos["rem"]); close(pos, dt, "sl"); sl_hits += 1; pos = None
                if pos and ((pos["side"] == "L" and fd) or (pos["side"] == "S" and fu)):
                    book(pos, c[i], pos["rem"]); close(pos, dt, "reverse"); pos = None
        if not pos and (not intraday or DAY_OPEN <= tod < NO_NEW):
            if fu: pos = open_pos("L", i)
            elif fd and not long_only: pos = open_pos("S", i)
    if pos:
        book(pos, c[-1], pos["rem"]); close(pos, dts[-1], "eod")

    n = len(trades)
    if n == 0:
        return None
    rp = [t["pts"]/t["entry"]*100 for t in trades]
    pts = [t["pts"] for t in trades]
    wins = [x for x in rp if x > 0]; losses = [x for x in rp if x <= 0]
    pf = sum(wins)/-sum(losses) if losses and sum(losses) < 0 else 99.0
    rmin = int(res)
    return {"n": n, "wr": len(wins)/n*100, "pf": pf, "avg_pct": sum(rp)/n, "tot_pct": sum(rp),
            "avgW": sum(wins)/len(wins) if wins else 0, "avgL": sum(losses)/len(losses) if losses else 0,
            "tp": [x/n*100 for x in tp_hits], "sl": sl_hits/n*100,
            "tot_pts": sum(pts), "avg_pts": sum(pts)/n,
            "t1_time_med": sstat.median([b*rmin for b in t1_bars]) if t1_bars else 0,
            "t1_disp_med_pts": sstat.median(t1_pts) if t1_pts else 0,
            "t1_disp_med_pct": sstat.median(t1_pct) if t1_pct else 0}


def run(res, idx="NIFTY", intraday=True, long_only=False):
    b = bt.load_bars(idx, res)
    s = _bt([x[0] for x in b], [x[1] for x in b], [x[2] for x in b],
            [x[3] for x in b], [x[4] for x in b], res, intraday, long_only)
    if s: s["idx"] = idx
    return s


def save_all(res="5"):
    rows = [run(res, ix, intraday=True) for ix in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX")]
    cols = ["idx", "n", "wr", "pf", "avg_pct", "tot_pct", "avgW", "avgL",
            "tp1%", "tp2%", "tp3%", "tp4%", "sl%", "tot_pts", "avg_pts",
            "tp1_time_med_min", "tp1_disp_med_pts", "tp1_disp_med_pct"]
    with OUT.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for r in rows:
            w.writerow([r["idx"], r["n"], f"{r['wr']:.1f}", f"{r['pf']:.2f}", f"{r['avg_pct']:.4f}",
                        f"{r['tot_pct']:.1f}", f"{r['avgW']:.4f}", f"{r['avgL']:.4f}",
                        f"{r['tp'][0]:.0f}", f"{r['tp'][1]:.0f}", f"{r['tp'][2]:.0f}", f"{r['tp'][3]:.0f}",
                        f"{r['sl']:.0f}", f"{r['tot_pts']:.0f}", f"{r['avg_pts']:.2f}",
                        f"{r['t1_time_med']:.0f}", f"{r['t1_disp_med_pts']:.1f}", f"{r['t1_disp_med_pct']:.3f}"])
    print(f"saved -> {OUT}")
    for r in rows:
        print(f"  {r['idx']:10} n={r['n']:4d} win {r['wr']:.0f}% PF {r['pf']:.2f} "
              f"avg {r['avg_pct']:+.3f}% total {r['tot_pts']:+,.0f} pts")


def run_option():
    import fyers_client as fy
    from datetime import date, timedelta, datetime, timezone
    IST = timezone(timedelta(hours=5, minutes=30))
    end = date.today()
    print("\nIndicator applied DIRECTLY on the real option strike (long-only, intraday):")
    print(f"{'contract':22} {'tf':>3} {'trades':>6} {'win%':>5} {'PF':>5} {'avg%':>7} {'total%':>8} {'TP1%':>5}")
    print("-"*66)
    for sym in ("NSE:NIFTY2680424000CE", "NSE:NIFTY2680424000PE"):
        for res in ("1", "5"):
            r = fy.fetch_history(sym, (end-timedelta(days=40)).isoformat(), end.isoformat(), res)
            if not r:
                print(f"{sym:22} {res:>3}m  no data"); continue
            dts = [datetime.fromtimestamp(x[0], IST) for x in r]
            s = _bt(dts, [x[1] for x in r], [x[2] for x in r], [x[3] for x in r],
                    [x[4] for x in r], res, intraday=True, long_only=True)
            if not s:
                print(f"{sym:22} {res:>3}m  0 trades"); continue
            print(f"{sym:22} {res:>3}m {s['n']:6d} {s['wr']:4.0f}% {s['pf']:5.2f} "
                  f"{s['avg_pct']:+7.3f} {s['tot_pct']:+8.1f} {s['tp'][0]:4.0f}%")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "timing"
    if cmd == "save":
        save_all("5")
    elif cmd == "option":
        run_option()
    else:
        for ix in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
            s = run("5", ix)
            print(f"{ix:10} win {s['wr']:.0f}% PF {s['pf']:.2f} TP1 {s['tp'][0]:.0f}% "
                  f"t1~{s['t1_time_med']:.0f}min disp~{s['t1_disp_med_pts']:.0f}pts")

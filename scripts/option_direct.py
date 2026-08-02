"""Apply Supertrend DIRECTLY on a single real option strike (1 month of live data)
and trade the option off its OWN signal. No index involved.

Long-only (you can only BUY the option): in when the option's Supertrend is up,
out when it flips down. Intraday only -> flat by 15:20, no overnight (theta).

Run:  py option_direct.py NSE:NIFTY2680424000CE
"""
import sys
from datetime import timedelta, time, datetime, timezone
import fyers_client as fy
import st_option_backtest as bt

IST = timezone(timedelta(hours=5, minutes=30))
LOT = 65
FORCE_FLAT = time(15, 20)
NO_NEW = time(15, 0)


def backtest(sym, res, lots=1, days=40):
    from datetime import date
    end = date.today()
    rows = fy.fetch_history(sym, (end - timedelta(days=days)).isoformat(), end.isoformat(), res)
    if not rows:
        print(f"  {sym} {res}m: no data"); return
    dts = [datetime.fromtimestamp(r[0], IST) for r in rows]
    h = [r[2] for r in rows]; l = [r[3] for r in rows]; c = [r[4] for r in rows]
    st, tr = bt.supertrend(h, l, c)
    qty = lots * LOT

    trades = []
    pos = None  # {entry, i}
    for i in range(17, len(rows)):
        dt = dts[i]; tod = dt.time()
        # EOD flat
        if pos and (tod >= FORCE_FLAT or dt.date() != dts[pos["i"]].date()):
            ex = c[i]
            g = (ex - pos["entry"]) * qty; fee = bt.charges(pos["entry"], ex, qty)
            trades.append({"in": dts[pos["i"]], "out": dt, "entry": pos["entry"],
                           "exit": ex, "net": g - fee, "reason": "eod"})
            pos = None
        if tod < time(9, 15) or tod >= FORCE_FLAT:
            continue
        up = tr[i] == 1 and tr[i-1] == -1
        dn = tr[i] == -1 and tr[i-1] == 1
        if pos and dn:                       # option Supertrend flipped down -> exit
            ex = c[i]; g = (ex - pos["entry"]) * qty; fee = bt.charges(pos["entry"], ex, qty)
            trades.append({"in": dts[pos["i"]], "out": dt, "entry": pos["entry"],
                           "exit": ex, "net": g - fee, "reason": "flip"})
            pos = None
        if not pos and up and tod < NO_NEW:  # Supertrend up -> buy the option
            pos = {"entry": c[i], "i": i}
    if pos:
        ex = c[-1]; g = (ex - pos["entry"]) * qty
        trades.append({"in": dts[pos["i"]], "out": dts[-1], "entry": pos["entry"],
                       "exit": ex, "net": g - bt.charges(pos["entry"], ex, qty), "reason": "eod"})

    if not trades:
        print(f"  {sym} {res}m: 0 trades"); return
    net = [t["net"] for t in trades]; tot = sum(net)
    w = sum(1 for x in net if x > 0)
    span = f"{dts[0].date()} -> {dts[-1].date()}"
    print(f"  {res:>2}m: {len(trades):3d} trades | win {w/len(trades)*100:3.0f}% | "
          f"NET Rs{tot:+8,.0f} | avg Rs{tot/len(trades):+6,.0f} | {span}")
    return trades


if __name__ == "__main__":
    syms = sys.argv[1:] or ["NSE:NIFTY2680424000CE", "NSE:NIFTY2680424000PE"]
    for sym in syms:
        print(f"\n{sym}  (Supertrend applied on the option itself, long-only, 1 lot):")
        for res in ("5", "1"):
            backtest(sym, res)

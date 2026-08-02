"""Rupee P&L each engine's signals would have made TODAY, per index.
Signal (index flip) -> buy ATM option, hold until opposite flip or EOD.
BS+VIX priced (VIX x index iv_mult), real Dhan charges."""
import sys
from datetime import date, timedelta, datetime, timezone, time
import fyers_client as fy
import st_option_backtest as bt
import lux_algo as la

IST = timezone(timedelta(hours=5, minutes=30))
VIX = 12.16
FORCE_FLAT = time(15, 20); NO_NEW = time(15, 0); DAY_OPEN = time(9, 15)


def today_bars(sym, res):
    e = date.today()
    r = fy.fetch_history(sym, (e-timedelta(days=1)).isoformat(), e.isoformat(), res)
    seen = {x[0]: x for x in r}; r = [seen[k] for k in sorted(seen)]
    if not r:
        return None, []
    latest = sorted({datetime.fromtimestamp(x[0], IST).date() for x in r})[-1]
    return latest, [x for x in r if datetime.fromtimestamp(x[0], IST).date() == latest]


def run(bars, engine, res, cfg, lots=1, show=True):
    step = cfg["step"]; lot = cfg["lot"]; exp = cfg["expiry"]; iv = VIX/100*cfg["iv_mult"]
    qty = lots*lot
    def prem(side, S, dt, K):
        return bt.bs_price(S, K, bt.tau_years(dt, exp), iv, side)
    dts = [datetime.fromtimestamp(x[0], IST) for x in bars]
    o = [x[1] for x in bars]; h = [x[2] for x in bars]; l = [x[3] for x in bars]; c = [x[4] for x in bars]
    if engine == "versomil":
        st, tr = bt.supertrend(h, l, c)
        sig = lambda i: (tr[i] == 1 and tr[i-1] == -1, tr[i] == -1 and tr[i-1] == 1)
    else:
        st, dr = la.lux_supertrend(o, h, l, c); sm = la.sma(c, la.SMA_LEN)
        sig = lambda i: (c[i] > st[i] and c[i-1] <= st[i-1] and c[i] >= sm[i],
                         c[i] < st[i] and c[i-1] >= st[i-1] and c[i] <= sm[i])
    trades = []; pos = None
    for i in range(bt.ST_ATR_LEN+2, len(bars)):
        dt = dts[i]; tod = dt.time(); up, dn = sig(i)
        if pos:
            opp = (pos["side"] == "CE" and dn) or (pos["side"] == "PE" and up)
            if tod >= FORCE_FLAT or opp:
                xp = prem(pos["side"], c[i], dt, pos["K"])
                trades.append({"net": (xp-pos["ep"])*qty - bt.charges(pos["ep"], xp, qty),
                               "side": pos["side"], "in": pos["t"], "out": tod.strftime("%H:%M"),
                               "ep": pos["ep"], "xp": xp}); pos = None
        if not pos and DAY_OPEN <= tod < NO_NEW and (up or dn):
            side = "CE" if up else "PE"; K = round(c[i]/step)*step
            pos = {"side": side, "K": K, "ep": prem(side, c[i], dt, K), "t": tod.strftime("%H:%M")}
    if pos:
        xp = prem(pos["side"], c[-1], dts[-1], pos["K"])
        trades.append({"net": (xp-pos["ep"])*qty - bt.charges(pos["ep"], xp, qty), "side": pos["side"],
                       "in": pos["t"], "out": dts[-1].time().strftime("%H:%M"), "ep": pos["ep"], "xp": xp})
    tot = sum(t["net"] for t in trades)
    if show:
        print(f"  {engine:8} {res}m ({lots}lot={qty}q): ", end="")
        if not trades:
            print("no trades -> Rs0"); return 0.0, 0
        print(f"{len(trades)} trade(s) -> Rs{tot:+,.0f}")
        for t in trades:
            print(f"       {t['side']} {t['in']}->{t['out']}  {t['ep']:.1f}->{t['xp']:.1f}  Rs{t['net']:+,.0f}")
    return tot, len(trades)


if __name__ == "__main__":
    names = sys.argv[1:] or ["BANKNIFTY", "SENSEX"]
    for name in names:
        cfg = bt.INDEXES[name]
        print("\n" + "="*60)
        for res in ("5", "1"):
            d, b = today_bars(cfg["sym"], res)
            if not b:
                print(f"{name} {res}m: no data"); continue
            rng = max(x[2] for x in b) - min(x[3] for x in b)
            print(f"{name} {d} {res}m | bars {len(b)} | O{b[0][1]:.0f} H{max(x[2] for x in b):.0f} "
                  f"L{min(x[3] for x in b):.0f} C{b[-1][4]:.0f} | range {rng:.0f}pt "
                  f"(lot {cfg['lot']}, {cfg['expiry']})")
            for eng in ("versomil", "lux"):
                run(b, eng, res, cfg, lots=1)

"""Last ~week: per-day trades + rupee P&L each engine would have made per index.
Signal (index flip) -> ATM option, hold to opposite flip / EOD. BS+VIX, charges.
Indicators run continuously across days (realistic); positions flat by 15:20."""
import sys
from collections import defaultdict, OrderedDict
from datetime import date, timedelta, datetime, timezone, time
import fyers_client as fy
import st_option_backtest as bt
import lux_algo as la

IST = timezone(timedelta(hours=5, minutes=30))
FORCE_FLAT = time(15, 20); NO_NEW = time(15, 0); DAY_OPEN = time(9, 15)
DAYS = 9  # calendar lookback to capture ~5 trading days


def bars(sym, res):
    e = date.today()
    r = fy.fetch_history(sym, (e-timedelta(days=DAYS)).isoformat(), e.isoformat(), res)
    seen = {x[0]: x for x in r}
    return [seen[k] for k in sorted(seen)]


def vix_series():
    r = bars("NSE:INDIAVIX-INDEX", "D")
    return {datetime.fromtimestamp(x[0], IST).date(): x[4] for x in r}


def run(rows, engine, cfg, vixmap, lots=1):
    step = cfg["step"]; lot = cfg["lot"]; exp = cfg["expiry"]; ivm = cfg["iv_mult"]; qty = lots*lot
    dts = [datetime.fromtimestamp(x[0], IST) for x in rows]
    o = [x[1] for x in rows]; h = [x[2] for x in rows]; l = [x[3] for x in rows]; c = [x[4] for x in rows]
    def vfor(d):
        if d in vixmap: return vixmap[d]/100*ivm
        pri = [k for k in vixmap if k <= d]
        return (vixmap[max(pri)] if pri else 13.0)/100*ivm
    def prem(side, S, dt, K):
        return bt.bs_price(S, K, bt.tau_years(dt, exp), vfor(dt.date()), side)
    if engine == "versomil":
        st, tr = bt.supertrend(h, l, c)
        sig = lambda i: (tr[i] == 1 and tr[i-1] == -1, tr[i] == -1 and tr[i-1] == 1)
    else:
        st, dr = la.lux_supertrend(o, h, l, c); sm = la.sma(c, la.SMA_LEN)
        sig = lambda i: (c[i] > st[i] and c[i-1] <= st[i-1] and c[i] >= sm[i],
                         c[i] < st[i] and c[i-1] >= st[i-1] and c[i] <= sm[i])
    perday = defaultdict(lambda: [0.0, 0])  # date -> [pnl, ntrades]
    pos = None
    for i in range(bt.ST_ATR_LEN+2, len(rows)):
        dt = dts[i]; tod = dt.time(); up, dn = sig(i)
        if pos:
            opp = (pos["side"] == "CE" and dn) or (pos["side"] == "PE" and up)
            if tod >= FORCE_FLAT or opp or dt.date() != pos["d"]:
                xp = prem(pos["side"], (o[i] if dt.date() != pos["d"] else c[i]), dt, pos["K"])
                net = (xp-pos["ep"])*qty - bt.charges(pos["ep"], xp, qty)
                perday[pos["d"]][0] += net; perday[pos["d"]][1] += 1; pos = None
        if not pos and DAY_OPEN <= tod < NO_NEW and (up or dn):
            side = "CE" if up else "PE"; K = round(c[i]/step)*step
            pos = {"side": side, "K": K, "ep": prem(side, c[i], dt, K), "d": dt.date()}
    return perday


if __name__ == "__main__":
    names = sys.argv[1:] or ["NIFTY", "BANKNIFTY", "SENSEX"]
    vixmap = vix_series()
    for name in names:
        cfg = bt.INDEXES[name]
        r5 = bars(cfg["sym"], "5"); r1 = bars(cfg["sym"], "1")
        days = sorted({datetime.fromtimestamp(x[0], IST).date() for x in r5})[-5:]
        rng = {d: 0 for d in days}
        for x in r5:
            d = datetime.fromtimestamp(x[0], IST).date()
            if d in rng: rng[d] = max(rng[d], x[2])
        v5 = {e: run(r5, e, cfg, vixmap) for e in ("versomil", "lux")}
        v1 = {e: run(r1, e, cfg, vixmap) for e in ("versomil", "lux")}
        print("\n" + "="*72)
        print(f"{name}  (1 lot = {cfg['lot']}q, {cfg['expiry']})   last {len(days)} trading days")
        print(f"{'date':12} | {'5m Verso':>16} | {'5m Lux':>16} | {'1m Verso':>13} | {'1m Lux':>13}")
        print("-"*72)
        tot = defaultdict(float)
        for d in days:
            def cell(v, e):
                p, n = v[e].get(d, [0.0, 0]); tot[(e, id(v))] += p
                return f"{n}t Rs{p:+,.0f}" if n else "0t  --"
            print(f"{d.isoformat():12} | {cell(v5,'versomil'):>16} | {cell(v5,'lux'):>16} | "
                  f"{cell(v1,'versomil'):>13} | {cell(v1,'lux'):>13}")
        s5v = sum(v5['versomil'][d][0] for d in days); s5l = sum(v5['lux'][d][0] for d in days)
        s1v = sum(v1['versomil'][d][0] for d in days); s1l = sum(v1['lux'][d][0] for d in days)
        n5v = sum(v5['versomil'][d][1] for d in days); n5l = sum(v5['lux'][d][1] for d in days)
        n1v = sum(v1['versomil'][d][1] for d in days); n1l = sum(v1['lux'][d][1] for d in days)
        print("-"*72)
        print(f"{'WEEK':12} | {f'{n5v}t Rs{s5v:+,.0f}':>16} | {f'{n5l}t Rs{s5l:+,.0f}':>16} | "
              f"{f'{n1v}t Rs{s1v:+,.0f}':>13} | {f'{n1l}t Rs{s1l:+,.0f}':>13}")

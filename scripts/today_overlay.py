"""Overlay today's Supertrend(Versomil) + Lux signals on the user's actual Dhan
trades for NIFTY. Prints every flip with time/price/direction and the index level
at each of the user's entries/exits."""
from datetime import date, timedelta, datetime, timezone, time
import fyers_client as fy
import st_option_backtest as bt
import lux_algo as la

IST = timezone(timedelta(hours=5, minutes=30))

# user's actual trades today (from Executed_Orders): time, side(index-view), contract, opt price
USER = [
    ("09:28", "PUT-buy (bearish)", "24300PE", 143.15),
    ("09:31", "PUT-sell (exit)",   "24300PE", 136.975),
    ("09:34", "PUT-buy (bearish)", "24300PE", 142.80),
    ("09:38", "PUT-sell (exit)",   "24300PE", 148.10),
    ("10:35", "CALL-buy (bullish)","24200CE", 124.60),
    ("10:52", "CALL-sell (exit)",  "24200CE", 138.15),
]


def today_bars(res):
    e = date.today()
    r = fy.fetch_history("NSE:NIFTY50-INDEX", (e-timedelta(days=1)).isoformat(), e.isoformat(), res)
    seen = {x[0]: x for x in r}                       # dedupe by timestamp
    r = [seen[k] for k in sorted(seen)]
    days = sorted({datetime.fromtimestamp(x[0], IST).date() for x in r})
    latest = days[-1]
    return latest, [x for x in r if datetime.fromtimestamp(x[0], IST).date() == latest]


def flips(bars, st_fn, label, res):
    dts = [datetime.fromtimestamp(x[0], IST) for x in bars]
    o = [x[1] for x in bars]; h = [x[2] for x in bars]; l = [x[3] for x in bars]; c = [x[4] for x in bars]
    if st_fn == "versomil":
        st, tr = bt.supertrend(h, l, c)          # hl2, 15, 5
        sig = lambda i: (tr[i] == 1 and tr[i-1] == -1, tr[i] == -1 and tr[i-1] == 1)
    else:
        st, direc = la.lux_supertrend(o, h, l, c)  # close, 11, 5.5
        sm = la.sma(c, la.SMA_LEN)
        sig = lambda i: (c[i] > st[i] and c[i-1] <= st[i-1] and c[i] >= sm[i],
                         c[i] < st[i] and c[i-1] >= st[i-1] and c[i] <= sm[i])
    out = []
    for i in range(bt.ST_ATR_LEN+2, len(bars)):
        up, dn = sig(i)
        if up: out.append((dts[i].strftime("%H:%M"), "BUY  (CE)", c[i]))
        elif dn: out.append((dts[i].strftime("%H:%M"), "SELL (PE)", c[i]))
    print(f"\n{label} on NIFTY {res}m today -- flips:")
    if not out:
        print("  (no flips)")
    for t, d, p in out:
        print(f"   {t}  {d}  @ {p:.1f}")
    return out


def idx_at(bars):
    """map HH:MM -> index close for annotating user trades (5m/1m nearest)."""
    m = {}
    for x in bars:
        m[datetime.fromtimestamp(x[0], IST).strftime("%H:%M")] = x[4]
    return m


def nearest(m, hhmm):
    if hhmm in m: return m[hhmm]
    hh, mm = int(hhmm[:2]), int(hhmm[3:])
    tgt = hh*60+mm
    best = min(m.keys(), key=lambda k: abs((int(k[:2])*60+int(k[3:]))-tgt))
    return m[best]


if __name__ == "__main__":
    d1, b1 = today_bars("1")
    d5, b5 = today_bars("5")
    print(f"NIFTY {d5}: bars 1m={len(b1)} 5m={len(b5)} | "
          f"O {b5[0][1]:.1f} H {max(x[2] for x in b5):.1f} L {min(x[3] for x in b5):.1f} C {b5[-1][4]:.1f}")
    m1 = idx_at(b1)
    print("\nYour actual trades (index level at that minute):")
    for t, what, con, px in USER:
        print(f"   {t}  {what:20} {con:8} opt@{px:7.2f}  | NIFTY ~{nearest(m1, t):.1f}")
    flips(b5, "versomil", "Versomil ST(15/5,hl2)", "5")
    flips(b5, "lux", "Lux ST(11/5.5,close)+SMA13", "5")
    flips(b1, "versomil", "Versomil ST(15/5,hl2)", "1")

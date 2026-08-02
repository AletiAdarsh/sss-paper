"""Option's OWN Supertrend buy signal, but only executed when the INDEX 5m
trend agrees:  CE buy only if index is GREEN (up),  PE buy only if index is RED.

Tests whether the index-trend filter rescues the (theta-noisy) option-own signal.
Real 1-month option data (24000 CE & PE), long-only, intraday, flat by EOD.

Run:  py option_index_filter.py
"""
from datetime import date, timedelta, datetime, timezone, time
import fyers_client as fy
import st_option_backtest as bt

IST = timezone(timedelta(hours=5, minutes=30))
LOT = 65
FORCE_FLAT = time(15, 20); NO_NEW = time(15, 0)


import bisect

def index_trend_lookup():
    """Return fn(ts)->index 5m trend of the last CLOSED 5m bar at time ts (no look-ahead)."""
    b = bt.load_bars("NIFTY", "5")
    h = [x[2] for x in b]; l = [x[3] for x in b]; c = [x[4] for x in b]
    st, tr = bt.supertrend(h, l, c)
    close_ts = [int(b[i][0].timestamp()) + 300 for i in range(len(b))]   # 5m bar close epoch
    def at(ts):
        j = bisect.bisect_right(close_ts, ts) - 1
        return tr[j] if j >= 0 else 0
    return at


def run(sym, want_index, label, itr, res="1", days=40):
    """want_index: +1 => require index GREEN (CE);  -1 => require index RED (PE);
    None => no filter."""
    end = date.today()
    rows = fy.fetch_history(sym, (end-timedelta(days=days)).isoformat(), end.isoformat(), res)
    if not rows:
        print(f"  {label}: no data"); return
    dts = [datetime.fromtimestamp(r[0], IST) for r in rows]
    h = [r[2] for r in rows]; l = [r[3] for r in rows]; c = [r[4] for r in rows]
    st, tr = bt.supertrend(h, l, c)
    trades = []; pos = None
    for i in range(17, len(rows)):
        dt = dts[i]; tod = dt.time()
        if pos and (tod >= FORCE_FLAT or dt.date() != dts[pos["i"]].date()):
            ex = c[i]; trades.append((ex-pos["e"])*LOT - bt.charges(pos["e"], ex, LOT)); pos = None
        if tod < time(9, 15) or tod >= FORCE_FLAT:
            continue
        up = tr[i] == 1 and tr[i-1] == -1; dn = tr[i] == -1 and tr[i-1] == 1
        if pos and dn:
            ex = c[i]; trades.append((ex-pos["e"])*LOT - bt.charges(pos["e"], ex, LOT)); pos = None
        if not pos and up and tod < NO_NEW:
            idx_ok = want_index is None or itr(int(rows[i][0])) == want_index
            if idx_ok:
                pos = {"e": c[i], "i": i}
    if pos:
        ex = c[-1]; trades.append((ex-pos["e"])*LOT - bt.charges(pos["e"], ex, LOT))
    if not trades:
        print(f"  {label}: 0 trades (filter blocked all)"); return
    tot = sum(trades); w = sum(1 for x in trades if x > 0)
    print(f"  {label:38}: {len(trades):3d} trades | win {w/len(trades)*100:3.0f}% | "
          f"NET Rs{tot:+8,.0f} | avg Rs{tot/len(trades):+6,.0f}")


if __name__ == "__main__":
    itr = index_trend_lookup()
    print("\n24000 CE (option's own 1m buy signal, filtered by INDEX 5m trend):")
    run("NSE:NIFTY2680424000CE", None, "unfiltered", itr, res="1")
    run("NSE:NIFTY2680424000CE", +1, "ONLY if index 5m GREEN (agree)", itr, res="1")
    run("NSE:NIFTY2680424000CE", -1, "ONLY if index 5m RED (disagree, sanity)", itr, res="1")
    print("\n24000 PE (option's own 1m buy signal, filtered by INDEX 5m trend):")
    run("NSE:NIFTY2680424000PE", None, "unfiltered", itr, res="1")
    run("NSE:NIFTY2680424000PE", -1, "ONLY if index 5m RED (agree)", itr, res="1")
    run("NSE:NIFTY2680424000PE", +1, "ONLY if index 5m GREEN (disagree, sanity)", itr, res="1")

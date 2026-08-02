"""Pick N random Nifty-50 stocks, apply Supertrend(15,5) on each across
1m/5m/15m/1H over all available Fyers history, and report the stats.

Trade model: classic long/short REVERSAL — go long on an up-flip, reverse to
short on a down-flip (position always in the market). Returns are per-trade %,
carried across days (equity, no theta). Compared to buy & hold.

Run:  py st_stock_backtest.py            # 5 random
      py st_stock_backtest.py INFY TCS   # specific
"""
import sys, random
from datetime import date, timedelta, datetime, timezone
import fyers_client as fy
import st_option_backtest as bt

IST = timezone(timedelta(hours=5, minutes=30))
NIFTY50 = [
    "RELIANCE","HDFCBANK","ICICIBANK","INFY","TCS","ITC","LT","SBIN","BHARTIARTL",
    "KOTAKBANK","HINDUNILVR","AXISBANK","BAJFINANCE","ASIANPAINT","MARUTI","TITAN",
    "SUNPHARMA","NESTLEIND","ULTRACEMCO","WIPRO","ONGC","NTPC","POWERGRID","M&M",
    "TATASTEEL","JSWSTEEL","HCLTECH","ADANIENT","ADANIPORTS","COALINDIA","GRASIM",
    "BAJAJFINSV","BAJAJ-AUTO","HDFCLIFE","SBILIFE","BRITANNIA","DRREDDY","CIPLA",
    "EICHERMOT","HEROMOTOCO","TECHM","INDUSINDBK","APOLLOHOSP","HINDALCO","BPCL",
    "TATACONSUM","SHRIRAMFIN","TRENT","BEL","JIOFIN",
]
LOOKBACK = {"1": 250, "5": 500, "15": 900, "60": 1500}   # days back per resolution


def fetch(sym, res):
    end = date.today(); rows = []; cur = end - timedelta(days=LOOKBACK[res])
    while cur <= end:
        nxt = min(end, cur + timedelta(days=90))
        try:
            rows += fy.fetch_history(f"NSE:{sym}-EQ", cur.isoformat(), nxt.isoformat(), res)
        except Exception:
            pass
        cur = nxt + timedelta(days=1)
    seen = {r[0]: r for r in rows}
    return [seen[k] for k in sorted(seen)]


def st_stats(rows, long_only=True):
    """Supertrend flips. long_only=True -> buy on up-flip, exit (flat) on down-flip,
    never short, no separate SL. Returns dict of stats."""
    h = [r[2] for r in rows]; l = [r[3] for r in rows]; c = [r[4] for r in rows]
    st, tr = bt.supertrend(h, l, c)
    rets = []
    entry = None; side = None
    for i in range(bt.ST_ATR_LEN + 2, len(rows)):
        flip_up = tr[i] == 1 and tr[i-1] == -1
        flip_dn = tr[i] == -1 and tr[i-1] == 1
        if entry is not None and (flip_up or flip_dn):
            r = (c[i] - entry) / entry if side == "L" else (entry - c[i]) / entry
            rets.append(r * 100)
            entry = None
        if flip_up:
            entry, side = c[i], "L"
        elif flip_dn and not long_only:
            entry, side = c[i], "S"
    if entry is not None:                       # close final open trade at last bar
        r = (c[-1] - entry) / entry if side == "L" else (entry - c[-1]) / entry
        rets.append(r * 100)
    if not rets:
        return None
    wins = [x for x in rets if x > 0]; losses = [x for x in rets if x <= 0]
    tot = sum(rets)
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf")
    bh = (c[-1] - c[0]) / c[0] * 100
    dt0 = datetime.fromtimestamp(rows[0][0], IST).date()
    dt1 = datetime.fromtimestamp(rows[-1][0], IST).date()
    return {"bars": len(rows), "span": (dt1 - dt0).days, "from": dt0,
            "trades": len(rets), "win": len(wins)/len(rets)*100, "tot": tot,
            "avg": tot/len(rets), "pf": pf, "bh": bh}


if __name__ == "__main__":
    picks = sys.argv[1:] or random.sample(NIFTY50, 5)
    print(f"Stocks: {', '.join(picks)}\n")
    print(f"{'stock':10} {'tf':>4} {'bars':>7} {'days':>5} {'trades':>6} "
          f"{'win%':>5} {'tot%':>8} {'avg%':>6} {'PF':>5} {'buy&hold%':>9}")
    print("-" * 78)
    for sym in picks:
        for res in ("1", "5", "15", "60"):
            try:
                r = fetch(sym, res)
                s = st_stats(r) if r else None
            except Exception as e:
                print(f"{sym:10} {res:>3}m  err {str(e)[:30]}"); continue
            if not s:
                print(f"{sym:10} {res:>3}m  no data"); continue
            print(f"{sym:10} {res:>3}m {s['bars']:7,} {s['span']:5d} {s['trades']:6d} "
                  f"{s['win']:5.0f} {s['tot']:+8.0f} {s['avg']:+6.2f} {s['pf']:5.2f} {s['bh']:+9.0f}")
        print()

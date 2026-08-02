"""Rank the Nifty 50 by volatility (avg daily range %) and liquidity (turnover).
Most volatile + most traded = best intraday movers.

Run:  py nifty50_movers.py
"""
from datetime import date, timedelta
import fyers_client as fy

NIFTY50 = [
    "RELIANCE","HDFCBANK","ICICIBANK","INFY","TCS","ITC","LT","SBIN","BHARTIARTL",
    "KOTAKBANK","HINDUNILVR","AXISBANK","BAJFINANCE","ASIANPAINT","MARUTI","TITAN",
    "SUNPHARMA","NESTLEIND","ULTRACEMCO","WIPRO","ONGC","NTPC","POWERGRID","M&M",
    "TATAMOTORS","TATASTEEL","JSWSTEEL","HCLTECH","ADANIENT","ADANIPORTS","COALINDIA",
    "GRASIM","BAJAJFINSV","BAJAJ-AUTO","HDFCLIFE","SBILIFE","BRITANNIA","DRREDDY",
    "CIPLA","EICHERMOT","HEROMOTOCO","TECHM","INDUSINDBK","APOLLOHOSP","HINDALCO",
    "BPCL","TATACONSUM","SHRIRAMFIN","TRENT","BEL","JIOFIN",
]


def stats(sym, days=95):
    end = date.today()
    rows = fy.fetch_history(f"NSE:{sym}-EQ", (end - timedelta(days=days)).isoformat(),
                            end.isoformat(), "D")
    if len(rows) < 20:
        return None
    rng, tos, moves = [], [], []
    for k in range(1, len(rows)):
        o, hi, lo, c, v = rows[k][1], rows[k][2], rows[k][3], rows[k][4], rows[k][5]
        pc = rows[k-1][4]
        if pc <= 0:
            continue
        rng.append((hi - lo) / pc * 100)          # daily range %
        tos.append(c * v / 1e7)                    # turnover in Rs cr
        moves.append(abs(c / pc - 1) * 100)        # close-to-close move %
    n = len(rng)
    return {
        "sym": sym, "adr": sum(rng)/n, "turn": sum(tos)/n,
        "pct2": sum(1 for m in moves if m >= 2)/n*100,
        "last": rows[-1][4], "days": n,
    }


rows = []
for s in NIFTY50:
    try:
        r = stats(s)
        if r: rows.append(r)
    except Exception as e:
        print(f"  {s}: err {str(e)[:40]}")

rows.sort(key=lambda x: -x["adr"])
print(f"\nNifty 50 ranked by volatility (avg daily range %), ~{rows[0]['days']}d\n")
print(f"{'#':>2} {'symbol':12} {'ADR%':>6} {'>2%days':>7} {'turnover(cr)':>12} {'last':>9}")
print("-" * 54)
for i, r in enumerate(rows, 1):
    print(f"{i:2d} {r['sym']:12} {r['adr']:6.2f} {r['pct2']:6.0f}% {r['turn']:11,.0f} {r['last']:9,.1f}")

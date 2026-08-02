"""For each stock in a Groww holdings xlsx, apply Supertrend(15,5) on the DAILY
chart: report current trend (UP/DOWN), the last signal (flip) date/price, a
long-only backtest stat, and current 1H state.

Run:  py holdings_supertrend.py
"""
from datetime import date, timedelta, datetime, timezone
import pandas as pd
import fyers_client as fy
import st_option_backtest as bt

IST = timezone(timedelta(hours=5, minutes=30))
HOLD = r"C:\Users\adars\Downloads\Stocks_Holdings_Statement_9171416127_20-07-2026.xlsx"
CONST = r"C:\Users\adars\sss\data\nifty_total_market_constituents.csv"

# hardcoded fallbacks for names not in the constituents file
FALLBACK = {
    "INE153T01027": "BLS", "INE758T01015": "ETERNAL", "INE093A01041": "HEXT",
    "INE249Z01020": "MAZDOCK", "INE531F01023": "NUVAMA", "INE045601023": "PARAS",
    "INE940H01022": "PGIL", "INE105J01010": "RPGLIFE", "INE151G01028": "SHAILY",
    "INE673O01025": "TBOTEK", "INE956G01038": "VMM", "INE270I01022": "VISHNU",
    "INE382Z01011": "GRSE", "INE066F01020": "HAL", "INE752E01010": "POWERGRID",
    "INE160A01022": "PNB", "INE221J01015": "SHARDACROP", "INE508G01029": "TIMETECHNO",
    "INE849A01020": "TRENT", "INE01EA01019": "WABAG",
}


def isin_map():
    df = pd.read_csv(CONST)
    return dict(zip(df["ISIN Code"], df["Symbol"]))


def fetch(sym, res, days):
    end = date.today(); rows = []; cur = end - timedelta(days=days)
    while cur <= end:
        nxt = min(end, cur + timedelta(days=(360 if res == "D" else 90)))
        try:
            rows += fy.fetch_history(f"NSE:{sym}-EQ", cur.isoformat(), nxt.isoformat(), res)
        except Exception:
            pass
        cur = nxt + timedelta(days=1)
    seen = {r[0]: r for r in rows}
    return [seen[k] for k in sorted(seen)]


def analyse(rows):
    h = [r[2] for r in rows]; l = [r[3] for r in rows]; c = [r[4] for r in rows]
    st, tr = bt.supertrend(h, l, c)
    # last flip
    last_i = None
    for i in range(len(rows)-1, bt.ST_ATR_LEN, -1):
        if tr[i] != tr[i-1]:
            last_i = i; break
    # long-only stat
    rets = []; entry = None
    for i in range(bt.ST_ATR_LEN+2, len(rows)):
        up = tr[i] == 1 and tr[i-1] == -1; dn = tr[i] == -1 and tr[i-1] == 1
        if entry is not None and dn:
            rets.append((c[i]-entry)/entry*100); entry = None
        if up: entry = c[i]
    if entry is not None: rets.append((c[-1]-entry)/entry*100)
    pf = 0
    if rets:
        wsum = sum(x for x in rets if x > 0); lsum = -sum(x for x in rets if x <= 0)
        pf = wsum/lsum if lsum else 99
        tot = sum(rets); win = sum(1 for x in rets if x > 0)/len(rets)*100
    else:
        tot = win = 0
    bh = (c[-1]-c[0])/c[0]*100
    flip = None
    if last_i is not None:
        fd = datetime.fromtimestamp(rows[last_i][0], IST).date()
        flip = (fd, "BUY" if tr[last_i] == 1 else "SELL", rows[last_i][4])
    return {"state": "UP" if tr[-1] == 1 else "DOWN", "flip": flip,
            "pf": pf, "tot": tot, "win": win, "bh": bh, "trades": len(rets),
            "last_px": c[-1]}


def main():
    df = pd.read_excel(HOLD, header=10)
    df.columns = [str(c).strip() for c in df.columns]
    imap = isin_map()
    print(f"{'stock':11} {'dTrend':>6} {'last daily signal':>22} {'PF':>5} {'strat%':>7} {'B&H%':>7} {'1H':>5}")
    print("-"*74)
    for _, row in df.iterrows():
        isin = row["ISIN"]; name = str(row["Stock Name"])[:20]
        sym = imap.get(isin) or FALLBACK.get(isin)
        if not sym:
            print(f"{name:11} unmapped ISIN {isin}"); continue
        try:
            dr = fetch(sym, "D", 1400)
            if len(dr) < 40:
                print(f"{sym:11} insufficient daily data"); continue
            d = analyse(dr)
            hr = fetch(sym, "60", 90)
            h1 = analyse(hr)["state"] if hr and len(hr) > 40 else "?"
            fl = d["flip"]
            fs = f"{fl[0]} {fl[1]} @{fl[2]:.0f}" if fl else "-"
            mark = "" if d["state"] == "UP" else " <-"
            print(f"{sym:11} {d['state']:>6} {fs:>22} {d['pf']:5.2f} {d['tot']:+7.0f} {d['bh']:+7.0f} {h1:>5}{mark}")
        except Exception as e:
            print(f"{sym:11} err {str(e)[:34]}")


if __name__ == "__main__":
    main()

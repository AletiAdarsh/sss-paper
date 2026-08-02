"""Live futures OI + basis for an NSE F&O stock, via Fyers depth endpoint.

Unlike the NSE bhavcopy (end-of-day only), this updates intraday.

  py scripts/live_oi.py KALYANKJIL            # one shot
  py scripts/live_oi.py KALYANKJIL --watch 60 # refresh every 60s
"""
import sys, json, time, argparse, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fyers_client import creds

DEPTH = "https://api-t1.fyers.in/data/depth"
QUOTES = "https://api-t1.fyers.in/data/quotes"
IST = timezone(timedelta(hours=5, minutes=30))

# Fyers front-month futures suffix, e.g. 26JULFUT. Roll manually after expiry.
def fut_symbol(sym, expiry):
    return f"NSE:{sym}{expiry}FUT"


def _get(url, params):
    c = creds()
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": f'{c["app_id"]}:{c["access_token"]}',
                 "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())


def snapshot(sym, expiry):
    fut = fut_symbol(sym, expiry)
    d = _get(DEPTH, {"symbol": fut, "ohlcv_flag": "1"})["d"][fut]
    spot = _get(QUOTES, {"symbols": f"NSE:{sym}-EQ"})["d"][0]["v"]

    oi, pdoi = d["oi"], d["pdoi"]
    ltp, prev = d["ltp"], d["c"]
    px_chg = (ltp / prev - 1) * 100
    oi_chg = (oi / pdoi - 1) * 100 if pdoi else float("nan")

    # price/OI quadrant -> what the new money is doing
    if px_chg > 0 and oi_chg > 0:
        read, mean = "LONG BUILDUP", "fresh positions entering on a rising price"
    elif px_chg > 0 and oi_chg <= 0:
        read, mean = "SHORT COVERING", "shorts buying back to close - squeeze unwinding"
    elif px_chg <= 0 and oi_chg > 0:
        read, mean = "SHORT BUILDUP", "fresh shorts entering on a falling price"
    else:
        read, mean = "LONG UNWINDING", "longs closing out"

    basis = ltp - spot["lp"]
    basis_pct = basis / spot["lp"] * 100
    return {
        "t": datetime.now(IST), "spot": spot["lp"], "spot_chg": spot["chp"],
        "fut": ltp, "fut_chg": px_chg, "oi": oi, "pdoi": pdoi, "oi_chg": oi_chg,
        "basis": basis, "basis_pct": basis_pct, "read": read, "meaning": mean,
        "upper_ckt": d.get("upper_ckt"), "lower_ckt": d.get("lower_ckt"),
    }


def show(s, sym):
    print(f"\n{sym}  @ {s['t']:%H:%M:%S IST}")
    print(f"  spot     {s['spot']:>10,.2f}  ({s['spot_chg']:+.2f}%)")
    print(f"  futures  {s['fut']:>10,.2f}  ({s['fut_chg']:+.2f}%)   circuit {s['lower_ckt']}-{s['upper_ckt']}")
    print(f"  basis    {s['basis']:>+10,.2f}  ({s['basis_pct']:+.2f}%)  "
          f"{'DISCOUNT - cash being squeezed / futures sold' if s['basis'] < 0 else 'premium (normal)'}")
    print(f"  OI       {s['oi']:>10,}  vs {s['pdoi']:,} yday   ({s['oi_chg']:+.1f}%)")
    print(f"  -> {s['read']}: {s['meaning']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("symbol", nargs="?", default="KALYANKJIL")
    p.add_argument("--expiry", default="26JUL", help="Fyers expiry code, e.g. 26JUL")
    p.add_argument("--watch", type=int, default=0, help="refresh every N seconds")
    a = p.parse_args()

    while True:
        try:
            show(snapshot(a.symbol, a.expiry), a.symbol)
        except Exception as e:
            print(f"error: {e}")
        if not a.watch:
            break
        time.sleep(a.watch)

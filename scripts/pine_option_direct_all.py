"""Apply the Pine strategy DIRECTLY on the ATM option strike of each index
(NIFTY, BANKNIFTY, FINNIFTY, SENSEX), on 1m & 5m, long-only, and save the stats.

Resolves the live ATM contract off the Fyers symbol master (nearest expiry,
nearest strike to spot). BankNifty/FinNifty are monthly-only now; Sensex is BSE.

Run:  py pine_option_direct_all.py
"""
import csv, urllib.request, io, time
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
import fyers_client as fy
import st_option_backtest as bt
import pine_strategy as ps

IST = timezone(timedelta(hours=5, minutes=30))
DATA = Path(r"C:\Users\adars\sss\data")
OUT = DATA / "pine_option_direct_stats.csv"
MASTERS = {"NSE": "https://public.fyers.in/sym_details/NSE_FO.csv",
           "BSE": "https://public.fyers.in/sym_details/BSE_FO.csv"}
INDEX = {  # underlying token in master, index symbol for spot, exchange
    "NIFTY":     ("NIFTY",     "NSE:NIFTY50-INDEX",  "NSE"),
    "BANKNIFTY": ("BANKNIFTY", "NSE:NIFTYBANK-INDEX", "NSE"),
    "FINNIFTY":  ("FINNIFTY",  "NSE:FINNIFTY-INDEX",  "NSE"),
    "SENSEX":    ("SENSEX",    "BSE:SENSEX-INDEX",    "BSE"),
}


def load_master(exch):
    p = DATA / f"{exch}_FO_master.csv"
    if not p.exists():
        req = urllib.request.Request(MASTERS[exch], headers={"User-Agent": "Mozilla/5.0"})
        p.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    return list(csv.reader(io.StringIO(p.read_text("utf-8", "ignore"))))


def resolve_atm(exch, underlying, spot):
    rows = load_master(exch)
    today = time.time()
    opts = []
    for r in rows:
        if len(r) < 10:
            continue
        desc = r[1].split()
        if not desc or desc[0] != underlying or desc[-1] not in ("CE", "PE"):
            continue
        try:
            exp = float(r[8]); strike = float(desc[-2])
        except (ValueError, IndexError):
            continue
        if exp < today:
            continue
        opts.append((exp, strike, desc[-1], r[9]))
    if not opts:
        return None
    nearest_exp = min(o[0] for o in opts)
    same = [o for o in opts if o[0] == nearest_exp]
    strikes = sorted({o[1] for o in same})
    atm = min(strikes, key=lambda s: abs(s - spot))
    ce = next((o[3] for o in same if o[1] == atm and o[2] == "CE"), None)
    pe = next((o[3] for o in same if o[1] == atm and o[2] == "PE"), None)
    expd = datetime.fromtimestamp(nearest_exp, IST).date()
    return {"strike": atm, "ce": ce, "pe": pe, "expiry": expd}


def spot(sym):
    end = date.today()
    r = fy.fetch_history(sym, (end - timedelta(days=4)).isoformat(), end.isoformat(), "5")
    return r[-1][4] if r else None


def backtest_option(sym, res, days=95):
    end = date.today()
    r = fy.fetch_history(sym, (end - timedelta(days=days)).isoformat(), end.isoformat(), res)
    if not r:
        return None
    dts = [datetime.fromtimestamp(x[0], IST) for x in r]
    return ps._bt(dts, [x[1] for x in r], [x[2] for x in r], [x[3] for x in r],
                  [x[4] for x in r], res, intraday=True, long_only=True), len(r), dts[0].date(), dts[-1].date()


def main():
    results = []
    for name, (und, spot_sym, exch) in INDEX.items():
        sp = spot(spot_sym)
        if not sp:
            print(f"{name}: no spot"); continue
        info = resolve_atm(exch, und, sp)
        if not info or not (info["ce"] and info["pe"]):
            print(f"{name}: could not resolve ATM (spot {sp:.0f})"); continue
        print(f"\n{name}  spot {sp:.0f}  ATM {info['strike']:.0f}  exp {info['expiry']}")
        for typ, osym in (("CE", info["ce"]), ("PE", info["pe"])):
            for res in ("1", "5"):
                out = backtest_option(osym, res)
                if not out or not out[0]:
                    print(f"   {osym} {res}m: no data/trades"); continue
                s, nbars, d0, d1 = out
                print(f"   {typ} {res}m {osym:24} | {s['n']:3d} tr | win {s['wr']:.0f}% | "
                      f"PF {s['pf']:.2f} | total {s['tot_pct']:+.1f}% | TP1 {s['tp'][0]:.0f}% | {d0}->{d1}")
                results.append({"index": name, "strike": f"{info['strike']:.0f}", "type": typ,
                                "symbol": osym, "expiry": info["expiry"], "tf": f"{res}m",
                                "trades": s["n"], "win%": f"{s['wr']:.0f}", "PF": f"{s['pf']:.2f}",
                                "avg%": f"{s['avg_pct']:.3f}", "total%": f"{s['tot_pct']:.1f}",
                                "TP1%": f"{s['tp'][0]:.0f}", "days": f"{d0}..{d1}"})
    if results:
        with OUT.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader(); w.writerows(results)
        print(f"\nsaved {len(results)} rows -> {OUT}")


if __name__ == "__main__":
    main()

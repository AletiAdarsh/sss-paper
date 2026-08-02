"""Apply the Lux Algo signal DIRECTLY on the option premium's own chart
(long-only -- you can only buy premium), the same test we ran for Versomil.

Synthetic ATM-at-open premium: each trading day we pick that day's ATM strike
(round spot at the first bar) and price the CE and PE with Black-Scholes using
that day's India VIX and the correct time-to-expiry.  The Lux indicators are
computed PER DAY (intraday reset) and Lux trades long-only, flat by EOD -- i.e.
exactly how you'd trade the option's own 1m/5m signal.

This needs NO token (built from the cached index + VIX). Real fixed-contract
data needs a live Fyers token.

Run:  py lux_option_direct.py
"""
from collections import defaultdict
import st_option_backtest as bt
import lux_algo as la

INDEXES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]


def premium_ohlc(day_bars, K, side, cfg, vix):
    """Build synthetic option OHLC for one day at fixed strike K."""
    ivm = cfg["iv_mult"]; exp = cfg["expiry"]
    dts = [b[0] for b in day_bars]
    o = []; h = []; l = []; c = []
    for (dt, io, ih, il, ic) in day_bars:
        T = bt.tau_years(dt, exp); sig = bt.vix_for(vix, dt.date())/100*ivm
        po = bt.bs_price(io, K, T, sig, side)
        pc = bt.bs_price(ic, K, T, sig, side)
        # CE premium rises with index -> high at index-high; PE is inverted
        if side == "CE":
            ph = bt.bs_price(ih, K, T, sig, side); pl = bt.bs_price(il, K, T, sig, side)
        else:
            ph = bt.bs_price(il, K, T, sig, side); pl = bt.bs_price(ih, K, T, sig, side)
        o.append(po); h.append(max(ph, po, pc)); l.append(min(pl, po, pc)); c.append(pc)
    return dts, o, h, l, c


SPREAD = 1.0   # assumed round-trip bid-ask haircut, in premium points (conservative for ATM weekly)


def rupee_stats(trades, lot):
    """Gross (frictionless) vs net-with-real-costs, in rupees, per trade."""
    if not trades:
        return None
    gross = []; net = []
    for t in trades:
        g = t["pts"]*lot
        exitp = t["entry"] + t["pts"]
        n = (t["pts"] - SPREAD)*lot - bt.charges(t["entry"], max(exitp, 0.05), lot)
        gross.append(g); net.append(n)
    nn = len(net)
    winsn = [x for x in net if x > 0]
    return {"n": nn, "gross": sum(gross), "net": sum(net), "avg_net": sum(net)/nn,
            "wr_net": len(winsn)/nn*100}


def run_index(idx, res):
    cfg = bt.INDEXES[idx]; step = cfg["step"]; lot = cfg["lot"]
    bars = bt.load_bars(idx, res); vix = bt.load_vix()
    days = defaultdict(list)
    for b in bars:
        days[b[0].date()].append(b)
    out = {}
    for side in ("CE", "PE"):
        trades = []
        for d, db in days.items():
            if len(db) < 25:
                continue
            spot0 = db[0][4]
            K = round(spot0/step)*step
            dts, o, h, l, c = premium_ohlc(db, K, side, cfg, vix)
            s = la.lux_bt(dts, o, h, l, c, res, intraday=True, long_only=True)
            if s:
                trades += s["_trades"]
        out[side] = (la.agg_stats(trades), rupee_stats(trades, lot))
    return out


def main():
    print("\nLUX ALGO directly on the option's own chart (synthetic ATM-at-open, long-only, 1 lot)")
    print(f"  gross = frictionless BS pnl;  NET = after Dhan charges + {SPREAD:.0f}pt round-trip spread")
    print(f"{'index':10} {'tf':>3} {'type':>4} | {'n':>4} {'win%':>5} {'PF':>5} {'tot%':>8} | "
          f"{'GROSS Rs':>11} {'NET Rs':>11} {'netwin%':>7}")
    print("-"*90)
    for idx in INDEXES:
        for res in ("1", "5"):
            try:
                bt.load_bars(idx, res)
            except SystemExit:
                print(f"{idx:10} {res:>3}  (no {res}m index cache -- skip)"); continue
            r = run_index(idx, res)
            for side in ("CE", "PE"):
                s, rs = r[side]
                if not s:
                    print(f"{idx:10} {res:>3} {side:>4} |  0 trades"); continue
                print(f"{idx:10} {res:>3} {side:>4} | {s['n']:4d} {s['wr']:4.0f}% {s['pf']:5.2f} "
                      f"{s['tot_pct']:+7.1f} | {rs['gross']:+11,.0f} {rs['net']:+11,.0f} {rs['wr_net']:6.0f}%")
        print("-"*90)


if __name__ == "__main__":
    main()

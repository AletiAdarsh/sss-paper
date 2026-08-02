"""Can tuning rescue the 1-MINUTE timeframe? NIFTY (only index with 1m cache).

Same Lux entry -> ATM option model, after real Dhan charges. Hold length 11, gate
on, reverse exit; sweep only the factor, on 1m vs 5m. Then walk-forward the 1m
factor to get the honest out-of-sample number. Charges are tracked explicitly so
we can see the cost drag that kills fast timeframes.
"""
import functools
from collections import Counter
from datetime import time
import st_option_backtest as bt
import lux_algo as la

bt.load_bars = functools.lru_cache(maxsize=None)(bt.load_bars)
bt.load_vix  = functools.lru_cache(maxsize=None)(bt.load_vix)

IDX = "NIFTY"
FACTORS = [7.0, 6.0, 5.5, 5.0, 4.5, 4.0, 3.5, 3.0]
DAY_OPEN = time(9, 15); NO_NEW = time(15, 0); FORCE_FLAT = time(15, 20)


def lux_trades(res, atrlen, factor, gate=True, exitmode="R"):
    cfg = bt.INDEXES[IDX]; step = cfg["step"]; lot = cfg["lot"]; exp = cfg["expiry"]; ivm = cfg["iv_mult"]
    bars = bt.load_bars(IDX, res); vix = bt.load_vix()
    dts = [b[0] for b in bars]; o = [b[1] for b in bars]; h = [b[2] for b in bars]
    l = [b[3] for b in bars]; c = [b[4] for b in bars]
    st, _ = la.lux_supertrend(o, h, l, c, factor, atrlen)
    sm = la.sma(c, la.SMA_LEN); atr14 = bt.wilder_atr(h, l, c, 14)
    qty = lot; warm = max(atrlen, la.SMA_LEN, 14) + 2
    trades = []; pos = None

    def price(side, S, dt, K):
        sigma = bt.vix_for(vix, dt.date()) / 100.0 * ivm
        return bt.bs_price(S, K, bt.tau_years(dt, exp), sigma, side)

    def close_pos(S, dt):
        xp = price(pos["side"], S, dt, pos["K"])
        fee = bt.charges(pos["ep"], xp, qty)
        trades.append({"day": pos["dt"].date(), "net": (xp - pos["ep"]) * qty - fee, "fee": fee})

    for i in range(warm, len(dts)):
        dt = dts[i]; S = c[i]; tod = dt.time()
        bull = c[i] > st[i] and c[i-1] <= st[i-1] and (not gate or c[i] >= sm[i])
        bear = c[i] < st[i] and c[i-1] >= st[i-1] and (not gate or c[i] <= sm[i])
        if pos and dt.date() != pos["dt"].date():
            close_pos(o[i], dt); pos = None
        if pos and tod >= FORCE_FLAT:
            close_pos(S, dt); pos = None; continue
        if pos:
            opp = (pos["side"] == "CE" and bear) or (pos["side"] == "PE" and bull)
            if opp:
                close_pos(S, dt); pos = None
        if not pos and DAY_OPEN <= tod < NO_NEW and (bull or bear):
            side = "CE" if bull else "PE"; K = round(S / step) * step
            pos = {"side": side, "K": K, "ep": price(side, S, dt, K), "dt": dt}
    if pos:
        close_pos(c[-1], dts[-1])
    return trades


def stats(tr):
    if not tr:
        return None
    net = [t["net"] for t in tr]; fee = sum(t["fee"] for t in tr)
    wins = [x for x in net if x > 0]; losses = [x for x in net if x <= 0]
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf")
    return {"n": len(net), "net": sum(net), "pf": pf, "wr": len(wins)/len(net)*100,
            "fee": fee, "rt": sum(net)/len(net)}


def sweep():
    print(f"\nNIFTY full-year factor sweep (len 11, gate on, reverse exit) -- 1m vs 5m")
    print(f"{'res':>3} {'factor':>6} {'trades':>7} {'win%':>6} {'PF':>5} {'net Rs':>11} "
          f"{'Rs/trade':>9} {'charges Rs':>11}")
    print("-" * 74)
    for res in ("5", "1"):
        for f in FACTORS:
            s = stats(lux_trades(res, 11, f))
            pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
            print(f"{res+'m':>3} {f:>6} {s['n']:>7} {s['wr']:>5.1f}% {pf:>5} {s['net']:>+11,.0f} "
                  f"{s['rt']:>+9,.0f} {s['fee']:>11,.0f}")
        print("-" * 74)


def walk_forward_1m():
    print(f"\nNIFTY 1m walk-forward (re-pick best factor monthly, trade next month blind)")
    res = "1"
    days = sorted({b[0].date() for b in bt.load_bars(IDX, res)})
    book = {f: lux_trades(res, 11, f) for f in FACTORS}
    INIT, BLK = 150, 21
    sl = lambda tr, a, b: [t for t in tr if a <= t["day"] < b]
    folds = []; t = INIT
    while t < len(days):
        lo, cut = days[0], days[t]; hi = days[min(t + BLK, len(days) - 1)]
        best = None
        for f, tr in book.items():
            s = stats(sl(tr, lo, cut))
            if not s or s["n"] < 30 or s["pf"] < 1.3 or s["net"] <= 0:
                continue
            if best is None or s["net"] > best[1]["net"]:
                best = (f, s)
        chosen = best[0] if best else 5.5
        folds.append((cut, chosen, stats(sl(book[chosen], cut, hi))))
        t += BLK
    tot = sum((f[2]["net"] if f[2] else 0) for f in folds)
    tn = sum((f[2]["n"] if f[2] else 0) for f in folds)
    print(f"  {'OOS from':>10} {'factor':>6} {'net':>10} {'n':>4}")
    for cut, fac, s in folds:
        print(f"  {str(cut):>10} {fac:>6} {(s['net'] if s else 0):>+10,.0f} {(s['n'] if s else 0):>4}")
    stab = Counter(f[1] for f in folds).most_common()
    print(f"  -> 1m walk-forward OOS TOTAL: net Rs{tot:+,.0f} over {tn} trades  "
          f"(factors picked: {', '.join(f'{k}x{v}' for k,v in stab)})")

    # compare: 5m walk-forward, same method
    res = "5"; days = sorted({b[0].date() for b in bt.load_bars(IDX, res)})
    book5 = {f: lux_trades(res, 11, f) for f in FACTORS}
    folds5 = []; t = INIT
    while t < len(days):
        lo, cut = days[0], days[t]; hi = days[min(t + BLK, len(days) - 1)]
        best = None
        for f, tr in book5.items():
            s = stats(sl(tr, lo, cut))
            if not s or s["n"] < 30 or s["pf"] < 1.3 or s["net"] <= 0:
                continue
            if best is None or s["net"] > best[1]["net"]:
                best = (f, s)
        chosen = best[0] if best else 5.5
        folds5.append(stats(sl(book5[chosen], cut, hi)))
        t += BLK
    tot5 = sum((f["net"] if f else 0) for f in folds5)
    tn5 = sum((f["n"] if f else 0) for f in folds5)
    print(f"  -> 5m walk-forward OOS TOTAL: net Rs{tot5:+,.0f} over {tn5} trades  (for reference)")


if __name__ == "__main__":
    sweep()
    walk_forward_1m()

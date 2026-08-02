"""FULL Lux parameter tuning -- every knob, all combinations, walk-forward.

Purpose: fairly test whether tuning ALL Lux params beats the simple 'just set
factor=4.0' change. Three things compared out-of-sample, per index:
    A) incumbent   : atrlen 11, factor 5.5, gate SMA13, reverse exit
    B) factor-only : atrlen 11, factor 4.0, gate SMA13, reverse exit   (my rec)
    C) full-tuned  : re-pick the best of ALL combos every month, trade blind

Grid/index (5m, cached 1yr):
    atrlen   : 7, 10, 11, 14, 21
    factor   : 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0
    gate     : off | SMA8 | SMA13 | SMA20
    exit     : R (reverse+EOD) | A4 (4xATR stop) | ST (Lux Smart-Trail 13/4)
  => 5*7*4*3 = 420 configs/index. Same walk-forward, same charges.

If C >> B out-of-sample, tuning the other params adds real value (my rec was too
narrow). If C ~= B or worse, factor is the only real lever and the rest is noise.
"""
import sys, functools
from collections import Counter
from datetime import time
import st_option_backtest as bt
import lux_algo as la

bt.load_bars = functools.lru_cache(maxsize=None)(bt.load_bars)
bt.load_vix  = functools.lru_cache(maxsize=None)(bt.load_vix)

RES = "5"
ATR_LENS = [7, 10, 11, 14, 21]
FACTORS  = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
GATES    = [0, 8, 13, 20]           # 0 = no gate; else SMA length
EXITS    = ["R", "A4", "ST"]
DAY_OPEN = time(9, 15); NO_NEW = time(15, 0); FORCE_FLAT = time(15, 20)
INCUMBENT   = (11, 5.5, 13, "R")
FACTOR_ONLY = (11, 4.0, 13, "R")
INIT, BLK, MINTR, MINPF = 150, 21, 30, 1.30


def lux_trades(idx, atrlen, factor, sma_len, exitmode):
    cfg = bt.INDEXES[idx]; step = cfg["step"]; lot = cfg["lot"]; exp = cfg["expiry"]; ivm = cfg["iv_mult"]
    bars = bt.load_bars(idx, RES); vix = bt.load_vix()
    dts = [b[0] for b in bars]; o = [b[1] for b in bars]; h = [b[2] for b in bars]
    l = [b[3] for b in bars]; c = [b[4] for b in bars]
    st, _ = la.lux_supertrend(o, h, l, c, factor, atrlen)
    sm = la.sma(c, sma_len) if sma_len else None
    atr14 = bt.wilder_atr(h, l, c, 14)
    trail = la.smart_trail_trend(h, l, c) if exitmode == "ST" else None
    qty = lot; warm = max(atrlen, sma_len or 0, 14, 15) + 2
    trades = []; pos = None

    def price(side, S, dt, K):
        sigma = bt.vix_for(vix, dt.date()) / 100.0 * ivm
        return bt.bs_price(S, K, bt.tau_years(dt, exp), sigma, side)

    def close_pos(S, dt):
        xp = price(pos["side"], S, dt, pos["K"])
        trades.append({"day": pos["dt"].date(), "net": (xp - pos["ep"]) * qty - bt.charges(pos["ep"], xp, qty)})

    for i in range(warm, len(dts)):
        dt = dts[i]; S = c[i]; tod = dt.time()
        bull = c[i] > st[i] and c[i-1] <= st[i-1] and (sm is None or c[i] >= sm[i])
        bear = c[i] < st[i] and c[i-1] >= st[i-1] and (sm is None or c[i] <= sm[i])
        if pos and dt.date() != pos["dt"].date():
            close_pos(o[i], dt); pos = None
        if pos and tod >= FORCE_FLAT:
            close_pos(S, dt); pos = None; continue
        if pos:
            opp = (pos["side"] == "CE" and bear) or (pos["side"] == "PE" and bull)
            stop = exitmode == "A4" and ((pos["side"] == "CE" and l[i] <= pos["stop"]) or
                                         (pos["side"] == "PE" and h[i] >= pos["stop"]))
            tflip = exitmode == "ST" and ((pos["side"] == "CE" and trail[i] == -1) or
                                          (pos["side"] == "PE" and trail[i] == 1))
            if stop:
                close_pos(pos["stop"], dt); pos = None
            elif tflip or opp:
                close_pos(S, dt); pos = None
        if not pos and DAY_OPEN <= tod < NO_NEW and (bull or bear):
            side = "CE" if bull else "PE"; K = round(S / step) * step
            stp = (S - 4 * atr14[i]) if side == "CE" else (S + 4 * atr14[i])
            pos = {"side": side, "K": K, "ep": price(side, S, dt, K), "dt": dt, "stop": stp}
    if pos:
        close_pos(c[-1], dts[-1])
    return trades


def stats(tr):
    if not tr:
        return None
    net = [t["net"] for t in tr]
    wins = [x for x in net if x > 0]; losses = [x for x in net if x <= 0]
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf")
    return {"n": len(net), "net": sum(net), "pf": pf, "wr": len(wins)/len(net)*100}


def cfgs():
    for a in ATR_LENS:
        for f in FACTORS:
            for g in GATES:
                for e in EXITS:
                    yield (a, f, g, e)


def lab(c):
    return f"{c[0]}/{c[1]}/{'g'+str(c[2]) if c[2] else 'nogate'}/{c[3]}"


def run_index(idx):
    print(f"\n{'='*84}\n{idx}  ({RES}m)   {len(list(cfgs()))} full-combo configs/fold\n{'='*84}")
    days = sorted({b[0].date() for b in bt.load_bars(idx, RES)})
    book = {c: lux_trades(idx, *c) for c in cfgs()}
    for ref in (INCUMBENT, FACTOR_ONLY):
        if ref not in book:
            book[ref] = lux_trades(idx, *ref)
    sl = lambda tr, a, b: [t for t in tr if a <= t["day"] < b]

    folds = []; t = INIT
    while t < len(days):
        lo, cut = days[0], days[t]; hi = days[min(t + BLK, len(days) - 1)]
        best = None
        for c, tr in book.items():
            s = stats(sl(tr, lo, cut))
            if not s or s["n"] < MINTR or s["pf"] < MINPF or s["net"] <= 0:
                continue
            if best is None or s["net"] > best[1]["net"]:
                best = (c, s)
        chosen = best[0] if best else INCUMBENT
        folds.append({"cut": cut, "cfg": chosen,
                      "C": stats(sl(book[chosen], cut, hi)),
                      "A": stats(sl(book[INCUMBENT], cut, hi)),
                      "B": stats(sl(book[FACTOR_ONLY], cut, hi))})
        t += BLK

    def tot(k):
        return sum((f[k]["net"] if f[k] else 0) for f in folds), sum((f[k]["n"] if f[k] else 0) for f in folds)
    a_net, _ = tot("A"); b_net, _ = tot("B"); c_net, _ = tot("C")
    print(f"  {'OOS from':>10} | {'C: full-tuned pick':24} | {'C net':>9} | {'B fac4':>8} | {'A base':>8}")
    for f in folds:
        cn = f["C"]["net"] if f["C"] else 0; bn = f["B"]["net"] if f["B"] else 0; an = f["A"]["net"] if f["A"] else 0
        print(f"  {str(f['cut']):>10} | {lab(f['cfg']):24} | {cn:>+9,.0f} | {bn:>+8,.0f} | {an:>+8,.0f}")
    stab = Counter(f["cfg"] for f in folds).most_common(3)
    print(f"\n  OOS TOTALS:  A incumbent Rs{a_net:+,.0f}   |   B factor=4.0 Rs{b_net:+,.0f}   |   "
          f"C full-tuned Rs{c_net:+,.0f}")
    print(f"  C minus B (does tuning the OTHER params beat just factor?): Rs{c_net-b_net:+,.0f}")
    print(f"  full-tuned stability: " + ", ".join(f"{lab(c)}x{k}" for c, k in stab))
    return {"idx": idx, "A": a_net, "B": b_net, "C": c_net}


if __name__ == "__main__":
    idxs = [sys.argv[1].upper()] if len(sys.argv) > 1 else ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
    res = [run_index(ix) for ix in idxs]
    print(f"\n\n{'#'*84}\nDOES FULL TUNING BEAT 'JUST FACTOR=4.0'?  (out-of-sample net)\n{'#'*84}")
    print(f"  {'index':10} {'A incumbent':>13} {'B factor=4.0':>14} {'C full-tuned':>14} {'C-B':>10}")
    ta = tb = tc = 0
    for r in res:
        ta += r["A"]; tb += r["B"]; tc += r["C"]
        print(f"  {r['idx']:10} {r['A']:>+13,.0f} {r['B']:>+14,.0f} {r['C']:>+14,.0f} {r['C']-r['B']:>+10,.0f}")
    print(f"  {'TOTAL':10} {ta:>+13,.0f} {tb:>+14,.0f} {tc:>+14,.0f} {tc-tb:>+10,.0f}")

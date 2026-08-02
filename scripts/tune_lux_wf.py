"""WIDE walk-forward tune of the LUX entry signal -> ATM option (what live_paper runs).

Lux entry = Supertrend(source=close, atrlen, factor) crossover, optionally gated by
close vs SMA(sma_len). Exit = opposite Lux flip + EOD (matches live_paper.py; the
Smart-Trail exit is NOT used live, so it's not tuned here). Priced BS+VIX, after
real Dhan charges, 1 lot.

Grid/index (cached 1yr, 5m):
    atrlen : 7, 10, 11, 14
    factor : 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0     (incumbent 5.5)
    gate   : on (close>=SMA13) | off
    exit   : R  reverse+EOD | A4  +4xATR index stop
  => 4*8*2*2 = 128 configs. Incumbent = close/11/5.5/gate-on/R.

Walk-forward: expand train, every ~month re-pick best by train net (n>=30, PF>=1.3),
trade next month blind, sum OOS only. Also prints fixed incumbent over same months,
and the overfit best-fit-whole-year config (the mirage).

Usage:  py tune_lux_wf.py           # all 4 indices
        py tune_lux_wf.py NIFTY
"""
import sys, functools
from collections import Counter
from datetime import time
import st_option_backtest as bt
import lux_algo as la

bt.load_bars = functools.lru_cache(maxsize=None)(bt.load_bars)
bt.load_vix  = functools.lru_cache(maxsize=None)(bt.load_vix)

RES = "5"
ATR_LENS = [7, 10, 11, 14]
FACTORS  = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0]
GATES    = [True, False]
EXITS    = ["R", "A4"]
SMA_LEN  = la.SMA_LEN                 # 13
INCUMBENT = (11, 5.5, True, "R")
DAY_OPEN = time(9, 15); NO_NEW = time(15, 0); FORCE_FLAT = time(15, 20)

INIT_TRAIN_DAYS = 150
TEST_BLOCK = 21
MIN_TR_TRAIN = 30
MIN_PF_TRAIN = 1.30


def lux_option_trades(idx, atrlen, factor, gate, exitmode):
    """Lux signal on the index -> ATM option, reverse/EOD exit. Returns list of {day,net}."""
    cfg = bt.INDEXES[idx]; step = cfg["step"]; lot = cfg["lot"]; exp = cfg["expiry"]; ivm = cfg["iv_mult"]
    bars = bt.load_bars(idx, RES); vix = bt.load_vix()
    dts = [b[0] for b in bars]; o = [b[1] for b in bars]; h = [b[2] for b in bars]
    l = [b[3] for b in bars]; c = [b[4] for b in bars]
    st, _ = la.lux_supertrend(o, h, l, c, factor, atrlen)
    sm = la.sma(c, SMA_LEN)
    atr14 = bt.wilder_atr(h, l, c, 14)
    qty = lot
    warm = max(atrlen, SMA_LEN, 14) + 2
    trades = []; pos = None

    def price(side, S, dt, K):
        sigma = bt.vix_for(vix, dt.date()) / 100.0 * ivm
        return bt.bs_price(S, K, bt.tau_years(dt, exp), sigma, side)

    def close_pos(S, dt):
        xp = price(pos["side"], S, dt, pos["K"])
        gross = (xp - pos["ep"]) * qty
        fee = bt.charges(pos["ep"], xp, qty)
        trades.append({"day": pos["dt"].date(), "net": gross - fee})

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
            stophit = exitmode == "A4" and (
                (pos["side"] == "CE" and l[i] <= pos["stop"]) or
                (pos["side"] == "PE" and h[i] >= pos["stop"]))
            if stophit:
                close_pos(pos["stop"], dt); pos = None
            elif opp:
                close_pos(S, dt); pos = None
        if not pos and DAY_OPEN <= tod < NO_NEW and (bull or bear):
            side = "CE" if bull else "PE"; K = round(S / step) * step
            stop = (S - 4 * atr14[i]) if side == "CE" else (S + 4 * atr14[i])
            pos = {"side": side, "K": K, "ep": price(side, S, dt, K), "dt": dt, "stop": stop}
    if pos:
        close_pos(c[-1], dts[-1])
    return trades


def stats(trades):
    if not trades:
        return None
    net = [t["net"] for t in trades]
    wins = [x for x in net if x > 0]; losses = [x for x in net if x <= 0]
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf")
    return {"n": len(net), "net": sum(net), "pf": pf, "wr": len(wins)/len(net)*100}


def all_cfgs():
    for a in ATR_LENS:
        for fct in FACTORS:
            for g in GATES:
                for ex in EXITS:
                    yield (a, fct, g, ex)


def lab(c):
    return f"{c[0]}/{c[1]}/{'gate' if c[2] else 'nogate'}/{c[3]}"


def walk_forward(idx):
    print(f"\n{'='*82}\n{idx}  ({RES}m, cached 1yr)   {len(list(all_cfgs()))} Lux configs/fold\n{'='*82}")
    days = sorted({b[0].date() for b in bt.load_bars(idx, RES)})
    book = {c: lux_option_trades(idx, *c) for c in all_cfgs()}
    if INCUMBENT not in book:
        book[INCUMBENT] = lux_option_trades(idx, *INCUMBENT)

    def sl(tr, d0, d1):
        return [t for t in tr if d0 <= t["day"] < d1]

    folds = []; t = INIT_TRAIN_DAYS
    while t < len(days):
        lo = days[0]; cut = days[t]; hi = days[min(t + TEST_BLOCK, len(days) - 1)]
        best = None
        for c, tr in book.items():
            s = stats(sl(tr, lo, cut))
            if not s or s["n"] < MIN_TR_TRAIN or s["pf"] < MIN_PF_TRAIN or s["net"] <= 0:
                continue
            if best is None or s["net"] > best[1]["net"]:
                best = (c, s)
        chosen = best[0] if best else INCUMBENT
        folds.append({"cut": cut, "cfg": chosen,
                      "test": stats(sl(book[chosen], cut, hi)),
                      "inc": stats(sl(book[INCUMBENT], cut, hi))})
        t += TEST_BLOCK

    print(f"  Walk-forward OOS months (train on all prior, trade next ~{TEST_BLOCK}d blind):")
    print(f"    {'OOS from':>10} | {'chosen Lux config':26} | {'tuned net':>10} {'n':>3} | {'incumbent net':>13}")
    wf = inc = wn = iN = 0
    for f in folds:
        tn = f["test"]["net"] if f["test"] else 0; tc = f["test"]["n"] if f["test"] else 0
        ic = f["inc"]["net"] if f["inc"] else 0; icn = f["inc"]["n"] if f["inc"] else 0
        wf += tn; inc += ic; wn += tc; iN += icn
        print(f"    {str(f['cut']):>10} | {lab(f['cfg']):26} | {tn:+10,.0f} {tc:>3} | {ic:+13,.0f}")

    stab = Counter(f["cfg"] for f in folds).most_common(3)
    print(f"\n  WALK-FORWARD TOTAL (out-of-sample, {len(folds)} months):")
    print(f"    tuned (re-pick monthly)     : net Rs{wf:+,.0f}  over {wn} trades")
    print(f"    fixed incumbent close/11/5.5/gate/R: net Rs{inc:+,.0f}  over {iN} trades")
    print(f"    stability: " + ", ".join(f"{lab(c)}x{k}" for c, k in stab))

    fy = [(c, stats(tr)) for c, tr in book.items()]; fy = [(c, s) for c, s in fy if s]
    bf, bfs = max(fy, key=lambda x: x[1]["net"])
    print(f"\n  (Overfit reference) best single config fit to WHOLE year: {lab(bf)}  "
          f"net Rs{bfs['net']:+,.0f} PF {bfs['pf']:.2f} n{bfs['n']}")
    return {"idx": idx, "wf": wf, "wn": wn, "inc": inc, "iN": iN, "months": len(folds),
            "stab": stab, "bestfull": (bf, bfs)}


if __name__ == "__main__":
    idxs = [sys.argv[1].upper()] if len(sys.argv) > 1 else ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
    res = [walk_forward(ix) for ix in idxs]
    print(f"\n\n{'#'*82}\nLUX WALK-FORWARD SUMMARY (out-of-sample only)\n{'#'*82}")
    print(f"  {'index':10} {'OOS mo':>6} {'tuned net':>12} {'incumbent net':>14} {'edge':>10}")
    for r in res:
        print(f"  {r['idx']:10} {r['months']:>6} {r['wf']:>+12,.0f} {r['inc']:>+14,.0f} {r['wf']-r['inc']:>+10,.0f}")

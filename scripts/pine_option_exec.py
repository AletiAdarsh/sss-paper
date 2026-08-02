"""NIFTY 5m signal -> buy ATM option. Exit on:
   - fixed 10-point OPTION stop (premium drops SL_PTS from entry), OR
   - TP1 target = INDEX moves 1.5xATR in your favour (reprice option there), OR
   - end of day.
Full 1-lot position, no partials. Synthetic BS+VIX option pricing.

Run:  py pine_option_exec.py [SL_pts] [tp_atr_mult]
"""
import sys, statistics as stt
from datetime import time
import st_option_backtest as bt

LOT = 65
SL_PTS = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0   # option-premium stop
TP_ATR = float(sys.argv[2]) if len(sys.argv) > 2 else 1.5    # TP1 = 1.5xATR on index
DAY_OPEN = time(9, 15); NO_NEW = time(15, 0); FORCE_FLAT = time(15, 20)


def run(res="5", idx="NIFTY", lots=1):
    cfg = bt.INDEXES[idx]; step = cfg["step"]; lot = cfg["lot"]; qty = lots*lot
    bars = bt.load_bars(idx, res)
    dts = [b[0] for b in bars]
    o = [b[1] for b in bars]; h = [b[2] for b in bars]; l = [b[3] for b in bars]; c = [b[4] for b in bars]
    st, tr = bt.supertrend(h, l, c)
    atr = bt.wilder_atr(h, l, c, 14)
    vix = bt.load_vix(); exp = cfg["expiry"]; ivm = cfg["iv_mult"]

    def prem(side, S, dt, K):
        return bt.bs_price(S, K, bt.tau_years(dt, exp), bt.vix_for(vix, dt.date())/100*ivm, side)

    trades = []; pos = None
    for i in range(bt.ST_ATR_LEN+2, len(bars)):
        dt = dts[i]; tod = dt.time()
        if pos:
            newday = dt.date() != dts[pos["i"]].date()
            K = pos["K"]; side = pos["side"]; ep = pos["ep"]
            exit_prem = None; reason = None
            if tod >= FORCE_FLAT or newday:
                exit_prem = prem(side, o[i] if newday else c[i], dt, K); reason = "eod"
            else:
                # worst-case premium in the bar (for the stop) & index target check
                if side == "CE":
                    lo_prem = prem(side, l[i], dt, K)          # lowest premium this bar
                    if lo_prem <= ep - SL_PTS:
                        exit_prem = ep - SL_PTS; reason = "sl"
                    elif h[i] >= pos["tp"]:
                        exit_prem = prem(side, pos["tp"], dt, K); reason = "tp1"
                else:  # PE
                    lo_prem = prem(side, h[i], dt, K)          # PE worst when index rises
                    if lo_prem <= ep - SL_PTS:
                        exit_prem = ep - SL_PTS; reason = "sl"
                    elif l[i] <= pos["tp"]:
                        exit_prem = prem(side, pos["tp"], dt, K); reason = "tp1"
            if exit_prem is not None:
                g = (exit_prem - ep)*qty - bt.charges(ep, exit_prem, qty)
                trades.append({"net": g, "reason": reason, "bars": i-pos["i"],
                               "side": side}); pos = None

        if not pos and DAY_OPEN <= tod < NO_NEW:
            fu = tr[i] == 1 and tr[i-1] == -1; fd = tr[i] == -1 and tr[i-1] == 1
            if fu or fd:
                side = "CE" if fu else "PE"
                K = round(c[i]/step)*step
                ep = prem(side, c[i], dt, K)
                tp = c[i] + TP_ATR*atr[i] if fu else c[i] - TP_ATR*atr[i]
                pos = {"side": side, "K": K, "ep": ep, "tp": tp, "i": i}

    n = len(trades)
    net = [t["net"] for t in trades]; tot = sum(net)
    wins = [x for x in net if x > 0]; losses = [x for x in net if x <= 0]
    pf = sum(wins)/-sum(losses) if losses and sum(losses) < 0 else 99
    reasons = {}
    for t in trades: reasons[t["reason"]] = reasons.get(t["reason"], 0)+1
    rmin = int(res)*1
    tp_time = [t["bars"]*rmin for t in trades if t["reason"] == "tp1"]
    print(f"\n{idx} {res}m | signal->ATM option | SL {SL_PTS:.0f} opt-pts | TP1={TP_ATR}xATR index | 1 lot ({qty}q)")
    print(f"  trades {n} | win {len(wins)/n*100:.0f}% | PF {pf:.2f} | NET Rs{tot:+,.0f} | avg Rs{tot/n:+,.0f}")
    print(f"  avg win Rs{sum(wins)/len(wins) if wins else 0:+,.0f} | avg loss Rs{sum(losses)/len(losses) if losses else 0:+,.0f}")
    print(f"  exits: {reasons}")
    if tp_time:
        print(f"  time-to-TP1 hit (min): mean {stt.mean(tp_time):.0f}  median {stt.median(tp_time):.0f}  max {max(tp_time):.0f}")


if __name__ == "__main__":
    run("5", "NIFTY")

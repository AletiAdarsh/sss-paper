"""Hyperparameter tuning for the 'Versomil' signal = Supertrend flip.

The Versomil entry signal is a Supertrend(ATR len, mult, hl2) crossover. The
user's live money model is: index Supertrend flip -> buy ATM option, exit on the
opposite flip or by 15:20. We tune (ATR len, mult) PER INDEX on that real,
after-charges rupee P&L -- NOT index points.

Anti-overfit: each index's ~1yr of 5m history is split into TRAIN (first ~70% of
trading days) and TEST (last ~30%). We pick the best params on TRAIN only, then
report how those exact params do on the unseen TEST slice. A config that wins on
train but dies on test is curve-fit noise and is called out as such.

Exits are reverse+EOD only (atr_mult=100 disables the wide 6xATR stop), to match
scripts/live_paper.py. Charges are Dhan's real intraday-option round-trip.

Usage:  py tune_versomil.py            # tune all 4 indices, 5m
        py tune_versomil.py NIFTY      # one index
"""
import sys
from statistics import median
import st_option_backtest as bt

RES = "5"
ATR_LENS = [7, 10, 12, 15, 18, 21, 25]
MULTS    = [2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]
TRAIN_FRAC = 0.70
MIN_TRADES_TRAIN = 25          # ignore configs too sparse to trust
BIG_STOP = 100.0               # atr_mult so large the stop never fires -> reverse/EOD only

DEFAULT = (bt.ST_ATR_LEN, bt.ST_MULT)   # incumbent (15, 5)


def stats(trades):
    if not trades:
        return None
    net = [t["net"] for t in trades]
    wins = [x for x in net if x > 0]; losses = [x for x in net if x <= 0]
    tot = sum(net)
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf")
    eq = peak = mdd = 0.0
    for x in net:
        eq += x; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    return {"n": len(net), "net": tot, "pf": pf,
            "wr": len(wins) / len(net) * 100, "exp": tot / len(net), "mdd": mdd}


def split_day(idx):
    """Return the date cutoff so ~TRAIN_FRAC of trading days are <= cutoff."""
    days = sorted({b[0].date() for b in bt.load_bars(idx, RES)})
    return days[int(len(days) * TRAIN_FRAC)]


def eval_cfg(idx, atrlen, mult, cutoff):
    trades = bt.run(RES, 1, idx=idx, quiet=True, atr_mult=BIG_STOP,
                    st_atr_len=atrlen, st_mult=mult)
    tr = [t for t in trades if t["day"] < cutoff]
    te = [t for t in trades if t["day"] >= cutoff]
    return stats(tr), stats(te)


def line(tag, s):
    if not s:
        return f"    {tag:14} (no trades)"
    pf = "inf " if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    return (f"    {tag:14} n={s['n']:4d}  win {s['wr']:4.1f}%  PF {pf:>4}  "
            f"net Rs{s['net']:+9,.0f}  exp {s['exp']:+6.0f}  mdd {s['mdd']:+8,.0f}")


def tune(idx):
    cutoff = split_day(idx)
    print(f"\n{'='*78}\n{idx}  ({RES}m)   train: <{cutoff}   test: >={cutoff}\n{'='*78}")
    rows = []
    for a in ATR_LENS:
        for m in MULTS:
            tr, te = eval_cfg(idx, a, m, cutoff)
            rows.append((a, m, tr, te))

    # incumbent baseline
    base = next(r for r in rows if (r[0], r[1]) == DEFAULT)
    print("  incumbent Supertrend(15, 5):")
    print(line("  train", base[2]))
    print(line("  TEST ", base[3]))

    # candidates: profitable & liquid enough on TRAIN
    cand = [r for r in rows if r[2] and r[2]["n"] >= MIN_TRADES_TRAIN and r[2]["net"] > 0]
    if not cand:
        print("\n  No config was net-positive on TRAIN. Signal has no edge here.")
        return None
    best_pf  = max(cand, key=lambda r: r[2]["pf"])
    best_net = max(cand, key=lambda r: r[2]["net"])

    print(f"\n  Top 5 TRAIN configs by profit factor (n>={MIN_TRADES_TRAIN}, then their TEST):")
    print(f"    {'len':>3} {'mult':>4} | {'TRAIN':^42} | {'TEST':^30}")
    for a, m, tr, te in sorted(cand, key=lambda r: r[2]["pf"], reverse=True)[:5]:
        trs = f"n{tr['n']:<3} PF{tr['pf']:.2f} net{tr['net']:+8,.0f} win{tr['wr']:.0f}%"
        tes = f"n{te['n']:<3} PF{te['pf']:.2f} net{te['net']:+8,.0f}" if te else "no test trades"
        star = " <-PF" if (a, m) == (best_pf[0], best_pf[1]) else ""
        star += " <-NET" if (a, m) == (best_net[0], best_net[1]) else ""
        print(f"    {a:>3} {m:>4} | {trs:^42} | {tes:^30}{star}")

    def verdict(pick, label):
        a, m, tr, te = pick
        print(f"\n  >> Best on TRAIN by {label}: Supertrend({a}, {m})")
        print(line("  train", tr))
        print(line("  TEST ", te))
        if te and te["net"] > 0 and te["pf"] > 1.2:
            print(f"     HOLDS out-of-sample (test PF {te['pf']:.2f}, net Rs{te['net']:+,.0f}).")
        elif te and te["net"] > 0:
            print(f"     Marginal OOS (test net +ve but PF only {te['pf']:.2f}).")
        else:
            print("     FAILS out-of-sample -> curve-fit. Do not deploy this.")
        return (a, m, tr, te)

    vp = verdict(best_pf, "profit factor")
    if (best_net[0], best_net[1]) != (best_pf[0], best_pf[1]):
        verdict(best_net, "total net")
    return vp


if __name__ == "__main__":
    idxs = [sys.argv[1].upper()] if len(sys.argv) > 1 else ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
    summary = []
    for ix in idxs:
        try:
            summary.append((ix, tune(ix)))
        except SystemExit as e:
            print(f"\n{ix}: {e}")
    print(f"\n\n{'#'*78}\nSUMMARY -- best TRAIN-by-PF params and whether they survived TEST\n{'#'*78}")
    for ix, v in summary:
        if not v:
            print(f"  {ix:10} -- no net-positive config on train"); continue
        a, m, tr, te = v
        ok = "HOLDS" if (te and te["net"] > 0 and te["pf"] > 1.2) else \
             ("marginal" if te and te["net"] > 0 else "FAILS OOS")
        print(f"  {ix:10} ST({a},{m})  train PF {tr['pf']:.2f}  ->  test PF "
              f"{(te['pf'] if te else 0):.2f}  [{ok}]")

"""WIDE walk-forward tune of the Versomil Supertrend signal -> ATM option.

Grid swept PER INDEX (cached 1yr, 5m):
    source   : hl2 (Versomil) | close (Lux-style)
    atr_len  : 7, 10, 14, 21
    mult     : 2.5, 3, 3.5, 4, 4.5, 5, 6
    exit     : R      reverse+EOD only
               A3     index 3xATR stop + reverse
               A4     index 4xATR stop + reverse
               O40    option 40% stop + reverse
               O30T50 option 30% stop / 50% target + reverse
  => 2*4*7*5 = 280 configs/index.

Walk-forward (the honest part): expanding train window; every ~1 month we re-pick
the best config on everything seen SO FAR (by train net rupees, guarded by min
trades + PF>=1.3), then trade that config BLIND over the next month. We sum only
those out-of-sample months. We also print (a) the fixed incumbent hl2/15/5/R over
the same OOS months, and (b) the single best-over-the-whole-year config and its
full-year net -- the overfit mirage -- so you can see the gap.

Charges are Dhan's real intraday round-trip. 1 lot. No look-ahead: Supertrend is
causal; OOS trades never see future bars.

Usage:  py tune_wf.py            # all 4 indices
        py tune_wf.py NIFTY
"""
import sys, csv, functools
from collections import Counter
from pathlib import Path
import st_option_backtest as bt

# cache disk loads -- we call run() ~1120 times
bt.load_bars = functools.lru_cache(maxsize=None)(bt.load_bars)
bt.load_vix  = functools.lru_cache(maxsize=None)(bt.load_vix)

RES = "5"
SOURCES = ["hl2", "close"]
ATR_LENS = [7, 10, 14, 21]
MULTS    = [2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]
EXITS = {                        # label -> run() kwargs
    "R":      dict(atr_mult=100.0),
    "A3":     dict(atr_mult=3.0),
    "A4":     dict(atr_mult=4.0),
    "O40":    dict(opt_stop=0.40),
    "O30T50": dict(opt_stop=0.30, opt_target=0.50),
}
INCUMBENT = ("hl2", 15, 5.0, "R")

INIT_TRAIN_DAYS = 150            # first ~7 months to learn on
TEST_BLOCK = 21                  # ~1 trading month per OOS fold
MIN_TR_TRAIN = 30                # config must trade this much on train to be eligible
MIN_PF_TRAIN = 1.30
OUT = Path(r"C:\Users\adars\sss\data\versomil_wf.csv")


def stats(trades):
    if not trades:
        return None
    net = [t["net"] for t in trades]
    wins = [x for x in net if x > 0]; losses = [x for x in net if x <= 0]
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf")
    return {"n": len(net), "net": sum(net), "pf": pf, "wr": len(wins)/len(net)*100}


def all_configs():
    for s in SOURCES:
        for a in ATR_LENS:
            for m in MULTS:
                for ex in EXITS:
                    yield (s, a, m, ex)


def full_trades(idx, cfg):
    s, a, m, ex = cfg
    return bt.run(RES, 1, idx=idx, quiet=True, st_source=s, st_atr_len=a,
                  st_mult=m, **EXITS[ex])


def days_of(idx):
    return sorted({b[0].date() for b in bt.load_bars(idx, RES)})


def walk_forward(idx):
    print(f"\n{'='*80}\n{idx}  ({RES}m, cached 1yr)   {len(list(all_configs()))} configs/fold\n{'='*80}")
    days = days_of(idx)
    # precompute every config's full-year trades ONCE, keyed by cfg
    book = {cfg: full_trades(idx, cfg) for cfg in all_configs()}
    if INCUMBENT not in book:                       # ensure incumbent is comparable
        book[INCUMBENT] = full_trades(idx, INCUMBENT)

    def slice_days(trades, d0, d1):
        return [t for t in trades if d0 <= t["day"] < d1]

    folds = []
    t = INIT_TRAIN_DAYS
    while t < len(days):
        train_lo = days[0]; cut = days[t]
        hi = days[min(t + TEST_BLOCK, len(days) - 1)]
        # pick best config on train (all days < cut)
        best = None
        for cfg, tr in book.items():
            s = stats(slice_days(tr, train_lo, cut))
            if not s or s["n"] < MIN_TR_TRAIN or s["pf"] < MIN_PF_TRAIN or s["net"] <= 0:
                continue
            if best is None or s["net"] > best[1]["net"]:
                best = (cfg, s)
        chosen = best[0] if best else INCUMBENT
        te = stats(slice_days(book[chosen], cut, hi))
        inc = stats(slice_days(book[INCUMBENT], cut, hi))
        folds.append({"cut": cut, "hi": hi, "cfg": chosen, "test": te, "inc": inc})
        t += TEST_BLOCK

    # aggregate OOS
    def agg(key):
        tr = [f for f in folds if f[key]]
        net = sum(f[key]["net"] for f in tr)
        n = sum(f[key]["n"] for f in tr)
        gw = sum(f[key]["net"] for f in tr if f[key]["net"] > 0)  # not a true PF; recompute below
        return net, n

    print(f"  Walk-forward OOS months (train on all prior, trade next ~{TEST_BLOCK}d blind):")
    print(f"    {'OOS from':>10} | {'chosen config':22} | {'tuned net':>10} {'n':>3} | {'incumbent net':>13}")
    wf_net = wf_n = inc_net = inc_n = 0
    for f in folds:
        c = f["cfg"]; lab = f"{c[0]}/{c[1]}/{c[2]}/{c[3]}"
        tnet = f["test"]["net"] if f["test"] else 0; tn = f["test"]["n"] if f["test"] else 0
        inet = f["inc"]["net"] if f["inc"] else 0; iN = f["inc"]["n"] if f["inc"] else 0
        wf_net += tnet; wf_n += tn; inc_net += inet; inc_n += iN
        print(f"    {str(f['cut']):>10} | {lab:22} | {tnet:+10,.0f} {tn:>3} | {inet:+13,.0f}")

    stab = Counter(f["cfg"] for f in folds).most_common(3)
    print(f"\n  WALK-FORWARD TOTAL (out-of-sample, {len(folds)} months):")
    print(f"    tuned (re-pick monthly): net Rs{wf_net:+,.0f}  over {wf_n} trades")
    print(f"    fixed incumbent hl2/15/5/R: net Rs{inc_net:+,.0f}  over {inc_n} trades")
    print(f"    config stability (how often each was picked): "
          + ", ".join(f"{c[0]}/{c[1]}/{c[2]}/{c[3]}x{k}" for c, k in stab))

    # the overfit mirage: single best over the WHOLE year
    fy = [(cfg, stats(tr)) for cfg, tr in book.items()]
    fy = [(cfg, s) for cfg, s in fy if s]
    bestfull = max(fy, key=lambda x: x[1]["net"])
    bf, bfs = bestfull
    print(f"\n  (Overfit reference) best single config fit to the WHOLE year: "
          f"{bf[0]}/{bf[1]}/{bf[2]}/{bf[3]}  net Rs{bfs['net']:+,.0f} PF {bfs['pf']:.2f} n{bfs['n']}")
    print(f"    ^ that full-year number is NOT tradable -- it used the future to pick itself.")
    return {"idx": idx, "wf_net": wf_net, "wf_n": wf_n, "inc_net": inc_net,
            "inc_n": inc_n, "months": len(folds), "stab": stab,
            "bestfull": (bf, bfs), "folds": folds, "book_stats": fy}


def save_grid(results):
    rows = []
    for r in results:
        for cfg, s in r["book_stats"]:
            rows.append({"index": r["idx"], "source": cfg[0], "atr_len": cfg[1],
                         "mult": cfg[2], "exit": cfg[3], "full_yr_trades": s["n"],
                         "full_yr_net": f"{s['net']:.0f}", "full_yr_pf": f"{s['pf']:.2f}",
                         "full_yr_win%": f"{s['wr']:.0f}"})
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\nfull grid ({len(rows)} rows) saved -> {OUT}")


if __name__ == "__main__":
    idxs = [sys.argv[1].upper()] if len(sys.argv) > 1 else ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
    res = [walk_forward(ix) for ix in idxs]
    print(f"\n\n{'#'*80}\nWALK-FORWARD SUMMARY (out-of-sample only -- the number that matters)\n{'#'*80}")
    print(f"  {'index':10} {'OOS months':>10} {'tuned net':>12} {'incumbent net':>14} {'edge':>10}")
    for r in res:
        edge = r["wf_net"] - r["inc_net"]
        print(f"  {r['idx']:10} {r['months']:>10} {r['wf_net']:>+12,.0f} {r['inc_net']:>+14,.0f} {edge:>+10,.0f}")
    save_grid(res)

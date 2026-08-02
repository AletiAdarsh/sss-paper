"""Opening Range Breakout (ORB) intraday backtest — research phase.

Data: existing Fyers 5-min feed (fyers_client). Execution later on Dhan.
Goal: does a simple ORB edge survive realistic Indian intraday costs?

Strategy (few params on purpose, to resist overfitting):
  - Opening range = first OR_BARS 5-min candles (default 3 => 09:15-09:30).
  - Long  when a later 5-min bar CLOSES > OR_high*(1+BUF) and close > VWAP and vol filter.
  - Short when a later 5-min bar CLOSES < OR_low *(1-BUF) and close < VWAP and vol filter.
  - Stop = opposite side of the OR. Risk R = |entry - stop|. Target = TGT_R * R.
  - One trade per symbol per day (first valid signal). Square off at SQUAREOFF.
  - Fill assumed at the signal bar's close (conservative-ish; slippage added in costs).

Run:  py orb_backtest.py            # uses cache, pulls if missing
      py orb_backtest.py refetch    # force re-pull
"""
import sys, json, time
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
import pandas as pd
import numpy as np
import fyers_client as fy

ROOT   = Path(r"C:\Users\adars\sss\data")
CACHE  = ROOT / "intraday_cache"
CACHE.mkdir(exist_ok=True)

# ---- universe: liquid large-caps (tight spreads => survivable slippage) ----
UNIVERSE = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
            "SBIN", "AXISBANK", "ITC", "LT", "BHARTIARTL"]

# ---- backtest window ----
START = "2024-07-01"
END   = "2026-07-17"
RES   = "5"                      # 5-min candles

# ---- strategy params ----
OR_BARS   = 3                    # opening-range = first 3 x 5min = 15 min
BUF       = 0.0005               # 0.05% breakout buffer beyond OR
TGT_R     = 1.5                  # target = 1.5x risk
VOL_MULT  = 1.2                  # entry bar vol must exceed VOL_MULT * OR avg vol
SQUAREOFF = "15:15"             # force exit time (IST)
SESS_OPEN = "09:15"
IST       = timezone(timedelta(hours=5, minutes=30))
TRAIL      = False              # if True: ignore fixed target, trail by TRAIL_R * risk
TRAIL_R    = 1.0               # trailing distance in units of initial risk R

# ---- cost model (Dhan intraday equity, realistic) ----
BROKERAGE_PER_ORDER = 20.0       # Dhan flat, per executed leg
STT_SELL   = 0.00025             # 0.025% intraday sell side
EXCH_TXN   = 0.0000297           # NSE ~0.00297% each side
SEBI_FEE   = 0.000001            # Rs 10 / crore
STAMP_BUY  = 0.00003             # 0.003% buy side
GST        = 0.18                # on (brokerage + exch + sebi)
SLIPPAGE   = 0.0003              # 0.03% per side assumption for large caps


def fetch_symbol(sym):
    """Pull 5-min candles across START..END in <=90-day chunks; cache to CSV."""
    f = CACHE / f"{sym}_{RES}m.csv"
    if f.exists():
        df = pd.read_csv(f)
        return df
    s = date.fromisoformat(START); e = date.fromisoformat(END)
    rows, cur = [], s
    while cur <= e:
        nxt = min(e, cur + timedelta(days=90))
        for attempt in range(3):
            try:
                rows += fy.fetch_history(f"NSE:{sym}-EQ", cur.isoformat(), nxt.isoformat(), RES)
                break
            except Exception as ex:
                if attempt == 2:
                    print(f"  ! {sym} {cur}: {ex}")
                time.sleep(1 + attempt)
        time.sleep(0.25)
        cur = nxt + timedelta(days=1)
    seen = {r[0]: r for r in rows}
    rows = [seen[k] for k in sorted(seen)]
    df = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"])
    df.to_csv(f, index=False)
    print(f"  {sym}: {len(df)} bars cached")
    return df


def prep(df):
    """Add IST datetime, date, time, session VWAP (resets daily)."""
    df = df.copy()
    dt = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(IST)
    df["dt"] = dt
    df["day"] = dt.dt.date
    df["hm"] = dt.dt.strftime("%H:%M")
    df["tp"] = (df["h"] + df["l"] + df["c"]) / 3
    df["pv"] = df["tp"] * df["v"]
    g = df.groupby("day")
    df["cum_pv"] = g["pv"].cumsum()
    df["cum_v"]  = g["v"].cumsum()
    df["vwap"]   = df["cum_pv"] / df["cum_v"]
    return df


def costs(buy_val, sell_val):
    """Total round-trip cost in rupees for a buy_val entry and sell_val exit notional."""
    brok = BROKERAGE_PER_ORDER * 2
    stt  = STT_SELL * sell_val
    exch = EXCH_TXN * (buy_val + sell_val)
    sebi = SEBI_FEE * (buy_val + sell_val)
    stamp = STAMP_BUY * buy_val
    gst  = GST * (brok + exch + sebi)
    slip = SLIPPAGE * (buy_val + sell_val)
    return brok + stt + exch + sebi + stamp + gst + slip


def simulate_day(day_df, capital_per_trade):
    """Return one trade dict for the day, or None. day_df sorted by time."""
    d = day_df.reset_index(drop=True)
    if len(d) < OR_BARS + 2:
        return None
    orb = d.iloc[:OR_BARS]
    or_hi, or_lo = orb["h"].max(), orb["l"].min()
    or_vol = orb["v"].mean()
    if or_hi <= or_lo:
        return None

    for i in range(OR_BARS, len(d)):
        bar = d.iloc[i]
        if bar["hm"] >= SQUAREOFF:
            break
        long_sig  = bar["c"] > or_hi * (1 + BUF) and bar["c"] > bar["vwap"]
        short_sig = bar["c"] < or_lo * (1 - BUF) and bar["c"] < bar["vwap"]
        vol_ok    = bar["v"] > VOL_MULT * or_vol
        if not vol_ok:
            continue
        if not (long_sig or short_sig):
            continue

        side  = "L" if long_sig else "S"
        entry = bar["c"]
        stop  = or_lo if side == "L" else or_hi
        risk  = abs(entry - stop)
        if risk <= 0:
            return None
        tgt = entry + TGT_R * risk if side == "L" else entry - TGT_R * risk
        qty = max(1, int(capital_per_trade / entry))

        # walk forward bars to resolve stop / target / squareoff
        exit_px, reason = None, None
        trail_stop = stop
        peak = entry
        for j in range(i + 1, len(d)):
            b = d.iloc[j]
            if TRAIL:
                # update trailing stop toward the running peak, never loosen
                if side == "L":
                    peak = max(peak, b["h"])
                    trail_stop = max(trail_stop, peak - TRAIL_R * risk)
                    if b["l"] <= trail_stop: exit_px, reason = trail_stop, "trail"; break
                else:
                    peak = min(peak, b["l"])
                    trail_stop = min(trail_stop, peak + TRAIL_R * risk)
                    if b["h"] >= trail_stop: exit_px, reason = trail_stop, "trail"; break
            else:
                if side == "L":
                    if b["l"] <= stop:  exit_px, reason = stop, "stop"; break
                    if b["h"] >= tgt:   exit_px, reason = tgt, "target"; break
                else:
                    if b["h"] >= stop:  exit_px, reason = stop, "stop"; break
                    if b["l"] <= tgt:   exit_px, reason = tgt, "target"; break
            if b["hm"] >= SQUAREOFF:
                exit_px, reason = b["c"], "squareoff"; break
        if exit_px is None:
            exit_px, reason = d.iloc[-1]["c"], "eod"

        gross = (exit_px - entry) * qty if side == "L" else (entry - exit_px) * qty
        buy_val  = entry * qty
        sell_val = exit_px * qty
        cost = costs(buy_val, sell_val)
        net = gross - cost
        return {"day": d.iloc[0]["day"], "entry_hm": bar["hm"], "side": side, "entry": entry, "exit": exit_px,
                "qty": qty, "stop": stop, "tgt": tgt, "reason": reason,
                "gross": gross, "cost": cost, "net": net,
                "R": risk * qty, "notional": buy_val}
    return None


def backtest(sym, df, capital_per_trade=200000):
    df = prep(df)
    trades = []
    for day, dd in df.groupby("day"):
        t = simulate_day(dd, capital_per_trade)
        if t: trades.append(t)
    return pd.DataFrame(trades)


def summarize(name, tr):
    if tr.empty:
        print(f"{name:12s}  no trades"); return None
    n = len(tr)
    net = tr["net"]
    wins = net > 0
    gross_sum = tr["gross"].sum()
    cost_sum = tr["cost"].sum()
    exp = net.mean()
    r_multiple = (net / tr["R"]).replace([np.inf, -np.inf], np.nan)
    row = {
        "sym": name, "n": n, "win%": wins.mean() * 100,
        "gross_tot": gross_sum, "cost_tot": cost_sum, "net_tot": net.sum(),
        "exp/trade": exp, "avg_R": r_multiple.mean(),
        "best": net.max(), "worst": net.min(),
        "pf": (net[wins].sum() / -net[~wins].sum()) if (~wins).any() and net[~wins].sum() < 0 else np.nan,
    }
    return row


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "refetch":
        for f in CACHE.glob("*.csv"): f.unlink()

    print(f"Pulling/loading {len(UNIVERSE)} symbols, {RES}-min, {START}..{END} ...")
    data = {}
    for sym in UNIVERSE:
        data[sym] = fetch_symbol(sym)

    print("\n" + "=" * 110)
    print(f"ORB BACKTEST  |  OR={OR_BARS}bars buf={BUF*100:.2f}% tgt={TGT_R}R volx{VOL_MULT} "
          f"sqoff={SQUAREOFF}  |  slip={SLIPPAGE*100:.2f}%/side brok=Rs{BROKERAGE_PER_ORDER}")
    print("=" * 110)

    rows, all_tr = [], []
    for sym in UNIVERSE:
        tr = backtest(sym, data[sym])
        if not tr.empty:
            tr["sym"] = sym
            all_tr.append(tr)
        r = summarize(sym, tr)
        if r: rows.append(r)

    summ = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    print(summ.to_string(index=False))

    if all_tr:
        agg = pd.concat(all_tr, ignore_index=True)
        net = agg["net"]
        wins = net > 0
        print("\n" + "-" * 110)
        print("POOLED (all symbols, treating each trade equally):")
        print(f"  trades={len(agg):,}  win%={wins.mean()*100:.1f}  "
              f"gross=Rs{agg['gross'].sum():,.0f}  costs=Rs{agg['cost'].sum():,.0f}  "
              f"NET=Rs{net.sum():,.0f}")
        print(f"  expectancy/trade = Rs{net.mean():,.1f}   "
              f"(gross/trade Rs{agg['gross'].mean():,.1f}, cost/trade Rs{agg['cost'].mean():,.1f})")
        print(f"  avg R-multiple(net) = {(net/agg['R']).mean():.3f}")
        print(f"  exit reasons: {agg['reason'].value_counts().to_dict()}")
        # verdict
        print("\nVERDICT:", "EDGE SURVIVES COSTS [OK]" if net.mean() > 0 else
              "negative after costs [FAIL] -- do NOT trade this as-is")
        print("NOTE: gross expectancy/trade = Rs%.1f (edge exists at all only if this is clearly >0)"
              % agg['gross'].mean())

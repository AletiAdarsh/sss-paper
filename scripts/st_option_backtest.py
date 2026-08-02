"""Supertrend -> ATM-option backtest on the Nifty index.

Ports the real trade logic out of the user's "Signals @Versomil" Pine strategy:
its engine is just a Supertrend(ATR 15, mult 5) crossover on hl2 --
    price crosses ABOVE supertrend -> BUY  (go long  -> buy ATM CE)
    price crosses BELOW supertrend -> SELL (go short -> buy ATM PE)
(the RSI/ATR "sideways" filter is OFF by default; the A/B/C/D timeframe blocks
and all the Binance/Zignaly/Telegram code are dashboard/alert noise, not trades.)

We run those signals on the Nifty *index* at 5m (or 1m), and on each flip
"execute" an ATM option, pricing the premium with Black-Scholes using India VIX
as the IV input. Fills are at the signal price with NO slippage (user's call);
only real Dhan charges are deducted.

Stage 1 exit model: reverse on the opposite flip, plus a hard 6xATR index stop.
Flat by end of day -- no overnight holds.

Usage:
    py st_option_backtest.py fetch            # pull 5m + 1m Nifty + daily VIX (needs token)
    py st_option_backtest.py run 5            # backtest on 5m
    py st_option_backtest.py run 1            # backtest on 1m
    py st_option_backtest.py selftest         # validate supertrend + BS, no token
"""
import sys, math, csv
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
import os
ROOT = Path(os.environ.get("SSS_ROOT", r"C:\Users\adars\sss"))
DATA = ROOT / "data" / "intraday_cache"
DATA.mkdir(parents=True, exist_ok=True)

# ---- strategy params (from the Pine) ------------------------------------
ST_ATR_LEN = 15        # supertrend ATR length
ST_MULT    = 5         # supertrend multiplier
STOP_ATR   = 6         # hard stop = 6 x ATR(14) on the index
TP_ATR_LEN = 14

# ---- indices (symbol, cache-file stem, lot size, strike step) -------------
# expiry: "weekly" (Nifty & Sensex still have weeklies) or "monthly" (BankNifty &
# FinNifty weeklies were discontinued late-2024 -> monthly only). iv_mult scales
# India VIX to that index's own vol (BankNifty runs ~1.25x Nifty).
INDEXES = {
    "NIFTY":     {"sym": "NSE:NIFTY50-INDEX",   "file": "NIFTY50INDEX", "lot": 65, "step": 50,  "expiry": "weekly",  "iv_mult": 1.00},
    "BANKNIFTY": {"sym": "NSE:NIFTYBANK-INDEX",  "file": "BANKNIFTY",    "lot": 30, "step": 100, "expiry": "monthly", "iv_mult": 1.25},
    "FINNIFTY":  {"sym": "NSE:FINNIFTY-INDEX",   "file": "FINNIFTY",     "lot": 60, "step": 50,  "expiry": "monthly", "iv_mult": 1.05},
    "SENSEX":    {"sym": "BSE:SENSEX-INDEX",     "file": "SENSEX",       "lot": 20, "step": 100, "expiry": "weekly",  "iv_mult": 1.00},
}

LOT       = 65         # default (Nifty) lot size
STRIKE_STEP = 50       # default (Nifty) strike step
R_FREE    = 0.065
EXPIRY_WD = 1          # weekly expiry weekday: Tue=1 (Mon=0)  [per memory]
NO_NEW_AFTER = time(15, 0)    # don't open fresh trades after this
FORCE_FLAT   = time(15, 20)   # square off by this
DAY_OPEN     = time(9, 15)

# =========================================================================
# Black-Scholes
# =========================================================================
def _ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bs_price(S, K, T, sigma, kind, r=R_FREE):
    """European option price. kind 'CE' or 'PE'. T in years, sigma abs (0.13=13%)."""
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K) if kind == "CE" else max(0.0, K - S)
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / sq
    d2 = d1 - sq
    if kind == "CE":
        return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)

def next_expiry(dt, wd=EXPIRY_WD):
    """Next weekly-expiry datetime (that weekday, 15:30 IST) at or after dt."""
    d = dt.date()
    ahead = (wd - d.weekday()) % 7
    exp = datetime.combine(d + timedelta(days=ahead), time(15, 30), tzinfo=IST)
    if dt > exp:
        exp += timedelta(days=7)
    return exp

def last_weekday_of_month(y, m, wd):
    import calendar
    last = calendar.monthrange(y, m)[1]
    d = date(y, m, last)
    return d - timedelta(days=(d.weekday() - wd) % 7)

def expiry_dt(dt, mode="weekly", wd=EXPIRY_WD):
    if mode == "monthly":
        e = datetime.combine(last_weekday_of_month(dt.year, dt.month, wd),
                             time(15, 30), tzinfo=IST)
        if dt > e:
            ny, nm = (dt.year + 1, 1) if dt.month == 12 else (dt.year, dt.month + 1)
            e = datetime.combine(last_weekday_of_month(ny, nm, wd), time(15, 30), tzinfo=IST)
        return e
    return next_expiry(dt, wd)

def tau_years(dt, mode="weekly"):
    secs = (expiry_dt(dt, mode) - dt).total_seconds()
    return max(secs, 900) / (365 * 24 * 3600)   # floor 15 min so premium never 0

# =========================================================================
# Indicators
# =========================================================================
def wilder_atr(h, l, c, n):
    """RMA-smoothed ATR (Pine's atr())."""
    tr = [0.0] * len(c)
    for i in range(len(c)):
        if i == 0:
            tr[i] = h[i] - l[i]
        else:
            tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
    atr = [0.0] * len(c)
    if not c:
        return atr
    seed = sum(tr[:n]) / n if len(tr) >= n else tr[0]
    for i in range(len(c)):
        if i < n:
            atr[i] = seed
        else:
            atr[i] = (atr[i-1] * (n - 1) + tr[i]) / n
    return atr

def adx(h, l, c, n=14):
    """Wilder ADX. Low ADX (<~20) = sideways/choppy; high = trending."""
    N = len(c)
    tr = [0.0] * N; pdm = [0.0] * N; ndm = [0.0] * N
    for i in range(1, N):
        up = h[i] - h[i-1]; dn = l[i-1] - l[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i]  = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    def rma(x):
        out = [0.0]*N
        if N <= n: return out
        seed = sum(x[1:n+1]) / n
        out[n] = seed
        for i in range(n+1, N):
            out[i] = (out[i-1]*(n-1) + x[i]) / n
        return out
    atr_ = rma(tr); pdi_ = rma(pdm); ndi_ = rma(ndm)
    adx_ = [0.0]*N; dx = [0.0]*N
    for i in range(N):
        a = atr_[i]
        if a > 0:
            pdi = 100*pdi_[i]/a; ndi = 100*ndi_[i]/a
            ssum = pdi+ndi
            dx[i] = 100*abs(pdi-ndi)/ssum if ssum > 0 else 0.0
    # ADX = RMA of DX, starting after first valid window
    start = 2*n
    if N > start:
        adx_[start] = sum(dx[n+1:start+1]) / n
        for i in range(start+1, N):
            adx_[i] = (adx_[i-1]*(n-1) + dx[i]) / n
    return adx_


def supertrend(h, l, c, atr_len=ST_ATR_LEN, mult=ST_MULT, source="hl2"):
    """Faithful port of the Pine supertrend block. Returns (st[], trend[])."""
    n = len(c)
    atr = wilder_atr(h, l, c, atr_len)
    src = [(h[i] + l[i]) / 2 for i in range(n)] if source == "hl2" else list(c)
    up = [0.0] * n
    dn = [0.0] * n
    trend = [1] * n
    for i in range(n):
        up[i] = src[i] - mult * atr[i]
        dn[i] = src[i] + mult * atr[i]
        if i == 0:
            continue
        up1, dn1 = up[i-1], dn[i-1]
        up[i] = max(up[i], up1) if c[i-1] > up1 else up[i]
        dn[i] = min(dn[i], dn1) if c[i-1] < dn1 else dn[i]
        if trend[i-1] == -1 and c[i] > dn1:
            trend[i] = 1
        elif trend[i-1] == 1 and c[i] < up1:
            trend[i] = -1
        else:
            trend[i] = trend[i-1]
    st = [up[i] if trend[i] == 1 else dn[i] for i in range(n)]
    return st, trend

def swing_levels(h, l, L=3):
    """Pivot swings: last_sh[i]/last_sl[i] = most recent CONFIRMED swing high/low
    value known as of bar i (a pivot at j is confirmed L bars later, no look-ahead)."""
    n = len(h)
    last_sh = [None] * n; last_sl = [None] * n
    csh = csl = None
    for i in range(n):
        j = i - L
        if j - L >= 0:
            if h[j] == max(h[j-L:j+L+1]): csh = h[j]
            if l[j] == min(l[j-L:j+L+1]): csl = l[j]
        last_sh[i] = csh; last_sl[i] = csl
    return last_sh, last_sl


def htf_trend_for(dts, o, h, l, c, minutes=15):
    """Supertrend trend on a higher timeframe, mapped back to each base bar using
    only the last CLOSED higher-tf bar (no look-ahead)."""
    from collections import OrderedDict
    buckets = OrderedDict()
    for i, dt in enumerate(dts):
        key = dt.replace(minute=(dt.minute // minutes) * minutes, second=0, microsecond=0)
        b = buckets.get(key)
        if b is None:
            buckets[key] = [dt, o[i], h[i], l[i], c[i]]     # start,O,H,L,C
        else:
            b[2] = max(b[2], h[i]); b[3] = min(b[3], l[i]); b[4] = c[i]
    keys = list(buckets.keys())
    H = [buckets[k][2] for k in keys]; L_ = [buckets[k][3] for k in keys]
    C = [buckets[k][4] for k in keys]
    _, htrend = supertrend(H, L_, C)
    kt = {keys[j]: htrend[j] for j in range(len(keys))}
    kidx = {keys[j]: j for j in range(len(keys))}
    out = [0] * len(dts)
    for i, dt in enumerate(dts):
        key = dt.replace(minute=(dt.minute // minutes) * minutes, second=0, microsecond=0)
        j = kidx[key]
        out[i] = htrend[j-1] if j > 0 else htrend[j]        # last CLOSED htf bar
    return out


# =========================================================================
# Charges (Dhan intraday options, per round trip, on the whole position)
# =========================================================================
def charges(entry_prem, exit_prem, qty):
    buy_val  = entry_prem * qty
    sell_val = exit_prem  * qty
    brokerage = 20 + 20                                   # Dhan flat 20/order
    stt       = 0.001 * sell_val                          # 0.1% on sell premium
    exch      = 0.0003503 * (buy_val + sell_val)          # NSE txn charge
    sebi      = 0.000001 * (buy_val + sell_val)
    stamp     = 0.00003 * buy_val
    gst       = 0.18 * (brokerage + exch + sebi)
    return brokerage + stt + exch + sebi + stamp + gst

# =========================================================================
# Data
# =========================================================================
def cache_path(idx, res):
    return DATA / f"{INDEXES[idx]['file']}_{res}m.csv"

def fetch_index(idx, resolutions=("5", "1")):
    import fyers_client as fy
    end = date.today()
    sym = INDEXES[idx]["sym"]
    for res in resolutions:
        rows, cur = [], end - timedelta(days=360)
        while cur <= end:
            nxt = min(end, cur + timedelta(days=90))
            try:
                rows += fy.fetch_history(sym, cur.isoformat(), nxt.isoformat(), res)
            except Exception as e:
                print(f"  {idx} {res}m fetch err: {str(e)[:60]}")
            cur = nxt + timedelta(days=1)
        seen = {r[0]: r for r in rows}
        rows = [seen[k] for k in sorted(seen)]
        p = cache_path(idx, res)
        with p.open("w", newline="") as f:
            w = csv.writer(f); w.writerow(["ts", "o", "h", "l", "c", "v"])
            for r in rows:
                w.writerow(r[:6])
        print(f"  {idx} {res}m: {len(rows):,} bars -> {p.name}")

def fetch_all():
    fetch_index("NIFTY")
    import fyers_client as fy
    end = date.today()
    vrows = fy.fetch_history("NSE:INDIAVIX-INDEX",
                             (end - timedelta(days=360)).isoformat(), end.isoformat(), "D")
    p = DATA / "INDIAVIX_D.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["ts", "o", "h", "l", "c"])
        for r in vrows:
            w.writerow(r[:5])
    print(f"  VIX: {len(vrows):,} days -> {p.name}")

def load_bars(idx, res):
    p = cache_path(idx, res)
    if not p.exists():
        sys.exit(f"no cache for {idx} {res}m -- run: py st_option_backtest.py fetchidx {idx}")
    out = []
    with p.open() as f:
        for row in csv.DictReader(f):
            dt = datetime.fromtimestamp(int(row["ts"]), IST)
            out.append((dt, float(row["o"]), float(row["h"]),
                        float(row["l"]), float(row["c"])))
    return out

def load_vix():
    p = DATA / "INDIAVIX_D.csv"
    vix = {}
    if p.exists():
        with p.open() as f:
            for row in csv.DictReader(f):
                d = datetime.fromtimestamp(int(row["ts"]), IST).date()
                vix[d] = float(row["c"])
    return vix

def vix_for(vix, d):
    if not vix:
        return 13.0                     # sane default if VIX missing
    if d in vix:
        return vix[d]
    prior = [k for k in vix if k <= d]
    return vix[max(prior)] if prior else vix[min(vix)]

# =========================================================================
# Backtest
# =========================================================================
def atm(strike_ref, step=STRIKE_STEP):
    return round(strike_ref / step) * step

def run(res, lots=1, adx_min=0.0, swing_stop=False, htf=0, swing_len=3,
        candle_stop=None, atr_mult=None, opt_stop=None, opt_target=None,
        idx="NIFTY", quiet=False, st_atr_len=ST_ATR_LEN, st_mult=ST_MULT,
        st_source="hl2"):
    cfg = INDEXES[idx]; lot_size = cfg["lot"]; step = cfg["step"]
    bars = load_bars(idx, res)
    vix = load_vix()
    dts  = [b[0] for b in bars]
    o = [b[1] for b in bars]; h = [b[2] for b in bars]
    l = [b[3] for b in bars]; c = [b[4] for b in bars]
    st, trend = supertrend(h, l, c, st_atr_len, st_mult, st_source)
    atr14 = wilder_atr(h, l, c, TP_ATR_LEN)
    adx_ = adx(h, l, c) if adx_min > 0 else None
    sh, sl = swing_levels(h, l, swing_len) if swing_stop else (None, None)
    htrend = htf_trend_for(dts, o, h, l, c, htf) if htf else None
    qty = lots * lot_size

    trades = []
    pos = None   # {side,K,exp,entry_S,entry_prem,entry_dt}

    exp_mode = cfg["expiry"]; iv_mult = cfg["iv_mult"]

    def price(side, S, dt, K):
        sigma = vix_for(vix, dt.date()) / 100.0 * iv_mult
        return bs_price(S, K, tau_years(dt, exp_mode), sigma, side)

    def close_pos(S, dt, reason):
        nonlocal pos
        exit_prem = price(pos["side"], S, dt, pos["K"])
        gross = (exit_prem - pos["entry_prem"]) * qty
        fee = charges(pos["entry_prem"], exit_prem, qty)
        trades.append({
            "day": pos["entry_dt"].date(), "side": pos["side"],
            "in": pos["entry_dt"], "out": dt, "K": pos["K"],
            "entry_prem": pos["entry_prem"], "exit_prem": exit_prem,
            "gross": gross, "fee": fee, "net": gross - fee, "reason": reason,
            "idx_move": (S - pos["entry_S"]) if pos["side"] == "CE" else (pos["entry_S"] - S),
        })
        pos = None

    n = len(bars)
    warmup = max(st_atr_len, TP_ATR_LEN) + 2
    for i in range(warmup, n):
        dt = dts[i]; S = c[i]; tod = dt.time()
        # new day boundary -> force-flat any leftover (shouldn't happen, safety)
        if pos and dt.date() != pos["entry_dt"].date():
            close_pos(o[i], dt, "day-gap")
        # end-of-day square off
        if pos and tod >= FORCE_FLAT:
            close_pos(S, dt, "eod")
            continue
        if tod < DAY_OPEN or tod >= FORCE_FLAT:
            continue

        flip_up   = trend[i] == 1 and trend[i-1] == -1
        flip_down = trend[i] == -1 and trend[i-1] == 1

        # ---- manage open position ----
        if pos:
            opp = (pos["side"] == "CE" and flip_down) or (pos["side"] == "PE" and flip_up)
            if opt_stop is not None:
                # risk denominated in the OPTION premium, not index points
                cur = price(pos["side"], S, dt, pos["K"])
                ep = pos["entry_prem"]
                if cur <= ep * (1 - opt_stop):
                    close_pos(S, dt, "opt-stop")
                elif opt_target is not None and cur >= ep * (1 + opt_target):
                    close_pos(S, dt, "target")
                elif opp:
                    close_pos(S, dt, "reverse")
            else:
                lvl = pos["stop"]
                intrabar = candle_stop is not None or atr_mult is not None
                if intrabar:
                    stop_hit = (pos["side"] == "CE" and l[i] <= lvl) or (pos["side"] == "PE" and h[i] >= lvl)
                    exit_S = lvl                  # stop fills ~at the level
                else:
                    stop_hit = (pos["side"] == "CE" and S <= lvl) or (pos["side"] == "PE" and S >= lvl)
                    exit_S = S
                if stop_hit:
                    close_pos(exit_S, dt, "stop")
                elif opp:
                    close_pos(S, dt, "reverse")

        # ---- new entry on flip ----
        trending = (adx_ is None) or (adx_[i] >= adx_min)
        htf_ok = (htrend is None) or (flip_up and htrend[i] == 1) or (flip_down and htrend[i] == -1)
        if not pos and trending and htf_ok and tod < NO_NEW_AFTER and (flip_up or flip_down):
            side = "CE" if flip_up else "PE"
            K = atm(S, step)
            # stop level
            if candle_stop is not None:
                k = min(candle_stop, i)            # candles back from the entry candle
                lvl = l[i - k] if side == "CE" else h[i - k]
            elif atr_mult is not None:
                lvl = S - atr_mult * atr14[i] if side == "CE" else S + atr_mult * atr14[i]
            elif swing_stop:
                if side == "CE":
                    lvl = sl[i] if sl[i] is not None else S - STOP_ATR * atr14[i]
                else:
                    lvl = sh[i] if sh[i] is not None else S + STOP_ATR * atr14[i]
            else:
                lvl = S - STOP_ATR * atr14[i] if side == "CE" else S + STOP_ATR * atr14[i]
            pos = {"side": side, "K": K, "entry_S": S, "stop": lvl,
                   "entry_prem": price(side, S, dt, K), "entry_dt": dt}

    if pos:
        close_pos(c[-1], dts[-1], "eod")

    if not quiet:
        bits = []
        if adx_min > 0: bits.append(f"ADX>={adx_min:.0f}")
        if htf: bits.append(f"{htf}m-agree")
        if opt_stop is not None:
            lab = f"opt-SL {opt_stop*100:.0f}%"
            if opt_target is not None: lab += f" / TP {opt_target*100:.0f}%"
            bits.append(lab)
        elif candle_stop is not None:
            bits.append(f"SL@low[-{candle_stop}]-tight")
        elif atr_mult is not None:
            bits.append(f"{atr_mult:g}xATR-stop")
        else:
            bits.append("swing-stop" if swing_stop else "6xATR-stop")
        report(res, trades, lots, " + ".join(bits), idx)
    return trades

# =========================================================================
# Report
# =========================================================================
def report(res, trades, lots, cfg="6xATR-stop", idx="NIFTY"):
    if not trades:
        print(f"\n{idx} {res}m [{cfg}]: no trades"); return
    net = [t["net"] for t in trades]
    wins = [x for x in net if x > 0]; losses = [x for x in net if x <= 0]
    total = sum(net); gross = sum(t["gross"] for t in trades); fees = sum(t["fee"] for t in trades)
    wr = len(wins) / len(trades) * 100
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf")
    # equity curve / max drawdown
    eq = 0; peak = 0; mdd = 0
    for x in net:
        eq += x; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    days = sorted({t["day"] for t in trades})
    by_day = {d: 0 for d in days}
    for t in trades:
        by_day[t["day"]] += t["net"]
    green_days = sum(1 for v in by_day.values() if v > 0)
    ce = [t for t in trades if t["side"] == "CE"]; pe = [t for t in trades if t["side"] == "PE"]
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    ls = INDEXES[idx]["lot"]
    print(f"\n{'='*66}\n{idx} {res}m  |  Supertrend(15,5) -> ATM  |  {lots} lot(s) ({lots*ls} qty)  |  {cfg}")
    print(f"{'='*66}")
    print(f"  Window            : {days[0]}  ->  {days[-1]}  ({len(days)} trading days)")
    print(f"  Trades            : {len(trades)}   ({len(ce)} CE / {len(pe)} PE)")
    print(f"  Win rate          : {wr:.1f}%   ({len(wins)}W / {len(losses)}L)")
    print(f"  Avg win / avg loss: +{(sum(wins)/len(wins) if wins else 0):,.0f}  /  {(sum(losses)/len(losses) if losses else 0):,.0f}")
    print(f"  Expectancy/trade  : {total/len(trades):+,.0f}")
    print(f"  Profit factor     : {pf:.2f}")
    print(f"  Gross P&L         : {gross:+,.0f}")
    print(f"  Charges paid      : -{fees:,.0f}   ({fees/len(trades):,.0f}/trade)")
    print(f"  NET P&L           : {total:+,.0f}")
    print(f"  Max drawdown      : {mdd:,.0f}")
    print(f"  Day win rate      : {green_days}/{len(days)} = {green_days/len(days)*100:.0f}%  "
          f"| avg/day {total/len(days):+,.0f}")
    print(f"  Exit reasons      : {reasons}")
    print(f"  --- per side ---")
    for label, grp in (("CE", ce), ("PE", pe)):
        if grp:
            gnet = sum(t['net'] for t in grp); gw = sum(1 for t in grp if t['net'] > 0)
            print(f"    {label}: {len(grp)} trades, {gw/len(grp)*100:.0f}% win, net {gnet:+,.0f}")

# =========================================================================
def selftest():
    # synthetic: a clean up-trend then down-trend -> supertrend must flip once each way
    import random
    random.seed(1)
    h=[];l=[];c=[]
    px=24000
    for i in range(120):
        drift = 8 if i < 60 else -8
        px += drift + random.uniform(-3, 3)
        hi=px+5; lo=px-5
        h.append(hi); l.append(lo); c.append(px)
    st, tr = supertrend(h,l,c)
    flips = sum(1 for i in range(1,len(tr)) if tr[i]!=tr[i-1])
    print("supertrend flips on synthetic trend-reversal:", flips, "(expect >=1)")
    # BS sanity: ATM call ~ ATM put (put-call parity ~ small for ATM short T)
    S=24000; K=24000; T=3/365; sig=0.13
    ce=bs_price(S,K,T,sig,"CE"); pe=bs_price(S,K,T,sig,"PE")
    print(f"ATM CE={ce:.1f}  PE={pe:.1f}  (should be close, ~tens of points)")
    print(f"tau on a Tue expiry morning: {tau_years(datetime(2026,7,28,9,15,tzinfo=IST))*365*24:.1f} hrs left")
    print(f"charges on 260q @120->118: Rs {charges(120,118,260):.0f}")

# =========================================================================
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "fetch":
        fetch_all()
    elif cmd == "fetchidx":
        fetch_index(sys.argv[2], resolutions=("5",))
    elif cmd == "indexcompare":
        lots = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        m = float(sys.argv[3]) if len(sys.argv) > 3 else 4
        for ix in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
            try:
                run("5", lots, atr_mult=m, idx=ix)
            except SystemExit as e:
                print(f"\n{ix}: {e}")
    elif cmd == "run":
        res = sys.argv[2] if len(sys.argv) > 2 else "5"
        lots = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        adxm = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
        run(res, lots, adxm)
    elif cmd == "compare":
        lots = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        for res in ("5", "1"):
            for adxm in (0.0, 20.0, 25.0):
                run(res, lots, adxm)
    elif cmd == "improve":
        lots = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        run("5", lots)                                          # baseline
        run("5", lots, swing_stop=True)                        # swing stop only
        run("5", lots, htf=15)                                 # 15m veto only
        run("5", lots, swing_stop=True, htf=15)                # both
        run("5", lots, swing_stop=True, htf=15, adx_min=20)    # both + ADX
    elif cmd == "tightstop":
        res  = sys.argv[2] if len(sys.argv) > 2 else "5"
        lots = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        run(res, lots)                                          # baseline (hold, wide)
        for k in (0, 1, 2, 3):
            run(res, lots, candle_stop=k)
    elif cmd == "atrsweep":
        res  = sys.argv[2] if len(sys.argv) > 2 else "5"
        lots = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        for m in (1, 2, 3, 4, 5, 6):
            run(res, lots, atr_mult=m)
    elif cmd == "optstop":
        ix = sys.argv[2] if len(sys.argv) > 2 else "NIFTY"
        run("5", 1, atr_mult=4, idx=ix)                        # index-ATR reference
        for s in (0.20, 0.30, 0.40, 0.50):
            run("5", 1, opt_stop=s, idx=ix)                    # option %-stop, let winners run
        run("5", 1, opt_stop=0.30, opt_target=0.50, idx=ix)   # option stop + option target
    elif cmd == "selftest":
        selftest()
    else:
        print(__doc__)

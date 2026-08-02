"""LIVE PAPER runner -- Lux Algo 5m signal on the INDEX -> buy ATM option.
NIFTY, BANKNIFTY, SENSEX. Paper only: NO broker/order calls exist here.

Each pass: refresh token, for each index pull recent 5m bars, look at the last
FULLY-CLOSED 5m bar, and if it's a fresh Lux flip open a paper ATM option; close
on the opposite flip or by 15:20. Premium is BS+VIX modelled. Every action is
appended to data/live/ledger.csv; open positions live in data/live/state.json.

De-dupes on the 5m bar timestamp, so polling every 1 min is safe (acts once/bar).

Run once:      py live_paper.py
Poll 5x/1min:  py live_paper.py --loop 5 --interval 60
"""
import os, sys, csv, json, time as _time
from datetime import date, timedelta, datetime, timezone, time
from pathlib import Path
import fyers_client as fy
import fyers_auth
import st_option_backtest as bt
import lux_algo as la

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(os.environ.get("SSS_ROOT", r"C:\Users\adars\sss"))
LIVE = ROOT / "data" / "live"
LEDGER = LIVE / "ledger.csv"
STATE = LIVE / "state.json"
LOTS = {"NIFTY": 1, "BANKNIFTY": 1, "SENSEX": 1}
# Tuned Lux signal params (see TUNING_FINDINGS.md): factor 5.5 -> 4.0 is the one
# robust, walk-forward-validated change (+~60% OOS). Length 11, SMA-13 gate,
# reverse exit all unchanged. lux_algo.py stays at 5.5 for the comparison scripts.
LUX_FACTOR = 4.0
LUX_ATRLEN = 11
DAY_OPEN = time(9, 15); NO_NEW = time(15, 0); FORCE_FLAT = time(15, 20); MKT_CLOSE = time(15, 30)
COLS = ["ts_ist", "index", "action", "side", "strike", "index_px", "premium",
        "lots", "qty", "pnl", "reason", "bar_ts"]


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {}


def save_state(s):
    LIVE.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2))


def append(row):
    LIVE.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerow(row)


def vix_now():
    e = date.today()
    try:
        r = fy.fetch_history("NSE:INDIAVIX-INDEX", (e - timedelta(days=6)).isoformat(), e.isoformat(), "D")
        return r[-1][4] if r else 13.0
    except Exception:
        return 13.0


def bars5(sym):
    e = date.today()
    r = fy.fetch_history(sym, (e - timedelta(days=6)).isoformat(), e.isoformat(), "5")
    seen = {x[0]: x for x in r}
    return [seen[k] for k in sorted(seen)]


def lux_signal(rows):
    """Return (bar_ts, dt, flip) for the last FULLY-CLOSED 5m bar. flip in {+1,-1,0}."""
    now = _time.time()
    closed = [x for x in rows if x[0] + 300 <= now]
    if len(closed) < 20:
        return None
    o = [x[1] for x in closed]; h = [x[2] for x in closed]; l = [x[3] for x in closed]; c = [x[4] for x in closed]
    st, dr = la.lux_supertrend(o, h, l, c, LUX_FACTOR, LUX_ATRLEN); sm = la.sma(c, la.SMA_LEN)
    i = len(closed) - 1
    up = c[i] > st[i] and c[i - 1] <= st[i - 1] and c[i] >= sm[i]
    dn = c[i] < st[i] and c[i - 1] >= st[i - 1] and c[i] <= sm[i]
    return closed[i][0], datetime.fromtimestamp(closed[i][0], IST), (1 if up else -1 if dn else 0), c[i]


def process(name, state, vix):
    cfg = bt.INDEXES[name]; step = cfg["step"]; lot = cfg["lot"]; exp = cfg["expiry"]
    iv = vix / 100 * cfg["iv_mult"]; lots = LOTS[name]; qty = lots * lot
    sig = lux_signal(bars5(cfg["sym"]))
    if not sig:
        return
    bar_ts, dt, flip, px = sig
    tod = dt.time()
    if not (DAY_OPEN <= tod <= MKT_CLOSE):
        return
    st_i = state.setdefault(name, {"open": None, "last_bar_ts": 0})
    if bar_ts == st_i["last_bar_ts"]:
        return                                   # already handled this 5m bar
    st_i["last_bar_ts"] = bar_ts

    def prem(side, K):
        return bt.bs_price(px, K, bt.tau_years(dt, exp), iv, side)

    pos = st_i["open"]
    # ---- exits: opposite flip or end of day ----
    if pos:
        opp = (pos["side"] == "CE" and flip == -1) or (pos["side"] == "PE" and flip == 1)
        if opp or tod >= FORCE_FLAT:
            side0 = pos["side"]
            xp = prem(side0, pos["strike"])
            pnl = (xp - pos["premium"]) * qty - bt.charges(pos["premium"], xp, qty)
            append({"ts_ist": dt.strftime("%Y-%m-%d %H:%M"), "index": name, "action": "CLOSE",
                    "side": side0, "strike": pos["strike"], "index_px": f"{px:.1f}",
                    "premium": f"{xp:.2f}", "lots": lots, "qty": qty, "pnl": f"{pnl:.0f}",
                    "reason": "reverse" if opp else "eod", "bar_ts": bar_ts})
            st_i["open"] = None; pos = None
            print(f"  {name}: CLOSE {side0} -> pnl Rs{pnl:+,.0f}")
    # ---- entries: fresh flip, not after 15:00 ----
    if not st_i["open"] and flip != 0 and tod < NO_NEW:
        side = "CE" if flip == 1 else "PE"; K = round(px / step) * step
        ep = prem(side, K)
        st_i["open"] = {"side": side, "strike": K, "premium": ep, "bar_ts": bar_ts,
                        "opened": dt.strftime("%Y-%m-%d %H:%M")}
        append({"ts_ist": dt.strftime("%Y-%m-%d %H:%M"), "index": name, "action": "OPEN",
                "side": side, "strike": K, "index_px": f"{px:.1f}", "premium": f"{ep:.2f}",
                "lots": lots, "qty": qty, "pnl": "", "reason": "flip", "bar_ts": bar_ts})
        print(f"  {name}: OPEN {side} {K} @ {ep:.1f}  (index {px:.1f})")


def one_pass():
    try:
        fyers_auth.ensure_token()
    except Exception as e:
        print(f"token error: {e}"); return
    vix = vix_now()
    state = load_state()
    stamp = datetime.now(IST).strftime("%H:%M:%S")
    print(f"[{stamp}] check (VIX {vix})")
    for name in ("NIFTY", "BANKNIFTY", "SENSEX"):
        try:
            process(name, state, vix)
        except Exception as e:
            print(f"  {name}: ERR {e}")
    save_state(state)


def main():
    loop = 1; interval = 60
    if "--loop" in sys.argv:
        loop = int(sys.argv[sys.argv.index("--loop") + 1])
    if "--interval" in sys.argv:
        interval = int(sys.argv[sys.argv.index("--interval") + 1])
    for k in range(loop):
        one_pass()
        if k < loop - 1:
            _time.sleep(interval)


if __name__ == "__main__":
    main()

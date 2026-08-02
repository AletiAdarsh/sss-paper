"""Daily-range screener: find stocks that ACTUALLY MOVE enough to trade intraday.

Premise (the user's insight, confirmed by the ORB backtest): a stock that only
ranges 0.5-1% a day cannot pay ~0.3-0.5% round-trip costs. We want stocks whose
daily range is reliably 2-3%+ AND that are liquid enough that slippage stays sane.

For each of ~742 stocks over daily OHLCV we compute:
  ADR%        = mean( (high-low)/close ) * 100      -> average daily travel
  ADR%_1y     = same, last 250 trading days         -> is it STILL moving now?
  pct_days_2  = share of days with range >= 2%       -> consistency of movement
  pct_days_3  = share of days with range >= 3%
  turn_cr     = median daily turnover (close*vol) in Rs crore  -> liquidity
  last_close  = latest price (affordability at small capital)

Screen: ADR%_1y >= MIN_ADR  AND  pct_days_2(1y) >= MIN_CONSISTENCY  AND
        turn_cr >= MIN_TURNOVER   (liquidity floor keeps slippage realistic).

Run:  py range_screener.py
"""
import pandas as pd, numpy as np
from pathlib import Path

ROOT = Path(r"C:\Users\adars\sss\data")
OHLCV = ROOT / "ohlcv_fyers"
CONST = ROOT / "nifty_total_market_constituents.csv"

# ---- screen thresholds ----
MIN_ADR         = 2.5     # avg daily range % over last year
MIN_CONSISTENCY = 40.0    # >= this % of days ranged >= 2% (last year)
MIN_TURNOVER    = 25.0    # >= Rs 25 cr median daily turnover (liquidity floor)
YEAR_DAYS       = 250

const = pd.read_csv(CONST)
ind_map = dict(zip(const["Symbol"].astype(str), const["Industry"].astype(str)))

rows = []
for f in sorted(OHLCV.glob("*.csv")):
    sym = f.stem
    try:
        df = pd.read_csv(f)
    except Exception:
        continue
    if len(df) < 300 or not {"high", "low", "close", "volume"}.issubset(df.columns):
        continue
    df = df.dropna(subset=["high", "low", "close"])
    df = df[df["close"] > 0]
    if len(df) < 300:
        continue

    rng = (df["high"] - df["low"]) / df["close"] * 100.0
    turn = df["close"] * df["volume"] / 1e7          # Rs crore
    df5 = df.tail(YEAR_DAYS * 5)
    df1 = df.tail(YEAR_DAYS)
    rng5 = rng.tail(YEAR_DAYS * 5)
    rng1 = rng.tail(YEAR_DAYS)

    rows.append({
        "sym": sym,
        "industry": ind_map.get(sym, "")[:22],
        "adr5": rng5.mean(),
        "adr1": rng1.mean(),
        "pct2_1y": (rng1 >= 2).mean() * 100,
        "pct3_1y": (rng1 >= 3).mean() * 100,
        "turn_cr": turn.tail(YEAR_DAYS).median(),
        "last": df["close"].iloc[-1],
        "ndays": len(df),
    })

res = pd.DataFrame(rows)
pd.set_option("display.width", 220)
pd.set_option("display.float_format", lambda x: f"{x:,.2f}")

# apply screen
keep = res[(res["adr1"] >= MIN_ADR) &
           (res["pct2_1y"] >= MIN_CONSISTENCY) &
           (res["turn_cr"] >= MIN_TURNOVER)].copy()
keep = keep.sort_values("adr1", ascending=False)

print(f"Universe screened: {len(res)} stocks with >=300 daily bars")
print(f"Screen: ADR%(1y)>={MIN_ADR}  AND  %days>=2% (1y)>={MIN_CONSISTENCY}  "
      f"AND  turnover>=Rs{MIN_TURNOVER}cr")
print(f"PASSED: {len(keep)} stocks\n")
print("=== TRADEABLE MOVERS (ranked by last-year avg daily range %) ===")
cols = ["sym", "industry", "adr1", "adr5", "pct2_1y", "pct3_1y", "turn_cr", "last"]
print(keep[cols].head(40).to_string(index=False))

# affordability note for small capital: qty of 1 lot vs 50k
print("\n=== affordability at Rs50k (with ~5x MIS => ~2.5L buying power) ===")
aff = keep.copy()
aff["shares_2.5L"] = (250000 / aff["last"]).astype(int)
print(aff[["sym", "last", "adr1", "shares_2.5L", "turn_cr"]].head(20).to_string(index=False))

keep.to_csv(ROOT / "tradeable_movers.csv", index=False)
print(f"\nSaved full passing list -> {ROOT/'tradeable_movers.csv'}")

# sanity: what the large-caps I first backtested actually score (why they lost)
print("\n=== why the first backtest lost: ADR of the large-caps I tested ===")
firsts = ["RELIANCE","HDFCBANK","ICICIBANK","INFY","TCS","SBIN","AXISBANK","ITC","LT","BHARTIARTL"]
print(res[res["sym"].isin(firsts)][["sym","adr1","pct2_1y","pct3_1y","turn_cr"]]
      .sort_values("adr1", ascending=False).to_string(index=False))

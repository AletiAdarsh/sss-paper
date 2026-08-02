"""Technical scorecard for the current Groww holdings (as of 20-07-2026).

Uses local daily OHLCV cache (data/ohlcv_fyers) + the statement's closing price.
Computes trend (vs 50/200 DMA), momentum (1/3/6/12M), 52w-high distance, RSI(14),
and a simple 0-10 technical score so the portfolio can be ranked for culling.

Run:  py portfolio_technicals.py
"""
import pandas as pd, numpy as np, warnings
from pathlib import Path
warnings.filterwarnings("ignore")

ROOT = Path(r"C:\Users\adars\sss\data")
OHLCV = ROOT / "ohlcv_fyers"
STMT = r"C:\Users\adars\Downloads\Stocks_Holdings_Statement_9171416127_20-07-2026.xlsx"

FIX = {"INE105J01010": "RPGLIFE", "INE270I01022": "VISHNU"}


def load_holdings():
    d = pd.read_excel(STMT, header=None)
    h = d.iloc[11:].copy()
    h.columns = ["name", "isin", "qty", "avg", "buyval", "cp", "cv", "pnl"]
    h = h.dropna(subset=["isin"]).reset_index(drop=True)
    c = pd.read_csv(ROOT / "nifty_total_market_constituents.csv")
    m = dict(zip(c["ISIN Code"], c["Symbol"]))
    h["sym"] = h["isin"].map(m)
    h["sym"] = h.apply(lambda r: FIX.get(r["isin"], r["sym"]), axis=1)
    for col in ["qty", "avg", "buyval", "cp", "cv", "pnl"]:
        h[col] = pd.to_numeric(h[col])
    h["pnl_pct"] = h["pnl"] / h["buyval"] * 100
    return h


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + up/dn)


def tech(sym, cp):
    f = OHLCV / f"{sym}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f, parse_dates=["date"]).sort_values("date")
    if len(df) < 220:
        return None
    c = df["close"]
    # splice the statement's fresher close on the end so DMAs/returns are current
    c = pd.concat([c, pd.Series([cp])], ignore_index=True)
    last = c.iloc[-1]
    out = {
        "dma50":  c.rolling(50).mean().iloc[-1],
        "dma200": c.rolling(200).mean().iloc[-1],
        "r1m":  last / c.iloc[-22] - 1 if len(c) > 22 else np.nan,
        "r3m":  last / c.iloc[-64] - 1 if len(c) > 64 else np.nan,
        "r6m":  last / c.iloc[-127] - 1 if len(c) > 127 else np.nan,
        "r12m": last / c.iloc[-250] - 1 if len(c) > 250 else np.nan,
        "hi52": c.iloc[-250:].max(),
        "lo52": c.iloc[-250:].min(),
        "rsi": rsi(c).iloc[-1],
    }
    out["v50"] = last / out["dma50"] - 1
    out["v200"] = last / out["dma200"] - 1
    out["from_hi"] = last / out["hi52"] - 1
    out["above_lo"] = last / out["lo52"] - 1
    return out


def score(t):
    """0-10 technical score: trend + momentum + position in range."""
    s = 0.0
    if t["v200"] > 0: s += 2.5                      # above 200DMA = primary uptrend
    if t["v50"] > 0:  s += 1.5
    if t["dma50"] > t["dma200"]: s += 1.0           # golden-cross structure
    for k, w in [("r3m", 1.5), ("r6m", 1.0), ("r12m", 1.0)]:
        if pd.notna(t[k]) and t[k] > 0: s += w
    if t["from_hi"] > -0.15: s += 1.0               # near highs
    elif t["from_hi"] < -0.40: s -= 1.0             # deep in drawdown
    if 45 <= t["rsi"] <= 70: s += 0.5
    return max(0, min(10, s))


h = load_holdings()
rows = []
for _, r in h.iterrows():
    t = tech(r["sym"], r["cp"]) if pd.notna(r["sym"]) else None
    d = {"stock": r["name"][:26], "sym": r["sym"], "invested": r["buyval"],
         "pnl_pct": r["pnl_pct"], "cp": r["cp"]}
    if t:
        d.update({"vs200": t["v200"]*100, "vs50": t["v50"]*100,
                  "r3m": t["r3m"]*100, "r6m": t["r6m"]*100, "r12m": t["r12m"]*100,
                  "from_hi": t["from_hi"]*100, "rsi": t["rsi"], "tscore": score(t)})
    else:
        d.update({k: np.nan for k in ["vs200","vs50","r3m","r6m","r12m","from_hi","rsi","tscore"]})
    rows.append(d)

res = pd.DataFrame(rows).sort_values("tscore", ascending=False)
pd.set_option("display.width", 250)
fmt = lambda x: f"{x:,.1f}"
pd.set_option("display.float_format", fmt)
print(f"TECHNICAL SCORECARD  |  portfolio as of 20-07-2026  |  invested Rs{h['buyval'].sum():,.0f}  "
      f"value Rs{h['cv'].sum():,.0f}  ({h['pnl'].sum()/h['buyval'].sum()*100:+.1f}%)\n")
print(res[["stock","sym","invested","pnl_pct","cp","vs200","vs50","r3m","r6m","r12m","from_hi","rsi","tscore"]]
      .to_string(index=False))
res.to_csv(ROOT / "portfolio_tech_scores.csv", index=False)
print("\nsaved -> data/portfolio_tech_scores.csv")
missing = res[res["tscore"].isna()]["sym"].tolist()
if missing: print("no local price history for:", missing)

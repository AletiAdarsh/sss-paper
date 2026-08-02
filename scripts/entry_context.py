"""Entry-context table: for every Supertrend signal, measure the DISPLACEMENT
(how much price moved) in the candles just BEFORE the entry, at 1m and 5m
granularity, and put it next to the trade's outcome.

Displacement is oriented to the TRADE direction: positive = price was moving the
way we're betting (momentum INTO the entry), negative = moving against us.

Output: an Excel with two sheets --
  'signals'  : one row per trade with all displacement features + outcome
  'summary'  : average of each feature for WINNERS vs LOSERS (does prior
               displacement predict a good trade?)

Run:  py entry_context.py
"""
import bisect
from datetime import timedelta
from pathlib import Path
import pandas as pd
import st_option_backtest as bt

OUT = Path(r"C:\Users\adars\Downloads\entry_context.xlsx")


def build():
    trades = bt.run("5", 1, quiet=True)
    b5 = bt.load_bars("5")           # (dt,o,h,l,c)
    b1 = bt.load_bars("1")
    dt5 = [b[0] for b in b5]; i5_by = {b[0]: k for k, b in enumerate(b5)}
    dt1 = [b[0] for b in b1]

    rows = []
    for t in trades:
        et = t["in"]; side = t["side"]; d = 1 if side == "CE" else -1
        i5 = i5_by.get(et)
        if i5 is None or i5 < 8:
            continue
        sig = b5[i5]                          # the 5m candle whose close triggered entry
        prev7 = b5[i5-7:i5]                   # the 7 five-min candles before it (35 min)

        # ---- 1-minute lead-in: last completed 1m bar is at et+4min (5m bar closes at et+5) ----
        jt = et + timedelta(minutes=4)
        j = bisect.bisect_right(dt1, jt) - 1
        one = {}
        if j >= 15:
            L = b1[j]
            one = {
                "1m_last_body":  round((L[4] - L[1]) * d, 1),
                "1m_net_3":      round((b1[j][4] - b1[j-2][1]) * d, 1),
                "1m_net_5":      round((b1[j][4] - b1[j-4][1]) * d, 1),
                "1m_net_15":     round((b1[j][4] - b1[j-14][1]) * d, 1),
                "1m_avg_range15": round(sum(x[2]-x[3] for x in b1[j-14:j+1]) / 15, 1),
            }

        rows.append({
            "day": t["day"], "time": et.strftime("%H:%M"), "side": side,
            "entry_idx": round(sig[4], 1), "strike": t["K"],
            # ---- 5-minute lead-in ----
            "5m_signal_body": round((sig[4]-sig[1]) * d, 1),        # the trigger candle itself
            "5m_net_7":       round((b5[i5-1][4]-b5[i5-7][1]) * d, 1),  # net move over prior 35 min
            "5m_avg_range7":  round(sum(x[2]-x[3] for x in prev7) / 7, 1),
            "5m_avg_body7":   round(sum(abs(x[4]-x[1]) for x in prev7) / 7, 1),
            **one,
            # ---- outcome ----
            "hold_min": round((t["out"] - t["in"]).total_seconds() / 60),
            "exit": t["reason"],
            "idx_move": round(t["idx_move"], 1),
            "opt_pts": round(t["exit_prem"] - t["entry_prem"], 1),
            "net_pnl": round(t["net"]),
            "win": t["net"] > 0,
        })

    df = pd.DataFrame(rows)
    feats = ["5m_signal_body", "5m_net_7", "5m_avg_range7", "5m_avg_body7",
             "1m_last_body", "1m_net_3", "1m_net_5", "1m_net_15", "1m_avg_range15"]

    # winners-vs-losers summary
    w = df[df["win"]]; ls = df[~df["win"]]
    summ = pd.DataFrame({
        "feature": feats,
        "winners_avg": [round(w[f].mean(), 1) for f in feats],
        "losers_avg":  [round(ls[f].mean(), 1) for f in feats],
    })
    summ["edge (W-L)"] = (summ["winners_avg"] - summ["losers_avg"]).round(1)

    try:
        with pd.ExcelWriter(OUT, engine="openpyxl") as xl:
            df.to_excel(xl, sheet_name="signals", index=False)
            summ.to_excel(xl, sheet_name="summary", index=False)
        print(f"Wrote {len(df)} signals -> {OUT}")
    except Exception as e:
        # fallback to CSVs if no excel engine
        df.to_csv(OUT.with_suffix(".signals.csv"), index=False)
        summ.to_csv(OUT.with_suffix(".summary.csv"), index=False)
        print(f"(xlsx engine missing: {e})  wrote CSVs instead next to {OUT.name}")

    # console preview of the key question
    print(f"\nSignals: {len(df)}  |  winners {df['win'].sum()}  losers {(~df['win']).sum()}")
    print("\nDoes prior DISPLACEMENT predict a winner?  (avg of each feature)")
    print(summ.to_string(index=False))
    return df, summ


if __name__ == "__main__":
    build()

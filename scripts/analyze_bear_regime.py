"""Drill into 2025-2026 vs the full sample.

Same pattern blocks (PEAD, buy-the-dip, pre-signatures, industry, by-quarter),
but the cuts are:
  - FULL: all events 2016-2026
  - BULL_BASELINE: 2020-2024 (strong bull-leaning years)
  - BEAR_2018: a previous bear year for comparison
  - CURRENT_BEAR: 2025-01-01 to today (2026-05-14)

For each cut, report: event-day distribution, PEAD gap by horizon,
buy-the-dip recovery, top/bottom pre-signatures, industry tilts.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"C:\Users\adars\sss\data")
RPT  = Path(r"C:\Users\adars\sss\reports")
RPT.mkdir(parents=True, exist_ok=True)
OUT  = RPT / "bear_regime_drilldown.txt"

POST_W = [1, 3, 5, 7, 14, 21, 30, 45, 60]
lines = []
def p(*a): s = " ".join(str(x) for x in a); lines.append(s); print(s)

def vp(p_, v_):
    if pd.isna(p_) or pd.isna(v_): return None, None
    vs = "V+" if v_ > 1.2 else ("V-" if v_ < 0.8 else "V0")
    ps = "P+" if p_ > 0.5 else ("P-" if p_ < -0.5 else "P0")
    return vs, ps

df = pd.read_csv(ROOT/"metrics"/"all_event_metrics.csv")
df["filing_date"] = pd.to_datetime(df["filing_date"])
df["vs"], df["ps"] = zip(*[vp(p_, v_) for p_, v_ in zip(df["pre_7d_price_chg_pct"],
                                                         df["pre_7d_volume_vs_prior20x"])])
df["ed_sign"] = np.sign(df["event_day_price_chg_pct"]).astype("Int64")

CUTS = {
    "FULL_10Y":      (pd.Timestamp("2016-01-01"), pd.Timestamp("2026-12-31")),
    "BULL_2020_24":  (pd.Timestamp("2020-01-01"), pd.Timestamp("2024-12-31")),
    "BEAR_2018":     (pd.Timestamp("2018-01-01"), pd.Timestamp("2018-12-31")),
    "CURRENT_BEAR":  (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-12-31")),
}

def block(name, sub):
    p("\n" + "="*100)
    p(f"REGIME: {name}    n={len(sub):,}    "
      f"range: {sub['filing_date'].min().date()} -> {sub['filing_date'].max().date()}")
    p("="*100)

    # event-day distribution
    ed = sub["event_day_price_chg_pct"].dropna()
    if len(ed) < 20: p("  not enough data"); return
    p(f"\n  Event-day: mean={ed.mean():+.3f}%  median={ed.median():+.3f}%  "
      f"std={ed.std():.2f}  hit_pos={(ed>0).mean():.1%}")

    # PEAD
    p(f"\n  PEAD (UP vs DOWN gap):")
    p(f"  {'horizon':>10}{'n_up':>8}{'mean_up':>11}{'hit_up':>10}{'n_dn':>8}{'mean_dn':>11}{'hit_dn':>10}{'gap':>10}")
    for w in POST_W:
        col = f"post_{w}d_price_chg_pct"
        u = sub.loc[sub["ed_sign"]==1, col].dropna()
        d_ = sub.loc[sub["ed_sign"]==-1, col].dropna()
        if len(u)<20 or len(d_)<20: continue
        p(f"  post-{w:>2}d {len(u):>7,}{u.mean():>+10.3f}%{(u>0).mean():>9.1%}{len(d_):>7,}"
          f"{d_.mean():>+10.3f}%{(d_>0).mean():>9.1%}{(u.mean()-d_.mean()):>+9.2f}%")

    # buy-the-dip
    dn = sub[sub["ed_sign"]==-1]
    p(f"\n  Buy-the-dip recovery (% of {len(dn)} event-day-DOWN that recover):")
    for w in [7, 21, 45, 60]:
        col = f"post_{w}d_price_chg_pct"
        s = dn[col].dropna()
        rec = (s > 0).sum()
        p(f"    post-{w:>2}d   recovered: {rec}/{len(s)}  ({rec/max(len(s),1):.1%})   mean={s.mean():+.2f}%")

    # top/bottom pre-signatures
    p("\n  Pre-7d sig x event-day -> post-45d (n>=50):")
    cells = (sub.dropna(subset=["vs","ps","ed_sign"])
               .groupby(["vs","ps","ed_sign"])
               .agg(n=("symbol","size"),
                    ed=("event_day_price_chg_pct","mean"),
                    p21=("post_21d_price_chg_pct","mean"),
                    p45=("post_45d_price_chg_pct","mean"),
                    p60=("post_60d_price_chg_pct","mean"),
                    p45_hit=("post_45d_price_chg_pct", lambda s:(s>0).mean()))
               .round(2))
    cells = cells[cells["n"]>=50].sort_values("p45", ascending=False)
    p("  TOP 5:");    p(cells.head(5).to_string())
    p("  BOTTOM 5:"); p(cells.tail(5).to_string())

    # industry
    p("\n  By industry (post-45d, n>=30):")
    ind = (sub.groupby("industry")
             .agg(n=("symbol","size"),
                  ed=("event_day_price_chg_pct","mean"),
                  p45=("post_45d_price_chg_pct","mean"),
                  p60=("post_60d_price_chg_pct","mean"),
                  p45_hit=("post_45d_price_chg_pct", lambda s:(s>0).mean()))
             .round(2))
    ind = ind[ind["n"]>=30].sort_values("p45", ascending=False)
    p(ind.to_string())

for name, (lo, hi) in CUTS.items():
    sub = df[(df["filing_date"]>=lo) & (df["filing_date"]<=hi)].copy()
    block(name, sub)

# ---- HEAD-TO-HEAD comparison: CURRENT_BEAR vs FULL ----
p("\n" + "="*100)
p("HEAD-TO-HEAD: CURRENT_BEAR (2025-2026 YTD) vs FULL_10Y baseline")
p("="*100)
cb = df[(df["filing_date"]>=CUTS["CURRENT_BEAR"][0]) & (df["filing_date"]<=CUTS["CURRENT_BEAR"][1])]
fu = df

p(f"\n  {'horizon':>10}{'FULL_mean':>15}{'BEAR_mean':>15}{'delta':>10}")
for w in POST_W:
    col = f"post_{w}d_price_chg_pct"
    f_mean = fu[col].mean()
    c_mean = cb[col].mean()
    p(f"  post-{w:>2}d   {f_mean:>+13.3f}%  {c_mean:>+13.3f}%  {(c_mean-f_mean):>+8.2f}%")

p(f"\n  PEAD GAP (UP-DOWN) comparison:")
p(f"  {'horizon':>10}{'FULL_gap':>14}{'BEAR_gap':>14}")
for w in POST_W:
    col = f"post_{w}d_price_chg_pct"
    fg = fu.loc[fu["ed_sign"]==1, col].mean() - fu.loc[fu["ed_sign"]==-1, col].mean()
    cg = cb.loc[cb["ed_sign"]==1, col].mean() - cb.loc[cb["ed_sign"]==-1, col].mean()
    p(f"  post-{w:>2}d   {fg:>+12.2f}%  {cg:>+12.2f}%")

# Quarter-level view of the bear period
p(f"\n  CURRENT_BEAR by year+quarter:")
cb_yq = cb.copy()
cb_yq["yq"] = cb_yq["filing_date"].dt.to_period("Q")
yq = (cb_yq.groupby("yq")
          .agg(n=("symbol","size"),
               ed=("event_day_price_chg_pct","mean"),
               p21=("post_21d_price_chg_pct","mean"),
               p45=("post_45d_price_chg_pct","mean"),
               p60=("post_60d_price_chg_pct","mean"))
          .round(2))
p(yq.to_string())

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"\nReport: {OUT}")

"""Dividend pattern analysis — same blocks as quarterly results."""
from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

ROOT = Path(r"C:\Users\adars\sss\data")
RPT  = Path(r"C:\Users\adars\sss\reports")
RPT.mkdir(parents=True, exist_ok=True)
OUT  = RPT / "dividend_patterns.txt"

POST_W = [1, 3, 5, 7, 14, 21, 30, 45, 60]
lines = []
def p(*a): s = " ".join(str(x) for x in a); lines.append(s); print(s)

def vp(p_, v_):
    if pd.isna(p_) or pd.isna(v_): return None, None
    vs = "V+" if v_ > 1.2 else ("V-" if v_ < 0.8 else "V0")
    ps = "P+" if p_ > 0.5 else ("P-" if p_ < -0.5 else "P0")
    return vs, ps

df = pd.read_csv(ROOT/"metrics"/"all_dividend_metrics.csv")
df["filing_date"] = pd.to_datetime(df["filing_date"])
df["year"] = df["filing_date"].dt.year
df["vs"], df["ps"] = zip(*[vp(p_, v_) for p_, v_ in zip(df["pre_7d_price_chg_pct"],
                                                         df["pre_7d_volume_vs_prior20x"])])
df["ed_sign"] = np.sign(df["event_day_price_chg_pct"]).astype("Int64")

p("="*100)
p(f"DIVIDEND DATASET: {len(df):,} events from {df['symbol'].nunique()} stocks")
p(f"date range: {df['filing_date'].min().date()} -> {df['filing_date'].max().date()}")
p(f"industries: {df['industry'].nunique()}")
p("="*100)

ed = df["event_day_price_chg_pct"].dropna()
p(f"\n--- Event-day distribution ---")
p(f"  n={len(ed):,}  mean={ed.mean():+.3f}%  median={ed.median():+.3f}%  "
  f"std={ed.std():.2f}  hit_pos={(ed>0).mean():.1%}")
p(f"  10/25/50/75/90 pctile: {ed.quantile([.1,.25,.5,.75,.9]).round(2).tolist()}")

# raw_category breakdown — what kind of dividend filings are we seeing?
p("\n--- Filing-type breakdown (top 15) ---")
rc = df["raw_category"].value_counts().head(15)
p(rc.to_string())

# PEAD
p("\n" + "="*100); p("PEAD — event-day direction predicts post drift"); p("="*100)
p(f"  {'horizon':>10}{'n_up':>8}{'mean_up':>11}{'hit_up':>10}{'n_dn':>8}{'mean_dn':>11}{'hit_dn':>10}{'gap':>10}")
for w in POST_W:
    col = f"post_{w}d_price_chg_pct"
    u = df.loc[df["ed_sign"]==1, col].dropna()
    d_ = df.loc[df["ed_sign"]==-1, col].dropna()
    if len(u)<30 or len(d_)<30: continue
    p(f"  post-{w:>2}d {len(u):>7,}{u.mean():>+10.3f}%{(u>0).mean():>9.1%}{len(d_):>7,}"
      f"{d_.mean():>+10.3f}%{(d_>0).mean():>9.1%}{(u.mean()-d_.mean()):>+9.2f}%")

# Buy-the-dip
p("\n" + "="*100); p("Buy-the-dip recovery (event-day DOWN)"); p("="*100)
dn = df[df["ed_sign"]==-1]
for w in POST_W:
    col = f"post_{w}d_price_chg_pct"
    s = dn[col].dropna()
    rec = (s>0).sum()
    p(f"  post-{w:>2}d   recovered: {rec:>5}/{len(s):<6}  ({rec/max(len(s),1):.1%})   mean={s.mean():+.2f}%")

# Pre-7d signature -> post-45d
p("\n" + "="*100); p("Pre-7d sig x event-day -> post-45d drift (n>=100)"); p("="*100)
cells = (df.dropna(subset=["vs","ps","ed_sign"])
           .groupby(["vs","ps","ed_sign"])
           .agg(n=("symbol","size"),
                ed=("event_day_price_chg_pct","mean"),
                p21=("post_21d_price_chg_pct","mean"),
                p45=("post_45d_price_chg_pct","mean"),
                p60=("post_60d_price_chg_pct","mean"),
                p45_hit=("post_45d_price_chg_pct", lambda s:(s>0).mean()))
           .round(2))
cells = cells[cells["n"]>=100].sort_values("p45", ascending=False)
p("TOP 8:");    p(cells.head(8).to_string())
p("BOTTOM 8:"); p(cells.tail(8).to_string())

# Industry
p("\n" + "="*100); p("By industry (n>=50)"); p("="*100)
ind = (df.groupby("industry")
         .agg(n=("symbol","size"),
              ed=("event_day_price_chg_pct","mean"),
              ed_hit=("event_day_price_chg_pct", lambda s:(s>0).mean()),
              p21=("post_21d_price_chg_pct","mean"),
              p45=("post_45d_price_chg_pct","mean"),
              p60=("post_60d_price_chg_pct","mean"),
              p45_hit=("post_45d_price_chg_pct", lambda s:(s>0).mean()))
         .round(2))
ind = ind[ind["n"]>=50].sort_values("p45", ascending=False)
p(ind.to_string())

# By year
p("\n" + "="*100); p("By year"); p("="*100)
y = (df.groupby("year")
       .agg(n=("symbol","size"),
            ed=("event_day_price_chg_pct","mean"),
            p21=("post_21d_price_chg_pct","mean"),
            p45=("post_45d_price_chg_pct","mean"),
            p60=("post_60d_price_chg_pct","mean"),
            p45_hit=("post_45d_price_chg_pct", lambda s:(s>0).mean()))
       .round(2))
p(y.to_string())

# CURRENT BEAR cut
p("\n" + "="*100); p("CURRENT BEAR (2025-01-01 to today)"); p("="*100)
cb = df[df["filing_date"]>=pd.Timestamp("2025-01-01")]
p(f"n={len(cb):,}")
ed = cb["event_day_price_chg_pct"].dropna()
p(f"event-day: mean={ed.mean():+.3f}%  hit_pos={(ed>0).mean():.1%}")
p(f"  {'horizon':>10}{'mean':>12}{'hit+':>10}")
for w in POST_W:
    s = cb[f"post_{w}d_price_chg_pct"].dropna()
    if len(s)<30: continue
    p(f"  post-{w:>2}d {s.mean():>+11.3f}%{(s>0).mean():>9.1%}")
p("\nPEAD gap (current bear):")
for w in POST_W:
    u = cb.loc[cb["ed_sign"]==1, f"post_{w}d_price_chg_pct"].mean()
    d_ = cb.loc[cb["ed_sign"]==-1, f"post_{w}d_price_chg_pct"].mean()
    p(f"  post-{w:>2}d  UP={u:+.2f}%  DN={d_:+.2f}%  gap={u-d_:+.2f}%")

# Quick comparison: dividend vs earnings — same horizons
em_path = ROOT/"metrics"/"all_event_metrics.csv"
if em_path.exists():
    em = pd.read_csv(em_path)
    p("\n" + "="*100); p("DIVIDEND vs EARNINGS_RESULTS — full sample mean returns"); p("="*100)
    p(f"  {'horizon':>10}{'DIV mean':>14}{'DIV hit+':>12}{'EARN mean':>14}{'EARN hit+':>12}")
    for w in POST_W:
        col = f"post_{w}d_price_chg_pct"
        ds, es = df[col].dropna(), em[col].dropna()
        if len(ds)<30 or len(es)<30: continue
        p(f"  post-{w:>2}d  {ds.mean():>+12.3f}%  {(ds>0).mean():>11.1%}  "
          f"{es.mean():>+12.3f}%  {(es>0).mean():>11.1%}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"\nReport -> {OUT}")

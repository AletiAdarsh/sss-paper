"""Pattern study on the full NIFTY Total Market quarterly-results dataset.

Reads:    data/metrics/all_event_metrics.csv
Outputs:  reports/quarterly_results_patterns.txt
          reports/quarterly_results_patterns_by_segment.csv

Segmentation:
  - All stocks
  - By industry
  - By cap segment (NIFTY 50 / Next50 / Midcap150 / Smallcap250 / rest)
       - inferred from constituent metadata if we have it,
         else by trading-volume rank as proxy
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

ROOT  = Path(r"C:\Users\adars\sss\data")
RPT   = Path(r"C:\Users\adars\sss\reports")
RPT.mkdir(parents=True, exist_ok=True)
OUT_TXT = RPT / "quarterly_results_patterns.txt"
OUT_CSV = RPT / "quarterly_results_patterns_by_segment.csv"

PRE_W  = [1, 3, 5, 7, 14, 21, 30, 45, 60]
POST_W = [1, 3, 5, 7, 14, 21, 30, 45, 60]

lines = []
def p(*a): s = " ".join(str(x) for x in a); lines.append(s); print(s)

def summary(s, label):
    s = pd.to_numeric(s, errors="coerce").dropna()
    if len(s) < 30: return None
    t,_ = stats.ttest_1samp(s, 0)
    return dict(label=label, n=len(s), mean=s.mean(), median=s.median(),
                t=t, hit=(s>0).mean())

def vp(p_, v_):
    if pd.isna(p_) or pd.isna(v_): return None, None
    vs = "V+" if v_ > 1.2 else ("V-" if v_ < 0.8 else "V0")
    ps = "P+" if p_ > 0.5 else ("P-" if p_ < -0.5 else "P0")
    return vs, ps

df = pd.read_csv(ROOT/"metrics"/"all_event_metrics.csv")
df["filing_date"] = pd.to_datetime(df["filing_date"])
df["year"] = df["filing_date"].dt.year
df["vs"], df["ps"] = zip(*[vp(p_, v_) for p_, v_ in zip(df["pre_7d_price_chg_pct"],
                                                         df["pre_7d_volume_vs_prior20x"])])
df["ed_sign"] = np.sign(df["event_day_price_chg_pct"]).astype("Int64")

p("="*100); p(f"DATASET: {len(df):,} earnings events from {df['symbol'].nunique()} stocks")
p(f"date range: {df['filing_date'].min().date()} -> {df['filing_date'].max().date()}")
p(f"industries: {df['industry'].nunique()}")
p("="*100)

# Event-day distribution
p("\n--- Event-day reaction distribution ---")
ed = df["event_day_price_chg_pct"].dropna()
p(f"  n={len(ed):,}  mean={ed.mean():+.3f}%  median={ed.median():+.3f}%  "
  f"std={ed.std():.2f}  hit_pos={(ed>0).mean():.1%}")
p(f"  10/25/50/75/90 pctile: {ed.quantile([.1,.25,.5,.75,.9]).round(2).tolist()}")

# Pattern 1 — PEAD
p("\n" + "="*100); p("PATTERN 1 — PEAD (event-day direction predicts post drift)"); p("="*100)
p(f"{'horizon':>10}{'n_up':>8}{'mean_up':>12}{'hit_up':>10}{'n_dn':>8}{'mean_dn':>12}{'hit_dn':>10}{'gap':>10}")
for w in POST_W:
    col = f"post_{w}d_price_chg_pct"
    u = df.loc[df["ed_sign"]==1, col].dropna()
    d_ = df.loc[df["ed_sign"]==-1, col].dropna()
    if len(u)<30 or len(d_)<30: continue
    p(f"  post-{w:>2}d {len(u):>7,}{u.mean():>+11.3f}%{(u>0).mean():>9.1%}{len(d_):>7,}"
      f"{d_.mean():>+11.3f}%{(d_>0).mean():>9.1%}{(u.mean()-d_.mean()):>+9.2f}%")

# Pattern 2 — Buy-the-dip recovery
p("\n" + "="*100); p("PATTERN 2 — Buy-the-dip: % of event-day-DOWN that recover"); p("="*100)
dn = df[df["ed_sign"]==-1]
for w in POST_W:
    col = f"post_{w}d_price_chg_pct"
    s = dn[col].dropna()
    rec = (s > 0).sum()
    p(f"  post-{w:>2}d   recovered_to_positive: {rec:>5}/{len(s):<6}  ({rec/max(len(s),1):.1%})   mean={s.mean():+.2f}%")

# Pattern 3 — Pre-7d signature predicting post-45d
p("\n" + "="*100); p("PATTERN 3 — Pre-7d signature x event-day direction -> post-45d drift (n>=200)"); p("="*100)
cells = (df.dropna(subset=["vs","ps","ed_sign"])
           .groupby(["vs","ps","ed_sign"])
           .agg(n=("symbol","size"),
                ed=("event_day_price_chg_pct","mean"),
                p21=("post_21d_price_chg_pct","mean"),
                p45=("post_45d_price_chg_pct","mean"),
                p60=("post_60d_price_chg_pct","mean"),
                p45_hit=("post_45d_price_chg_pct", lambda s:(s>0).mean()))
           .round(3))
cells = cells[cells["n"]>=200].sort_values("p45", ascending=False)
p("Top 8 signatures:"); p(cells.head(8).to_string())
p("Bottom 8 signatures:"); p(cells.tail(8).to_string())

# Pattern 4 — by industry
p("\n" + "="*100); p("PATTERN 4 — Event-day reaction & post-45d drift by industry"); p("="*100)
ind = (df.groupby("industry")
         .agg(n=("symbol","size"),
              ed=("event_day_price_chg_pct","mean"),
              ed_hit=("event_day_price_chg_pct", lambda s:(s>0).mean()),
              p45=("post_45d_price_chg_pct","mean"),
              p45_hit=("post_45d_price_chg_pct", lambda s:(s>0).mean()),
              p60=("post_60d_price_chg_pct","mean"))
         .round(3))
ind = ind[ind["n"]>=100].sort_values("p45", ascending=False)
p(ind.to_string())

# Pattern 5 — by year (regime check)
p("\n" + "="*100); p("PATTERN 5 — post-45d mean by year (regime check)"); p("="*100)
y = df.groupby("year")["post_45d_price_chg_pct"].agg(["count","mean","median"]).round(3)
p(y.to_string())

# Save outputs
OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
cells.reset_index().to_csv(OUT_CSV, index=False)
print(f"\nReport -> {OUT_TXT}")
print(f"Cells  -> {OUT_CSV}")

# Supertrend / Lux Hyperparameter Tuning — Findings

_Generated 2026-08-02. Data: cached 5-minute bars, 2025-08-04 → 2026-07-29
(~250 trading days, all four indices) + daily India VIX._

## What was tested and how

All tuning is scored in the **real money model**: index signal → buy ATM option,
priced Black-Scholes with India VIX, **after actual Dhan intraday round-trip
charges**, 1 lot, reverse/EOD exits (the model `live_paper.py` runs). Metric =
**net rupees**, not index points.

**Honesty guardrail — walk-forward:** the grid is re-tuned on all data seen so
far, then traded *blind* over the next ~1 month, rolling forward. Only those
out-of-sample (OOS) months are counted. A giant grid + "pick the best" always
curve-fits; walk-forward reports what you could actually have traded.

Data caveat: only ~1 year of 5m is available (Fyers almost certainly cannot serve
5 years of intraday; the token was dead at time of run). OOS window is ~5 months
(Mar–Jul 2026), a trend-friendly regime — so absolute OOS PFs run optimistic.
Anchor expectations to the lower end.

---

## PART 1 — Versomil (plain Supertrend, hl2 source): tuning DID NOT help

Grid = source(hl2/close) × ATR len(7/10/14/21) × mult(2.5–6) × 5 exit models =
280 configs/index, walk-forward.

### Walk-forward out-of-sample (5 months)

| Index | Tuned (re-pick monthly) | Incumbent hl2/15/5 reverse | Tuning edge |
|---|--:|--:|--:|
| NIFTY | +72,151 | +64,497 | **+7,654** |
| BANKNIFTY | +116,343 | +138,922 | **−22,579** |
| FINNIFTY | +98,890 | +92,503 | **+6,387** |
| SENSEX | +63,674 | +78,270 | **−14,595** |
| **TOTAL** | **+351,058** | **+374,192** | **−23,134** |

**The plain default beat the tuned system by ₹23k.** On BankNifty and Sensex,
monthly re-tuning actively *lost* money. Verdict: for Versomil the incumbent
`Supertrend(15, 5)` is already near-optimal; parameter tuning is a rounding error
you can only lose by chasing.

### The overfit mirage (why "pick the best combo" is a trap)

Best single config fit to the **whole year** (NOT tradable — used the future to
pick itself):

| Index | Best-fit-whole-year | Full-year net | vs. honest WF |
|---|---|--:|---|
| NIFTY | close/14/3.5/A4 | +235,070 | ~3.3× the ₹72k reality |
| BANKNIFTY | close/14/4.0/R | +326,331 | ~2.8× the ₹116k reality |
| FINNIFTY | hl2/10/3.5/A3 | +270,544 | ~2.7× the ₹99k reality |
| SENSEX | close/21/3.5/A4 | +232,671 | ~3.7× the ₹64k reality |

That 3–4× gap **is** the overfitting.

### What still held (robust, minor)

- Multiplier wants ~3.5–4 vs 5 (small, consistent — real but not a jackpot).
- `close` source ≈ `hl2` source (no reliable winner).
- **FINNIFTY hl2/10/3.5/3×ATR-stop** = the one genuine Versomil tuning win
  (picked in all 5 folds, beat default every month).
- BankNifty & Sensex: leave at default.

---

## PART 2 — Lux (close source + SMA-13 gate): tuning WON on all four

Grid = ATR len(7/10/11/14) × factor(3.0–7.0) × SMA-gate(on/off) × exit(reverse /
+4×ATR stop) = 128 configs/index, walk-forward. Exit = opposite Lux flip + EOD
(the Smart-Trail exit is not used live, so it was not tuned).

### Walk-forward out-of-sample (5 months)

| Index | Tuned (WF) | Incumbent close/11/5.5/gate | Edge | Most-picked config |
|---|--:|--:|--:|---|
| NIFTY | +68,562 | +58,320 | +10,242 | 14/3.5/gate/A4 (3/5) |
| BANKNIFTY | +149,211 | +116,874 | +32,337 | 14/3.5/gate/R (3/5) |
| FINNIFTY | +97,203 | +77,513 | +19,690 | 11/3.5/gate/R (**4/5**) |
| SENSEX | +72,524 | +52,780 | +19,744 | 10/3.5/gate/A4 (2/5) |
| **TOTAL** | **+387,500** | **+305,487** | **+82,013 (+27%)** | |

### The one robust finding

**`LUX_FACTOR = 5.5` is too loose — drop it to ~4.0.** Every index, every fold,
the chosen factor was **3.5–4.0**, never 5.5. At 5.5 the signal enters and exits
late, leaving ~27% on the table. This is the strongest converging signal in the
whole study.

Two more that hold up:
- **Keep the SMA-13 gate ON** — it survived in *every* winning config.
- ATR length 11–14 is fine (second-order); exit is a wash (BankNifty/FinNifty
  prefer reverse-only; Nifty/Sensex slightly prefer a 4×ATR stop).

Overfit mirage still present (full-year "best" ₹230k–325k vs honest ₹70k–150k),
so walk-forward discipline still matters — but here the *honest* tuned number
beats the incumbent cleanly, because the shipped default really is miscalibrated.

---

## BOTTOM LINE / RECOMMENDATION

1. **The edge is in the strategy design, not the knobs**: 5-minute, index → ATM
   option, reverse exits, trade rarely. Versomil proved that dialing parameters
   doesn't beat leaving them alone.
2. **The single actionable change**: in the live Lux system, set
   **`LUX_FACTOR` 5.5 → 4.0**, keep the **SMA-13 gate ON**, ATR length **11**.
   Supported across all four indices and validated out-of-sample (+27% vs the
   current 5.5). (3.5 squeezes slightly more but trades ~50% more = more cost.)
3. **Do NOT deploy per-index cherry-picked params** — the walk-forward shows the
   flashy full-year "best" configs are 3–4× mirages.
4. **Next real lever is deeper history, not more tuning**: a fresh Fyers login to
   fetch 2–3 years so these edges can be tested against a different regime.

---

## PART 3 — Can tuning rescue the 1-MINUTE timeframe? NO. (NIFTY only — sole 1m cache)

Same Lux → ATM option model, after charges. Length 11, gate on, reverse exit;
factor swept on 1m vs 5m.

### Why 1m loses no matter the parameters

1. **Accuracy collapses**: NIFTY win% ~50% on 5m vs **~32–34% on 1m** — 1-min bars
   are mostly noise; a 32% hit-rate can't carry premium decay.
2. **Charges explode** (~6× the trade count): at factor 4.0, 5m pays ₹17,650 in
   charges vs **1m ₹107,717**. The ~₹104/round-trip cost wall eats everything.
3. **The tuning knob runs backwards on 1m.** On 5m, tightening the factor to ~4
   *helps*; on 1m it *destroys*:

| factor | 5m net | 1m net |
|--:|--:|--:|
| 7.0 (loose) | +86,627 | +136,767 |
| 5.5 | +174,023 | +72,224 |
| 4.0 | +223,392 | **−34,652** |
| 3.0 (tight) | +212,023 | **−99,379** |

   The only 1m configs that stay positive are the loosest ones that barely trade —
   i.e. the best you can do to a 1m signal is make it imitate 5m.

### Honest walk-forward (re-pick factor monthly, trade blind)

- **5m: +₹78,261 over 123 trades** (~₹636/trade)
- **1m: +₹26,513 over 350 trades** (~₹76/trade)

5m makes **3× the money on 1/3 the trades**; ~8× better per trade. Best tuned 1m
PF ~1.23 (razor-thin) vs 5m ~1.8–1.9.

### Lesson

Tuning **sharpens** a signal that already has edge (5m Lux, default too loose) but
**cannot manufacture** edge where none exists (1m = noise + cost). Timeframe
question settled: **trade the 5-minute, forget 1-minute.** (Only NIFTY has 1m
cached; BankNifty/FinNifty/Sensex 1m would need a fresh fetch, but the structural
result is not index-specific.)

---

## PART 4 — Does tuning ALL Lux params beat just setting factor=4.0? NO.

Fairness test (built to try to DISPROVE the "just factor" recommendation): full
grid = atrlen(5) × factor(7) × gate-length(off/8/13/20) × exit(reverse / 4×ATR /
Smart-Trail) = **420 combos/index**, walk-forward. Compared OOS, per index:
A) incumbent 11/5.5/gate13/R, B) factor-only 11/**4.0**/gate13/R, C) full-tuned
(re-pick any combo monthly).

| Index | A incumbent | B factor=4.0 | C full-tuned | C − B |
|---|--:|--:|--:|--:|
| NIFTY | +58,320 | +77,426 | +59,325 | −18,101 |
| BANKNIFTY | +116,874 | +173,192 | +110,242 | −62,950 |
| FINNIFTY | +77,513 | +133,636 | +97,793 | −35,843 |
| SENSEX | +52,780 | +105,473 | +102,062 | −3,411 |
| **TOTAL** | **+305,486** | **+489,728** | **+369,422** | **−120,306** |

**Full tuning LOST on all four** — by ₹120k. More knobs = more overfitting; the
winning full-combo lurched (21/3.5/g20/A4, nogate/R, g8/ST…) fold to fold, which
is the noise showing. The simple one-knob change (factor=4.0, everything else at
Lux defaults) held flat and won — it even beats the earlier monthly re-tuning.

Caveat: 4.0 is not optimal-to-the-decimal; it's the robust center every slice
pointed at. Lesson: **one robust setting beats elaborate fitting.**

**FINAL:** Lux, 5m only, change exactly one thing — **factor 5.5 → 4.0** (keep
length 11, SMA-13 gate on, reverse exit). ≈ +₹184k / **+60%** over incumbent OOS
across the four indices, and better than tuning everything else.

---

## Scripts & artifacts

- `scripts/tune_versomil.py` — simple 70/30 train/test tune (Versomil Supertrend).
- `scripts/tune_wf.py` — wide walk-forward sweep (Versomil); grid dump →
  `data/versomil_wf.csv` (1,124 rows, every combo's full-year net/PF/win%).
- `scripts/tune_lux_wf.py` — wide walk-forward sweep (Lux entry).
- `scripts/tune_1m_compare.py` — NIFTY 1m-vs-5m factor sweep + 1m walk-forward.
- `scripts/tune_lux_full.py` — full 420-combo Lux tune; full-tuned vs factor-only.
- Engine change: `scripts/st_option_backtest.py` `run()`/`supertrend()` gained
  `st_source` / `st_atr_len` / `st_mult` params (safe; `live_paper.py` unaffected).

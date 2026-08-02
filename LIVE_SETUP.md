# Live paper system — Lux 5m index → ATM option (NIFTY / BankNifty / Sensex)

**Paper only.** There is no order/broker call anywhere in this code — it cannot
touch your Dhan or Fyers account. It logs what it *would* trade to
`data/live/ledger.csv`, which the workflow auto-commits after every run.

## How it works
- Every 5 min during market hours (09:15–15:30 IST), GitHub Actions runs
  `scripts/live_paper.py`, which **polls every 60s internally** (GitHub cron can't
  fire faster than 5 min, so we loop inside each run → effective ~1-min checks).
- For each index it reads the **last fully-closed 5m bar**, runs the **Lux**
  signal (Supertrend close/11/5.5 + SMA-13). On a fresh flip it "buys" the ATM
  option (BS+VIX priced); it exits on the opposite flip or by 15:20.
- It de-dupes on the 5m bar timestamp, so the 1-min polling never double-trades.

## One-time setup

### 1. Enable Fyers TOTP (for hands-free daily login)
Fyers → **My Account → Security / 2FA → enable an Authenticator app**. When it
shows the QR, click "can't scan / manual entry" to reveal the **base32 secret**
(a string like `JBSWY3DPEHPK3PXP`). Save it — that's `FYERS_TOTP_SECRET`.

### 2. Put this project on GitHub (public repo = unlimited free Actions minutes)
From `C:\Users\adars\sss`:
```bash
git init
git add .
git commit -m "live paper system"
gh repo create sss-paper --public --source . --push
# (or create the repo on github.com and: git remote add origin <url>; git push -u origin main)
```
> Your real `data/fyers_creds.json` and `token.json` are in `.gitignore`, so your
> secrets are **not** pushed. The public repo only contains code + the paper ledger.

### 3. Add 5 repo secrets
GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `FYERS_APP_ID`     | your client id, e.g. `Y084N3A0NM-200` |
| `FYERS_SECRET_ID`  | your app secret |
| `FYERS_FY_ID`      | your Fyers login id, e.g. `XA12345` |
| `FYERS_PIN`        | your 4-digit PIN |
| `FYERS_TOTP_SECRET`| the base32 secret from step 1 |

### 4. Turn it on / test
- Repo → **Actions** tab → enable workflows if prompted.
- Click **paper-run → Run workflow** to test now (works any time; outside market
  hours it just checks and logs nothing).
- After that it runs automatically Mon–Fri, 09:15–15:30 IST.

## Watching it
- **`data/live/ledger.csv`** — every OPEN/CLOSE with strike, premium, and paper P&L.
  Pull the repo (or view on github.com) any time.
- **`data/live/state.json`** — current open positions per index.

## Notes / knobs
- Size is 1 lot per index (`LOTS` in `live_paper.py`). Change if you want.
- Premium is **model-priced** (Black-Scholes + India VIX). To log the *real* ATM
  option LTP instead, that's a later upgrade (needs live strike resolution).
- Want a Telegram ping on each signal later? Easy add — it's just one more step
  in the run.

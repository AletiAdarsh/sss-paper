"""Fyers API v3 client (stdlib only): auth-code URL, token exchange, historical candles.

Flow:
  1) python fyers_client.py url          -> prints login URL; you log in, get redirected
  2) python fyers_client.py token "<auth_code>"  -> exchanges for access_token, saves to creds
  3) import and call fetch_history(sym, from, to)
"""
import os, sys, json, hashlib, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("SSS_ROOT", r"C:\Users\adars\sss"))
CREDS = ROOT / "data" / "fyers_creds.json"
AUTH_URL  = "https://api-t1.fyers.in/api/v3/generate-authcode"
TOKEN_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"
HIST_URL  = "https://api-t1.fyers.in/data/history"

def creds():
    return json.loads(CREDS.read_text())

def save_creds(c):
    CREDS.write_text(json.dumps(c, indent=2))

def auth_url():
    c = creds()
    q = urllib.parse.urlencode({
        "client_id": c["app_id"],
        "redirect_uri": c["redirect_uri"],
        "response_type": "code",
        "state": "sample",
    })
    return f"{AUTH_URL}?{q}"

def exchange_token(auth_code):
    c = creds()
    app_hash = hashlib.sha256(f'{c["app_id"]}:{c["secret_id"]}'.encode()).hexdigest()
    body = json.dumps({"grant_type": "authorization_code",
                       "appIdHash": app_hash, "code": auth_code}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if resp.get("s") != "ok" and "access_token" not in resp:
        raise RuntimeError(f"token exchange failed: {resp}")
    c["access_token"] = resp["access_token"]
    save_creds(c)
    return resp["access_token"]

def fetch_history(symbol, range_from, range_to, resolution="D"):
    """symbol e.g. 'NSE:TITAN-EQ'; dates 'YYYY-MM-DD'. Returns list[[ts,o,h,l,c,v]]."""
    c = creds()
    q = urllib.parse.urlencode({
        "symbol": symbol, "resolution": resolution, "date_format": "1",
        "range_from": range_from, "range_to": range_to, "cont_flag": "1",
    })
    req = urllib.request.Request(f"{HIST_URL}?{q}",
                                 headers={"Authorization": f'{c["app_id"]}:{c["access_token"]}',
                                          "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if resp.get("s") == "no_data":          # stock not listed yet in this window / holiday span
        return []
    if resp.get("s") != "ok":
        raise RuntimeError(f"{symbol}: {resp}")
    return resp.get("candles", [])

def fetch_history_range(symbol, start_iso, end_iso, resolution="D", sleep=0.2):
    """Chunk into <=360-day windows (Fyers daily cap ~366d) and concatenate candles."""
    from datetime import date, timedelta
    s = date.fromisoformat(start_iso); e = date.fromisoformat(end_iso)
    out = []
    cur = s
    while cur <= e:
        nxt = min(e, cur + timedelta(days=360))
        for attempt in range(3):
            try:
                out += fetch_history(symbol, cur.isoformat(), nxt.isoformat(), resolution)
                break
            except Exception as ex:
                if attempt == 2: raise
                time.sleep(1 + attempt)
        time.sleep(sleep)
        cur = nxt + timedelta(days=1)
    # dedupe by timestamp, sorted
    seen = {}
    for c in out:
        seen[c[0]] = c
    return [seen[k] for k in sorted(seen)]

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "url"
    if cmd == "url":
        print(auth_url())
    elif cmd == "token":
        tok = exchange_token(sys.argv[2])
        print("access_token saved (len=%d)" % len(tok))
    elif cmd == "test":
        rows = fetch_history("NSE:TITAN-EQ", "2026-06-01", "2026-07-09")
        print(f"TITAN candles: {len(rows)}")
        for r in rows[-3:]: print(r)

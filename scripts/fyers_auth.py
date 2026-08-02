"""Unattended Fyers v3 token via TOTP (no browser, no Cloudflare page).

Flow: send_login_otp -> verify_otp(TOTP) -> verify_pin -> token(auth_code)
      -> exchange_token (reuses fyers_client). Token cached to data/live/token.json
      for the day so we don't re-login every 5 minutes.

Secrets come from env (GitHub Secrets) or fall back to the creds file:
    FYERS_FY_ID       your Fyers id, e.g. XA12345
    FYERS_PIN         4-digit login PIN
    FYERS_TOTP_SECRET base32 secret from Fyers 2FA setup
    FYERS_APP_ID      client id e.g. Y084N3A0NM-200   (also in creds)
    FYERS_SECRET_ID   app secret                       (also in creds)
"""
import os, json, time, base64, hmac, struct, urllib.request, urllib.parse, urllib.error
from datetime import date
from pathlib import Path
import fyers_client as fy

ROOT = Path(os.environ.get("SSS_ROOT", r"C:\Users\adars\sss"))
TOKFILE = ROOT / "data" / "live" / "token.json"
# Headless-login endpoints (unofficial but standard): the OTP/PIN steps live on the
# api-t2 "vagator/v2" host; the authcode step on api.fyers.in/api/v2/token.
VAGATOR = "https://api-t2.fyers.in/vagator/v2"
TOKEN_URL = "https://api.fyers.in/api/v2/token"


def _b64(s):
    return base64.b64encode(str(s).encode()).decode()


def totp(secret, digits=6, period=30):
    key = base64.b32decode(secret.strip().upper() + "=" * ((8 - len(secret.strip()) % 8) % 8))
    msg = struct.pack(">Q", int(time.time() // period))
    h = hmac.new(key, msg, "sha1").digest()
    off = h[-1] & 0x0F
    return str((struct.unpack(">I", h[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)).zfill(digits)


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0", **(headers or {})})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        raise RuntimeError(f"HTTP {e.code} at {url.rsplit('/', 1)[-1]} -> {detail}") from None


def _secret(name, creds_key=None):
    v = os.environ.get(name)
    if v:
        return v
    try:
        return fy.creds().get(creds_key or name.lower().replace("fyers_", ""))
    except Exception:
        return None


def totp_login():
    c = fy.creds()
    fy_id = _secret("FYERS_FY_ID", "fy_id")
    pin = _secret("FYERS_PIN", "pin")
    secret = _secret("FYERS_TOTP_SECRET", "totp_secret")
    if not (fy_id and pin and secret):
        raise RuntimeError("missing FYERS_FY_ID / FYERS_PIN / FYERS_TOTP_SECRET")
    client_id = c["app_id"]; app_short, app_type = client_id.split("-")

    r = _post(f"{VAGATOR}/send_login_otp_v2", {"fy_id": _b64(fy_id), "app_id": "2"})
    rk = r["request_key"]
    # TOTP can roll over mid-call; retry once on the next window
    for attempt in range(2):
        try:
            r = _post(f"{VAGATOR}/verify_otp", {"request_key": rk, "otp": totp(secret)})
            rk = r["request_key"]; break
        except Exception:
            if attempt: raise
            time.sleep(2)
    r = _post(f"{VAGATOR}/verify_pin_v2", {"request_key": rk, "identity_type": "pin", "identifier": _b64(pin)})
    login_tok = r["data"]["access_token"]
    print(f"[auth] client_id={client_id!r} app_short={app_short!r} appType={app_type!r} redirect={c['redirect_uri']!r}")
    payload = {"fyers_id": fy_id, "app_id": app_short, "redirect_uri": c["redirect_uri"],
               "appType": app_type, "code_challenge": "", "state": "sample", "scope": "",
               "nonce": "", "response_type": "code", "create_cookie": True}
    r = _post(TOKEN_URL, payload, headers={"Authorization": f"Bearer {login_tok}"})
    auth_code = urllib.parse.parse_qs(urllib.parse.urlparse(r["Url"]).query)["auth_code"][0]
    return fy.exchange_token(auth_code)          # saves access_token into creds


def _token_works():
    try:
        from datetime import date, timedelta
        e = date.today()
        return bool(fy.fetch_history("NSE:NIFTY50-INDEX", (e - __import__("datetime").timedelta(days=3)).isoformat(),
                                     e.isoformat(), "D"))
    except Exception:
        return False


def ensure_token():
    """Return a working access_token, reusing today's cached one or logging in via TOTP."""
    TOKFILE.parent.mkdir(parents=True, exist_ok=True)
    if TOKFILE.exists():
        try:
            d = json.loads(TOKFILE.read_text())
            if d.get("date") == date.today().isoformat():
                c = fy.creds(); c["access_token"] = d["access_token"]; fy.save_creds(c)
                if _token_works():
                    return d["access_token"]
        except Exception:
            pass
    # fall back to an already-valid token sitting in the creds file (e.g. manual login)
    try:
        if fy.creds().get("access_token") and _token_works():
            return fy.creds()["access_token"]
    except Exception:
        pass
    tok = totp_login()
    TOKFILE.write_text(json.dumps({"access_token": tok, "date": date.today().isoformat()}))
    return tok


if __name__ == "__main__":
    t = ensure_token()
    print(f"token OK (len={len(t)})")

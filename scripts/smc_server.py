"""Local SMC chart server — Fyers candles + EzSMC structure, with LIVE ticks.

Dhan's charts won't take the Pine indicator, so this renders the same BOS/MSS
structure locally, streaming real ticks off the Fyers v3 websocket.

Run:   py smc_server.py
Then:  http://localhost:8765

  /                -> chart page
  /api/data?...    -> historical candles + swings/events (also subscribes live)
  /api/stream?...  -> Server-Sent Events: {ltp, ts} pushed on every tick
  /api/status      -> websocket health
"""
import json, time, urllib.parse, urllib.error, traceback
from datetime import date, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fyers_client as fy
import smc_engine
from smc_live import FEED

HERE = Path(__file__).parent
PORT = 8765
IST_OFFSET = 5 * 3600 + 30 * 60      # chart lib renders UTC; shift so it reads IST

DEFAULT_DAYS = {"1": 5, "3": 10, "5": 20, "15": 45, "30": 90, "60": 150, "D": 500}
RES_SEC = {"1": 60, "3": 180, "5": 300, "15": 900, "30": 1800, "60": 3600, "D": 86400}


def norm_symbol(s):
    s = (s or "").strip().upper()
    if not s:
        return "NSE:NIFTY50-INDEX"
    if ":" in s:
        return s
    alias = {"NIFTY": "NIFTY50-INDEX", "NIFTY50": "NIFTY50-INDEX",
             "BANKNIFTY": "NIFTYBANK-INDEX", "FINNIFTY": "FINNIFTY-INDEX",
             "SENSEX": "SENSEX-INDEX"}
    s = alias.get(s, s)
    return f"NSE:{s}" if s.endswith("-INDEX") else f"NSE:{s}-EQ"


def fetch(symbol, res, days):
    end = date.today()
    start = end - timedelta(days=days)
    rows, chunk, cur = [], (90 if res != "D" else 360), end - timedelta(days=days)
    while cur <= end:
        nxt = min(end, cur + timedelta(days=chunk))
        rows += fy.fetch_history(symbol, cur.isoformat(), nxt.isoformat(), res)
        cur = nxt + timedelta(days=1)
    seen = {r[0]: r for r in rows}
    return [seen[k] for k in sorted(seen)]


def build(symbol, res, days, swing):
    raw = fetch(symbol, res, days)
    if not raw:
        return {"error": "no data for that symbol/range"}
    o, h, l, c = ([r[i] for r in raw] for i in (1, 2, 3, 4))
    st = smc_engine.analyse(o, h, l, c, length=swing)
    candles = [{"time": r[0] + IST_OFFSET, "open": r[1], "high": r[2],
                "low": r[3], "close": r[4]} for r in raw]
    t = [x["time"] for x in candles]

    def stamp(items):
        out = []
        for e in items:
            i = e.get("i")
            if i is None or not (0 <= i < len(t)):
                continue
            d = dict(e)
            d["time"] = t[i]
            out.append(d)
        return out

    return {"symbol": symbol, "resolution": res, "bars": len(candles),
            "res_sec": RES_SEC.get(res, 300), "ist_offset": IST_OFFSET,
            "candles": candles, "swings": stamp(st["swings"]),
            "events": stamp(st["events"]), "levels": st["levels"],
            "trend": st["trend"], "last": c[-1]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            f = HERE / "smc_web.html"
            return self._send(200, f.read_bytes(), "text/html; charset=utf-8") \
                if f.exists() else self._send(500, "smc_web.html missing", "text/plain")

        if u.path == "/api/status":
            return self._send(200, json.dumps(FEED.status()))

        if u.path == "/api/data":
            sym = norm_symbol(q.get("symbol", [""])[0])
            res = q.get("res", ["5"])[0]
            swing = int(q.get("swing", ["3"])[0])
            days = int(q.get("days", [DEFAULT_DAYS.get(res, 20)])[0])
            try:
                out = build(sym, res, days, swing)
                if "error" not in out:
                    FEED.subscribe(sym)             # start streaming this symbol
                    out["feed"] = FEED.status()
                return self._send(200, json.dumps(out))
            except urllib.error.HTTPError as e:
                return self._send(200, json.dumps(
                    {"error": "TOKEN_EXPIRED" if e.code == 401 else f"HTTP {e.code}"}))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, json.dumps({"error": str(e)}))

        if u.path == "/api/stream":
            sym = norm_symbol(q.get("symbol", [""])[0])
            FEED.subscribe(sym)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_ts = 0
            try:
                while True:
                    tick = FEED.get(sym)
                    if tick and tick["ts"] != last_ts:
                        last_ts = tick["ts"]
                        payload = {"ltp": tick["ltp"], "ts": tick["ts"],
                                   "state": FEED.state}
                        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                        self.wfile.flush()
                    else:
                        # heartbeat so the browser knows we're alive
                        self.wfile.write(f": {FEED.state}\n\n".encode())
                        self.wfile.flush()
                    time.sleep(0.4)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return
            except Exception:
                return

        self._send(404, "not found", "text/plain")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"SMC live chart  ->  http://localhost:{PORT}")
    print("Ctrl+C to stop. If you see TOKEN_EXPIRED, refresh the daily Fyers token:")
    print('  py fyers_client.py url  ->  login  ->  py fyers_client.py token "<auth_code>"')
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

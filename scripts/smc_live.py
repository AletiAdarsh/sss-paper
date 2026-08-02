"""Fyers v3 websocket feed -> in-memory LTP store.

Real ticks (not polling). The HTTP server pushes these to the browser over SSE,
which builds the forming candle live and re-runs the SMC engine on each close.

Token note: the websocket auths with the SAME daily access_token as the REST API,
so if that's expired the socket won't connect and `state` reports it.
"""
import threading, time, json
from pathlib import Path

CREDS = Path(r"C:\Users\adars\sss\data\fyers_creds.json")


class LiveFeed:
    def __init__(self):
        self.ltp = {}            # symbol -> {"ltp": float, "ts": epoch_sec}
        self.subs = set()
        self.sock = None
        self.state = "idle"      # idle | connecting | connected | error | expired
        self.err = None
        self._lock = threading.Lock()
        self._started = False

    # ---- websocket callbacks -------------------------------------------------
    def _on_message(self, msg):
        try:
            items = msg if isinstance(msg, list) else [msg]
            now = time.time()
            with self._lock:
                for m in items:
                    if not isinstance(m, dict):
                        continue
                    sym = m.get("symbol") or m.get("s")
                    px = m.get("ltp") or m.get("lp") or m.get("last_price")
                    if sym and px:
                        self.ltp[sym] = {"ltp": float(px), "ts": now}
        except Exception as e:
            self.err = f"msg parse: {e}"

    def _on_connect(self):
        self.state = "connected"
        if self.subs:
            self._do_subscribe(list(self.subs))

    def _on_close(self, m=None):
        if self.state != "expired":
            self.state = "idle"

    def _on_error(self, m=None):
        s = str(m)
        self.err = s[:200]
        self.state = "expired" if ("401" in s or "auth" in s.lower()) else "error"

    # ---- control -------------------------------------------------------------
    def start(self):
        if self._started:
            return
        self._started = True
        self.state = "connecting"
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            from fyers_apiv3.FyersWebsocket import data_ws
            c = json.loads(CREDS.read_text())
            self.sock = data_ws.FyersDataSocket(
                access_token=f'{c["app_id"]}:{c["access_token"]}',
                log_path="", litemode=True, write_to_file=False, reconnect=True,
                on_connect=self._on_connect, on_close=self._on_close,
                on_error=self._on_error, on_message=self._on_message,
            )
            self.sock.connect()
        except Exception as e:
            self.err = str(e)[:200]
            self.state = "error"
            self._started = False

    def _do_subscribe(self, syms):
        try:
            self.sock.subscribe(symbols=syms, data_type="SymbolUpdate")
        except Exception as e:
            self.err = f"subscribe: {e}"

    def subscribe(self, symbol):
        """Idempotent — safe to call on every /api/data request."""
        self.start()
        if symbol in self.subs:
            return
        self.subs.add(symbol)
        if self.state == "connected" and self.sock:
            self._do_subscribe([symbol])

    def get(self, symbol):
        with self._lock:
            return self.ltp.get(symbol)

    def status(self):
        return {"state": self.state, "error": self.err,
                "subscribed": sorted(self.subs), "symbols_live": len(self.ltp)}


FEED = LiveFeed()

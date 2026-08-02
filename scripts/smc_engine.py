"""EzSMC market-structure engine — full port of the user's Pine indicator.

Ports `calculate_swing_points(length)` plus the BOS/MSS state machine, in BOTH
directions (the earlier gap_mss_backtest.py port only did the bearish side).

  swing high/low : confirmed `length` bars late, same as the indicator
  BOS  (Break of Structure)   = break that CONTINUES the current trend
  MSS  (Market Structure Shift) = first break AGAINST the current trend

Used by smc_server.py to render a local chart. Import and call `analyse()`.
"""


def calc_swings(h, l, length):
    """Faithful port of calculate_swing_points -> (swing_high[], swing_low[]).
    A non-zero value marks the bar where the swing is CONFIRMED (length bars late)."""
    n = len(h)
    sh = [0.0] * n
    sl = [0.0] * n
    prev = 0
    for i in range(n):
        if i - length < 0:
            continue
        win_hi = max(h[i - length + 1:i + 1])   # ta.highest(length)
        win_lo = min(l[i - length + 1:i + 1])   # ta.lowest(length)
        h_len = h[i - length]                    # high[length]
        l_len = l[i - length]                    # low[length]
        before = prev
        if h_len > win_hi:
            prev = 0
        elif l_len < win_lo:
            prev = 1
        if prev == 0 and before != 0:
            sh[i] = h_len
        if prev == 1 and before != 1:
            sl[i] = l_len
    return sh, sl


def analyse(o, h, l, c, length=3):
    """Run the structure state machine.

    Returns dict with:
      swings : [{i, kind:'high'|'low', price}]
      events : [{i, kind:'BOS'|'MSS', dir:'bull'|'bear', level, price}]
      levels : {'up': last swing high, 'dn': last swing low}  (live, for alerts)
      trend  : +1 bullish structure, -1 bearish, 0 undecided
    """
    n = len(c)
    sh, sl = calc_swings(h, l, length)

    dn_broke = up_broke = True
    iy_up = iy_dn = 0.0          # last confirmed swing high / low levels
    up_i = dn_i = None           # bar index where that swing was confirmed
    t_ms = 0                     # +1 after a bullish break, -1 after bearish

    swings, events = [], []
    for i in range(n):
        if sh[i] != 0:
            up_broke = True
            iy_up = sh[i]
            up_i = i - length
            swings.append({"i": up_i, "kind": "high", "price": sh[i]})
        if sl[i] != 0:
            dn_broke = True
            iy_dn = sl[i]
            dn_i = i - length
            swings.append({"i": dn_i, "kind": "low", "price": sl[i]})

        # --- bearish break: close crosses UNDER the last swing low ---
        if i > 0 and iy_dn > 0 and c[i] < iy_dn and c[i - 1] >= iy_dn and dn_broke:
            is_mss = t_ms > 0            # prior structure was up -> shift
            dn_broke = False
            t_ms = -1
            events.append({"i": i, "kind": "MSS" if is_mss else "BOS",
                           "dir": "bear", "level": iy_dn, "price": c[i],
                           "from_i": dn_i})

        # --- bullish break: close crosses OVER the last swing high ---
        if i > 0 and iy_up > 0 and c[i] > iy_up and c[i - 1] <= iy_up and up_broke:
            is_mss = t_ms < 0            # prior structure was down -> shift
            up_broke = False
            t_ms = 1
            events.append({"i": i, "kind": "MSS" if is_mss else "BOS",
                           "dir": "bull", "level": iy_up, "price": c[i],
                           "from_i": up_i})

    return {"swings": swings, "events": events, "trend": t_ms,
            "levels": {"up": iy_up or None, "dn": iy_dn or None,
                       "up_live": bool(up_broke), "dn_live": bool(dn_broke)}}

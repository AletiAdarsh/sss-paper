#!/usr/bin/env python3
"""Fetch daily OHLCV from Yahoo Finance chart API into CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dt_time, timezone


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
CSV_FIELDS = ["date", "open", "high", "low", "close", "adj_close", "volume"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Yahoo Finance daily OHLCV.")
    parser.add_argument("--ticker", default="RELIANCE.NS", help="Yahoo ticker.")
    parser.add_argument(
        "--from-date",
        default="2016-01-01",
        help="Start date in YYYY-MM-DD format. Use a buffer before event dates.",
    )
    parser.add_argument(
        "--to-date",
        default=date.today().isoformat(),
        help="End date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--out",
        default="data/reliance_ohlcv_yahoo.csv",
        help="Output CSV path.",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds.")
    return parser.parse_args()


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date {value!r}; use YYYY-MM-DD") from exc


def epoch_seconds(day: date, end_of_day: bool = False) -> int:
    clock = dt_time(23, 59, 59) if end_of_day else dt_time(0, 0, 0)
    return int(datetime.combine(day, clock, tzinfo=timezone.utc).timestamp())


def fetch_chart(ticker: str, start: date, end: date, timeout: int) -> dict:
    params = {
        "period1": str(epoch_seconds(start)),
        "period2": str(epoch_seconds(end, end_of_day=True)),
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    url = f"{YAHOO_CHART_URL.format(ticker=urllib.parse.quote(ticker))}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_rows(payload: dict) -> list[dict[str, str]]:
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(chart["error"])
    result = (chart.get("result") or [None])[0]
    if not result:
        return []

    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    adjclose = ((result.get("indicators") or {}).get("adjclose") or [{}])[0]

    rows: list[dict[str, str]] = []
    for index, timestamp in enumerate(timestamps):
        row_date = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        close = value_at(quote.get("close"), index)
        adj_close = value_at(adjclose.get("adjclose"), index)
        if close == "" and adj_close == "":
            continue
        rows.append(
            {
                "date": row_date,
                "open": value_at(quote.get("open"), index),
                "high": value_at(quote.get("high"), index),
                "low": value_at(quote.get("low"), index),
                "close": close,
                "adj_close": adj_close,
                "volume": value_at(quote.get("volume"), index, decimals=0),
            }
        )
    return rows


def value_at(values, index: int, decimals: int = 6) -> str:
    if not values or index >= len(values) or values[index] is None:
        return ""
    value = values[index]
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{decimals}f}"


def write_csv(rows: list[dict[str, str]], out_path: str) -> None:
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    start = parse_iso_date(args.from_date)
    end = parse_iso_date(args.to_date)
    if start > end:
        print("--from-date cannot be after --to-date", file=sys.stderr)
        return 2

    payload = fetch_chart(args.ticker, start, end, args.timeout)
    rows = extract_rows(payload)
    rows.sort(key=lambda row: row["date"])
    write_csv(rows, args.out)
    if rows:
        print(f"Wrote {len(rows)} rows to {args.out} ({rows[0]['date']} to {rows[-1]['date']})")
    else:
        print(f"Wrote 0 rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

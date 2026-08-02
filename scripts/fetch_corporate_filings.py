#!/usr/bin/env python3
"""Fetch official NSE/BSE corporate filings into a normalized CSV.

The script intentionally uses only Python's standard library so it can run in a
fresh workspace without installing dependencies.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http.cookiejar import CookieJar
from typing import Iterable


NSE_BOOTSTRAP_URL = (
    "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
)
NSE_API_URL = "https://www.nseindia.com/api/corporate-announcements"
BSE_API_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
BSE_ATTACHMENT_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachHis"


CSV_FIELDS = [
    "source",
    "symbol",
    "bse_scrip",
    "isin",
    "company_name",
    "event_datetime",
    "event_date",
    "event_type",
    "raw_category",
    "headline",
    "description",
    "source_event_id",
    "critical_flag",
    "attachment_url",
    "file_size",
    "dedupe_key",
]


EVENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "earnings_results",
        (
            "financial result",
            "financial results",
            "quarterly result",
            "quarterly results",
            "audited result",
            "unaudited result",
            "limited review",
            "standalone and consolidated",
            "integrated filing (financial)",
        ),
    ),
    (
        "board_meeting",
        (
            "board meeting",
            "meeting of the board",
            "outcome of board",
            "board of directors",
        ),
    ),
    ("dividend", ("dividend", "interim dividend", "final dividend")),
    ("buyback", ("buyback", "buy-back", "buy back")),
    ("bonus", ("bonus issue", "bonus share", "bonus shares")),
    ("stock_split", ("sub-division", "sub division", "split of shares", "stock split")),
    ("rights_issue", ("rights issue", "right issue", "rights entitlement")),
    (
        "merger_acquisition",
        (
            "acquisition",
            "amalgamation",
            "merger",
            "scheme of arrangement",
            "slump sale",
            "divestment",
            "stake sale",
            "joint venture",
        ),
    ),
    (
        "management_change",
        (
            "change in management",
            "appointment",
            "resignation",
            "cessation",
            "chief executive",
            "ceo",
            "chief financial",
            "cfo",
            "director",
            "key managerial personnel",
            "kmp",
        ),
    ),
    (
        "credit_rating",
        ("credit rating", "rating action", "rating reaffirmed", "rating revised"),
    ),
    (
        "shareholding",
        ("shareholding pattern", "shareholding", "share holder pattern"),
    ),
    (
        "pledge",
        ("pledge", "encumbrance", "release of encumbrance", "promoter pledge"),
    ),
    (
        "insider_trading",
        (
            "insider trading",
            "trading window",
            "pit regulations",
            "prohibition of insider",
        ),
    ),
    (
        "litigation_regulatory",
        (
            "litigation",
            "show cause",
            "sebi",
            "penalty",
            "fine",
            "tax demand",
            "order passed",
            "regulatory",
        ),
    ),
    (
        "investor_meet_call",
        (
            "investor presentation",
            "analyst meet",
            "investor meet",
            "earnings call",
            "conference call",
            "audio recording",
            "transcript",
            "schedule of analysts",
        ),
    ),
    ("press_release", ("press release", "media release")),
    (
        "business_update_order",
        (
            "order received",
            "work order",
            "contract",
            "agreement",
            "business update",
            "capacity addition",
        ),
    ),
]


@dataclass(frozen=True)
class Chunk:
    start: date
    end: date


class HttpJsonClient:
    def __init__(self, timeout: int, sleep_seconds: float) -> None:
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds
        self.cookie_jar = CookieJar()
        self.bootstrapped_urls: set[str] = set()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

    def get_json(
        self,
        url: str,
        params: dict[str, str],
        headers: dict[str, str],
        retries: int = 3,
        bootstrap_url: str | None = None,
    ):
        encoded_url = f"{url}?{urllib.parse.urlencode(params)}"
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            needs_bootstrap = (
                bootstrap_url
                and bootstrap_url not in self.bootstrapped_urls
                and attempt == 1
            )
            retry_after_http_error = (
                bootstrap_url and isinstance(last_error, urllib.error.HTTPError)
            )
            if needs_bootstrap or retry_after_http_error:
                self.get_text(bootstrap_url, headers=headers, retries=1)
                self.bootstrapped_urls.add(bootstrap_url)

            request = urllib.request.Request(encoded_url, headers=headers)
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    payload = response.read().decode("utf-8", errors="replace")
                if self.sleep_seconds:
                    time.sleep(self.sleep_seconds)
                return json.loads(payload)
            except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt == retries:
                    raise
                time.sleep(min(2**attempt, 10))

        raise RuntimeError(f"Failed to fetch {encoded_url}: {last_error}")

    def get_text(
        self,
        url: str,
        headers: dict[str, str],
        retries: int = 3,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            request = urllib.request.Request(url, headers=headers)
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                last_error = exc
                if attempt == retries:
                    raise
                time.sleep(min(2**attempt, 10))

        raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch NSE/BSE corporate filings into a normalized CSV."
    )
    parser.add_argument("--symbol", default="RELIANCE", help="NSE symbol.")
    parser.add_argument("--bse-scrip", default="500325", help="BSE scrip code.")
    parser.add_argument(
        "--from-date",
        default="2016-05-14",
        help="Start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--to-date",
        default=date.today().isoformat(),
        help="End date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--out",
        default="data/reliance_corporate_filings.csv",
        help="Output CSV path.",
    )
    parser.add_argument(
        "--sources",
        default="nse,bse",
        help="Comma-separated sources: nse,bse.",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=90,
        help="Date range size per request. Smaller chunks reduce exchange timeouts.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="Delay between requests in seconds.",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds.")
    return parser.parse_args()


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date {value!r}; use YYYY-MM-DD") from exc


def iter_chunks(start: date, end: date, chunk_days: int) -> Iterable[Chunk]:
    if chunk_days < 1:
        raise ValueError("--chunk-days must be at least 1")
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end)
        yield Chunk(start=current, end=chunk_end)
        current = chunk_end + timedelta(days=1)


def classify_event(*parts: str | None) -> str:
    text = " ".join(part or "" for part in parts).lower()
    text = " ".join(text.split())
    for event_type, needles in EVENT_RULES:
        if any(needle in text for needle in needles):
            return event_type
    return "other"


def parse_datetime(value: str | None) -> tuple[str, str]:
    if not value:
        return "", ""

    value = value.strip()
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%d-%b-%Y %H:%M:%S",
        "%d%m%Y%H%M%S",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.isoformat(sep=" "), parsed.date().isoformat()
        except ValueError:
            continue

    return value, value[:10]


def nse_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": NSE_BOOTSTRAP_URL,
    }


def bse_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.bseindia.com/corporates/ann.html",
    }


def fetch_nse(
    client: HttpJsonClient,
    symbol: str,
    start: date,
    end: date,
    chunk_days: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for chunk in iter_chunks(start, end, chunk_days):
        params = {
            "index": "equities",
            "symbol": symbol.upper(),
            "from_date": chunk.start.strftime("%d-%m-%Y"),
            "to_date": chunk.end.strftime("%d-%m-%Y"),
        }
        data = client.get_json(
            NSE_API_URL,
            params=params,
            headers=nse_headers(),
            bootstrap_url=NSE_BOOTSTRAP_URL,
        )
        if not isinstance(data, list):
            continue

        for item in data:
            event_datetime, event_date = parse_datetime(
                item.get("sort_date") or item.get("an_dt") or item.get("dt")
            )
            headline = clean_text(item.get("attchmntText") or item.get("desc") or "")
            description = clean_text(item.get("desc") or "")
            rows.append(
                {
                    "source": "NSE",
                    "symbol": clean_text(item.get("symbol") or symbol.upper()),
                    "bse_scrip": "",
                    "isin": clean_text(item.get("sm_isin") or ""),
                    "company_name": clean_text(item.get("sm_name") or ""),
                    "event_datetime": event_datetime,
                    "event_date": event_date,
                    "event_type": classify_event(description, headline),
                    "raw_category": description,
                    "headline": headline,
                    "description": description,
                    "source_event_id": str(item.get("seq_id") or ""),
                    "critical_flag": "",
                    "attachment_url": clean_text(item.get("attchmntFile") or ""),
                    "file_size": clean_text(
                        item.get("attFileSize") or item.get("fileSize") or ""
                    ),
                    "dedupe_key": make_dedupe_key(
                        event_date, symbol, headline, item.get("attchmntFile")
                    ),
                }
            )
    return rows


def fetch_bse(
    client: HttpJsonClient,
    symbol: str,
    bse_scrip: str,
    start: date,
    end: date,
    chunk_days: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for chunk in iter_chunks(start, end, chunk_days):
        params = {
            "strCat": "-1",
            "strPrevDate": chunk.start.strftime("%Y%m%d"),
            "strScrip": str(bse_scrip),
            "strSearch": "P",
            "strToDate": chunk.end.strftime("%Y%m%d"),
            "strType": "C",
        }
        data = client.get_json(BSE_API_URL, params=params, headers=bse_headers())
        table = data.get("Table", []) if isinstance(data, dict) else []
        if not isinstance(table, list):
            continue

        for item in table:
            event_datetime, event_date = parse_datetime(
                item.get("News_submission_dt")
                or item.get("DissemDT")
                or item.get("DT_TM")
                or item.get("NEWS_DT")
            )
            attachment_name = clean_text(item.get("ATTACHMENTNAME") or "")
            attachment_url = (
                f"{BSE_ATTACHMENT_BASE}/{attachment_name}" if attachment_name else ""
            )
            headline = clean_text(item.get("HEADLINE") or item.get("NEWSSUB") or "")
            description = clean_text(item.get("NEWSSUB") or "")
            raw_category = clean_text(item.get("CATEGORYNAME") or "")
            rows.append(
                {
                    "source": "BSE",
                    "symbol": symbol.upper(),
                    "bse_scrip": str(item.get("SCRIP_CD") or bse_scrip),
                    "isin": "",
                    "company_name": clean_text(item.get("SLONGNAME") or ""),
                    "event_datetime": event_datetime,
                    "event_date": event_date,
                    "event_type": classify_event(raw_category, description, headline),
                    "raw_category": raw_category,
                    "headline": headline,
                    "description": description,
                    "source_event_id": clean_text(item.get("NEWSID") or ""),
                    "critical_flag": str(item.get("CRITICALNEWS") or ""),
                    "attachment_url": attachment_url,
                    "file_size": str(item.get("Fld_Attachsize") or ""),
                    "dedupe_key": make_dedupe_key(
                        event_date, symbol, headline, attachment_name
                    ),
                }
            )
    return rows


def clean_text(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


def make_dedupe_key(
    event_date: str,
    symbol: str,
    headline: str | None,
    attachment: str | None,
) -> str:
    base = attachment or headline or ""
    normalized = "".join(ch.lower() for ch in base if ch.isalnum())
    return f"{event_date}|{symbol.upper()}|{normalized[:80]}"


def dedupe_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        identity = (row["source"], row["source_event_id"] or row["dedupe_key"])
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(row)
    return sorted(
        deduped,
        key=lambda row: (row.get("event_datetime") or "", row.get("source") or ""),
    )


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

    sources = {source.strip().lower() for source in args.sources.split(",") if source.strip()}
    unsupported = sources.difference({"nse", "bse"})
    if unsupported:
        print(f"Unsupported source(s): {', '.join(sorted(unsupported))}", file=sys.stderr)
        return 2

    client = HttpJsonClient(timeout=args.timeout, sleep_seconds=args.sleep)
    rows: list[dict[str, str]] = []
    if "nse" in sources:
        rows.extend(fetch_nse(client, args.symbol, start, end, args.chunk_days))
    if "bse" in sources:
        rows.extend(fetch_bse(client, args.symbol, args.bse_scrip, start, end, args.chunk_days))

    rows = dedupe_rows(rows)
    write_csv(rows, args.out)
    print(f"Wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

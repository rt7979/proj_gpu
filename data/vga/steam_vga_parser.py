"""Scrape Steam Hardware Survey video-card usage into a CSV file.

Steam currently publishes only the latest five monthly columns on this page.
The ten-year query is sent to Steam, but the script keeps the months actually
returned by Steam and reports the available range instead of inventing data.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PAGE_URL = "https://store.steampowered.com/hwsurvey/videocard/"
USER_AGENT = "Mozilla/5.0 (compatible; steam-vga-parser/1.0)"
MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def download_page(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def report_month(page: str) -> tuple[int, int]:
    match = re.search(r"Steam Hardware [^:<]+:\s*([A-Za-z]+)\s+(20\d{2})", page, re.I)
    if not match:
        raise ValueError("找不到 Steam 調查報告月份")
    return MONTHS[match.group(1)[:3].upper()], int(match.group(2))


def month_columns(page: str) -> list[str]:
    report_number, report_year = report_month(page)
    header_match = re.search(
        r'<div class="substats_col_left col_header">ALL VIDEO CARDS</div>(.*?)'
        r'<div class="substats_col_left col_header">',
        page,
        re.I | re.S,
    )
    if not header_match:
        raise ValueError("找不到 Steam ALL VIDEO CARDS 區段")
    abbreviations = re.findall(
        r'<div class="substats_col_month(?:_last_pct)? col_header">(?:<strong>)?([A-Z]{3})',
        header_match.group(1),
        re.I | re.S,
    )
    columns: list[str] = []
    for abbreviation in abbreviations:
        number = MONTHS[abbreviation.upper()]
        year = report_year - (1 if number > report_number else 0)
        columns.append(f"{year:04d}-{number:02d}")
    return columns


def parse_usage(value: str) -> float | None:
    value = clean_text(value)
    if value == "-":
        return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def extract_records(page: str, source_url: str) -> list[dict[str, str]]:
    columns = month_columns(page)
    header_match = re.search(
        r'<div class="substats_col_left col_header">ALL VIDEO CARDS</div>(.*?)'
        r'<div class="substats_col_left col_header">',
        page,
        re.I | re.S,
    )
    if not header_match:
        return []

    records: list[dict[str, str]] = []
    row_pattern = r'<div class="substats_row[^>]*">(.*?)(?=<div class="substats_row|<div class="substats_col_left col_header>)'
    for row_match in re.finditer(row_pattern, header_match.group(1), re.I | re.S):
        row = row_match.group(1)
        name_match = re.search(r'<div class="substats_col_left">(.*?)</div>', row, re.I | re.S)
        if not name_match:
            continue
        gpu = clean_text(name_match.group(1))
        values = re.findall(
            r'<div class="substats_col_month(?:_last_pct)?(?:\s[^>]*)?">(.*?)</div>',
            row,
            re.I | re.S,
        )
        if len(values) != len(columns):
            continue
        for month, raw_value in zip(columns, values):
            usage = parse_usage(raw_value)
            if usage is None:
                continue
            records.append(
                {
                    "month": month,
                    "gpu": gpu,
                    "usage_percent": f"{usage:.2f}",
                    "category": "all_video_cards",
                    "source_url": source_url,
                }
            )
    return records


def save_csv(records: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["month", "gpu", "usage_percent", "category", "source_url"]
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Steam Hardware Survey GPU usage.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).with_name("steam_vga_usage.csv"),
    )
    args = parser.parse_args()

    today = date.today()
    ten_years_ago = today.replace(year=today.year - 10)
    query = urlencode(
        {
            "start_date": ten_years_ago.isoformat(),
            "end_date": today.isoformat(),
            "l": "english",
        }
    )
    source_url = f"{PAGE_URL}?{query}"
    page = download_page(source_url)
    records = extract_records(page, source_url)
    save_csv(records, args.output)

    if not records:
        raise RuntimeError("Steam 頁面沒有找到顯卡使用率資料")
    print(f"Saved {len(records)} records to {args.output}")
    print(f"Available range: {records[0]['month']} to {records[-1]['month']}")
    print("Note: Steam currently returns the latest five monthly columns on this page.")


if __name__ == "__main__":
    main()
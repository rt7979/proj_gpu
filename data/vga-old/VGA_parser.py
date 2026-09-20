"""Download Pangoly graphics-card price trend data into a CSV file.

Pangoly currently documents that price trends cover the latest five years.
The parser accepts a ten-year window, but preserves only records returned by
the website instead of fabricating values for unavailable dates.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from html.parser import HTMLParser
from datetime import date, timedelta
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen


PAGE_URL = "https://pangoly.com/en/price-trends/vga"
USER_AGENT = "Mozilla/5.0 (compatible; VGA-price-parser/1.0)"


def download_page(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": PAGE_URL,
        },
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


class TrendLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href") or ""
        match = re.fullmatch(r"(?:https://pangoly\.com)?/en/price-trends/vga/([^/?#]+)", href)
        if match:
            self.links[match.group(1)] = ""

    def handle_data(self, data: str) -> None:
        if not self.links:
            return
        slug = next(reversed(self.links))
        name = " ".join(data.split())
        if name:
            self.links[slug] = f"{self.links[slug]} {name}".strip()


def find_categories(page: str) -> list[tuple[str, str]]:
    parser = TrendLinkParser()
    parser.feed(page)
    categories = []
    for slug, raw_name in parser.links.items():
        name = re.split(r"\s+[+-]\d|\s+\$", raw_name, maxsplit=1)[0].strip()
        categories.append((slug, name or slug))
    return categories


def parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"(20\d{2})[-/]([01]?\d)[-/]([0-3]?\d)", value)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_price(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str):
        value = value.replace(",", "")
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if not match:
            return None
        value = match.group(0)
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price >= 0 else None


def iter_json_values(page: str):
    for raw in re.findall(r"<script[^>]*>(.*?)</script>", page, re.I | re.S):
        text = unescape(raw).strip()
        if not text or text.startswith(("function", "const ", "let ", "var ")):
            continue
        try:
            yield json.loads(text)
        except json.JSONDecodeError:
            for candidate in re.findall(r"(?:\[[^;]+\]|\{[^;]+\})", text, re.S):
                try:
                    yield json.loads(candidate)
                except json.JSONDecodeError:
                    continue


def records_from_value(value: object, source_url: str, product: str = ""):
    if isinstance(value, dict):
        keys = {str(key).lower(): item for key, item in value.items()}
        date_value = next((keys[key] for key in ("date", "day", "timestamp", "x") if key in keys), None)
        price_value = next(
            (keys[key] for key in ("price", "value", "y", "average", "avg") if key in keys),
            None,
        )
        record_date = parse_date(date_value)
        price = parse_price(price_value)
        if record_date and price is not None:
            yield {
                "date": record_date.isoformat(),
                "category": "vga",
                "product": str(keys.get("product", keys.get("name", product))),
                "price": f"{price:.2f}",
                "currency": str(keys.get("currency", "USD")),
                "source_url": source_url,
            }
        for child in value.values():
            yield from records_from_value(child, source_url, product)
    elif isinstance(value, list):
        for child in value:
            yield from records_from_value(child, source_url, product)


def extract_records(page: str, source_url: str) -> list[dict[str, str]]:
    records: dict[tuple[str, str, str], dict[str, str]] = {}
    for data in iter_json_values(page):
        for record in records_from_value(data, source_url):
            key = (record["date"], record["product"], record["currency"])
            records[key] = record
    return sorted(records.values(), key=lambda item: (item["date"], item["product"]))


def extract_category_records(page: str, slug: str, product: str) -> list[dict[str, str]]:
    try:
        data = json.loads(page)
    except json.JSONDecodeError:
        return []
    records = []
    for series_name in ("avg", "min", "max"):
        for point in data.get(series_name, []):
            if not isinstance(point, list) or len(point) < 2:
                continue
            timestamp, price = point[:2]
            record_date = date.fromtimestamp(float(timestamp) / 1000).isoformat()
            parsed_price = parse_price(price)
            if parsed_price is None:
                continue
            records.append(
                {
                    "date": record_date,
                    "category": f"vga_{series_name}",
                    "product": product,
                    "price": f"{parsed_price:.2f}",
                    "currency": "USD",
                    "source_url": f"{PAGE_URL}/{slug}",
                }
            )
    return records


def save_csv(records: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["date", "category", "product", "price", "currency", "source_url"]
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Pangoly VGA price trends.")
    parser.add_argument("-o", "--output", type=Path, default=Path("vga_price_history.csv"))
    args = parser.parse_args()

    page = download_page(PAGE_URL)
    categories = find_categories(page)
    records: list[dict[str, str]] = []
    for slug, product in categories:
        endpoint = f"{PAGE_URL.rsplit('/', 1)[0]}/data/vga/{slug}"
        records.extend(extract_category_records(download_page(endpoint), slug, product))
    if not records:
        records = extract_records(page, PAGE_URL)
    cutoff = date.today() - timedelta(days=365 * 10)
    records = [record for record in records if record["date"] >= cutoff.isoformat()]
    save_csv(records, args.output)

    if records:
        print(f"Saved {len(records)} records to {args.output}")
        print(f"Available range: {records[0]['date']} to {records[-1]['date']}")
    else:
        print("No chart records were found. Pangoly may have changed its page format.")


if __name__ == "__main__":
    main()
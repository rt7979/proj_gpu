"""Scrape graphics-card sales information from Mindfactory.de.

Mindfactory exposes an approximate lifetime sold count on product listings
(for example, ``uber 3.790 verkauft``). This script stores that public value;
it is not a daily sales figure and is unavailable for some products.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import time
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen


BASE_URL = "https://www.mindfactory.de/Hardware/Grafikkarten+(VGA).html"
USER_AGENT = "Mozilla/5.0 (compatible; mindfactory-vga-parser/1.0)"


def download_page(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


def parse_price(text: str) -> str:
    match = re.search(r"€\s*([\d.]+)(?:,-|,\d{2})", text)
    if not match:
        return ""
    return match.group(1).replace(".", "")


def parse_sold(text: str) -> str:
    match = re.search(r"(?:über|ueber|�ber)\s+([\d.]+)\s+verkauft", text, re.I)
    return match.group(1).replace(".", "") if match else ""


def parse_article_number(text: str) -> str:
    match = re.search(r"Artnr:\s*([\w-]+)", text, re.I)
    return match.group(1) if match else ""


def extract_products(page: str, page_url: str) -> list[dict[str, str]]:
    product_links = list(
        re.finditer(
            r'href="(?P<href>https?://www\.mindfactory\.de/product_info\.php/[^"?]+|/product_info\.php/[^"?]+)"',
            page,
            re.I,
        )
    )
    products: list[dict[str, str]] = []
    index = 0
    while index < len(product_links):
        match = product_links[index]
        url = urljoin(page_url, html.unescape(match.group("href")))
        product_id = re.search(r"_(\d+)\.html", url)
        product_key = product_id.group(1) if product_id else url
        next_index = index + 1
        while next_index < len(product_links):
            next_url = urljoin(page_url, html.unescape(product_links[next_index].group("href")))
            next_id = re.search(r"_(\d+)\.html", next_url)
            next_key = next_id.group(1) if next_id else next_url
            if next_key != product_key:
                break
            next_index += 1
        end = product_links[next_index].start() if next_index < len(product_links) else len(page)
        block = page[match.start() : end]
        name_match = re.search(r'<div class="pname">(.*?)</div>', block, re.I | re.S)
        name = clean_text(name_match.group(1)) if name_match else ""
        text = clean_text(block)
        if not name or "verkauft" not in text.lower():
            continue
        products.append(
            {
                "product_name": name,
                "price_eur": parse_price(text),
                "sold_count": parse_sold(text),
                "article_number": parse_article_number(text),
                "availability": "In stock" if "Lagernd" in text else "",
                "product_url": url,
            }
        )
        index = next_index
    return products


def next_page_url(page: str, current_url: str) -> str | None:
    match = re.search(r'href="([^"]+?/Grafikkarten\+\(VGA\)\.html/page/\d+)"[^>]*>[^<]*Nächste Seite', page, re.I)
    return urljoin(current_url, html.unescape(match.group(1))) if match else None


def save_csv(products: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["product_name", "price_eur", "sold_count", "article_number", "availability", "product_url"]
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(products)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Mindfactory graphics-card sales.")
    parser.add_argument("-o", "--output", type=Path, default=Path(__file__).with_name("mindfactory_vga_sales.csv"))
    parser.add_argument("--max-pages", type=int, default=0, help="Limit pages; 0 means all pages.")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between page requests.")
    args = parser.parse_args()

    products: list[dict[str, str]] = []
    page_url: str | None = BASE_URL
    page_number = 0
    while page_url and (not args.max_pages or page_number < args.max_pages):
        page_number += 1
        page = download_page(page_url)
        products.extend(extract_products(page, page_url))
        print(f"Page {page_number}: {len(products)} products collected")
        page_url = next_page_url(page, page_url)
        if page_url:
            time.sleep(max(0.0, args.delay))

    unique_products = {product["product_url"]: product for product in products}
    result = list(unique_products.values())
    save_csv(result, args.output)
    print(f"Saved {len(result)} products to {args.output}")
    print("sold_count is Mindfactory's public cumulative 'verkauft' value.")


if __name__ == "__main__":
    main()
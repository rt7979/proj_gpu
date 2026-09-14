"""Download Pangoly graphics-card price history and export weekly prices.

Run once with::

	uv run python -m proj_gpu.gpu_parser.parser_gpu_history

Pangoly renders the chart in a browser and may protect the site with
Cloudflare. This scraper therefore uses Playwright instead of a plain HTTP
client. It does not bypass a challenge; the browser must be allowed to load
the page normally.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from playwright_stealth import stealth_sync

import pandas as pd
from playwright.sync_api import Browser, Page, Response, TimeoutError, sync_playwright


BASE_URL = "https://pangoly.com/en/price-trends/vga/"
OUTPUT_PATH = Path(__file__).resolve().parents[4] / "data" / "all_gpu_weekly_prices.csv"
LOGGER = logging.getLogger(__name__)
DATE_KEYS = ("date", "datetime", "timestamp", "time", "day", "x")
PRICE_KEYS = ("price", "value", "average", "avg", "mean", "median", "avgprice", "averageprice")
MIN_KEYS = ("min", "minimum", "low", "lowest", "minprice", "minimumprice", "lowprice")
MAX_KEYS = ("max", "maximum", "high", "highest", "maxprice", "maximumprice", "highprice")


@dataclass(frozen=True)
class PricePoint:
	date: pd.Timestamp
	minimum: float
	maximum: float
	average: float


def _normalise_key(key: Any) -> str:
	return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _first_value(record: dict[str, Any], keys: Iterable[str]) -> Any:
	normalised = {_normalise_key(key): value for key, value in record.items()}
	for key in keys:
		value = normalised.get(_normalise_key(key))
		if value is not None:
			return value
	return None


def _number(value: Any) -> float | None:
	if isinstance(value, bool) or value is None:
		return None
	if isinstance(value, (int, float)):
		return float(value)
	match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
	return float(match.group()) if match else None


def _date(value: Any) -> pd.Timestamp | None:
	if value is None:
		return None
	if isinstance(value, (int, float)):
		number = float(value)
		if number > 10_000_000_000:
			number /= 1000
		try:
			return pd.Timestamp(datetime.fromtimestamp(number, tz=timezone.utc)).tz_localize(None)
		except (OverflowError, OSError, ValueError):
			return None
	parsed = pd.to_datetime(value, errors="coerce", utc=True)
	if pd.isna(parsed):
		return None
	return parsed.tz_localize(None)


def _point_from_record(record: dict[str, Any]) -> PricePoint | None:
	date = _date(_first_value(record, DATE_KEYS))
	if date is None:
		return None
	average = _number(_first_value(record, PRICE_KEYS))
	minimum = _number(_first_value(record, MIN_KEYS))
	maximum = _number(_first_value(record, MAX_KEYS))
	if average is None and minimum is None and maximum is None:
		return None
	values = [value for value in (minimum, maximum, average) if value is not None]
	minimum = minimum if minimum is not None else min(values)
	maximum = maximum if maximum is not None else max(values)
	average = average if average is not None else sum(values) / len(values)
	if min(minimum, maximum, average) < 0:
		return None
	return PricePoint(date, minimum, maximum, average)


def _points_from_payload(payload: Any) -> list[PricePoint]:
	points: list[PricePoint] = []

	def visit(value: Any) -> None:
		if isinstance(value, dict):
			point = _point_from_record(value)
			if point is not None:
				points.append(point)
			for child in value.values():
				visit(child)
		elif isinstance(value, list):
			for item in value:
				if isinstance(item, (list, tuple)) and len(item) >= 2:
					date = _date(item[0])
					price = _number(item[1])
					if date is not None and price is not None and price >= 0:
						points.append(PricePoint(date, price, price, price))
				visit(item)

	visit(payload)
	return points


def _json_values(text: str) -> list[Any]:
	values: list[Any] = []
	decoder = json.JSONDecoder()
	for match in re.finditer(r"[\[{]", text):
		try:
			value, _ = decoder.raw_decode(text[match.start() :])
		except json.JSONDecodeError:
			continue
		if isinstance(value, (dict, list)):
			values.append(value)
	return values


def _model_slug(url: str) -> str:
	return urlparse(url).path.rstrip("/").split("/")[-1]


def _model_name(page: Page, url: str) -> str:
	for selector in ("h1", "main h2", "title"):
		try:
			text = page.locator(selector).first.inner_text(timeout=1500).strip()
		except TimeoutError:
			continue
		if text and "price" not in text.lower() and "trend" not in text.lower():
			return text
	return re.sub(r"[-_]", " ", _model_slug(url)).strip().title()


def _click_max_history(page: Page) -> None:
	patterns = re.compile(r"^(max|max history|all time|5y|5 years)$", re.IGNORECASE)
	for locator in (
		page.get_by_role("button", name=patterns),
		page.get_by_role("link", name=patterns),
		page.get_by_text(patterns),
	):
		try:
			if locator.count():
				locator.first.click(timeout=2000)
				page.wait_for_timeout(500)
				return
		except Exception:
			continue


def _discover_model_urls(page: Page) -> dict[str, str]:
	urls: dict[str, str] = {}
	for _ in range(4):
		for link in page.locator("a[href]").all():
			href = link.get_attribute("href")
			if not href:
				continue
			absolute = urljoin(BASE_URL, href).split("#", 1)[0]
			path = urlparse(absolute).path.rstrip("/")
			if re.fullmatch(r"/en/price-trends/vga/[^/]+", path):
				urls[absolute] = link.inner_text().strip() or _model_slug(absolute)
		for option in page.locator("option[value], [data-url]").all():
			href = option.get_attribute("value") or option.get_attribute("data-url")
			if not href:
				continue
			absolute = urljoin(BASE_URL, href).split("#", 1)[0]
			path = urlparse(absolute).path.rstrip("/")
			if re.fullmatch(r"/en/price-trends/vga/[^/]+", path):
				urls[absolute] = option.inner_text().strip() or _model_slug(absolute)
		page.mouse.wheel(0, 4000)
		page.wait_for_timeout(300)
	return urls


def _collect_page_payloads(page: Page, responses: list[Any]) -> list[Any]:
	payloads: list[Any] = list(responses)
	for text in page.locator("script").all_text_contents():
		payloads.extend(_json_values(text))
	return payloads


def _response_payload(response: Response) -> Any | None:
	content_type = response.headers.get("content-type", "").lower()
	if "json" not in content_type and not re.search(r"(chart|history|price|trend|api)", response.url, re.I):
		return None
	try:
		return response.json()
	except Exception:
		return None


def scrape_all_gpu_weekly_prices(
	output_path: Path = OUTPUT_PATH,
	headless: bool = True,
	timeout_ms: int = 30_000,
) -> pd.DataFrame:
	"""Scrape every GPU trend page and write the weekly result CSV."""
	with sync_playwright() as playwright:
		browser: Browser = playwright.chromium.launch(headless=headless)
		context = browser.new_context(viewport={"width": 1440, "height": 1000})
		index_page = context.new_page()
		stealth_sync(index_page)  # 讓這一個分頁套用隱身效果，偽裝成真實 Chrome
		index_page.set_default_timeout(timeout_ms)
		index_page.goto(BASE_URL, wait_until="domcontentloaded")
		index_page.wait_for_timeout(1500)
		model_urls = _discover_model_urls(index_page)
		if not model_urls:
			browser.close()
			raise RuntimeError("找不到顯示卡型號；網站可能仍在 Cloudflare challenge 或頁面結構已變更。")

		raw_rows: list[dict[str, Any]] = []
		for index, (url, link_name) in enumerate(model_urls.items(), start=1):
			LOGGER.info("[%d/%d] %s", index, len(model_urls), url)
			page = context.new_page()
			responses: list[Any] = []
			page.on("response", lambda response: responses.append(_response_payload(response)))
			try:
				page.goto(url, wait_until="domcontentloaded")
				page.wait_for_timeout(1200)
				_click_max_history(page)
				payloads = _collect_page_payloads(page, [item for item in responses if item is not None])
				points = _points_from_payload(payloads)
				model = _model_name(page, url) or link_name
				seen: set[tuple[Any, ...]] = set()
				for point in points:
					key = (point.date, point.minimum, point.maximum, point.average)
					if key not in seen:
						seen.add(key)
						raw_rows.append({
							"顯卡型號": model,
							"date": point.date,
							"minimum": point.minimum,
							"maximum": point.maximum,
							"average": point.average,
						})
			except Exception as exc:
				LOGGER.warning("跳過 %s：%s", url, exc)
			finally:
				page.close()
		browser.close()

	if not raw_rows:
		raise RuntimeError("沒有解析到歷史價格資料；請確認瀏覽器可通過網站驗證，或檢查網站資料格式。")
	result = pd.DataFrame(raw_rows)
	result["日期(以週為單位)"] = result["date"].dt.to_period("W-SUN").apply(lambda period: period.start_time)
	result = (
		result.groupby(["顯卡型號", "日期(以週為單位)"], as_index=False)
		.agg({"minimum": "min", "maximum": "max", "average": "mean"})
		.rename(columns={"minimum": "最低價格", "maximum": "最高價格", "average": "平均價格"})
	)
	result = result[["顯卡型號", "日期(以週為單位)", "最低價格", "最高價格", "平均價格"]]
	result = result.sort_values(["顯卡型號", "日期(以週為單位)"]).reset_index(drop=True)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	result.to_csv(output_path, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
	return result


def main() -> None:
	parser = argparse.ArgumentParser(description="一次性擷取 Pangoly 全部顯示卡每週歷史價格")
	parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="輸出 CSV 路徑")
	parser.add_argument("--headed", action="store_true", help="顯示瀏覽器視窗，方便通過網站驗證")
	parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING"))
	args = parser.parse_args()
	logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
	result = scrape_all_gpu_weekly_prices(args.output, headless=not args.headed)
	LOGGER.info("完成：%d 筆每週資料已寫入 %s", len(result), args.output)


if __name__ == "__main__":
	main()

"""
Download Pangoly graphics-card price trend data into a CSV file.

Pangoly currently documents that price trends cover the latest five years.
The parser accepts a ten-year window, but preserves only records returned by
the website instead of fabricating values for unavailable dates.

網站： "https://pangoly.com/en/price-trends/vga"
目標： 爬蟲所有顯卡歷史價格，一周一筆
欄位： [顯卡型號, 日期(以週為單位), 最低價格,最高價格,平均價格]

執行方法：uv run python src/proj_gpu/gpu_parser/VGA_parser_week_final.py
或直接執行即可

"""


from __future__ import annotations

import argparse
from html import unescape
import json
import re
import time
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from urllib.parse import quote
import pandas as pd
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

BASE_URL = "https://pangoly.com"
TREND_INDEX_URL = f"{BASE_URL}/en/price-trends/vga"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


class PangolyBrowser:
    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=headless)
        self.context = self.browser.new_context(user_agent=USER_AGENT)
        Stealth(navigator_user_agent_override=USER_AGENT).apply_stealth_sync(self.context)
        self.page = self.context.new_page()

    def download_page(self, url: str, retries: int = 3, backoff: float = 15.0) -> str:
        for attempt in range(1, retries + 1):
            try:
                response = self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                if response is None or response.status >= 400:
                    status = response.status if response is not None else "no response"
                    if status == 403 and not self.headless:
                        print(" ⚠️ Pangoly 要求 Cloudflare 驗證，請在開啟的 Chromium 視窗完成驗證。")
                        input("完成驗證後按 Enter 繼續...")
                        response = self.page.reload(wait_until="domcontentloaded", timeout=30_000)
                        if response is not None and response.status < 400:
                            self.page.wait_for_timeout(1_000)
                            return response.text()
                    raise RuntimeError(f"HTTP {status}")
                self.page.wait_for_timeout(1_000)
                return response.text()
            except Exception as error:
                if attempt == retries:
                    raise error
                print(f" ⚠️ 網路連線異常或遭阻擋 ({error})。等待 {backoff} 秒後重試...")
                time.sleep(backoff)
        return ""

    def close(self) -> None:
        self.browser.close()
        self.playwright.stop()

    def download_category_data(self, slug: str, retries: int = 3) -> str:
        model_url = f"{TREND_INDEX_URL}/{quote(slug)}"
        endpoint = f"{BASE_URL}/en/price-trends/data/vga/{quote(slug)}"

        for attempt in range(1, retries + 1):
            responses = []
            context = self.browser.new_context(user_agent=USER_AGENT)
            Stealth(navigator_user_agent_override=USER_AGENT).apply_stealth_sync(context)
            page = context.new_page()

            def capture(response) -> None:
                if response.url.rstrip("/") == endpoint.rstrip("/"):
                    responses.append(response)

            page.on("response", capture)
            try:
                page_response = page.goto(model_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2_000)
            finally:
                page.remove_listener("response", capture)

            try:
                if responses and responses[-1].status < 400:
                    return responses[-1].text()

                status = page_response.status if page_response is not None else "no response"
                if status == 403 and not self.headless:
                    print(" ⚠️ Pangoly 要求 Cloudflare 驗證，請在開啟的 Chromium 視窗完成驗證。")
                    input("完成驗證後按 Enter 繼續...")
                    continue

                if attempt < retries:
                    print(f" ⚠️ 型號頁或價格資料暫時無法取得 (HTTP {status})，稍後重試...")
                    time.sleep(5)
            finally:
                page.close()
                context.close()

        raise RuntimeError(f"無法取得 {slug} 的價格 JSON (HTTP {status})")

def find_categories_by_regex(html_content: str) -> list[tuple[str, str]]:
    pattern = r'href=["\'](?:https://pangoly\.com)?/en/price-trends/vga/([a-zA-Z0-9-]+)["\'][^>]*>(.*?)<\/a>'
    matches = re.findall(pattern, html_content, re.DOTALL)
    
    categories = []
    seen_slugs = set()
    
    for slug, raw_name in matches:
        slug = slug.strip()
        if slug in seen_slugs:
            continue
            
        clean_name = re.sub(r'<[^>]+>', '', raw_name)
        clean_name = " ".join(unescape(clean_name).split())
        clean_name = re.split(
            r"\s+Price\s+|\s+[+-]\d|\s+\$", clean_name, maxsplit=1, flags=re.IGNORECASE
        )[0].strip()
        
        if clean_name and slug not in ["", "data"]:
            categories.append((slug, clean_name))
            seen_slugs.add(slug)
            
    return categories

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

def extract_category_records(page: str, product: str) -> list[dict[str, str]]:
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
            try:
                record_date = datetime.fromtimestamp(float(timestamp) / 1000, tz=timezone.utc).date().isoformat()
            except (TypeError, ValueError, OverflowError, OSError):
                continue
            parsed_price = parse_price(price)
            if parsed_price is None:
                continue
            records.append(
                {
                    "date": record_date,
                    "category": series_name,
                    "product": product,
                    "price": f"{parsed_price:.2f}",
                }
            )
    return records

def process_and_append_to_csv(records: list[dict[str, str]], output: Path) -> None:
    """將單個顯卡的原始紀錄進行特定日期（1, 8, 15, 23日）抽樣。若無資料則嘗試順延一天，並即時寫入 CSV"""
    if not records:
        return
        
    columns = ["顯卡型號", "報告日期", "最低價格", "最高價格", "平均價格"]
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df["price"] = pd.to_numeric(df["price"])

    pivoted = df.pivot_table(index=["product", "date"], columns="category", values="price").reset_index()
    for col in ["min", "max", "avg"]:
        if col not in pivoted.columns:
            pivoted[col] = None

    pivoted = pivoted.rename(columns={"product": "顯卡型號", "min": "最低價格", "max": "最高價格", "avg": "平均價格"})
    
    # === 🚀 核心修改：目標日無資料時，自動順延一天 ===
    # 建立每個月的年月標籤 (例如 "2023-05")，方便分組處理
    pivoted["year_month"] = pivoted["date"].dt.to_period("M")
    
    # 定義我們的首選目標日（1, 8, 15, 23）
    target_days = [1, 8, 15, 23]
    sampled_rows = []

    # 按照「顯示卡型號」與「各個月份」分組進行精準篩選
    for (prod_name, ym), group in pivoted.groupby(["顯卡型號", "year_month"]):
        # 建立該月已有的日期與資料橫列對照表
        day_map = {row["date"].day: row for _, row in group.iterrows()}
        
        for target in target_days:
            # 1. 優先檢查首選目標日（例如 8 日）
            if target in day_map:
                sampled_rows.append(day_map[target])
            # 2. 若首選日沒有，嘗試順延下一天（例如 9 日）
            elif (target + 1) in day_map:
                sampled_rows.append(day_map[target + 1])
            # 3. 兩天都沒有，則此區間視為缺失，留待事後人工補齊
            else:
                continue

    if not sampled_rows:
        return

    monthly_sampled = pd.DataFrame(sampled_rows)
    
    # 將實際抓到的日期格式化為字串，寫入「報告日期」欄位
    monthly_sampled["報告日期"] = monthly_sampled["date"].dt.strftime("%Y-%m-%d")
    
    # 格式化輸出
    monthly_sampled = monthly_sampled[columns]
    # ===================================================

    output.parent.mkdir(parents=True, exist_ok=True)
    file_exists = output.exists() and output.stat().st_size > 0
    monthly_sampled.to_csv(output, mode='a', index=False, header=not file_exists, encoding="utf-8-sig")

def post_clean_csv(output: Path) -> None:
    """任務完全結束或中斷時，對 CSV 進行全域去重與重新排序"""
    if not output.exists() or output.stat().st_size == 0:
        return
    print("正在對 CSV 檔案進行最終去重與排序優化...")
    df = pd.read_csv(output, encoding="utf-8-sig")
    df = df.drop_duplicates(subset=["顯卡型號", "報告日期"], keep='last')
    df = df.sort_values(by=["顯卡型號", "報告日期"]).reset_index(drop=True)
    df.to_csv(output, index=False, encoding="utf-8-sig")

def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Pangoly VGA price trends with flexible monthly sampling.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data/monthly_sampled_vga_prices.csv"),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--headed",
        dest="headless",
        action="store_false",
        help="顯示 Chromium 視窗，讓使用者完成 Pangoly 的 Cloudflare 驗證（預設）。",
    )
    mode.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="不顯示瀏覽器；若 Pangoly 要求驗證，抓取會被拒絕。",
    )
    parser.set_defaults(headless=False)
    args = parser.parse_args()

    completed_products = set()
    if args.output.exists() and args.output.stat().st_size > 0:
        try:
            existing_df = pd.read_csv(args.output, encoding="utf-8-sig")
            if "顯卡型號" in existing_df.columns:
                completed_products = set(existing_df["顯卡型號"].dropna().unique())
                print(f"📦 偵測到既有 CSV 檔案。已載入已完成的 {len(completed_products)} 個顯卡型號進度。")
        except Exception as e:
            print(f"⚠️ 無法讀取既有 CSV 檔案進度 ({e})，將重新開始抓取。")

    browser = PangolyBrowser(headless=args.headless)
    print(f"正在從總覽頁抓取所有顯示卡型號...")
    try:
        index_page = browser.download_page(TREND_INDEX_URL)
        categories = find_categories_by_regex(index_page)
    except Exception as e:
        print(f"無法讀取顯示卡總覽頁面: {e}")
        browser.close()
        return

    if not categories:
        print("未能在總覽頁面解析出任何顯卡型號，請確認總覽頁網址是否正確。")
        browser.close()
        return

    todo_categories = [(slug, prod) for slug, prod in categories if prod not in completed_products]
    total_all = len(categories)
    total_todo = len(todo_categories)
    
    print(f"總共有 {total_all} 個顯卡型號。已完成: {len(completed_products)} 個，剩餘待抓取: {total_todo} 個。")
    
    if total_todo == 0:
        print("🎉 所有型號皆已下載完成！")
        browser.close()
        post_clean_csv(args.output)
        return

    consecutive_failures = 0
    MAX_ALLOWED_FAILURES = 2
    cutoff = (date.today() - timedelta(days=365 * 10)).isoformat()  # 設定開始時間，10年前

    """
    # ************************************
    #
    # ********** 自行設定開始時間 **********
    #
    # ************************************
    #
    # === 🚀 核心修改：動態調整開始時間（自動取得當月 1 日） ===
    today = date.today()
    # 建立當月 1 日的日期物件 (例如 2026-09-01)
    current_month_start = date(today.year, today.month, 1)
    cutoff = current_month_start.isoformat()
    
    """

    try:
        for i, (slug, product) in enumerate(todo_categories, 1):
            safe_slug = quote(slug)
            print(f"[{i}/{total_todo}] 正在下載 {product} (代號: {slug}) ...")
            
            try:
                json_data = browser.download_category_data(safe_slug)
                new_records = extract_category_records(json_data, product)
                
                if new_records:
                    new_records = [r for r in new_records if r["date"] >= cutoff]
                    process_and_append_to_csv(new_records, args.output)
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    print(f" ⚠️ 警告：{product} 回傳空資料。")
                    
            except Exception as e:
                consecutive_failures += 1
                print(f" ❌ 錯誤：無法下載 {product} 的資料: {e}")
            
            if consecutive_failures >= MAX_ALLOWED_FAILURES:
                print(f"\n🚨 警報：已連續 {consecutive_failures} 個型號下載失敗！自動觸發停損中斷。")
                break
            
            time.sleep(1.0)
            
    except KeyboardInterrupt:
        print("\n🛑 偵測到手動中斷（Ctrl+C）。正在安全儲存進度...")

    browser.close()
    post_clean_csv(args.output)
    print("🏁 程式執行完畢。隨時可重新執行以接續未完成的進度。")

if __name__ == "__main__":
    main()

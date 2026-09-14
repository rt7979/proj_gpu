"""
Download Pangoly graphics-card price trend data into a CSV file.

Pangoly currently documents that price trends cover the latest five years.
The parser accepts a ten-year window, but preserves only records returned by
the website instead of fabricating values for unavailable dates.

網站： "https://pangoly.com/en/price-trends/vga"
目標： 爬蟲所有顯卡歷史價格，一周一筆
欄位： [顯卡型號, 日期(以週為單位), 最低價格,最高價格,平均價格]

"""


from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import URLError
import pandas as pd

BASE_URL = "https://pangoly.com"
TREND_INDEX_URL = "https://pangoly.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def download_page(url: str, retries: int = 3, backoff: float = 15.0) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": TREND_INDEX_URL,
        },
    )
    
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=15) as response:
                return response.read().decode("utf-8", errors="replace")
        except (URLError, Exception) as e:
            if attempt == retries:
                raise e
            print(f" ⚠️ 網路連線異常或遭阻擋 ({e})。將強制靜置等待 {backoff} 秒後，進行第 {attempt}/{retries} 次重試...")
            time.sleep(backoff)
    return ""

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
        clean_name = " ".join(clean_name.split())
        clean_name = re.split(r"\s+Price\s+|\s+[+-]\d|\s+\$", clean_name, flags=re.IGNORECASE).strip()
        
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
            record_date = datetime.fromtimestamp(float(timestamp) / 1000, tz=timezone.utc).date().isoformat()
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
    """將單個顯卡的原始紀錄進行週抽樣，並即時追加寫入 CSV"""
    if not records:
        return
        
    columns = ["顯卡型號", "日期(以週為單位)", "最低價格", "最高價格", "平均價格"]
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df["price"] = pd.to_numeric(df["price"])

    pivoted = df.pivot_table(index=["product", "date"], columns="category", values="price").reset_index()
    for col in ["min", "max", "avg"]:
        if col not in pivoted.columns:
            pivoted[col] = None

    pivoted = pivoted.rename(columns={"product": "顯卡型號", "min": "最低價格", "max": "最高價格", "avg": "平均價格"})
    pivoted["日期(以週為單位)"] = pivoted["date"].dt.to_period("W-SUN").dt.start_time
    weekly = pivoted.groupby(["顯卡型號", "日期(以週為單位)"], as_index=False).first()
    weekly = weekly[columns]
    
    # 格式化日期為字串，方便 CSV 儲存
    weekly["日期(以週為單位)"] = weekly["日期(以週為單位)"].dt.strftime("%Y-%m-%d")

    output.parent.mkdir(parents=True, exist_ok=True)
    # 如果檔案不存在，寫入 Header；如果已存在，則不寫 Header 直接追加 (mode='a')
    file_exists = output.exists() and output.stat().st_size > 0
    weekly.to_csv(output, mode='a', index=False, header=not file_exists, encoding="utf-8-sig")

def post_clean_csv(output: Path) -> None:
    """任務完全結束或中斷時，對 CSV 進行全域去重與重新排序"""
    if not output.exists() or output.stat().st_size == 0:
        return
    print("正在對 CSV 檔案進行最終去重與排序優化...")
    df = pd.read_csv(output, encoding="utf-8-sig")
    # 根據顯卡型號與週日期去重，保留最新寫入的資料
    df = df.drop_duplicates(subset=["顯卡型號", "日期(以週為單位)"], keep='last')
    df = df.sort_values(by=["顯卡型號", "日期(以週為單位)"]).reset_index(drop=True)
    df.to_csv(output, index=False, encoding="utf-8-sig")

def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Pangoly VGA price trends with resume capability.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data/weekly_vga_prices.csv"),
    )
    args = parser.parse_args()

    # 【斷點續傳機制 1】載入既有的進度
    completed_products = set()
    if args.output.exists() and args.output.stat().st_size > 0:
        try:
            existing_df = pd.read_csv(args.output, encoding="utf-8-sig")
            if "顯卡型號" in existing_df.columns:
                completed_products = set(existing_df["顯卡型號"].dropna().unique())
                print(f"📦 偵測到既有 CSV 檔案。已載入已完成的 {len(completed_products)} 個顯卡型號進度。")
        except Exception as e:
            print(f"⚠️ 無法讀取既有 CSV 檔案進度 ({e})，將重新開始抓取。")

    print(f"正在從總覽頁抓取所有顯示卡型號...")
    try:
        index_page = download_page(TREND_INDEX_URL)
        categories = find_categories_by_regex(index_page)
    except Exception as e:
        print(f"無法讀取顯示卡總覽頁面: {e}")
        return

    if not categories:
        print("未能在總覽頁面解析出任何顯卡型號，請確認總覽頁網址是否正確。")
        return

    # 過濾掉已經抓過的型號
    todo_categories = [(slug, prod) for slug, prod in categories if prod not in completed_products]
    total_all = len(categories)
    total_todo = len(todo_categories)
    
    print(f"總共有 {total_all} 個顯卡型號。已完成: {len(completed_products)} 個，剩餘待抓取: {total_todo} 個。")
    
    if total_todo == 0:
        print("🎉 所有型號皆已下載完成！")
        post_clean_csv(args.output)
        return

    consecutive_failures = 0
    MAX_ALLOWED_FAILURES = 2
    cutoff = (date.today() - timedelta(days=365 * 10)).isoformat()

    try:
        for i, (slug, product) in enumerate(todo_categories, 1):
            safe_slug = quote(slug)
            endpoint = f"https://pangoly.com/data/{safe_slug}"
            print(f"[{i}/{total_todo}] 正在下載 {product} (代號: {slug}) ...")
            
            try:
                json_data = download_page(endpoint)
                new_records = extract_category_records(json_data, product)
                
                if new_records:
                    # 篩選 10 年內資料
                    new_records = [r for r in new_records if r["date"] >= cutoff]
                    # 【斷點續傳機制 2】一抓完，立刻將這款顯卡的資料追加進 CSV 落地保存
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

    # 最後進行整體的去重與格式整理
    post_clean_csv(args.output)
    print("🏁 程式執行完畢。隨時可重新執行以接續未完成的進度。")

if __name__ == "__main__":
    main()

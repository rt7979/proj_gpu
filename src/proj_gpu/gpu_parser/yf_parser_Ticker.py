"""
# ===============================
# 
# 股價跟指數抓取
# 使用yfinance插件爬蟲
# 
# ===============================

"""

import os
import yfinance as yf
import pandas as pd
from datetime import datetime

def download_tech_indicators(start_date="2021-01-01"):
    print("[*] 開始下載全球 AI 與半導體核心科技指標...")
    
    # 定義專題核心指標的 Ticker
    tickers = {
        "NVDA": "NVIDIA_股價",# NVIDIA的股價
        "AMD": "AMD_股價",  # 顯示卡雙雄對照組
        "TSM": "TSMC_ADR股價",  # 晶圓代工
        "MU": "美光_股價",  # 記憶體與HBM領先指標 (代表金士頓等零件成本)
        "SSNLF": "三星_股價(美金)",  # 全球記憶體老大 (已鎖定美金計價存託憑證)
        "^SOX": "費城半導體指數",  # 全球半導體大藍籌
        "IVV": "SP500_大盤指數",  # 大盤總體經濟
    }

    # 取得最新日期 (2026年最新數據)
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    # 下載數據
    raw_data = yf.download(
            list(tickers.keys()), start=start_date, end=end_date, progress=False
        )
    
    # 安全地提取 Adj Close 欄位，避免 Pandas 索引定位出錯
    if "Adj Close" in raw_data.columns.levels[0]:
        data = raw_data["Adj Close"]
    else:
        # 備用方案：如果沒有 Adj Close 則取 Close
        data = raw_data["Close"]
        
    # --- ETL 資料清洗與特徵工程 ---
    # 重設索引，將 Date 變成欄位
    df_indicators = data.reset_index()
    
    # 重新命名欄位，轉成中文與你的資料結構對齊
    df_indicators = df_indicators.rename(columns=tickers)
    df_indicators = df_indicators.rename(columns={"Date": "full_date"})

    
    # 格式化日期為 YYYY-MM-DD
    df_indicators["full_date"] = pd.to_datetime(df_indicators["full_date"]).dt.strftime("%Y-%m-%d")
    
    # 處理缺失值：金融市場週末不開盤，使用前一天交易日的價格填充 (Forward Fill)
    df_indicators = df_indicators.ffill()
    # 如果最開頭有 NaN，則用後一天交易日價格填充 (Backward Fill)
    df_indicators = df_indicators.bfill()
    
    print(f"[+] 資料抓取成功！共 {len(df_indicators)} 筆。")
    return df_indicators

if __name__ == "__main__":
    df_result = download_tech_indicators()

    # 資料預覽
    print("\n📊 資料預覽：")
    print(df_result.head())

    # 【防呆機制】即使 data 資料夾存在，這行程式也不會報錯；如果不存在，它會自動幫你建好
    os.makedirs("data", exist_ok=True)

    # 匯出 CSV 檔，路徑在專案的data/底下
    output_filename = "data/global_ai_and_tech_indicators.csv"
    df_result.to_csv(output_filename, index=False, encoding="utf-8-sig")
    print(f"\n[🎉] 檔案已成功匯出至：{output_filename}")
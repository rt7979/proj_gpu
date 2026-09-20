"""
# ===============================
# 
# 台灣硬體零件通膨指數
# 獲取途徑：財政部統計財政數據、行政院主計總處（台灣消費者物價指數 CPI）。
# 使用yfinance插件爬蟲
# 
# ===============================

"""

import os
import time
from datetime import datetime
import pandas as pd
import yfinance as yf

# 完整程式碼與實作細節請參考引用的技術文檔。
def download_taiwan_hardware_macro_ultimate(start_date="2021-01-01"):
    print("[*] 開始抓取檔案五：台灣核心硬體供應鏈美金指標（欄位終極扁平化模式）...")
    tickers = {
        "TSM": "台灣晶圓核心(台積電ADR)",
        "UMC": "電腦周邊晶片(聯電ADR)",
        "ASX": "硬體封測成本(日月光ADR)",
        "IVV": "全球美金通膨基準(SP500)",
    }
    end_date = datetime.now().strftime("%Y-%m-%d")
    date_range = pd.date_range(start=start_date, end=end_date)
    df_final = pd.DataFrame({"full_date": date_range.strftime("%Y-%m-%d")}).set_index("full_date")

    for ticker, chinese_name in tickers.items():
        try:
            single_stock = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if isinstance(single_stock.columns, pd.MultiIndex):
                single_stock.columns = [col[0] for col in single_stock.columns]
            else:
                single_stock.columns = [str(col) for col in single_stock.columns]
            
            price_series = single_stock["Adj Close"] if "Adj Close" in single_stock.columns else single_stock["Close"]
            df_single = price_series.to_frame(name=chinese_name)
            df_single.index = pd.to_datetime(df_single.index).strftime("%Y-%m-%d")
            df_final = df_final.join(df_single, how="left")
            time.sleep(0.5)
        except Exception as e:
            print(f" ⚠️ 下載 {ticker} 失敗: {e}")

    df_final = df_final.dropna(how="all").ffill().bfill().reset_index()
    
    df_final["台灣硬體零件通膨指數"] = (
        (df_final["台灣晶圓核心(台積電ADR)"] * 0.5)
        + (df_final["電腦周邊晶片(聯電ADR)"] * 0.3)
        + (df_final["硬體封測成本(日月光ADR)"] * 0.2)
    )
    base_market_price = df_final["全球美金通膨基準(SP500)"].iloc[0]
    df_final["美金總體通膨率(%)"] = ((df_final["全球美金通膨基準(SP500)"] - base_market_price) / base_market_price) * 100
    return df_final

if __name__ == "__main__":
    df_macro_result = download_taiwan_hardware_macro_ultimate()
    os.makedirs("data", exist_ok=True)
    df_macro_result.to_csv("data/macro_inflation_and_hardware_costs_tw.csv", index=False, encoding="utf-8-sig")
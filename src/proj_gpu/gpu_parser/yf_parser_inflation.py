"""
# ===============================
# 
# 總體經濟通膨與硬體成本大數據抓取
# 使用yfinance插件爬蟲
# 
# ===============================

"""

import os
from datetime import datetime
import pandas as pd
import yfinance as yf


def download_macro_and_hardware_data(start_date="2021-01-01"):
    print("[*] 開始抓取檔案五：總體經濟通膨與全球硬體零件通膨指標...")

    # 定義專題核心指標的 Ticker
    tickers = {
        "MU": "記憶體成本指標(美光)",
        "INTC": "CPU成本指標(Intel)",
        "AMD": "平台成本指標(AMD)",
        "CL=F": "全球物流通膨(原油)",
        "IVV": "美金購買力大盤(S&P500)",
    }

    # 取得最新日期 (2026年最新數據)
    end_date = datetime.now().strftime("%Y-%m-%d")

    # 下載數據
    raw_data = yf.download(
        list(tickers.keys()), start=start_date, end=end_date, progress=False
    )

    # --- 【🛠️ 修正點：完美相容新舊版本欄位結構的防呆邏輯】 ---
    # 檢查 columns 是否為 MultiIndex 結構
    if isinstance(raw_data.columns, pd.MultiIndex):
        if "Adj Close" in raw_data.columns.levels[0]:
            data = raw_data["Adj Close"]
        else:
            data = raw_data["Close"]
    else:
        # 如果是普通的一層索引，直接使用 columns.str.contains 或是直接安全提取
        # 大多數新版 yfinance 在單一層索引時會將 Adj Close 放在內文中，或是直接回傳普通欄位
        # 這裡採取最穩健的過濾方式：
        if "Adj Close" in raw_data.columns:
            data = raw_data["Adj Close"]
        else:
            # 處理部分新版格式為 'Adj Close' 變成雙層但降維的情況
            try:
                data = raw_data.xs("Adj Close", axis=1, level=0)
            except:
                data = raw_data

    # --- ETL 資料清洗 ---
    df_macro = data.reset_index()
    df_macro = df_macro.rename(columns=tickers)
    df_macro = df_macro.rename(columns={"Date": "full_date"})

    # 統一日期格式為 YYYY-MM-DD
    df_macro["full_date"] = pd.to_datetime(df_macro["full_date"]).dt.strftime(
        "%Y-%m-%d"
    )

    # 處理假日不開盤的缺失值 (前向與後向填充)
    df_macro = df_macro.ffill().bfill()

    # --- 📊 特徵工程 (Feature Engineering) ---
    print("[*] 正在進行高階特徵工程，建立專題核心衍生指標...")

    # (1) 計算硬體零件指數 (Hardware Cost Index)
    df_macro["上游硬體通膨指數"] = (
        (df_macro["記憶體成本指標(美光)"] * 0.4)
        + (df_macro["CPU成本指標(Intel)"] * 0.3)
        + (df_macro["平台成本指標(AMD)"] * 0.3)
    )

    # (2) 計算時間成本與大盤累計通膨率 (%)
    base_market = df_macro["美金購買力大盤(S&P500)"].iloc[0]
    df_macro["大盤累計通膨率(%)"] = (
        (df_macro["美金購買力大盤(S&P500)"] - base_market) / base_market
    ) * 100

    print(f"[+] 檔案五資料處理完成！共 {len(df_macro)} 筆每日詳細數據。")
    return df_macro


if __name__ == "__main__":
    df_macro_result = download_macro_and_hardware_data()

    # 資料預覽
    print("\n📊 特徵工程衍生後資料預覽：")
    print(df_macro_result[["full_date", "上游硬體通膨指數", "大盤累計通膨率(%)"]].head())

    # --- 儲存至指定的 data/ 資料夾 ---
    output_dir = "data"
    os.makedirs(output_dir, exist_ok=True)  # 防呆機制

    output_filepath = os.path.join(
        output_dir, "macro_inflation_and_hardware_costs.csv"
    )
    df_macro_result.to_csv(output_filepath, index=False, encoding="utf-8-sig")

    print(f"\n[🎉] 檔案已成功更新並儲存至：{output_filepath}")
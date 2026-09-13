# 🚀 數據分析與動態看板系統 (專案大標題)

這是一個整合 **MariaDB 資料庫、Streamlit 互動網頁、以及 Power BI 視覺化報表** 的全方位數據展示專案。

## 🌟 核心功能
* **即時數據動態看板**：內嵌 Power BI 互動式圖表，提供秒級的趨勢分析。
* **MariaDB 資料庫查詢**：透過前端介面安全、即時地與後端資料庫拉取數據。
* **多頁面流暢導覽**：採用標準的模組化架構，提供良好的使用者體驗。

## 🛠️ 開發工具與技術
* **前端與核心框架**: Python, Streamlit
* **環境管理工具**: uv
* **後端資料庫**: MariaDB
* **報表工具**: Power BI Desktop / Service

## 📦 本地快速啟動教學
1. 複製儲存庫：`git clone ...`
2. 安裝套件：`uv sync`
3. 填寫設定：在 `.streamlit/secrets.toml` 中填入你的資料庫連線資訊。
4. 啟動網站：`uv run streamlit run app.py`
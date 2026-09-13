"""
*****************************************
*
* 使用 streamlit run app.py 執行程式
* 使用 Ctrl + Shift + P 打開命令面板
* 輸入 Simple Browser 並貼上網址 http://localhost:8501 ，按下enter
* 終端機輸入 Ctrl + C 關閉預覽
*
*****************************************
"""

import streamlit as st
from proj_gpu.templates import base_template, footer_template, page_layout



# 🚀 1. 套用基礎樣板，並自訂該頁標題
base_template(title="銷售數據統計看板")

# 🚀 2. 這一頁自己獨有的內容
st.write("這裡擺放 Power BI 報表或 SQL 查詢表格...")
st.bar_chart({"data": [10, 20, 30, 40]})




# 主頁內容
st.title("hello")

st.divider(width="stretch")

# 🎯 直接讀取 static 資料夾下的個人照片
st.image("static/images/1001.jpg", width=200, caption="我是專案開發者")



"""
# 🎯 像 Flask block 一樣，把所有內容包在 with 裡面
with page_layout(title="SQL 即時查詢頁面"):
    
    st.write("請輸入查詢條件：")
    user_input = st.text_input("輸入用戶 ID")
    
    if st.button("查詢"):
        st.success(f"正在查詢：{user_input}")
"""


# 🚀 3. 套用頁尾樣板
footer_template()




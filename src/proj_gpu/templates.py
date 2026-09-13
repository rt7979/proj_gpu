"""
**********
*
* 定義樣板
*
**********

"""

from contextlib import contextmanager
import streamlit as st



def base_template(title="我的專案系統"):
    """
    網頁基本核心樣板（包含設定、頁首與側邊欄）
    """
    # 1. 統一網頁基本設定
    st.set_page_config(
        page_title=title,
        page_icon="🚀",
        layout="wide"
    )
    
    # 2. 統一的頁首 (Header)
    st.markdown(f"# 📊 {title}")
    st.markdown("---") # 分隔線
    
    # 3. 統一的側邊欄公共資訊
    with st.sidebar:
        st.image("static/images/177.jpg", width=100)
        st.write("👨‍💻 開發者：你的名字")
        st.write("📅 更新日期：2026-09")
        st.markdown("---")




def footer_template():
    """
    統一的頁尾 (Footer)
    """
    st.markdown("---")
    st.caption("© 2026 數據展示系統. All Rights Reserved. 隱私權與服務條款")




# 如果你希望程式碼看起來更像傳統框架的區塊套用
# 你可以利用 Python 的 with 語法（Context Manager）來做樣板：
@contextmanager
def page_layout(title="數據專案"):
    # 【前半段】：進入 with 時執行的公共頁首
    st.set_page_config(page_title=title, layout="wide")
    st.markdown(f"## 🚀 {title}")
    st.sidebar.title("選單導覽")
    
    yield # 💡 這裡代表中間「各個網頁自己寫的內容」會被塞進來的地方
    
    # 【後半段】：離開 with 時執行的公共頁尾
    st.markdown("---")
    st.caption("聯絡信箱：service@example.com")
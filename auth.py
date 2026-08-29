# -*- coding: utf-8 -*-
import streamlit as st
from supabase import Client

def render_login_sidebar(supabase: Client) -> dict:
    """從 Supabase 抓取使用者並在側邊欄渲染登入選單副程式"""
    try:
        users_data = supabase.table("users").select("*").execute().data
    except Exception as e:
        st.error("無法存取 users 資料表，請確認 Supabase 設定與授權。")
        st.stop()

    if not users_data:
        st.warning("資料庫中無使用者資料，請至 Supabase SQL Editor 寫入預設使用者。")
        st.stop()

    st.sidebar.divider()
    user_names = [u["name"] for u in users_data]
    current_user_name = st.sidebar.selectbox("👤 請選擇使用者登入：", user_names)
    
    current_user = next(u for u in users_data if u["name"] == current_user_name)
    
    role_title = "管理者 (媽媽)" if current_user['role'] == 'mom' else "學生 (複習與測驗)"
    st.sidebar.write(f"目前身分：**{role_title}**")
    
    return current_user, users_data

# -*- coding: utf-8 -*-
import streamlit as st
from collections import defaultdict
from supabase import Client

def render_grades_tab(users_data: list, supabase: Client, render_audio_fn, speech_rate: float, tts_engine: str):
    """【獨立副程式】查看與稽核學生單字學習成績頁籤"""
    st.subheader("📋 兩姐妹單字審核與過關設定")
    students = [u for u in users_data if u["role"] == "student"]
    
    if not students:
        st.info("目前系統中沒有學生資料。")
        return

    selected_student_name = st.selectbox("選擇學生：", [s["name"] for s in students])
    selected_student = next(s for s in students if s["name"] == selected_student_name)
    
    progress_data = supabase.table("user_word_progress") \
        .select("id, passed, correct_count, wrong_count, words(word, definition, example)") \
        .eq("user_id", selected_student["id"]).execute().data
    
    if not progress_data:
        st.info("該學生目前尚無單字練習紀錄。")
        return

    for item in progress_data:
        w_info = item["words"]
        if not w_info:
            continue
        col1, col2, col3, col4 = st.columns([2, 3, 2, 2])
        with col1:
            st.write(f"**{w_info['word']}**")
        with col2:
            st.write(f"答對: `{item.get('correct_count', 0)}` 次 | 答錯: `{item.get('wrong_count', 0)}` 次")
        with col3:
            is_passed = st.checkbox("通過審核", value=item["passed"], key=f"check_{item['id']}")
            if is_passed != item["passed"]:
                supabase.table("user_word_progress").update({"passed": is_passed}).eq("id", item["id"]).execute()
                st.rerun()
        with col4:
            render_audio_fn(w_info["word"], speech_rate, tts_engine)
        st.divider()


def delete_word_from_db(word_id: int, word_text: str, supabase: Client):
    """【刪除功能】刪除關聯進度紀錄與單字本體"""
    try:
        # 1. 刪除所有學生的該單字學習進度紀錄
        supabase.table("user_word_progress").delete().eq("word_id", word_id).execute()
        # 2. 刪除單字庫本體
        supabase.table("words").delete().eq("id", word_id).execute()
        st.success(f"🗑️ 單字 **{word_text}** 已成功從資料庫中刪除！")
        st.rerun()
    except Exception as e:
        st.error(f"刪除失敗：{e}")


def render_mom_interface(users_data: list, supabase: Client, fetch_word_fn, render_audio_fn, speech_rate: float, tts_engine: str):
    """【媽媽副程式入口】整合媽媽管理後台所有頁籤」"""
    st.header("👩‍🏫 媽媽管理後台")
    tab1, tab2, tab3 = st.tabs(["➕ 新增單字進資料庫", "📚 查看與管理單字庫", "📊 查看與稽核成績"])
    
    # 頁籤 1：新增單字
    with tab1:
        new_word = st.text_input("請輸入要新增的英文單字：").strip()
        if st.button("自動查詢並加入資料庫"):
            if new_word:
                details = fetch_word_fn(new_word)
                if details:
                    supabase.table("words").upsert(
                        {
                            "word": details["word"],
                            "definition": details["definition"],
                            "example": details["example"],
                            "phonetic": details["phonetic"]
                        },
                        on_conflict="word"
                    ).execute()
                    
                    words_in_db = supabase.table("words").select("id").eq("word", details["word"]).execute().data
                    if words_in_db:
                        w_id = words_in_db[0]["id"]
                        students = [u for u in users_data if u["role"] == "student"]
                        for s in students:
                            exist_record = supabase.table("user_word_progress").select("id").eq("user_id", s["id"]).eq("word_id", w_id).execute().data
                            if not exist_record:
                                supabase.table("user_word_progress").insert({
                                    "user_id": s["id"],
                                    "word_id": w_id,
                                    "passed": False
                                }).execute()
                            
                    st.success(f"單字 **{new_word}** 已成功更新/加入資料庫！")
                    st.markdown("**英英解釋（多重詞性與字義）：**")
                    st.markdown(details["definition"])
                    st.write("**經典例句：**", details["example"])
                    render_audio_fn(new_word, speech_rate, tts_engine)
                else:
                    st.error("查詢時發生預料外錯誤。")
            else:
                st.warning("請先輸入單字！")

    # 頁籤 2：查看與管理現有單字庫（含刪除功能）
    with tab2:
        st.subheader("📖 資料庫現有單字清單 (依字首 A-Z 分類)")
        try:
            all_words = supabase.table("words").select("*").order("word", desc=False).execute().data
            if all_words:
                st.write(f"目前資料庫共有 **{len(all_words)}** 個單字：")
                
                search_query = st.text_input("🔍 搜尋資料庫中的單字：", "").strip().lower()
                filtered_words = [w for w in all_words if search_query in w["word"].lower()] if search_query else all_words
                
                grouped_words = defaultdict(list)
                for w in filtered_words:
                    first_letter = w["word"][0].upper() if w["word"] else "#"
                    grouped_words[first_letter].append(w)
                
                st.divider()
                
                for letter in sorted(grouped_words.keys()):
                    letter_words = grouped_words[letter]
                    st.markdown(f"### 🔠 字母 {letter} `({len(letter_words)} 個單字)`")
                    
                    for w in letter_words:
                        raw_date = w.get("created_at", "")
                        formatted_date = raw_date[:10] if raw_date else "未知日期"
                        
                        expander_label = f"🔤 {w['word']}   `{w.get('phonetic', '')}`   📅 加入日期：{formatted_date}"
                        
                        with st.expander(expander_label):
                            st.markdown("**發音選項：**")
                            render_audio_fn(w["word"], speech_rate, tts_engine)
                            st.divider()
                            st.markdown("**英英與中文解釋：**")
                            st.markdown(w["definition"])
                            st.write("**經典例句：**", w["example"])
                            render_audio_fn(w["example"], speech_rate, tts_engine)
                            st.divider()
                            
                            # 🗑️ 新增：刪除單字按鈕
                            if st.button(f"🗑️ 刪除單字 '{w['word']}'", key=f"del_btn_{w['id']}"):
                                delete_word_from_db(w["id"], w["word"], supabase)
                    st.divider()
            else:
                st.info("資料庫目前尚無任何單字，請至「新增單字進資料庫」頁籤建立第一個單字！")
        except Exception as e:
            st.error("無法讀取單字庫列表，請確認 Supabase 權限設定。")

    # 頁籤 3：查看與稽核成績
    with tab3:
        render_grades_tab(users_data, supabase, render_audio_fn, speech_rate, tts_engine)

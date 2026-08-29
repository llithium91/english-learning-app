# -*- coding: utf-8 -*-
import streamlit as st
from supabase import Client

def render_student_review_tab(student_words: list, render_audio_fn, speech_rate: float, tts_engine: str):
    """【學生副程式】翻牌單字卡複習頁籤"""
    st.subheader("📖 翻牌單字卡複習")
    unpassed_words = [w for w in student_words if w.get("words") and not w["passed"]]
    
    if not unpassed_words:
        st.balloons()
        st.success("🎉 太棒了！妳目前所有的單字都已經順利通過審核過關囉！")
        return

    word_options = [w["words"]["word"] for w in unpassed_words]
    selected_w_name = st.selectbox("請選擇要複習的單字：", word_options)
    curr_w = next(w["words"] for w in unpassed_words if w["words"]["word"] == selected_w_name)
    
    st.markdown(f"### 🔤 單字： **{curr_w['word']}** `{curr_w.get('phonetic', '')}`")
    render_audio_fn(curr_w["word"], speech_rate, tts_engine)
    
    with st.expander("點擊展開完整英英解釋與例句"):
        st.markdown("**英英與中文解釋：**")
        st.markdown(curr_w["definition"])
        st.write("**經典例句：**", curr_w["example"])
        render_audio_fn(curr_w["example"], speech_rate, tts_engine)


def render_spelling_quiz(q_word_item: dict, p_id: int, q_idx: int, supabase: Client, render_audio_fn, speech_rate: float, tts_engine: str):
    """【學生副程式】鍵盤拼字答題子模組"""
    input_key = f"quiz_input_{q_idx}"
    user_input = st.text_input("請拼寫出該英文單字：", key=input_key).strip().lower()
    
    if st.button("提交答案", key=f"btn_submit_{q_idx}"):
        if user_input == q_word_item["word"].lower():
            st.success("🎉 完全正確！太厲害了！")
            render_audio_fn(q_word_item["word"], speech_rate, tts_engine)
            
            curr_record = supabase.table("user_word_progress").select("correct_count").eq("id", p_id).execute().data
            curr_correct = (curr_record[0].get("correct_count", 0) or 0) if curr_record else 0
            supabase.table("user_word_progress").update({"correct_count": curr_correct + 1}).eq("id", p_id).execute()
        else:
            st.error(f"❌ 答錯囉！正確答案是：**{q_word_item['word']}**")
            render_audio_fn(q_word_item["word"], speech_rate, tts_engine)
            
            curr_record = supabase.table("user_word_progress").select("wrong_count").eq("id", p_id).execute().data
            curr_wrong = (curr_record[0].get("wrong_count", 0) or 0) if curr_record else 0
            supabase.table("user_word_progress").update({"wrong_count": curr_wrong + 1}).eq("id", p_id).execute()


def render_speaking_quiz(q_word_item: dict, render_stt_fn, render_audio_fn, speech_rate: float, tts_engine: str):
    """【學生副程式】口說發音答題子模組"""
    st.write("請點擊下方按鈕並朗讀出該單字：")
    render_stt_fn(q_word_item["word"])
    st.write("聽標準發音對照：")
    render_audio_fn(q_word_item["word"], speech_rate, tts_engine)


def render_student_quiz_tab(student_words: list, supabase: Client, render_audio_fn, render_stt_fn, speech_rate: float, tts_engine: str):
    """【學生副程式】單字測驗特訓主頁籤"""
    st.subheader("🎯 英英辨析單字測驗")
    
    quiz_mode = st.radio("選擇測驗範圍：", ["本週未通過生字", "資料庫全單字庫測驗"], horizontal=True)
    
    valid_student_words = [w for w in student_words if w.get("words")]
    unpassed_words = [w for w in student_words if w.get("words") and not w["passed"]]
    target_list = unpassed_words if quiz_mode == "本週未通過生字" else valid_student_words
    
    if not target_list:
        st.info("目前範圍內沒有可測驗的單字。")
        return

    if "quiz_index" not in st.session_state:
        st.session_state.quiz_index = 0

    q_idx = st.session_state.quiz_index % len(target_list)
    q_item = target_list[q_idx]
    q_word_item = q_item["words"]
    p_id = q_item["id"]

    st.markdown(f"**第 {q_idx + 1} / {len(target_list)} 題**")
    st.info("💡 **題目（解釋提示）：**")
    st.markdown(q_word_item['definition'])

    answer_type = st.radio("選擇答題方式：", ["鍵盤輸入拼字", "口說發音答題"], horizontal=True, key=f"ans_type_{q_idx}")

    st.divider()

    if answer_type == "鍵盤輸入拼字":
        render_spelling_quiz(q_word_item, p_id, q_idx, supabase, render_audio_fn, speech_rate, tts_engine)
    else:
        render_speaking_quiz(q_word_item, render_stt_fn, render_audio_fn, speech_rate, tts_engine)

    st.divider()
    if st.button("下一題 ➡️", key="btn_next_quiz"):
        st.session_state.quiz_index += 1
        st.rerun()


def render_student_interface(current_user: dict, supabase: Client, render_audio_fn, render_stt_fn, speech_rate: float, tts_engine: str):
    """【學生副程式入口】整合學生所有功能頁籤"""
    st.header(f"👧 {current_user['name']} 的單字學習小天地")
    
    student_words = supabase.table("user_word_progress") \
        .select("id, passed, correct_count, wrong_count, words(id, word, definition, example, phonetic)") \
        .eq("user_id", current_user["id"]).execute().data
    
    tab1, tab2 = st.tabs(["🎴 單字卡卡片複習", "📝 單字測驗特訓"])
    
    with tab1:
        render_student_review_tab(student_words, render_audio_fn, speech_rate, tts_engine)
    with tab2:
        render_student_quiz_tab(student_words, supabase, render_audio_fn, render_stt_fn, speech_rate, tts_engine)

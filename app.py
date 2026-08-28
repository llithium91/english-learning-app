# -*- coding: utf-8 -*-
import os
import sys
import io
import base64

# 設定系統環境變數以支援 UTF-8 編碼
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["LC_ALL"] = "en_US.UTF-8"
os.environ["LANG"] = "en_US.UTF-8"

import streamlit as st
import requests
from supabase import create_client, Client
from gtts import gTTS

# --- 1. 初始化 Supabase 連線 ---
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_supabase()
except Exception as e:
    st.error("⚠️ Supabase 連線失敗，請檢查 Streamlit Secrets 設定。")
    st.stop()

# --- 2. 側邊欄控制項：語音模組與語速拉霸 ---
st.sidebar.title("⚙️ 播放與系統設定")

tts_engine = st.sidebar.radio(
    "🎙️ 選擇語音發音模組：",
    ["Web Speech (裝置內建/無延遲)", "Google TTS (雲端高清/發音標準)"]
)

speech_rate = st.sidebar.slider(
    "🎛️ 調整播放語速：",
    min_value=0.5,
    max_value=1.5,
    value=0.85,
    step=0.05,
    help="0.5x 為慢速朗讀，1.0x 為正常語速，適合女兒練習聽力與跟讀。"
)

# --- 3. 核心功能：發音渲染器與字典 API ---
def render_audio_player(text: str, rate: float, engine: str):
    """根據選定的模組與語速渲染 HTML5 發音播放器"""
    clean_text = text.replace("'", "\\'").replace('"', '\\"').replace("\n", " ")
    
    # 方案 A：Google TTS (雲端產生語音音訊檔)
    if "Google TTS" in engine:
        try:
            tts = gTTS(text=text, lang='en', slow=(rate < 0.8))
            fp = io.BytesIO()
            tts.write_to_fp(fp)
            fp.seek(0)
            audio_b64 = base64.b64encode(fp.read()).decode()
            
            html_code = f"""
            <audio id="audio_{hash(text)}" src="data:audio/mp3;base64,{audio_b64}"></audio>
            <button onclick="document.getElementById('audio_{hash(text)}').play()" 
                    style="padding: 7px 15px; border-radius: 8px; border: 1px solid #2196F3; background-color: #e3f2fd; cursor: pointer; font-size: 14px; font-weight: bold; color: #0d47a1;">
                🔊 播放發音 (Google TTS - {rate}x)
            </button>
            """
            st.components.v1.html(html_code, height=45)
            return
        except Exception:
            st.warning("Google TTS 產生失敗，自動降級切換至 Web Speech 發音。")
            
    # 方案 B：Web Speech API (預設，原生發音 + 動態語速控制)
    html_code = f"""
    <button onclick="speak('{clean_text}')" 
            style="padding: 7px 15px; border-radius: 8px; border: 1px solid #4CAF50; background-color: #f1f9f1; cursor: pointer; font-size: 14px; font-weight: bold; color: #2e7d32;">
        🔊 播放發音 (Web Speech - {rate}x)
    </button>
    <script>
    function speak(text) {{
        window.speechSynthesis.cancel(); // 停止先前的發音
        var msg = new SpeechSynthesisUtterance(text);
        msg.lang = 'en-US';
        msg.rate = {rate};  // 套用側邊欄拉霸的語速設定
        msg.pitch = 1.0;
        window.speechSynthesis.speak(msg);
    }}
    </script>
    """
    st.components.v1.html(html_code, height=45)

def fetch_word_details(word: str):
    """呼叫 Free Dictionary API 取得所有詞性的英英解釋與例句"""
    api_url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word.strip().lower()}"
    try:
        res = requests.get(api_url, timeout=5)
        if res.status_code == 200:
            data = res.json()[0]
            phonetic = data.get("phonetic", "")
            meanings = data.get("meanings", [])
            
            definitions_list = []
            example = ""
            
            for m in meanings:
                part_of_speech = m.get("partOfSpeech", "")
                defs = m.get("definitions", [])
                
                sub_defs = []
                for idx, d in enumerate(defs[:3]):
                    def_text = d.get("definition", "")
                    if def_text:
                        sub_defs.append(f"({idx+1}) {def_text}")
                    if not example and d.get("example"):
                        example = d.get("example")
                        
                if sub_defs:
                    definitions_list.append(f"📌 **[{part_of_speech.upper()}]**\n" + "\n".join(sub_defs))
            
            full_definition = "\n\n".join(definitions_list) if definitions_list else "無提供英英解釋"
            final_example = example if example else "無提供例句"
            
            return {
                "word": word.strip().lower(), 
                "phonetic": phonetic, 
                "definition": full_definition, 
                "example": final_example
            }
    except Exception:
        pass
    return None

def render_speech_recognizer(target_word: str):
    """利用 Web Speech API 進行網頁端即時口說辨識 (STT)"""
    clean_target = target_word.lower().replace("'", "\\'").replace('"', '\\"')
    html_code = f"""
    <div style="margin-top: 5px;">
        <button id="start-btn" onclick="startDictation()" style="padding: 8px 16px; border-radius: 8px; background-color: #2196F3; color: white; border: none; cursor: pointer; font-weight: bold;">
            🎤 開始口說答題
        </button>
        <p id="result-text" style="font-weight: bold; margin-top: 10px; color: #333; font-size: 15px;">尚未錄音</p>
    </div>
    <script>
    function startDictation() {{
        if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {{
            var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            var recognition = new SpeechRecognition();
            recognition.lang = 'en-US';
            recognition.interimResults = false;
            
            document.getElementById('result-text').innerText = "聆聽中...請朗讀單字";
            document.getElementById('result-text').style.color = "#FF9800";
            
            recognition.onresult = function(event) {{
                var spokenText = event.results[0][0].transcript.toLowerCase().trim();
                var target = "{clean_target}";
                if (spokenText === target) {{
                    document.getElementById('result-text').innerText = "✅ 正確！妳說的是: " + spokenText;
                    document.getElementById('result-text').style.color = "#4CAF50";
                }} else {{
                    document.getElementById('result-text').innerText = "❌ 答案不符。妳說的是: " + spokenText;
                    document.getElementById('result-text').style.color = "#F44336";
                }}
            }};
            
            recognition.onerror = function(event) {{
                document.getElementById('result-text').innerText = "辨識失敗或收音不清楚，請再試一次。";
                document.getElementById('result-text').style.color = "#F44336";
            }};
            
            recognition.start();
        }} else {{
            alert("您的瀏覽器不支援語音辨識，請使用 Chrome 或 Edge 瀏覽器。");
        }}
    }}
    </script>
    """
    st.components.v1.html(html_code, height=90)

# --- 4. UI 主頁面與角色選擇 ---
st.set_page_config(page_title="英單特訓王", page_icon="🔤", layout="wide")
st.title("🔤 英文單字雲端特訓平台")

try:
    users_data = supabase.table("users").select("*").execute().data
except Exception as e:
    st.error("無法存取 users 資料表，請確認已在 Supabase 執行 SQL 建表指令與授權。")
    st.stop()

if not users_data:
    st.warning("資料庫中無使用者資料，請確認 Supabase SQL Editor 是否已寫入預設使用者。")
    st.stop()

st.sidebar.divider()
user_names = [u["name"] for u in users_data]
current_user_name = st.sidebar.selectbox("👤 請選擇使用者登入：", user_names)
current_user = next(u for u in users_data if u["name"] == current_user_name)

st.sidebar.write(f"目前身分：**{'管理者 (媽媽)' if current_user['role'] == 'mom' else '學生 (複習與測驗)'}**")

# --- 5. 媽媽介面 (管理者) ---
if current_user["role"] == "mom":
    st.header("👩‍🏫 媽媽管理後台")
    tab1, tab2, tab3 = st.tabs(["➕ 新增單字進資料庫", "📚 查看現有單字庫", "📊 查看與稽核成績"])
    
    with tab1:
        new_word = st.text_input("請輸入要新增的英文單字：").strip()
        if st.button("自動查詢並加入資料庫"):
            if new_word:
                details = fetch_word_details(new_word)
                if details:
                    # 加入 on_conflict="word" 避免重複單字引發 APIError 崩潰
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
                    render_audio_player(new_word, speech_rate, tts_engine)
                else:
                    st.error("查無此單字，請確認拼字是否正確。")
            else:
                st.warning("請先輸入單字！")

    # 查看現有單字庫
    with tab2:
        st.subheader("📖 資料庫現有單字清單")
        try:
            all_words = supabase.table("words").select("*").order("id", desc=True).execute().data
            if all_words:
                st.write(f"目前資料庫共有 **{len(all_words)}** 個單字：")
                
                # 搜尋過濾功能
                search_query = st.text_input("🔍 搜尋資料庫中的單字：", "").strip().lower()
                filtered_words = [w for w in all_words if search_query in w["word"].lower()] if search_query else all_words
                
                st.divider()
                for w in filtered_words:
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.markdown(f"### 🔤 **{w['word']}** `{w.get('phonetic', '')}`")
                    with c2:
                        render_audio_player(w["word"], speech_rate, tts_engine)
                        
                    with st.expander("展開查看詳細內容"):
                        st.markdown("**英英解釋：**")
                        st.markdown(w["definition"])
                        st.write("**例句：**", w["example"])
                        render_audio_player(w["example"], speech_rate, tts_engine)
                    st.divider()
            else:
                st.info("資料庫目前尚無任何單字，請至「新增單字進資料庫」頁籤建立第一個單字！")
        except Exception as e:
            st.error("無法讀取單字庫列表，請確認 Supabase 權限設定。")
                    
    with tab3:
        st.subheader("📋 兩姐妹單字審核與過關設定")
        students = [u for u in users_data if u["role"] == "student"]
        if students:
            selected_student_name = st.selectbox("選擇學生：", [s["name"] for s in students])
            selected_student = next(s for s in students if s["name"] == selected_student_name)
            
            progress_data = supabase.table("user_word_progress").select("id, passed, correct_count, wrong_count, words(word, definition, example)").eq("user_id", selected_student["id"]).execute().data
            
            if progress_data:
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
                        render_audio_player(w_info["word"], speech_rate, tts_engine)
                    st.divider()
            else:
                st.info("該學生目前尚無單字練習紀錄。")

# --- 6. 姊姊/妹妹介面 (學生) ---
else:
    st.header(f"👧 {current_user['name']} 的單字學習小天地")
    tab1, tab2 = st.tabs(["🎴 單字卡卡片複習", "📝 單字測驗特訓"])
    
    student_words = supabase.table("user_word_progress").select("id, passed, correct_count, wrong_count, words(id, word, definition, example, phonetic)").eq("user_id", current_user["id"]).execute().data
    
    with tab1:
        st.subheader("📖 翻牌單字卡複習")
        unpassed_words = [w for w in student_words if w.get("words") and not w["passed"]]
        if not unpassed_words:
            st.balloons()
            st.success("🎉 太棒了！妳目前所有的單字都已經順利通過審核過關囉！")
        else:
            word_options = [w["words"]["word"] for w in unpassed_words]
            selected_w_name = st.selectbox("請選擇要複習的單字：", word_options)
            curr_w = next(w["words"] for w in unpassed_words if w["words"]["word"] == selected_w_name)
            
            st.markdown(f"### 🔤 單字： **{curr_w['word']}** `{curr_w.get('phonetic', '')}`")
            render_audio_player(curr_w["word"], speech_rate, tts_engine)
            
            with st.expander("點擊展開完整英英解釋與例句"):
                st.markdown("**英英解釋（包含所有詞性）：**")
                st.markdown(curr_w["definition"])
                st.write("**經典例句：**", curr_w["example"])
                render_audio_player(curr_w["example"], speech_rate, tts_engine)

    with tab2:
        st.subheader("🎯 英英辨析單字測驗")
        quiz_mode = st.radio("選擇測驗範圍：", ["本週未通過生字", "資料庫全單字庫測驗"], horizontal=True)
        
        valid_student_words = [w for w in student_words if w.get("words")]
        target_list = unpassed_words if quiz_mode == "本週未通過生字" else valid_student_words
        
        if not target_list:
            st.info("目前範圍內沒有可測驗的單字。")
        else:
            if "quiz_index" not in st.session_state:
                st.session_state.quiz_index = 0
                
            q_idx = st.session_state.quiz_index % len(target_list)
            q_item = target_list[q_idx]
            q_word_item = q_item["words"]
            p_id = q_item["id"]
            
            st.info("💡 **題目（英英解釋）：**")
            st.markdown(q_word_item['definition'])
            
            answer_type = st.radio("選擇答題方式：", ["鍵盤輸入拼字", "口說發音答題"], horizontal=True)
            
            if answer_type == "鍵盤輸入拼字":
                user_input = st.text_input("請拼寫出該英文單字：", key=f"quiz_input_{q_idx}").strip().lower()
                if st.button("提交答案"):
                    if user_input == q_word_item["word"].lower():
                        st.success("🎉 完全正確！太厲害了！")
                        render_audio_player(q_word_item["word"], speech_rate, tts_engine)
                        curr_correct = q_item.get("correct_count", 0) or 0
                        supabase.table("user_word_progress").update({"correct_count": curr_correct + 1}).eq("id", p_id).execute()
                    else:
                        st.error(f"❌ 答錯囉！正確答案是：**{q_word_item['word']}**")
                        render_audio_player(q_word_item["word"], speech_rate, tts_engine)
                        curr_wrong = q_item.get("wrong_count", 0) or 0
                        supabase.table("user_word_progress").update({"wrong_count": curr_wrong + 1}).eq("id", p_id).execute()
                        
            else:  # 口說答題
                st.write("請點擊下方按鈕，朗讀出該單字：")
                render_speech_recognizer(q_word_item["word"])
                st.write("聽正確發音：")
                render_audio_player(q_word_item["word"], speech_rate, tts_engine)
                
            st.divider()
            if st.button("下一題 ➡️"):
                st.session_state.quiz_index += 1
                st.rerun()

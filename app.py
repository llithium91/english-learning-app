# -*- coding: utf-8 -*-
import os
import sys
import io
import base64
import json
from collections import defaultdict

# 設定系統環境變數以支援 UTF-8 編碼
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["LC_ALL"] = "en_US.UTF-8"
os.environ["LANG"] = "en_US.UTF-8"

import streamlit as st
import requests
from supabase import create_client, Client
from gtts import gTTS

# --- 匯入自訂子模組 ---
from auth import render_login_sidebar
from quiz import render_student_interface

# 嘗試載入 google-genai
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# --- 1. 初始化 Supabase 與 Gemini 連線 ---
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

gemini_client = None
if HAS_GENAI and "GEMINI_API_KEY" in st.secrets and st.secrets["GEMINI_API_KEY"]:
    try:
        gemini_client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    except Exception as e:
        st.warning("⚠️ Gemini API 初始化失敗，將降級使用傳統字典 API。")

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

# --- 3. 核心工具函式：發音與 API ---
@st.cache_data(show_spinner=False, max_entries=500, ttl=86400)
def get_gtts_audio_b64(text: str, slow: bool) -> str:
    tts = gTTS(text=text, lang='en', slow=slow)
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    fp.seek(0)
    return base64.b64encode(fp.read()).decode()

def render_audio_player(text: str, rate: float, engine: str):
    clean_text = text.replace("'", "\\'").replace('"', '\\"').replace("\n", " ")
    
    if "Google TTS" in engine:
        try:
            audio_b64 = get_gtts_audio_b64(text, rate < 0.8)
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
            st.warning("Google TTS 請求頻繁被擋，已自動切換至 Web Speech 發音。")
            
    html_code = f"""
    <button onclick="speak('{clean_text}')" 
            style="padding: 7px 15px; border-radius: 8px; border: 1px solid #4CAF50; background-color: #f1f9f1; cursor: pointer; font-size: 14px; font-weight: bold; color: #2e7d32;">
        🔊 播放發音 (Web Speech - {rate}x)
    </button>
    <script>
    function speak(text) {{
        window.speechSynthesis.cancel();
        var msg = new SpeechSynthesisUtterance(text);
        msg.lang = 'en-US';
        msg.rate = {rate};
        msg.pitch = 1.0;
        window.speechSynthesis.speak(msg);
    }}
    </script>
    """
    st.components.v1.html(html_code, height=45)

def fetch_word_details(word: str):
    clean_word = word.strip().lower()

    if gemini_client:
        try:
            prompt = f"""
            Please provide dictionary details for the English word: "{clean_word}".
            Return the result ONLY in strict JSON format with the following keys:
            - "word": string (lowercase)
            - "phonetic": string (IPA phonetic notation)
            - "definition": string (Clear English definition with parts of speech and Traditional Chinese translations. Format nicely using Markdown with 📌 for parts of speech)
            - "example": string (A natural, authentic, context-rich example sentence showing how the word is really used in modern English)
            """
            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            res_json = json.loads(response.text)
            return {
                "word": clean_word,
                "phonetic": res_json.get("phonetic", f"/{clean_word}/"),
                "definition": res_json.get("definition", "無提供解釋"),
                "example": res_json.get("example", f"Please practice using the word '{clean_word}'.")
            }
        except Exception as e:
            st.warning(f"Gemini API 查詢失敗 ({e})，切換至傳統字典 API。")

    api_url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{clean_word}"
    try:
        res = requests.get(api_url, timeout=5)
        if res.status_code == 200:
            data = res.json()[0]
            phonetic = data.get("phonetic", "")
            meanings = data.get("meanings", [])
            
            definitions_list = []
            example = ""
            first_pos = ""
            
            for m in meanings:
                part_of_speech = m.get("partOfSpeech", "")
                if not first_pos:
                    first_pos = part_of_speech.upper()
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
            
            if example:
                final_example = example
            else:
                if "ADJ" in first_pos or "ADJECTIVE" in first_pos:
                    final_example = f"His {clean_word} tone of voice made everyone feel quiet."
                elif "NOUN" in first_pos or "N" in first_pos:
                    final_example = f"The textbook explained the meaning of '{clean_word}' clearly."
                elif "VERB" in first_pos or "V" in first_pos:
                    final_example = f"They tried to {clean_word} as instructed by the teacher."
                else:
                    final_example = f"The passage described the situation using the word '{clean_word}'."
            
            return {
                "word": clean_word, 
                "phonetic": phonetic, 
                "definition": full_definition, 
                "example": final_example
            }
    except Exception:
        pass

    return {
        "word": clean_word,
        "phonetic": f"/{clean_word}/",
        "definition": f"📌 **[WORD]**\n(1) A vocabulary word: {clean_word}.",
        "example": f"The passage described the setting using the word '{clean_word}'."
    }

def render_speech_recognizer(target_word: str):
    clean_target = target_word.lower().replace("'", "\\'").replace('"', '\\"')
    html_code = f"""
    <div style="margin-top: 5px;">
        <button id="start-btn" onclick="startDictation()" style="padding: 10px 18px; border-radius: 8px; background-color: #2196F3; color: white; border: none; cursor: pointer; font-weight: bold; font-size: 15px;">
            🎤 開始口說答題
        </button>
        <p id="result-text" style="font-weight: bold; margin-top: 10px; color: #333; font-size: 15px;">尚未錄音 (點擊按鈕後請朗讀單字)</p>
    </div>
    <script>
    function startDictation() {{
        var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {{
            alert("您的瀏覽器不支援語音辨識。iPad/iPhone 請使用 iOS 14.5 以上的 Safari，Mac 請使用 Chrome 或 Safari。");
            return;
        }}

        var recognition = new SpeechRecognition();
        recognition.lang = 'en-US';
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;

        var resultEl = document.getElementById('result-text');
        resultEl.innerText = "🎙️ 聆聽中...請清楚朗讀單字";
        resultEl.style.color = "#FF9800";

        recognition.onresult = function(event) {{
            var spokenText = event.results[0][0].transcript.toLowerCase().trim();
            spokenText = spokenText.replace(/[.,?!]/g, "");
            var target = "{clean_target}";
            
            if (spokenText === target || spokenText.includes(target)) {{
                resultEl.innerText = "✅ 正確！妳說的是: " + spokenText;
                resultEl.style.color = "#4CAF50";
            }} else {{
                resultEl.innerText = "❌ 答案不符。妳說的是: " + spokenText;
                resultEl.style.color = "#F44336";
            }}
        }};

        recognition.onerror = function(event) {{
            if (event.error === 'not-allowed') {{
                resultEl.innerText = "🚫 麥克風權限被拒絕！請開啟權限。";
            }} else if (event.error === 'no-speech') {{
                resultEl.innerText = "⚠️ 沒有偵測到聲音，請再試一次。";
            }} else {{
                resultEl.innerText = "❌ 辨識失敗 (" + event.error + ")，請再試一次。";
            }}
            resultEl.style.color = "#F44336";
        }};

        try {{
            recognition.start();
        }} catch(e) {{
            resultEl.innerText = "⚠️ 錄音啟動中，請再點一次按鈕。";
        }}
    }}
    </script>
    """
    st.components.v1.html(html_code, height=100)

def render_mom_interface(users_data: list):
    """【媽媽副程式入口】"""
    st.header("👩‍🏫 媽媽管理後台")
    tab1, tab2, tab3 = st.tabs(["➕ 新增單字進資料庫", "📚 查看現有單字庫", "📊 查看與稽核成績"])
    
    with tab1:
        new_word = st.text_input("請輸入要新增的英文單字：").strip()
        if st.button("自動查詢並加入資料庫"):
            if new_word:
                details = fetch_word_details(new_word)
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
                    render_audio_player(new_word, speech_rate, tts_engine)
                else:
                    st.error("查詢時發生預料外錯誤。")
            else:
                st.warning("請先輸入單字！")

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
                            render_audio_player(w["word"], speech_rate, tts_engine)
                            st.divider()
                            st.markdown("**英英與中文解釋：**")
                            st.markdown(w["definition"])
                            st.write("**經典例句：**", w["example"])
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

# --- 4. 主流程 (Main Flow) ---

st.set_page_config(page_title="英單特訓王", page_icon="🔤", layout="wide")
st.title("🔤 英文單字雲端特訓平台")

# 調用 auth.py 副程式處理登入邏輯
current_user, users_data = render_login_sidebar(supabase)

# 根據角色分流執行專屬副程式
if current_user["role"] == "mom":
    render_mom_interface(users_data)
else:
    # 調用 quiz.py 副程式處理學生端測驗介面
    render_student_interface(
        current_user=current_user, 
        supabase=supabase, 
        render_audio_fn=render_audio_player, 
        render_stt_fn=render_speech_recognizer, 
        speech_rate=speech_rate, 
        tts_engine=tts_engine
    )

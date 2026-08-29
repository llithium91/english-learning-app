# -*- coding: utf-8 -*-
import os
import sys
import io
import base64
import json

# 設定系統環境變數以支援 UTF-8 編碼
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["LC_ALL"] = "en_US.UTF-8"
os.environ["LANG"] = "en_US.UTF-8"

import streamlit as st
import requests
from supabase import create_client, Client
from gtts import gTTS

# --- 匯入專案子模組 ---
from auth import render_login_sidebar
from quiz import render_student_interface
from admin import render_mom_interface

# 嘗試載入 groq 套件
try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False

# --- 1. 初始化 Supabase 與 Groq AI 連線 ---
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

# 初始化 Groq AI Client
groq_client = None
if HAS_GROQ and "GROQ_API_KEY" in st.secrets and st.secrets["GROQ_API_KEY"]:
    try:
        groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    except Exception as e:
        st.warning(f"⚠️ Groq API 初始化失敗 ({e})，將降級使用傳統字典 API。")

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

# --- 3. 核心工具函式：發音播放器與 AI 單字解析 ---
@st.cache_data(show_spinner=False, max_entries=500, ttl=86400)
def get_gtts_audio_b64(text: str, slow: bool) -> str:
    """快取 gTTS 生成結果"""
    tts = gTTS(text=text, lang='en', slow=slow)
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    fp.seek(0)
    return base64.b64encode(fp.read()).decode()

def render_audio_player(text: str, rate: float, engine: str):
    """根據選定的模組與語速渲染 HTML5 發音播放器"""
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
    """使用 Groq AI 配合多模型自動備援機制生成自然例句與繁中/英英解釋"""
    clean_word = word.strip().lower()

    # --- 優先方案：Groq AI (含動態多模型備援) ---
    if groq_client:
        # 備選模型清單：若首選失敗會順序嘗試後續模型
        candidate_models = [
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-20b",
            "llama-3.1-8b-instant",
            "groq/compound"
        ]
        
        prompt = f"""
        Please provide dictionary details for the English word: "{clean_word}".
        Return the result ONLY in strict JSON format with the following keys:
        - "word": string (lowercase)
        - "phonetic": string (IPA phonetic notation)
        - "definition": string (Clear English definition with parts of speech and Traditional Chinese translations. Format nicely using Markdown with 📌 for parts of speech)
        - "example": string (A natural, authentic, context-rich example sentence showing how the word is really used in modern English)

        Example JSON format:
        {{
            "word": "abettor",
            "phonetic": "/əˈbet.ər/",
            "definition": "📌 **[NOUN]** 教唆者；幫兇\\n(1) A person who encourages or assists someone to do something wrong, in particular to commit a crime.",
            "example": "He was charged as an abettor in the robbery."
        }}
        """

        last_error = ""
        for model_name in candidate_models:
            try:
                response = groq_client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"}
                )
                res_json = json.loads(response.choices[0].message.content)
                return {
                    "word": clean_word,
                    "phonetic": res_json.get("phonetic", f"/{clean_word}/"),
                    "definition": res_json.get("definition", "無提供解釋"),
                    "example": res_json.get("example", f"Please practice using the word '{clean_word}'.")
                }
            except Exception as e:
                last_error = str(e)
                continue # 嘗試下一個模型

        st.error(f"⚠️ Groq 所有模型呼叫失敗，最後錯誤：{last_error}")
    else:
        if not HAS_GROQ:
            st.warning("⚠️ 系統未偵測到 groq 套件，請確認 requirements.txt 已寫入 groq>=0.4.0")
        elif "GROQ_API_KEY" not in st.secrets:
            st.warning("⚠️ Streamlit Secrets 中未找到 GROQ_API_KEY 設定。")

    # --- 備援方案 1：Free Dictionary API ---
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

    # --- 備援方案 2：保底罐頭 ---
    return {
        "word": clean_word,
        "phonetic": f"/{clean_word}/",
        "definition": f"📌 **[WORD]**\n(1) A vocabulary word: {clean_word}.",
        "example": f"The passage described the setting using the word '{clean_word}'."
    }

def render_speech_recognizer(target_word: str):
    """Web Speech API 網頁端口說辨識 (STT) 模組"""
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

# --- 4. 主流程 (Main Flow) ---

st.set_page_config(page_title="英單特訓王", page_icon="🔤", layout="wide")
st.title("🔤 英文單字雲端特訓平台")

# 1. 執行登入模組 (來自 auth.py)
current_user, users_data = render_login_sidebar(supabase)

# 2. 權限與介面分流 (來自 admin.py 與 quiz.py)
if current_user["role"] == "mom":
    render_mom_interface(
        users_data=users_data, 
        supabase=supabase, 
        fetch_word_fn=fetch_word_details, 
        render_audio_fn=render_audio_player, 
        speech_rate=speech_rate, 
        tts_engine=tts_engine
    )
else:
    render_student_interface(
        current_user=current_user, 
        supabase=supabase, 
        render_audio_fn=render_audio_player, 
        render_stt_fn=render_speech_recognizer, 
        speech_rate=speech_rate, 
        tts_engine=tts_engine
    )

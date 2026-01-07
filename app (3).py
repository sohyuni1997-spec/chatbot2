import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from datetime import datetime, timedelta
import plotly.graph_objects as go
import re
import base64
import os
from pathlib import Path

# 분리된 모듈에서 함수 임포트
from legacy import fetch_db_data_legacy, query_gemini_ai_legacy
from hybrid import ask_professional_scheduler

# ==================== 환경 설정 ====================
st.set_page_config(page_title="orcHatStra", page_icon="🎯", layout="wide")


# ==================== 이미지 Base64 로더 ====================
def get_base64_of_bin_file(bin_file: str):
    """이미지 파일을 Base64로 인코딩 (경로 후보를 여러 개로 시도)"""
    candidates = [
        Path(bin_file),
        Path(__file__).resolve().parent / bin_file,
        Path.cwd() / bin_file,
    ]

    for p in candidates:
        try:
            if p.exists():
                return base64.b64encode(p.read_bytes()).decode("utf-8")
        except Exception:
            continue
    return None


# 로고, AI 아바타, 사용자 아바타 이미지 로드
logo_base64 = get_base64_of_bin_file("HSE.svg")
ai_avatar_base64 = get_base64_of_bin_file("ai 아바타.png")
user_avatar_base64 = get_base64_of_bin_file("이력서 사진.v카툰.png")


# ==================== ✅ (추가) 사이드바 DEBUG ====================
with st.sidebar.expander("🛠️ DEBUG (파일 로딩)", expanded=True):
    st.write("cwd:", os.getcwd())
    st.write("__file__:", __file__)
    st.write("app dir:", str(Path(__file__).resolve().parent))

    # 현재 폴더 파일 일부 보기
    try:
        st.write("cwd files:", sorted(os.listdir(os.getcwd()))[:80])
    except Exception as e:
        st.write("cwd list error:", e)

    # app.py가 있는 폴더 파일 일부 보기
    try:
        app_dir = Path(__file__).resolve().parent
        st.write("app dir files:", sorted([p.name for p in app_dir.iterdir()])[:80])
    except Exception as e:
        st.write("app dir list error:", e)

    # 각 파일이 실제로 존재하는지 체크
    targets = ["HSE.svg", "ai 아바타.png", "이력서 사진.v카툰.png"]
    for f in targets:
        p1 = Path(f)
        p2 = Path(__file__).resolve().parent / f
        p3 = Path(os.getcwd()) / f
        st.write(f"--- {f} ---")
        st.write("exists (rel):", p1.exists(), str(p1))
        st.write("exists (appdir):", p2.exists(), str(p2))
        st.write("exists (cwd):", p3.exists(), str(p3))

    st.write("logo loaded:", bool(logo_base64), "len:", 0 if not logo_base64 else len(logo_base64))
    st.write("ai avatar loaded:", bool(ai_avatar_base64), "len:", 0 if not ai_avatar_base64 else len(ai_avatar_base64))
    st.write("user avatar loaded:", bool(user_avatar_base64), "len:", 0 if not user_avatar_base64 else len(user_avatar_base64))


# ==================== 스타일/CSS ====================
st.markdown(
    f"""
<style>
    :root {{
        --bg-primary: #F5F5F7;
        --bg-secondary: #FFFFFF;
        --text-primary: #000000;
        --text-secondary: #1C1C1E;
        --border-color: #E5E5EA;
        --shadow-light: rgba(0, 0, 0, 0.1);
        --shadow-medium: rgba(0, 0, 0, 0.15);
        --user-gradient-start: #007AFF;
        --user-gradient-end: #0051D5;
        --ai-gradient-start: #34C759;
        --ai-gradient-end: #30D158;
        --input-bg: #FFFFFF;
        --header-bg: #FFFFFF;
        --header-text: #000000;
    }}

    @media (prefers-color-scheme: dark) {{
        :root {{
            --bg-primary: #000000;
            --bg-secondary: #1C1C1E;
            --text-primary: #FFFFFF;
            --text-secondary: #F5F5F7;
            --border-color: #38383A;
            --shadow-light: rgba(255, 255, 255, 0.1);
            --shadow-medium: rgba(255, 255, 255, 0.15);
            --user-gradient-start: #0A84FF;
            --user-gradient-end: #0066CC;
            --ai-gradient-start: #30D158;
            --ai-gradient-end: #28A745;
            --input-bg: #1C1C1E;
            --header-bg: #1C1C1E;
            --header-text: #FFFFFF;
        }}
    }}

    .stApp {{
        background-color: var(--bg-primary);
    }}

    .main {{
        background-color: var(--bg-primary);
        padding-top: 100px !important;
    }}

    [data-testid="stHeader"] {{
        display: none;
    }}

    .fixed-header {{
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        height: 80px;
        background-color: var(--header-bg);
        border-bottom: 1px solid var(--border-color);
        z-index: 9999;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0 40px;
        box-shadow: 0 2px 10px var(--shadow-light);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
    }}

    .header-content {{
        width: 100%;
        max-width: 1400px;
        display: flex;
        align-items: center;
        gap: 20px;
    }}

    .header-logo {{
        height: 50px;
        width: auto;
        display: block;
    }}

    .header-title {{
        color: var(--header-text);
        font-weight: 800;
        font-size: 2.5rem;
        letter-spacing: -1.5px;
        font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif;
        margin: 0;
    }}

    [data-testid="stChatMessage"] {{
        display: none !important;
    }}

    .chat-container {{
        max-width: 900px;
        margin: 0 auto;
        padding: 20px;
    }}

    .message-row {{
        display: flex;
        margin-bottom: 16px;
        align-items: flex-start;
        animation: fadeIn 0.3s ease-in;
    }}

    @keyframes fadeIn {{
        from {{ opacity: 0; transform: translateY(10px); }}
        to {{ opacity: 1; transform: translateY(0); }}
    }}

    .message-row.user {{
        flex-direction: row-reverse;
        justify-content: flex-start;
    }}

    .message-row.assistant {{
        flex-direction: row;
        justify-content: flex-start;
    }}

    .avatar {{
        width: 40px;
        height: 40px;
        min-width: 40px;
        min-height: 40px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
        flex-shrink: 0;
        box-shadow: 0 3px 10px var(--shadow-medium);
        overflow: hidden;
    }}

    .avatar.user {{
        background: transparent;
        margin-left: 12px;
        padding: 0;
        box-shadow: 0 3px 10px var(--shadow-medium);
    }}

    .avatar.user img {{
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: 50%;
        display: block;
    }}

    .avatar.assistant {{
        background: transparent;
        margin-right: 12px;
        padding: 0;
        box-shadow: 0 3px 10px var(--shadow-medium);
    }}

    .avatar.assistant img {{
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: 50%;
        display: block;
    }}

    .message-bubble {{
        max-width: 70%;
        padding: 12px 18px;
        border-radius: 20px;
        font-size: 15px;
        line-height: 1.6;
        word-wrap: break-word;
        overflow-wrap: break-word;
    }}

    .message-bubble.user {{
        background: linear-gradient(135deg, var(--user-gradient-start) 0%, var(--user-gradient-end) 100%);
        color: white;
        border-top-right-radius: 4px;
        box-shadow: 0 3px 12px rgba(0, 122, 255, 0.25);
    }}

    .message-bubble.assistant {{
        background-color: var(--bg-secondary);
        color: var(--text-primary);
        border-top-left-radius: 4px;
        box-shadow: 0 2px 8px var(--shadow-light);
        border: 1px solid var(--border-color);
    }}

    .loading-bubble {{
        max-width: 70%;
        padding: 16px 18px;
        border-radius: 20px;
        background-color: var(--bg-secondary);
        border-top-left-radius: 4px;
        box-shadow: 0 2px 8px var(--shadow-light);
        border: 1px solid var(--border-color);
        display: flex;
        align-items: center;
        gap: 6px;
    }}

    .loading-dot {{
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background-color: #8E8E93;
        animation: loadingPulse 1.4s ease-in-out infinite;
    }}

    .loading-dot:nth-child(1) {{ animation-delay: 0s; }}
    .loading-dot:nth-child(2) {{ animation-delay: 0.2s; }}
    .loading-dot:nth-child(3) {{ animation-delay: 0.4s; }}

    @keyframes loadingPulse {{
        0%, 60%, 100% {{
            opacity: 0.3;
            transform: scale(0.8);
        }}
        30% {{
            opacity: 1;
            transform: scale(1.1);
        }}
    }}

    .stChatInputContainer {{
        background-color: var(--bg-primary) !important;
        border-top: 1px solid var(--border-color) !important;
        padding: 20px 0 !important;
    }}

    .stChatInput > div {{
        background-color: var(--input-bg) !important;
        border: 2px solid var(--border-color) !important;
        border-radius: 25px !important;
        padding: 10px 20px !important;
        box-shadow: 0 2px 8px var(--shadow-light) !important;
        transition: all 0.3s ease !important;
    }}

    .stChatInput > div:focus-within {{
        border-color: #007AFF !important;
        box-shadow: 0 4px 12px rgba(0, 122, 255, 0.15) !important;
    }}

    .stChatInput input {{
        background-color: transparent !important;
        color: var(--text-primary) !important;
        font-size: 15px !important;
    }}

    .stSpinner {{
        display: none !important;
    }}

    .js-plotly-plot {{
        border-radius: 20px !important;
        overflow: hidden !important;
        box-shadow: 0 4px 16px var(--shadow-light) !important;
        background-color: var(--bg-secondary) !important;
        padding: 10px !important;
        margin-top: 20px !important;
    }}

    h2, h3 {{
        color: var(--text-primary) !important;
        font-weight: 600 !important;
        letter-spacing: -0.3px !important;
        margin-top: 2rem !important;
    }}

    .streamlit-expanderHeader {{
        background-color: var(--bg-secondary) !important;
        border-radius: 16px !important;
        color: var(--text-primary) !important;
        font-weight: 500 !important;
        border: 1px solid var(--border-color) !important;
        padding: 12px 16px !important;
        box-shadow: 0 2px 6px var(--shadow-light) !important;
    }}

    .stAlert {{
        border-radius: 16px !important;
        border: none !important;
        box-shadow: 0 2px 8px var(--shadow-light) !important;
    }}

    [data-testid="stDataFrame"] {{
        background-color: var(--bg-secondary);
        border-radius: 12px;
        overflow: hidden;
    }}
</style>
""",
    unsafe_allow_html=True,
)


# ==================== 고정 헤더 생성 ====================
if logo_base64:
    header_html = f"""
    <div class="fixed-header">
        <div class="header-content">
            <img src="data:image/svg+xml;base64,{logo_base64}" class="header-logo" alt="HSE Logo" onerror="this.style.display='none'">
            <h1 class="header-title">orcHatStra</h1>
        </div>
    </div>
    """
else:
    header_html = """
    <div class="fixed-header">
        <div class="header-content">
            <h1 class="header-title">orcHatStra</h1>
        </div>
    </div>
    """

st.markdown(header_html, unsafe_allow_html=True)


# ==================== Secrets 처리 ====================
try:
    URL = st.secrets.get("SUPABASE_URL", "https://qipphcdzlmqidhrjnjtt.supabase.co")
    KEY = st.secrets.get(
        "SUPABASE_KEY",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFpcHBoY2R6bG1xaWRocmpuanR0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjY5NTIwMTIsImV4cCI6MjA4MjUyODAxMn0.AsuvjVGCLUJF_IPvQevYASaM6uRF2C6F-CjwC3eCNVk",
    )
    GENAI_KEY = st.secrets.get("GEMINI_API_KEY", "AIzaSyAQaiwm46yOITEttdr0ify7duXCW3TwGRo")
except Exception:
    URL = "https://qipphcdzlmqidhrjnjtt.supabase.co"
    KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFpcHBoY2R6bG1xaWRocmpuanR0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjY5NTIwMTIsImV4cCI6MjA4MjUyODAxMn0.AsuvjVGCLUJF_IPvQevYASaM6uRF2C6F-CjwC3eCNVk"
    GENAI_KEY = "AIzaSyAQaiwm46yOITEttdr0ify7duXCW3TwGRo"


@st.cache_resource
def init_supabase():
    return create_client(URL, KEY)


supabase: Client = init_supabase()
genai.configure(api_key=GENAI_KEY)


CAPA_LIMITS = {"조립1": 3300, "조립2": 3700, "조립3": 3600}
FROZEN_DAYS = 3
TEST_MODE = True
TODAY = datetime(2026, 1, 5).date() if TEST_MODE else datetime.now().date()


# ==================== 데이터 로드 ====================
@st.cache_data(ttl=600)
def fetch_data(target_date=None):
    try:
        if target_date:
            dt = datetime.strptime(target_date, "%Y-%m-%d")
            start_date = (dt - timedelta(days=10)).strftime("%Y-%m-%d")
            end_date = (dt + timedelta(days=10)).strftime("%Y-%m-%d")
            plan_res = (
                supabase.table("production_plan_2026_01")
                .select("*")
                .gte("plan_date", start_date)
                .lte("plan_date", end_date)
                .execute()
            )
        else:
            plan_res = supabase.table("production_plan_2026_01").select("*").execute()

        plan_df = pd.DataFrame(plan_res.data) if plan_res.data else pd.DataFrame()
        hist_res = supabase.table("production_investigation").select("*").execute()
        hist_df = pd.DataFrame(hist_res.data) if hist_res.data else pd.DataFrame()

        if not plan_df.empty:
            plan_df["name_clean"] = plan_df["product_name"].apply(lambda x: re.sub(r"\s+", "", str(x)).strip())
            plt_map = plan_df.groupby("name_clean")["plt"].first().to_dict()
            product_map = plan_df.groupby("name_clean")["line"].unique().to_dict()
            for k in product_map:
                if "T6" in k.upper():
                    product_map[k] = ["조립1", "조립2", "조립3"]
            return plan_df, hist_df, product_map, plt_map

        return pd.DataFrame(), pd.DataFrame(), {}, {}
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), {}, {}


def extract_date(text):
    if not text:
        return None
    patterns = [r"(\d{1,2})/(\d{1,2})", r"(\d{1,2})월\s*(\d{1,2})일", r"202[56]-(\d{1,2})-(\d{1,2})"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            m, d = match.groups()
            return f"2026-{int(m):02d}-{int(d):02d}"
    return None


def clean_content(text):
    if not text:
        return ""
    text = re.sub(r"\n\n\n+", "\n\n", text)
    lines = text.split("\n")
    cleaned_lines = [line.rstrip() for line in lines]
    return "\n".join(cleaned_lines)


def detect_table(text):
    if not text:
        return [("text", "")]
    lines = text.split("\n")
    table_lines = []
    result_parts = []
    current_text = []

    for line in lines:
        if line.strip().startswith("|") and line.strip().endswith("|"):
            if current_text:
                result_parts.append(("text", "\n".join(current_text)))
                current_text = []
            table_lines.append(line)
        else:
            if table_lines:
                result_parts.append(("table", table_lines[:]))
                table_lines = []
            current_text.append(line)

    if current_text:
        result_parts.append(("text", "\n".join(current_text)))
    if table_lines:
        result_parts.append(("table", table_lines))

    return result_parts


def parse_table_to_html(table_lines):
    if not table_lines:
        return ""
    html_parts = ["<table>"]
    is_header = True
    header_written = False

    for line in table_lines:
        stripped = line.strip()

        if re.match(r"^\|[\s\-:]+\|[\s\-:|\s]*$", stripped):
            continue
        if not stripped or stripped == "|":
            continue

        cells = [cell.strip() for cell in stripped.split("|")]
        cells = [c for c in cells if c]

        if not cells:
            continue
        if all(re.match(r"^[\-:]+$", cell.strip()) for cell in cells):
            continue

        if is_header and not header_written:
            html_parts.append("<thead><tr>")
            for cell in cells:
                html_parts.append(f"<th>{cell}</th>")
            html_parts.append("</tr></thead><tbody>")
            header_written = True
            is_header = False
        else:
            html_parts.append("<tr>")
            for cell in cells:
                html_parts.append(f"<td>{cell}</td>")
            html_parts.append("</tr>")

    html_parts.append("</tbody></table>")
    return "".join(html_parts)


def markdown_to_html(text):
    import html

    if not text:
        return ""

    text = clean_content(text)
    parts = detect_table(text)
    result_html = []

    for part_type, content in parts:
        if part_type == "table":
            table_html = parse_table_to_html(content)
            result_html.append(table_html)
        else:
            code_blocks = []

            def save_code_block(match):
                code_blocks.append(match.group(0))
                return f"__CODE_BLOCK_{len(code_blocks)-1}__"

            content = re.sub(r"```[\s\S]*?```", save_code_block, content)

            inline_codes = []

            def save_inline_code(match):
                inline_codes.append(match.group(0))
                return f"__INLINE_CODE_{len(inline_codes)-1}__"

            content = re.sub(r"`[^`]+`", save_inline_code, content)
            content = html.escape(content)

            content = re.sub(r"^### (.+)$", r"<h3>\1</h3>", content, flags=re.MULTILINE)
            content = re.sub(r"^## (.+)$", r"<h2>\1</h2>", content, flags=re.MULTILINE)
            content = re.sub(r"^# (.+)$", r"<h1>\1</h1>", content, flags=re.MULTILINE)

            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(r"__(.+?)__", r"<strong>\1</strong>", content)
            content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", content)
            content = re.sub(r"_(.+?)_", r"<em>\1</em>", content)

            content = re.sub(r"^[\-\*] (.+)$", r"• \1", content, flags=re.MULTILINE)
            content = re.sub(r"^\d+\. (.+)$", r"<li>\1</li>", content, flags=re.MULTILINE)

            for i, code in enumerate(inline_codes):
                code_content = code[1:-1]
                content = content.replace(f"__INLINE_CODE_{i}__", f"<code>{html.escape(code_content)}</code>")

            for i, block in enumerate(code_blocks):
                match = re.match(r"```(\w*)\n?([\s\S]*?)```", block)
                if match:
                    _, code_content = match.groups()
                    content = content.replace(f"__CODE_BLOCK_{i}__", f"<pre><code>{html.escape(code_content)}</code></pre>")

            paragraphs = content.split("\n\n")
            formatted_paragraphs = []
            for para in paragraphs:
                para = para.strip()
                if para and not para.startswith("<") and not para.startswith("•"):
                    formatted_paragraphs.append(f"<p>{para}</p>")
                else:
                    formatted_paragraphs.append(para)

            content = "\n".join(formatted_paragraphs)
            content = re.sub(r"(?<!>)\n(?!<)", "<br>", content)
            result_html.append(content)

    return "".join(result_html)


def display_message(role, content):
    if not content:
        return

    if role == "user":
        avatar_html = f'<img src="data:image/png;base64,{user_avatar_base64}" alt="User Avatar">' if user_avatar_base64 else ""
    else:
        avatar_html = f'<img src="data:image/png;base64,{ai_avatar_base64}" alt="AI Avatar">' if ai_avatar_base64 else ""

    html_content = markdown_to_html(content)

    html_output = f"""
    <div class="message-row {role}">
        <div class="avatar {role}">{avatar_html}</div>
        <div class="message-bubble {role}">{html_content}</div>
    </div>
    """
    st.markdown(html_output, unsafe_allow_html=True)


def display_loading():
    avatar_html = f'<img src="data:image/png;base64,{ai_avatar_base64}" alt="AI Avatar">' if ai_avatar_base64 else ""

    html_output = f"""
    <div class="message-row assistant">
        <div class="avatar assistant">{avatar_html}</div>
        <div class="loading-bubble">
            <div class="loading-dot"></div>
            <div class="loading-dot"></div>
            <div class="loading-dot"></div>
        </div>
    </div>
    """
    st.markdown(html_output, unsafe_allow_html=True)


# ==================== 메인 화면 ====================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "is_loading" not in st.session_state:
    st.session_state.is_loading = False

st.markdown('<div class="chat-container">', unsafe_allow_html=True)

for msg in st.session_state.messages:
    if isinstance(msg, dict) and "role" in msg and "content" in msg:
        display_message(msg["role"], msg["content"])

if st.session_state.is_loading:
    display_loading()

st.markdown("</div>", unsafe_allow_html=True)

if prompt := st.chat_input("무엇을 도와드릴까요?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.is_loading = True
    st.rerun()

if st.session_state.is_loading:
    user_messages = [msg for msg in st.session_state.messages if isinstance(msg, dict) and msg.get("role") == "user"]
    if user_messages:
        prompt = user_messages[-1]["content"]
        target_date = extract_date(prompt)

        is_adjustment_mode = target_date and (
            any(line in prompt for line in ["조립1", "조립2", "조립3"])
            or re.search(r"\d+%", prompt)
            or "CAPA" in prompt.upper()
            or "줄여" in prompt
            or "생산하고" in prompt
        )

        try:
            if is_adjustment_mode:
                plan_df, hist_df, product_map, plt_map = fetch_data(target_date)

                if plan_df.empty:
                    answer = "❌ 데이터를 불러올 수 없습니다. 날짜를 확인해주세요."
                else:
                    # ⚠️ hybrid.py가 5개 반환(report, success, charts, status, validated_moves)일 수 있음
                    ret = ask_professional_scheduler(
                        question=prompt,
                        plan_df=plan_df,
                        hist_df=hist_df,
                        product_map=product_map,
                        plt_map=plt_map,
                        question_date=target_date,
                        mode="hybrid",
                        today=TODAY,
                        capa_limits=CAPA_LIMITS,
                        genai_key=GENAI_KEY,
                    )

                    if isinstance(ret, tuple) and len(ret) == 5:
                        report, success, charts, status, _validated_moves = ret
                    else:
                        report, success, charts, status = ret

                    answer = (f"✅ {status}\n\n{report}") if success else (f"⚠️ {status}\n\n{report}")

            else:
                db_result = fetch_db_data_legacy(prompt, supabase)
                if "찾을 수 없습니다" in db_result or "오류" in db_result:
                    answer = db_result
                else:
                    answer = query_gemini_ai_legacy(prompt, db_result, GENAI_KEY)

            st.session_state.messages.append({"role": "assistant", "content": answer})
        except Exception as e:
            error_msg = f"❌ **오류 발생**\n\n```\n{str(e)}\n```"
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
        finally:
            st.session_state.is_loading = False
            st.rerun()


# ==================== CAPA 차트 표시 ====================
if not st.session_state.is_loading and st.session_state.messages:
    last_user_msg = [msg for msg in st.session_state.messages if isinstance(msg, dict) and msg.get("role") == "user"]
    if last_user_msg:
        last_prompt = last_user_msg[-1]["content"]
        target_date = extract_date(last_prompt)

        is_adjustment_mode = target_date and (
            any(line in last_prompt for line in ["조립1", "조립2", "조립3"])
            or re.search(r"\d+%", last_prompt)
            or "CAPA" in last_prompt.upper()
            or "줄여" in last_prompt
            or "생산하고" in last_prompt
        )

        if is_adjustment_mode:
            plan_df, _, _, _ = fetch_data(target_date)

            if not plan_df.empty and "qty_1차" in plan_df.columns:
                st.subheader("📊 CAPA 사용 현황")

                daily_summary = plan_df.groupby(["plan_date", "line"])["qty_1차"].sum().reset_index()
                daily_summary.columns = ["plan_date", "line", "current_qty"]
                daily_summary["max_capa"] = daily_summary["line"].map(CAPA_LIMITS)
                daily_summary["remaining_capa"] = daily_summary["max_capa"] - daily_summary["current_qty"]

                chart_data = daily_summary.pivot(index="plan_date", columns="line", values="current_qty").fillna(0)

                fig = go.Figure()
                colors = {"조립1": "#007AFF", "조립2": "#34C759", "조립3": "#FF3B30"}

                for line in ["조립1", "조립2", "조립3"]:
                    if line in chart_data.columns:
                        fig.add_trace(
                            go.Bar(
                                name=f"{line}",
                                x=chart_data.index,
                                y=chart_data[line],
                                marker_color=colors[line],
                                hovertemplate="%{x}<br>수량: %{y:,}개",
                            )
                        )

                for line, limit in CAPA_LIMITS.items():
                    fig.add_hline(
                        y=limit,
                        line_dash="dash",
                        line_color=colors[line],
                        annotation_text=f"{line} 한계: {limit:,}",
                        annotation_position="right",
                    )

                fig.update_layout(
                    barmode="group",
                    height=450,
                    xaxis_title="날짜",
                    yaxis_title="수량 (개)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    hovermode="x unified",
                )

                st.plotly_chart(fig, use_container_width=True)

                with st.expander("📋 상세 데이터 보기"):
                    st.dataframe(
                        daily_summary.style.format(
                            {"current_qty": "{:,.0f}", "max_capa": "{:,.0f}", "remaining_capa": "{:,.0f}"}
                        ),
                        use_container_width=True,
                    )

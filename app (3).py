import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from datetime import datetime, timedelta
import plotly.graph_objects as go
import re
import base64
import os

# 분리된 모듈에서 함수 임포트
from legacy import fetch_db_data_legacy, query_gemini_ai_legacy
from hybrid import ask_professional_scheduler


# ==================== 환경 설정 ====================
st.set_page_config(page_title="orcHatStra", page_icon="🎯", layout="wide")


# 이미지 파일을 Base64로 인코딩하는 함수
def get_base64_of_bin_file(bin_file: str):
    """이미지 파일을 Base64로 인코딩"""
    possible_paths = [
        bin_file,
        os.path.join(os.path.dirname(__file__), bin_file) if "__file__" in globals() else bin_file,
        os.path.join(os.getcwd(), bin_file),
    ]

    for path in possible_paths:
        try:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    data = f.read()
                return base64.b64encode(data).decode()
        except Exception:
            continue

    return None


# 로고, AI 아바타, 사용자 아바타 이미지 로드
logo_base64 = get_base64_of_bin_file("HSE.svg")
ai_avatar_base64 = get_base64_of_bin_file("ai 아바타.png")
user_avatar_base64 = get_base64_of_bin_file("이력서 사진.v카툰.png")


st.markdown(
    f"""
<style>
    /* ==================== 다크모드/라이트모드 변수 설정 ==================== */
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

    /* ==================== 전체 배경 ==================== */
    .stApp {{
        background-color: var(--bg-primary);
    }}

    .main {{
        background-color: var(--bg-primary);
        padding-top: 100px !important;
    }}

    /* Streamlit 기본 헤더 숨기기 */
    [data-testid="stHeader"] {{
        display: none;
    }}

    /* ==================== 고정 헤더 배너 ==================== */
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

    /* ==================== Streamlit 기본 채팅 UI 숨기기 ==================== */
    [data-testid="stChatMessage"] {{
        display: none !important;
    }}

    /* ==================== 커스텀 채팅 컨테이너 ==================== */
    .chat-container {{
        max-width: 900px;
        margin: 0 auto;
        padding: 20px;
    }}

    /* ==================== 메시지 행 ==================== */
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

    /* 사용자 메시지 - 오른쪽 */
    .message-row.user {{
        flex-direction: row-reverse;
        justify-content: flex-start;
    }}

    /* AI 메시지 - 왼쪽 */
    .message-row.assistant {{
        flex-direction: row;
        justify-content: flex-start;
    }}

    /* ==================== 아바타 스타일 ==================== */
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

    /* 사용자 아바타 - 이미지 전용 */
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

    /* AI 아바타 - 이미지 전용 */
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

    /* ==================== 메시지 말풍선 ==================== */
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

    /* ==================== 로딩 애니메이션 ==================== */
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
        0%, 60%, 100% {{ opacity: 0.3; transform: scale(0.8); }}
        30% {{ opacity: 1; transform: scale(1.1); }}
    }}

    /* ==================== 마크다운 스타일링 ==================== */
    .message-bubble h1,
    .message-bubble h2,
    .message-bubble h3 {{
        color: inherit;
        margin-top: 0.8em;
        margin-bottom: 0.5em;
        font-weight: 600;
        line-height: 1.3;
    }}

    .message-bubble h1:first-child,
    .message-bubble h2:first-child,
    .message-bubble h3:first-child {{
        margin-top: 0;
    }}

    .message-bubble.user h1,
    .message-bubble.user h2,
    .message-bubble.user h3 {{
        color: white;
    }}

    .message-bubble h1 {{ font-size: 1.5em; }}
    .message-bubble h2 {{ font-size: 1.3em; }}
    .message-bubble h3 {{ font-size: 1.1em; }}

    .message-bubble p {{
        margin: 0.5em 0;
        line-height: 1.6;
    }}

    .message-bubble ul,
    .message-bubble ol {{
        margin: 0.5em 0;
        padding-left: 1.5em;
    }}

    .message-bubble li {{
        margin: 0.3em 0;
        line-height: 1.6;
    }}

    .message-bubble code {{
        background-color: rgba(128, 128, 128, 0.15);
        padding: 2px 6px;
        border-radius: 4px;
        font-family: 'SF Mono', Monaco, Consolas, monospace;
        font-size: 0.9em;
    }}

    .message-bubble.user code {{
        background-color: rgba(255, 255, 255, 0.2);
        color: white;
    }}

    .message-bubble pre {{
        background-color: rgba(128, 128, 128, 0.1);
        padding: 12px;
        border-radius: 8px;
        overflow-x: auto;
        margin: 0.8em 0;
        line-height: 1.5;
    }}

    .message-bubble.user pre {{
        background-color: rgba(255, 255, 255, 0.15);
    }}

    .message-bubble pre code {{
        background-color: transparent;
        padding: 0;
    }}

    .message-bubble blockquote {{
        border-left: 3px solid var(--border-color);
        margin: 0.8em 0;
        padding-left: 1em;
        opacity: 0.9;
    }}

    .message-bubble.user blockquote {{
        border-left-color: rgba(255, 255, 255, 0.5);
    }}

    .message-bubble table {{
        border-collapse: collapse;
        width: 100%;
        margin: 0.8em 0;
        font-size: 14px;
    }}

    .message-bubble table th,
    .message-bubble table td {{
        border: 1px solid var(--border-color);
        padding: 10px 16px;
        text-align: left;
    }}

    .message-bubble.user table th,
    .message-bubble.user table td {{
        border-color: rgba(255, 255, 255, 0.3);
    }}

    .message-bubble table th {{
        background-color: rgba(128, 128, 128, 0.15);
        font-weight: 600;
    }}

    .message-bubble.user table th {{
        background-color: rgba(255, 255, 255, 0.2);
    }}

    .message-bubble table tr:nth-child(even) {{
        background-color: rgba(128, 128, 128, 0.05);
    }}

    .message-bubble.user table tr:nth-child(even) {{
        background-color: rgba(255, 255, 255, 0.05);
    }}

    /* ==================== 채팅 입력창 ==================== */
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

    .stChatInput input::placeholder {{
        color: #8E8E93 !important;
    }}

    /* ==================== 스피너 숨기기 ==================== */
    .stSpinner {{
        display: none !important;
    }}

    /* ==================== 차트 컨테이너 ==================== */
    .js-plotly-plot {{
        border-radius: 20px !important;
        overflow: hidden !important;
        box-shadow: 0 4px 16px var(--shadow-light) !important;
        background-color: var(--bg-secondary) !important;
        padding: 10px !important;
        margin-top: 20px !important;
    }}

    /* ==================== Expander ==================== */
    .streamlit-expanderHeader {{
        background-color: var(--bg-secondary) !important;
        border-radius: 16px !important;
        color: var(--text-primary) !important;
        font-weight: 500 !important;
        border: 1px solid var(--border-color) !important;
        padding: 12px 16px !important;
        box-shadow: 0 2px 6px var(--shadow-light) !important;
    }}

    /* ==================== 데이터프레임 ==================== */
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


# ==================== (UI) report 분리 + 날짜별 변경량(Δ) ====================

def split_report_sections(report_md: str) -> dict:
    """hybrid 보고서는 보통 '## ' 섹션 헤더를 사용하므로 그 기준으로 분리"""
    if not report_md:
        return {}
    parts = re.split(r"\n##\s+", report_md.strip())
    sections = {"__FULL__": report_md.strip()}
    for p in parts[1:]:
        lines = p.splitlines()
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        sections[title] = body
    return sections


def render_datewise_delta_tables(validated_moves: list[dict] | None):
    """검증된 이동 내역(validated_moves)로 날짜별 변경량(Δ) 표를 세로로 나열"""
    if not validated_moves:
        st.caption("📊 변경량 표: 이동 내역이 없습니다.")
        return

    records: list[dict] = []
    for mv in validated_moves:
        item = str(mv.get("item", "")).strip()
        qty = int(mv.get("qty", 0) or 0)
        from_loc = str(mv.get("from", "") or "")
        to_loc = str(mv.get("to", "") or "")

        if not item or qty <= 0 or "_" not in from_loc or "_" not in to_loc:
            continue

        from_date, from_line = [x.strip() for x in from_loc.split("_", 1)]
        to_date, to_line = [x.strip() for x in to_loc.split("_", 1)]

        records.append({"date": from_date, "item": item, "line": from_line, "delta": -qty})
        records.append({"date": to_date, "item": item, "line": to_line, "delta": +qty})

    df = pd.DataFrame(records)
    if df.empty:
        st.caption("📊 변경량 표: 표시할 데이터가 없습니다.")
        return

    def _fmt_delta(x):
        if x is None or (isinstance(x, float) and pd.isna(x)) or x == 0:
            return ""
        try:
            n = int(x)
        except Exception:
            return str(x)
        return f"{n:+,}"

    for date in sorted(df["date"].unique()):
        day = df[df["date"] == date].copy()
        pivot_num = (
            day.pivot_table(index="item", columns="line", values="delta", aggfunc="sum", fill_value=0)
            .reindex(columns=["조립1", "조립2", "조립3"])
            .fillna(0)
        )
        pivot_disp = pivot_num.applymap(_fmt_delta)
        pivot_disp = pivot_disp.loc[~(pivot_disp == "").all(axis=1)]

        st.markdown(f"#### 📅 {date} 기준 변경분")
        if pivot_disp.empty:
            st.caption("(변경 없음)")
        else:
            st.dataframe(pivot_disp, use_container_width=True)


def render_hybrid_details(report_md: str):
    """검증/CAPA/원문 같은 상세 정보는 '탭 1개'로 접어서 제공"""
    sections = split_report_sections(report_md)
    with st.expander("🔎 상세 보기", expanded=False):
        (detail_tab,) = st.tabs(["🔎 상세"])
        with detail_tab:
            st.markdown("### ✅ 검증 결과")
            verify_key = next(
                (k for k in sections.keys() if "Python 검증" in k or "검증 결과" in k or "검증" in k),
                None,
            )
            st.markdown(sections.get(verify_key, "검증 섹션이 없습니다."))

            st.markdown("---")

            st.markdown("### 📊 CAPA 현황")
            capa_key = next((k for k in sections.keys() if "CAPA 현황" in k), None)
            st.markdown(sections.get(capa_key, "CAPA 섹션이 없습니다."))

            st.markdown("---")

            st.markdown("### 📄 전체 원문")
            st.markdown(sections.get("__FULL__", report_md))


def render_hybrid_result_ui(status: str, success: bool, report_md: str, validated_moves: list | None = None):
    """커스텀 채팅 UI 아래(일반 Streamlit 영역)에 '조치계획/Δ/상세'를 제공"""
    if success:
        st.success(status)
    else:
        st.warning(status)

    sections = split_report_sections(report_md)

    st.markdown("#### 🧾 조치계획(이동 내역)")
    action_key = next((k for k in sections.keys() if "최종 조치 계획" in k), None)
    action_body = sections.get(action_key, "").strip()

    if action_body:
        st.markdown(action_body)
        st.markdown("---")
        st.markdown("### 📊 생산계획 변경량 요약(Δ)")
        render_datewise_delta_tables(validated_moves)
    else:
        st.info("조치계획이 없습니다. (상세 보기에서 원문 확인 가능)")

    render_hybrid_details(report_md)


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
    """질문에서 날짜 추출"""
    if not text:
        return None
    patterns = [r"(\d{1,2})/(\d{1,2})", r"(\d{1,2})월\s*(\d{1,2})일", r"202[56]-(\d{1,2})-(\d{1,2})"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            m, d = match.groups()
            return f"2026-{int(m):02d}-{int(d):02d}"
    return None


# ==================== 커스텀 마크다운(HTML) 렌더링 ====================

def clean_content(text: str) -> str:
    """불필요한 연속 공백 제거하되 마크다운 구조는 유지"""
    if not text:
        return ""
    text = re.sub(r"\n\n\n+", "\n\n", text)
    lines = text.split("\n")
    cleaned_lines = [line.rstrip() for line in lines]
    return "\n".join(cleaned_lines)


def detect_table(text: str):
    """텍스트에서 표 형식을 감지하고 HTML 테이블로 변환"""
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
    """파이프로 구분된 표를 HTML 테이블로 변환 - 구분선 제거 개선"""
    if not table_lines:
        return ""

    html_parts = ["<table>"]
    is_header = True
    header_written = False

    for line in table_lines:
        stripped = line.strip()

        # 헤더 구분선(| --- | --- |, |:---:| 등) 제거
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


def markdown_to_html(text: str) -> str:
    """마크다운을 HTML로 변환"""
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
            continue

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
    """커스텀 메시지 표시 함수 - 사용자 및 AI 아바타 모두 이미지 사용"""
    if not content:
        return
    
    # 아바타 설정
    if role == "user":
        # 사용자 아바타는 무조건 이미지 사용 (이모지 제거)
        if user_avatar_base64:
            avatar_html = f'<img src="data:image/png;base64,{user_avatar_base64}" alt="User Avatar">'
        else:
            # 이미지 로드 실패 시에도 빈 공간 유지 (이모지 없음)
            avatar_html = ''
    else:
        # AI 아바타는 무조건 이미지 사용 (이모지 제거)
        if ai_avatar_base64:
            avatar_html = f'<img src="data:image/png;base64,{ai_avatar_base64}" alt="AI Avatar">'
        else:
            # 이미지 로드 실패 시에도 빈 공간 유지 (이모지 없음)
            avatar_html = ''
    
    html_content = markdown_to_html(content)
    
    html_output = f"""
    <div class="message-row {role}">
        <div class="avatar {role}">{avatar_html}</div>
        <div class="message-bubble {role}">{html_content}</div>
    </div>
    """
    st.markdown(html_output, unsafe_allow_html=True)



def display_loading():
    """AI 답변 대기 중 로딩 애니메이션 표시"""
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


# ==================== 메인 화면 (커스텀 채팅) ====================

# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

if "is_loading" not in st.session_state:
    st.session_state.is_loading = False

# 마지막 하이브리드 결과(상세 UI/차트 출력용)
if "last_hybrid" not in st.session_state:
    st.session_state.last_hybrid = None

# 채팅 컨테이너 시작
st.markdown('<div class="chat-container">', unsafe_allow_html=True)

# 기존 메시지 표시
for msg in st.session_state.messages:
    if isinstance(msg, dict) and "role" in msg and "content" in msg:
        display_message(msg["role"], msg["content"])

# 로딩 중일 때 로딩 애니메이션 표시
if st.session_state.is_loading:
    display_loading()

st.markdown("</div>", unsafe_allow_html=True)

# 사용자 입력
if prompt := st.chat_input("무엇을 도와드릴까요?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.is_loading = True
    st.rerun()

# 로딩 상태일 때만 AI 응답 생성
if st.session_state.is_loading:
    user_messages = [m for m in st.session_state.messages if isinstance(m, dict) and m.get("role") == "user"]
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
                    st.session_state.last_hybrid = None
                else:
                    result = ask_professional_scheduler(
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

                    # hybrid.py 버전에 따라 반환값 길이가 달라도 안전하게 처리
                    report = ""
                    success = False
                    charts = None
                    status = ""
                    validated_moves = None

                    if isinstance(result, tuple) or isinstance(result, list):
                        if len(result) == 5:
                            report, success, charts, status, validated_moves = result
                        elif len(result) == 4:
                            report, success, charts, status = result
                        else:
                            # 예외 케이스: 최소 4개는 기대
                            report = str(result)
                            success = False
                            status = "생산계획 조정 결과를 파싱하지 못했습니다."
                    else:
                        report = str(result)
                        success = False
                        status = "생산계획 조정 결과를 파싱하지 못했습니다."

                    status = str(status).replace("하이브리드 수사", "생산계획 조정")

                    sections = split_report_sections(report)
                    action_key = next((k for k in sections.keys() if "최종 조치 계획" in k), None)
                    action_body = sections.get(action_key, "").strip()

                    answer = f"{'✅' if success else '⚠️'} {status}\n\n"
                    answer += "🧾 조치계획(이동 내역)\n"
                    answer += (action_body if action_body else "(조치계획 없음)")
                    answer += "\n\n(아래에서 Δ/검증/CAPA/원문 확인 가능)"

                    st.session_state.last_hybrid = {
                        "target_date": target_date,
                        "status": status,
                        "success": bool(success),
                        "report_md": report,
                        "validated_moves": validated_moves,
                        "plan_df": plan_df,  # CAPA 차트용
                    }
            else:
                db_result = fetch_db_data_legacy(prompt, supabase)
                if "찾을 수 없습니다" in db_result or "오류" in db_result:
                    answer = db_result
                else:
                    answer = query_gemini_ai_legacy(prompt, db_result, GENAI_KEY)

                st.session_state.last_hybrid = None

            st.session_state.messages.append({"role": "assistant", "content": answer})

        except Exception as e:
            error_msg = f"❌ **오류 발생**\n\n```\n{str(e)}\n```"
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
            st.session_state.last_hybrid = None

        finally:
            st.session_state.is_loading = False
            st.rerun()


# ==================== 하이브리드 상세 UI + CAPA 차트 ====================
# (커스텀 채팅 아래에 Streamlit 기본 컴포넌트로 출력)
if not st.session_state.is_loading and st.session_state.last_hybrid:
    last = st.session_state.last_hybrid

    st.markdown("---")
    render_hybrid_result_ui(
        status=last.get("status", ""),
        success=bool(last.get("success", False)),
        report_md=last.get("report_md", ""),
        validated_moves=last.get("validated_moves"),
    )

    # CAPA 차트 표시 (기존 기능 유지)
    plan_df = last.get("plan_df")
    if isinstance(plan_df, pd.DataFrame) and not plan_df.empty and "qty_1차" in plan_df.columns:
        st.subheader("📊 CAPA 사용 현황")

        daily_summary = plan_df.groupby(["plan_date", "line"])["qty_1차"].sum().reset_index()
        daily_summary.columns = ["plan_date", "line", "current_qty"]
        daily_summary["max_capa"] = daily_summary["line"].map(CAPA_LIMITS)
        daily_summary["remaining_capa"] = daily_summary["max_capa"] - daily_summary["current_qty"]

        chart_data = daily_summary.pivot(index="plan_date", columns="line", values="current_qty").fillna(0)

        fig = go.Figure()

        # (원본 app(5) 스타일 유지) + line별 색상 정의
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
                        marker=dict(cornerradius=8),
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
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="SF Pro Display, -apple-system, BlinkMacSystemFont, sans-serif", size=13, color="#000000"),
            margin=dict(l=20, r=20, t=40, b=20),
        )

        st.plotly_chart(fig, use_container_width=True)

        with st.expander("📋 상세 데이터 보기"):
            st.dataframe(
                daily_summary.style.format(
                    {"current_qty": "{:,.0f}", "max_capa": "{:,.0f}", "remaining_capa": "{:,.0f}"}
                ),
                use_container_width=True,
            )

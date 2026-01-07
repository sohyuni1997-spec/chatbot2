# app.py
import os
import re
import base64
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from supabase import create_client, Client
import google.generativeai as genai

# 분리된 모듈에서 함수 임포트
from legacy import fetch_db_data_legacy, query_gemini_ai_legacy
from hybrid import ask_professional_scheduler


# ==================== 환경 설정 ====================
st.set_page_config(page_title="orcHatStra", page_icon="🎯", layout="wide")


# ==================== 이미지 로드 유틸 ====================
def get_base64_of_bin_file(rel_path: str):
    """레포 내 파일을 base64로 읽어오기 (Streamlit Cloud는 레포에 커밋된 파일만 접근 가능)"""
    candidates = [
        rel_path,
        os.path.join(os.path.dirname(__file__), rel_path) if "__file__" in globals() else rel_path,
        os.path.join(os.getcwd(), rel_path),
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                with open(p, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            pass
    return None


# ✅ 추천: assets/ 경로 + 영문 파일명
LOGO_PATH = "assets/logo.svg"
AI_AVATAR_PATH = "assets/ai_avatar.png"
USER_AVATAR_PATH = "assets/user_avatar.png"

logo_base64 = get_base64_of_bin_file(LOGO_PATH)
ai_avatar_base64 = get_base64_of_bin_file(AI_AVATAR_PATH)
user_avatar_base64 = get_base64_of_bin_file(USER_AVATAR_PATH)


# ==================== 스타일 ====================
st.markdown(
    """
<style>
    :root {
        --bg-primary: #F5F5F7;
        --bg-secondary: #FFFFFF;
        --text-primary: #000000;
        --border-color: #E5E5EA;
        --shadow-light: rgba(0, 0, 0, 0.10);
        --shadow-medium: rgba(0, 0, 0, 0.15);
        --user-gradient-start: #007AFF;
        --user-gradient-end: #0051D5;
        --header-bg: #FFFFFF;
        --header-text: #000000;
        --input-bg: #FFFFFF;
    }

    @media (prefers-color-scheme: dark) {
        :root {
            --bg-primary: #000000;
            --bg-secondary: #1C1C1E;
            --text-primary: #FFFFFF;
            --border-color: #38383A;
            --shadow-light: rgba(255, 255, 255, 0.10);
            --shadow-medium: rgba(255, 255, 255, 0.15);
            --user-gradient-start: #0A84FF;
            --user-gradient-end: #0066CC;
            --header-bg: #1C1C1E;
            --header-text: #FFFFFF;
            --input-bg: #1C1C1E;
        }
    }

    .stApp { background-color: var(--bg-primary); }
    .main { background-color: var(--bg-primary); padding-top: 100px !important; }

    [data-testid="stHeader"] { display: none; }

    .fixed-header {
        position: fixed; top: 0; left: 0; right: 0;
        height: 80px;
        background-color: var(--header-bg);
        border-bottom: 1px solid var(--border-color);
        z-index: 9999;
        display: flex; align-items: center; justify-content: center;
        padding: 0 40px;
        box-shadow: 0 2px 10px var(--shadow-light);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
    }
    .header-content {
        width: 100%; max-width: 1400px;
        display: flex; align-items: center; gap: 20px;
    }
    .header-logo { height: 50px; width: auto; display: block; }
    .header-title {
        color: var(--header-text);
        font-weight: 800;
        font-size: 2.5rem;
        letter-spacing: -1.5px;
        font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif;
        margin: 0;
    }

    /* Streamlit 기본 채팅 UI 숨기기 */
    [data-testid="stChatMessage"] { display: none !important; }

    .chat-container { max-width: 900px; margin: 0 auto; padding: 20px; }

    .message-row {
        display: flex; margin-bottom: 16px; align-items: flex-start;
        animation: fadeIn 0.25s ease-in;
    }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(8px); }
        to   { opacity: 1; transform: translateY(0); }
    }

    .message-row.user { flex-direction: row-reverse; }
    .message-row.assistant { flex-direction: row; }

    .avatar {
        width: 40px; height: 40px; min-width: 40px; min-height: 40px;
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 3px 10px var(--shadow-medium);
        overflow: hidden;
        background: transparent;
    }
    .avatar.user { margin-left: 12px; }
    .avatar.assistant { margin-right: 12px; }
    .avatar img { width: 100%; height: 100%; object-fit: cover; border-radius: 50%; display: block; }

    .message-bubble {
        max-width: 70%;
        padding: 12px 18px;
        border-radius: 20px;
        font-size: 15px;
        line-height: 1.6;
        word-wrap: break-word;
        overflow-wrap: break-word;
    }
    .message-bubble.user {
        background: linear-gradient(135deg, var(--user-gradient-start) 0%, var(--user-gradient-end) 100%);
        color: white;
        border-top-right-radius: 6px;
        box-shadow: 0 3px 12px rgba(0, 122, 255, 0.25);
    }
    .message-bubble.assistant {
        background-color: var(--bg-secondary);
        color: var(--text-primary);
        border-top-left-radius: 6px;
        box-shadow: 0 2px 8px var(--shadow-light);
        border: 1px solid var(--border-color);
    }

    /* 로딩 */
    .loading-bubble {
        max-width: 70%;
        padding: 16px 18px;
        border-radius: 20px;
        background-color: var(--bg-secondary);
        border-top-left-radius: 6px;
        box-shadow: 0 2px 8px var(--shadow-light);
        border: 1px solid var(--border-color);
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .loading-dot {
        width: 8px; height: 8px; border-radius: 50%;
        background-color: #8E8E93;
        animation: loadingPulse 1.4s ease-in-out infinite;
    }
    .loading-dot:nth-child(2) { animation-delay: 0.2s; }
    .loading-dot:nth-child(3) { animation-delay: 0.4s; }
    @keyframes loadingPulse {
        0%,60%,100% { opacity: .3; transform: scale(.85); }
        30% { opacity: 1; transform: scale(1.05); }
    }

    /* 입력창 */
    .stChatInputContainer {
        background-color: var(--bg-primary) !important;
        border-top: 1px solid var(--border-color) !important;
        padding: 18px 0 !important;
    }
    .stChatInput > div {
        background-color: var(--input-bg) !important;
        border: 2px solid var(--border-color) !important;
        border-radius: 25px !important;
        padding: 10px 20px !important;
        box-shadow: 0 2px 8px var(--shadow-light) !important;
        transition: all 0.2s ease !important;
    }
    .stChatInput > div:focus-within {
        border-color: #007AFF !important;
        box-shadow: 0 4px 12px rgba(0, 122, 255, 0.15) !important;
    }
    .stChatInput input {
        background-color: transparent !important;
        color: var(--text-primary) !important;
        font-size: 15px !important;
    }
    .stChatInput input::placeholder { color: #8E8E93 !important; }

    /* details 스타일 (말풍선 내부) */
    details.hy-detail {
        margin-top: 10px;
        border: 1px solid var(--border-color);
        border-radius: 14px;
        padding: 10px 12px;
        background: rgba(128,128,128,0.05);
    }
    details.hy-detail summary {
        cursor: pointer;
        font-weight: 600;
        outline: none;
    }
    details.hy-detail .hy-inner {
        margin-top: 10px;
    }

    /* bubble 내부 표 */
    .message-bubble table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 14px; }
    .message-bubble th, .message-bubble td { border: 1px solid var(--border-color); padding: 8px 10px; text-align: left; }
    .message-bubble th { background-color: rgba(128, 128, 128, 0.12); font-weight: 600; }
    .message-bubble pre { background-color: rgba(128, 128, 128, 0.10); padding: 10px; border-radius: 10px; overflow-x: auto; }
    .message-bubble code { background-color: rgba(128, 128, 128, 0.15); padding: 2px 6px; border-radius: 6px; }
    .message-bubble.user code { background-color: rgba(255,255,255,0.18); color: #fff; }
</style>
""",
    unsafe_allow_html=True,
)


# ==================== 고정 헤더 ====================
if logo_base64:
    header_html = f"""
    <div class="fixed-header">
        <div class="header-content">
            <img src="data:image/svg+xml;base64,{logo_base64}" class="header-logo" alt="Logo">
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


# ==================== Secrets 처리 (✅ 키 하드코딩 금지) ====================
SUPABASE_URL = st.secrets.get("SUPABASE_URL", None)
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", None)
GENAI_KEY = st.secrets.get("GEMINI_API_KEY", None)

if not SUPABASE_URL or not SUPABASE_KEY or not GENAI_KEY:
    st.error(
        "❌ Secrets가 설정되지 않았습니다.\n\n"
        "Streamlit Cloud 설정에서 다음을 등록하세요:\n"
        "- SUPABASE_URL\n- SUPABASE_KEY\n- GEMINI_API_KEY"
    )
    st.stop()


@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


supabase: Client = init_supabase()
genai.configure(api_key=GENAI_KEY)


# ==================== 설정 ====================
CAPA_LIMITS = {"조립1": 3300, "조립2": 3700, "조립3": 3600}
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
    patterns = [
        r"(\d{1,2})/(\d{1,2})",
        r"(\d{1,2})월\s*(\d{1,2})일",
        r"202[56]-(\d{1,2})-(\d{1,2})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            mm, dd = m.groups()
            return f"2026-{int(mm):02d}-{int(dd):02d}"
    return None


# ==================== 마크다운 -> HTML (✅ legacy 영향 없이) ====================
def clean_content(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\n\n\n+", "\n\n", text)
    lines = text.split("\n")
    return "\n".join([ln.rstrip() for ln in lines])


def detect_table(text: str):
    if not text:
        return [("text", "")]
    lines = text.split("\n")
    table_lines, result_parts, current_text = [], [], []
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
        cells = [c.strip() for c in stripped.split("|")]
        cells = [c for c in cells if c]
        if not cells:
            continue
        if all(re.match(r"^[\-:]+$", c.strip()) for c in cells):
            continue
        if is_header and not header_written:
            html_parts.append("<thead><tr>")
            for c in cells:
                html_parts.append(f"<th>{c}</th>")
            html_parts.append("</tr></thead><tbody>")
            header_written = True
            is_header = False
        else:
            html_parts.append("<tr>")
            for c in cells:
                html_parts.append(f"<td>{c}</td>")
            html_parts.append("</tr>")
    html_parts.append("</tbody></table>")
    return "".join(html_parts)


def markdown_to_html(text: str, raw_html_blocks: dict | None = None) -> str:
    """
    - 기본은 안전하게 escape
    - 단, 하이브리드에서만 raw_html_blocks 토큰을 주입해서 <details> 같은 HTML을 통과시킴
    - legacy는 raw_html_blocks를 None으로 호출 => 기존 답변 절대 영향 없음
    """
    import html

    if not text:
        return ""

    text = clean_content(text)

    # 0) raw html 토큰 임시 저장
    raw_map = raw_html_blocks or {}
    for token in raw_map.keys():
        text = text.replace(token, f"__RAWHTML_{token}__")

    parts = detect_table(text)
    result_html = []

    for part_type, content in parts:
        if part_type == "table":
            result_html.append(parse_table_to_html(content))
            continue

        code_blocks = []

        def save_code_block(m):
            code_blocks.append(m.group(0))
            return f"__CODE_BLOCK_{len(code_blocks)-1}__"

        content = re.sub(r"```[\s\S]*?```", save_code_block, content)

        inline_codes = []

        def save_inline_code(m):
            inline_codes.append(m.group(0))
            return f"__INLINE_CODE_{len(inline_codes)-1}__"

        content = re.sub(r"`[^`]+`", save_inline_code, content)
        content = html.escape(content)

        # 헤더/강조
        content = re.sub(r"^### (.+)$", r"<h3>\1</h3>", content, flags=re.MULTILINE)
        content = re.sub(r"^## (.+)$", r"<h2>\1</h2>", content, flags=re.MULTILINE)
        content = re.sub(r"^# (.+)$", r"<h1>\1</h1>", content, flags=re.MULTILINE)
        content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
        content = re.sub(r"__(.+?)__", r"<strong>\1</strong>", content)
        content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", content)
        content = re.sub(r"_(.+?)_", r"<em>\1</em>", content)

        # 리스트(단순)
        content = re.sub(r"^[\-\*] (.+)$", r"• \1", content, flags=re.MULTILINE)

        # 인라인 코드 복원
        for i, code in enumerate(inline_codes):
            code_content = code[1:-1]
            content = content.replace(
                f"__INLINE_CODE_{i}__",
                f"<code>{html.escape(code_content)}</code>",
            )

        # 코드블록 복원
        for i, block in enumerate(code_blocks):
            m = re.match(r"```(\w*)\n?([\s\S]*?)```", block)
            if m:
                _, code_content = m.groups()
                content = content.replace(
                    f"__CODE_BLOCK_{i}__",
                    f"<pre><code>{html.escape(code_content)}</code></pre>",
                )

        # 문단 처리
        paragraphs = content.split("\n\n")
        formatted = []
        for para in paragraphs:
            para = para.strip()
            if para and not para.startswith("<") and not para.startswith("•"):
                formatted.append(f"<p>{para}</p>")
            else:
                formatted.append(para)
        content = "\n".join(formatted)
        content = re.sub(r"(?<!>)\n(?!<)", "<br>", content)

        result_html.append(content)

    out = "".join(result_html)

    # 1) raw html 토큰 복원 (하이브리드에서만 존재)
    for token, raw in raw_map.items():
        out = out.replace(f"__RAWHTML_{token}__", raw)

    return out


# ==================== 하이브리드 보고서: 말풍선 안에 전부 넣기 ====================
def split_report_sections(report_md: str) -> dict:
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


def build_delta_markdown(validated_moves: list | None) -> str:
    """
    validated_moves를 날짜별 Δ 표(마크다운 표)로 생성.
    표는 markdown_to_html의 테이블 파서가 HTML table로 바꿔줌.
    """
    if not validated_moves:
        return "📊 **생산계획 변경량 요약(Δ)**\n\n(이동 내역이 없어 변경량을 계산할 수 없습니다.)"

    records = []
    for mv in validated_moves:
        item = str(mv.get("item", "")).strip()
        qty = int(mv.get("qty", 0) or 0)
        from_loc = str(mv.get("from", "") or "")
        to_loc = str(mv.get("to", "") or "")

        if not item or qty <= 0 or "_" not in from_loc or "_" not in to_loc:
            continue

        from_date, from_line = [x.strip() for x in from_loc.split("_", 1)]
        to_date, to_line = [x.strip() for x in to_loc.split("_", 1)]

        records.append((from_date, item, from_line, -qty))
        records.append((to_date, item, to_line, +qty))

    if not records:
        return "📊 **생산계획 변경량 요약(Δ)**\n\n(표시할 변경량 데이터가 없습니다.)"

    df = pd.DataFrame(records, columns=["date", "item", "line", "delta"])
    dates = sorted(df["date"].unique().tolist())
    lines = ["조립1", "조립2", "조립3"]

    out = ["📊 **생산계획 변경량 요약(Δ)**\n"]
    for d in dates:
        day = df[df["date"] == d]
        pivot = (
            day.pivot_table(index="item", columns="line", values="delta", aggfunc="sum", fill_value=0)
            .reindex(columns=lines)
            .fillna(0)
        )

        def fmt(v):
            try:
                v = int(v)
            except Exception:
                return ""
            return "" if v == 0 else f"{v:+,}"

        pivot_disp = pivot.applymap(fmt)
        pivot_disp = pivot_disp.loc[~(pivot_disp == "").all(axis=1)]

        out.append(f"#### 📅 {d} 기준 변경분")
        if pivot_disp.empty:
            out.append("(변경 없음)\n")
            continue

        out.append("| item | 조립1 | 조립2 | 조립3 |")
        out.append("|---|---:|---:|---:|")
        for item, row in pivot_disp.iterrows():
            out.append(f"| {item} | {row.get('조립1','')} | {row.get('조립2','')} | {row.get('조립3','')} |")
        out.append("")

    return "\n".join(out).strip()


def build_details_html(report_md: str) -> str:
    sections = split_report_sections(report_md)

    verify_key = next(
        (k for k in sections.keys() if ("Python 검증" in k) or ("검증 결과" in k) or (k.strip() == "검증")),
        None,
    )
    capa_key = next((k for k in sections.keys() if "CAPA 현황" in k), None)

    # 각 섹션은 markdown_to_html로 변환해서 details 내부에 HTML로 넣어줌
    verify_html = markdown_to_html(sections.get(verify_key, "검증 섹션이 없습니다."))
    capa_html = markdown_to_html(sections.get(capa_key, "CAPA 섹션이 없습니다."))
    full_html = markdown_to_html(sections.get("__FULL__", report_md))

    return f"""
<details class="hy-detail">
  <summary>🔎 상세 보기 (검증 / CAPA / 원문)</summary>
  <div class="hy-inner">
    <h3>✅ Python 검증</h3>
    {verify_html}
    <hr>
    <h3>📊 CAPA 현황</h3>
    {capa_html}
    <hr>
    <h3>📄 전체 원문</h3>
    {full_html}
  </div>
</details>
""".strip()


def build_hybrid_answer(status: str, success: bool, report_md: str, validated_moves: list | None):
    """
    ✅ 말풍선 안에:
    - 상태
    - 조치계획
    - Δ 표
    - (접힘) 상세(검증/CAPA/원문)
    """
    sections = split_report_sections(report_md)
    action_key = next((k for k in sections.keys() if "최종 조치 계획" in k), None)
    action_body = sections.get(action_key, "").strip() or "(조치계획 없음)"

    delta_md = build_delta_markdown(validated_moves)

    # details는 HTML로 넣어야 하므로 raw_html token 방식 사용
    token = "[[HY_DETAILS]]"
    raw_html_blocks = {token: build_details_html(report_md)}

    md = []
    md.append(f"{'✅' if success else '⚠️'} **{status}**")
    md.append("")
    md.append("🧾 **조치계획(이동 내역)**")
    md.append(action_body)
    md.append("")
    md.append("---")
    md.append(delta_md)
    md.append("")
    md.append(token)

    bubble_html = markdown_to_html("\n".join(md), raw_html_blocks=raw_html_blocks)
    return bubble_html


# ==================== 커스텀 메시지 출력 ====================
def display_message(role: str, content: str, already_html: bool = False):
    if not content:
        return

    if role == "user":
        avatar_html = f'<img src="data:image/png;base64,{user_avatar_base64}" alt="User">' if user_avatar_base64 else ""
    else:
        avatar_html = f'<img src="data:image/png;base64,{ai_avatar_base64}" alt="AI">' if ai_avatar_base64 else ""

    if already_html:
        html_content = content  # 하이브리드: 이미 HTML로 만들어 둠
    else:
        html_content = markdown_to_html(content)  # legacy: 기존 마크다운을 안전하게 렌더

    html_output = f"""
    <div class="message-row {role}">
        <div class="avatar {role}">{avatar_html}</div>
        <div class="message-bubble {role}">{html_content}</div>
    </div>
    """
    st.markdown(html_output, unsafe_allow_html=True)


def display_loading():
    avatar_html = f'<img src="data:image/png;base64,{ai_avatar_base64}" alt="AI">' if ai_avatar_base64 else ""
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


# ==================== 세션 상태 ====================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "is_loading" not in st.session_state:
    st.session_state.is_loading = False


# ==================== 화면 ====================
st.markdown('<div class="chat-container">', unsafe_allow_html=True)

for msg in st.session_state.messages:
    # msg = {"role": "assistant"/"user", "content": "...", "html": bool}
    if isinstance(msg, dict) and "role" in msg and "content" in msg:
        display_message(
            msg["role"],
            msg["content"],
            already_html=bool(msg.get("html", False)),
        )

if st.session_state.is_loading:
    display_loading()

st.markdown("</div>", unsafe_allow_html=True)


# ==================== 입력 ====================
if prompt := st.chat_input("무엇을 도와드릴까요?"):
    st.session_state.messages.append({"role": "user", "content": prompt, "html": False})
    st.session_state.is_loading = True
    st.rerun()


# ==================== 응답 생성 ====================
if st.session_state.is_loading:
    user_msgs = [m for m in st.session_state.messages if isinstance(m, dict) and m.get("role") == "user"]
    if user_msgs:
        prompt = user_msgs[-1]["content"]
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
                    st.session_state.messages.append(
                        {"role": "assistant", "content": "❌ 데이터를 불러올 수 없습니다. 날짜를 확인해주세요.", "html": False}
                    )
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

                    # 반환 길이 안전 처리
                    report, success, charts, status, validated_moves = "", False, None, "", None
                    if isinstance(result, (tuple, list)):
                        if len(result) == 5:
                            report, success, charts, status, validated_moves = result
                        elif len(result) == 4:
                            report, success, charts, status = result
                        else:
                            report = str(result)
                            status = "생산계획 조정 결과를 파싱하지 못했습니다."
                            success = False
                    else:
                        report = str(result)
                        status = "생산계획 조정 결과를 파싱하지 못했습니다."
                        success = False

                    status = str(status).replace("하이브리드 수사", "생산계획 조정")

                    # ✅ 말풍선 안에 전부 포함(HTML)
                    bubble_html = build_hybrid_answer(
                        status=status,
                        success=bool(success),
                        report_md=str(report),
                        validated_moves=validated_moves,
                    )

                    st.session_state.messages.append({"role": "assistant", "content": bubble_html, "html": True})

            else:
                # ✅ legacy는 그대로: 가공 X (표/마크다운 깨짐 방지)
                db_result = fetch_db_data_legacy(prompt, supabase)
                if "찾을 수 없습니다" in db_result or "오류" in db_result:
                    answer = db_result
                else:
                    answer = query_gemini_ai_legacy(prompt, db_result, GENAI_KEY)

                st.session_state.messages.append({"role": "assistant", "content": answer, "html": False})

        except Exception as e:
            st.session_state.messages.append(
                {"role": "assistant", "content": f"❌ **오류 발생**\n\n```\n{str(e)}\n```", "html": False}
            )

        finally:
            st.session_state.is_loading = False
            st.rerun()


# ==================== CAPA 차트(기존 유지) ====================
# 말풍선 아래에 표시되는 건 싫다면 이 블록을 주석 처리해도 됨.
last_user_msgs = [m for m in st.session_state.messages if m.get("role") == "user"]
if last_user_msgs:
    last_prompt = last_user_msgs[-1]["content"]
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
        if isinstance(plan_df, pd.DataFrame) and not plan_df.empty and "qty_1차" in plan_df.columns:
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

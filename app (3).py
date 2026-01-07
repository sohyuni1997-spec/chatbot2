import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from datetime import datetime, timedelta
import plotly.graph_objects as go
import re
import base64
import os

# ❗ legacy / hybrid 모듈은 그대로 사용 (수정 없음)
from legacy import fetch_db_data_legacy, query_gemini_ai_legacy
from hybrid import ask_professional_scheduler


# ==================== 환경 설정 ====================
st.set_page_config(page_title="orcHatStra", page_icon="🎯", layout="wide")


# ==================== 이미지 로더 (기존 방식 유지) ====================
def get_base64_of_bin_file(bin_file: str):
    candidates = [
        os.path.join("assets", bin_file),
        bin_file,
        os.path.join(os.getcwd(), bin_file),
        os.path.join(os.getcwd(), "assets", bin_file),
    ]
    if "__file__" in globals():
        candidates += [
            os.path.join(os.path.dirname(__file__), bin_file),
            os.path.join(os.path.dirname(__file__), "assets", bin_file),
        ]
    for path in candidates:
        try:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            pass
    return None


logo_base64 = get_base64_of_bin_file("HSE.svg") or get_base64_of_bin_file("logo.svg")
ai_avatar_base64 = get_base64_of_bin_file("ai 아바타.png") or get_base64_of_bin_file("ai_avatar.png")
user_avatar_base64 = get_base64_of_bin_file("이력서 사진.v카툰.png") or get_base64_of_bin_file("user_avatar.png")


# ==================== CSS (채팅 UI "박스"만. 내용 변환 없음) ====================
st.markdown(
    """
<style>
[data-testid="stHeader"] { display: none; }
.stApp { background-color: #F5F5F7; }
.main { padding-top: 90px !important; }

/* 고정 헤더 */
.fixed-header{
  position:fixed; top:0; left:0; right:0; height:70px;
  background:white; border-bottom:1px solid #E5E5EA;
  display:flex; align-items:center; gap:16px; padding:0 32px;
  z-index:9999;
}

/* "하이브리드 요약" 말풍선(텍스트만) */
.hy-bubble-wrap{ max-width: 900px; margin: 0 auto; padding: 12px 20px; }
.hy-row{ display:flex; margin-bottom: 14px; align-items:flex-start; }
.hy-row.user{ flex-direction: row-reverse; }
.hy-avatar{
  width:40px; height:40px; border-radius:50%;
  overflow:hidden; margin:0 12px;
  box-shadow:0 3px 10px rgba(0,0,0,0.15);
  background:#fff;
}
.hy-avatar img{ width:100%; height:100%; object-fit:cover; display:block; }
.hy-bubble{
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 18px;
  line-height: 1.6;
  font-size: 15px;
  background: white;
  border: 1px solid #E5E5EA;
}
.hy-bubble.user{
  background: linear-gradient(135deg,#007AFF,#0051D5);
  color: white;
  border: none;
}

/* 버블 내부 표 스타일 */
.hy-bubble table {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 14px;
}
.hy-bubble table th {
  background-color: #f0f0f0;
  padding: 8px;
  border: 1px solid #ddd;
  text-align: left;
  font-weight: 600;
}
.hy-bubble table td {
  padding: 8px;
  border: 1px solid #ddd;
}
.hy-bubble table tr:nth-child(even) {
  background-color: #f9f9f9;
}
.hy-bubble.user table th {
  background-color: rgba(255,255,255,0.2);
  color: white;
  border-color: rgba(255,255,255,0.3);
}
.hy-bubble.user table td {
  border-color: rgba(255,255,255,0.3);
}

/* 버블 내부 코드블록 스타일 */
.hy-bubble pre {
  background-color: #f5f5f5;
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 10px 0;
}
.hy-bubble code {
  background-color: #f5f5f5;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
}
.hy-bubble.user pre {
  background-color: rgba(255,255,255,0.2);
}
.hy-bubble.user code {
  background-color: rgba(255,255,255,0.2);
}
</style>
""",
    unsafe_allow_html=True,
)


# ==================== 고정 헤더 ====================
st.markdown(
    f"""
<div class="fixed-header">
  {f'<img src="data:image/svg+xml;base64,{logo_base64}" height="40">' if logo_base64 else ''}
  <h2 style="margin:0">orcHatStra</h2>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown("<div style='height:90px'></div>", unsafe_allow_html=True)


# ==================== Secrets ====================
try:
    URL = st.secrets.get("SUPABASE_URL")
    KEY = st.secrets.get("SUPABASE_KEY")
    GENAI_KEY = st.secrets.get("GEMINI_API_KEY")
except Exception:
    URL, KEY, GENAI_KEY = "", "", ""


@st.cache_resource
def init_supabase():
    return create_client(URL, KEY)

supabase: Client = init_supabase()
if GENAI_KEY:
    genai.configure(api_key=GENAI_KEY)


# ==================== 파라미터 ====================
CAPA_LIMITS = {"조립1": 3300, "조립2": 3700, "조립3": 3600}
TEST_MODE = True
TODAY = datetime(2026, 1, 5).date() if TEST_MODE else datetime.now().date()


# ==================== 유틸 ====================
def extract_date(text: str | None):
    if not text:
        return None
    patterns = [
        r"(2026-\d{2}-\d{2})",
        r"(\d{1,2})/(\d{1,2})",
        r"(\d{1,2})월\s*(\d{1,2})일",
    ]
    for p in patterns:
        m = re.search(p, text)
        if not m:
            continue
        if p.startswith("(2026-"):
            return m.group(1)
        mm = int(m.group(1))
        dd = int(m.group(2))
        return f"2026-{mm:02d}-{dd:02d}"
    return None


def markdown_to_html(text: str) -> str:
    """
    간단한 markdown → HTML 변환
    표, 코드블록, 볼드, 이탤릭, 링크 등을 HTML로 변환
    """
    if not text:
        return ""
    
    html = text
    
    # 코드블록 (```)
    html = re.sub(r'```(.*?)```', r'<pre><code>\1</code></pre>', html, flags=re.DOTALL)
    
    # 인라인 코드 (`)
    html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
    
    # 볼드 (**)
    html = re.sub(r'\*\*([^\*]+)\*\*', r'<strong>\1</strong>', html)
    
    # 이탤릭 (*)
    html = re.sub(r'\*([^\*]+)\*', r'<em>\1</em>', html)
    
    # 링크
    html = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', html)
    
    # 표 변환 (markdown table → HTML table)
    lines = html.split('\n')
    in_table = False
    result_lines = []
    
    for i, line in enumerate(lines):
        # 표 감지 (|로 시작하거나 포함)
        if '|' in line and line.strip().startswith('|'):
            if not in_table:
                # 표 시작
                result_lines.append('<table>')
                in_table = True
                
                # 헤더 행
                cells = [cell.strip() for cell in line.strip().split('|')[1:-1]]
                result_lines.append('<thead><tr>')
                for cell in cells:
                    result_lines.append(f'<th>{cell}</th>')
                result_lines.append('</tr></thead>')
                result_lines.append('<tbody>')
                
            elif i > 0 and re.match(r'^\s*\|[\s\-:]+\|\s*$', line):
                # 구분선 (|---|---|) 무시
                continue
            else:
                # 데이터 행
                cells = [cell.strip() for cell in line.strip().split('|')[1:-1]]
                result_lines.append('<tr>')
                for cell in cells:
                    result_lines.append(f'<td>{cell}</td>')
                result_lines.append('</tr>')
        else:
            if in_table:
                # 표 종료
                result_lines.append('</tbody></table>')
                in_table = False
            result_lines.append(line)
    
    # 표가 끝나지 않은 경우
    if in_table:
        result_lines.append('</tbody></table>')
    
    html = '\n'.join(result_lines)
    
    # 줄바꿈을 <br>로
    html = html.replace('\n', '<br>')
    
    return html


@st.cache_data(ttl=600)
def fetch_data(target_date: str | None = None):
    """하이브리드용 데이터 로드 (legacy 경로 영향 없음)"""
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

        product_map, plt_map = {}, {}
        if not plan_df.empty and "product_name" in plan_df.columns:
            plan_df["name_clean"] = plan_df["product_name"].apply(lambda x: re.sub(r"\s+", "", str(x)).strip())
            if "plt" in plan_df.columns:
                plt_map = plan_df.groupby("name_clean")["plt"].first().to_dict()
            if "line" in plan_df.columns:
                product_map = plan_df.groupby("name_clean")["line"].unique().to_dict()

            # T6 예외 유지(기존 로직)
            for k in list(product_map.keys()):
                if "T6" in str(k).upper():
                    product_map[k] = ["조립1", "조립2", "조립3"]

        return plan_df, hist_df, product_map, plt_map

    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), {}, {}


def moves_to_delta_df(validated_moves: list[dict] | None) -> pd.DataFrame:
    """Δ는 markdown 표 금지 → DataFrame으로만 생성"""
    if not validated_moves:
        return pd.DataFrame(columns=["date", "item", "line", "delta"])

    rows = []
    for mv in validated_moves:
        item = str(mv.get("item", "")).strip()
        qty = int(mv.get("qty", 0) or 0)
        from_loc = str(mv.get("from", "") or "")
        to_loc = str(mv.get("to", "") or "")

        if not item or qty <= 0 or "_" not in from_loc or "_" not in to_loc:
            continue

        from_date, from_line = [x.strip() for x in from_loc.split("_", 1)]
        to_date, to_line = [x.strip() for x in to_loc.split("_", 1)]

        rows.append({"date": from_date, "item": item, "line": from_line, "delta": -qty})
        rows.append({"date": to_date, "item": item, "line": to_line, "delta": +qty})

    return pd.DataFrame(rows, columns=["date", "item", "line", "delta"])


# ==================== 세션 ====================
if "messages" not in st.session_state:
    st.session_state.messages = []  # user/hybrid_summary/legacy
if "is_loading" not in st.session_state:
    st.session_state.is_loading = False
if "last_hybrid" not in st.session_state:
    st.session_state.last_hybrid = None


# ==================== "하이브리드 요약 말풍선" 렌더 ====================
def render_hybrid_bubble(role: str, text: str):
    """
    hybrid 대화창 렌더링 (markdown → HTML 변환 지원)
    """
    if not text:
        return

    if role == "user":
        avatar_img = user_avatar_base64
    else:
        avatar_img = ai_avatar_base64

    avatar_html = (
        f'<img src="data:image/png;base64,{avatar_img}">' if avatar_img else ""
    )
    
    # ✅ markdown을 HTML로 변환
    content_html = markdown_to_html(text)

    st.markdown(
        f"""
<div class="hy-bubble-wrap">
  <div class="hy-row {role}">
    <div class="hy-avatar">{avatar_html}</div>
    <div class="hy-bubble {role}">
      {content_html}
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


# ==================== 채팅 표시 ====================
# ✅ legacy 출력은 "기존 Streamlit markdown 렌더링 그대로" 유지
for m in st.session_state.messages:
    role = m.get("role")
    engine = m.get("engine")  # "legacy" | "hybrid"
    content = m.get("content", "")

    if engine == "legacy":
        # ✅ 영향 0: 기존 Streamlit markdown 그대로
        st.markdown(content)
    else:
        # ✅ hybrid: markdown → HTML 변환하여 버블로 표시
        render_hybrid_bubble(role, content)


# ==================== 입력 ====================
if prompt := st.chat_input("무엇을 도와드릴까요?"):
    st.session_state.messages.append({"role": "user", "content": prompt, "engine": "hybrid"})
    st.session_state.is_loading = True
    st.rerun()


# ==================== 응답 생성 ====================
if st.session_state.is_loading:
    prompt = st.session_state.messages[-1]["content"]
    target_date = extract_date(prompt)

    is_adjustment_mode = bool(target_date) and (
        any(x in prompt for x in ["조립1", "조립2", "조립3", "조립"])
        or re.search(r"\d+%", prompt) is not None
        or "CAPA" in prompt.upper()
        or any(x in prompt for x in ["줄여", "늘려", "추가", "증량", "감량"])
    )

    try:
        if is_adjustment_mode:
            plan_df, hist_df, product_map, plt_map = fetch_data(target_date)

            if plan_df.empty:
                summary = "❌ 데이터를 불러올 수 없습니다. 날짜/테이블을 확인해주세요."
                st.session_state.messages.append({"role": "assistant", "content": summary, "engine": "hybrid"})
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

                report, success, charts, status, validated_moves = "", False, None, "", None
                if isinstance(result, (tuple, list)):
                    if len(result) == 5:
                        report, success, charts, status, validated_moves = result
                    elif len(result) == 4:
                        report, success, charts, status = result
                    else:
                        report = str(result)
                        status = "생산계획 조정 결과를 파싱하지 못했습니다."
                else:
                    report = str(result)
                    status = "생산계획 조정 결과를 파싱하지 못했습니다."

                # ✅ 말풍선에 전체 report 표시 (markdown 표 포함)
                summary = f"{'✅' if success else '⚠️'} {status}\n\n{report}"
                st.session_state.messages.append({"role": "assistant", "content": summary, "engine": "hybrid"})

                # ✅ 상세 보기 데이터 저장
                st.session_state.last_hybrid = {
                    "status": status,
                    "success": bool(success),
                    "report_md": report,
                    "validated_moves": validated_moves,
                    "plan_df": plan_df,
                    "target_date": target_date,
                }

        else:
            # ✅ legacy 경로 (영향 0)
            ctx = fetch_db_data_legacy(prompt, supabase)
            answer = ctx if ("찾을 수 없습니다" in ctx or "오류" in ctx) else query_gemini_ai_legacy(prompt, ctx, GENAI_KEY)
            st.session_state.messages.append({"role": "assistant", "content": answer, "engine": "legacy"})
            st.session_state.last_hybrid = None

    except Exception as e:
        st.session_state.messages.append(
            {"role": "assistant", "content": f"❌ **오류 발생**\n\n```\n{str(e)}\n```", "engine": "legacy"}
        )
        st.session_state.last_hybrid = None
    finally:
        st.session_state.is_loading = False
        st.rerun()


# ==================== 상세 보기(Expander + Tabs) ====================
if not st.session_state.is_loading and st.session_state.last_hybrid:
    last = st.session_state.last_hybrid
    report_md = last.get("report_md", "")
    plan_df = last.get("plan_df")
    validated_moves = last.get("validated_moves")

    st.markdown("---")
    with st.expander("📦 상세 보기", expanded=False):
        t1, t2, t3, t4 = st.tabs(["🧾 조치계획", "📊 Δ", "🔎 검증/원문", "📈 CAPA 그래프"])

        with t1:
            # ✅ 조치계획: Streamlit native markdown
            st.markdown(report_md)

        with t2:
            # ✅ Δ: 무조건 dataframe
            delta_df = moves_to_delta_df(validated_moves)
            if delta_df.empty:
                st.info("Δ(변경량) 데이터가 없습니다.")
            else:
                # 보기 좋게 피벗
                pivot = (
                    delta_df.pivot_table(index=["date", "item"], columns="line", values="delta", aggfunc="sum", fill_value=0)
                    .reset_index()
                )
                # 컬럼 정렬
                for col in ["조립1", "조립2", "조립3"]:
                    if col not in pivot.columns:
                        pivot[col] = 0
                pivot = pivot[["date", "item", "조립1", "조립2", "조립3"]]
                st.dataframe(pivot, use_container_width=True)

        with t3:
            # ✅ 검증/원문: Streamlit native markdown
            st.markdown(report_md)

        with t4:
            # ✅ CAPA 그래프: plotly + dataframe
            if isinstance(plan_df, pd.DataFrame) and (not plan_df.empty) and ("qty_1차" in plan_df.columns):
                daily = plan_df.groupby(["plan_date", "line"])["qty_1차"].sum().reset_index()
                daily.columns = ["plan_date", "line", "current_qty"]
                daily["max_capa"] = daily["line"].map(CAPA_LIMITS)
                daily["remaining_capa"] = daily["max_capa"] - daily["current_qty"]

                chart_data = daily.pivot(index="plan_date", columns="line", values="current_qty").fillna(0)

                fig = go.Figure()
                for line in ["조립1", "조립2", "조립3"]:
                    if line in chart_data.columns:
                        fig.add_trace(go.Bar(name=line, x=chart_data.index, y=chart_data[line]))

                # CAPA limit line
                for line, limit in CAPA_LIMITS.items():
                    fig.add_hline(y=limit, line_dash="dash", annotation_text=f"{line} 한계: {limit:,}", annotation_position="right")

                fig.update_layout(
                    barmode="group",
                    height=450,
                    xaxis_title="날짜",
                    yaxis_title="수량(개)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    hovermode="x unified",
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=20, r=20, t=40, b=20),
                )

                st.plotly_chart(fig, use_container_width=True)
                st.markdown("##### 📋 CAPA 상세 데이터")
                st.dataframe(daily, use_container_width=True)
            else:
                st.info("CAPA 그래프를 그릴 데이터가 없습니다.")


# ==================== END ====================
pass

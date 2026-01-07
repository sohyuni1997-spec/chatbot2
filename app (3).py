import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from datetime import datetime, timedelta
import plotly.graph_objects as go
import re
import base64
import os

from legacy import fetch_db_data_legacy, query_gemini_ai_legacy
from hybrid import ask_professional_scheduler

# ==================== 환경 설정 ====================
st.set_page_config(page_title="orcHatStra", page_icon="🎯", layout="wide")

# ==================== 이미지 로딩 (없어도 UI 유지) ====================
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

logo_base64 = get_base64_of_bin_file("logo.svg")
ai_avatar_base64 = get_base64_of_bin_file("ai_avatar.png")
user_avatar_base64 = get_base64_of_bin_file("user_avatar.png")

# ==================== CSS ====================
st.markdown(
    """
<style>
:root{
  --bg-primary:#F5F5F7; --bg-secondary:#FFFFFF;
  --text-primary:#000000; --border-color:#E5E5EA;
  --shadow-light: rgba(0,0,0,0.1); --shadow-medium: rgba(0,0,0,0.15);
  --user-start:#007AFF; --user-end:#0051D5;
  --header-bg:#FFFFFF; --header-text:#000000;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg-primary:#000000; --bg-secondary:#1C1C1E;
    --text-primary:#FFFFFF; --border-color:#38383A;
    --shadow-light: rgba(255,255,255,0.08); --shadow-medium: rgba(255,255,255,0.12);
    --user-start:#0A84FF; --user-end:#0066CC;
    --header-bg:#1C1C1E; --header-text:#FFFFFF;
  }
}
.stApp{background-color:var(--bg-primary);}
.main{background-color:var(--bg-primary); padding-top:100px !important;}
[data-testid="stHeader"]{display:none;}

.fixed-header{
  position:fixed; top:0; left:0; right:0; height:80px;
  background-color:var(--header-bg); border-bottom:1px solid var(--border-color);
  z-index:9999; display:flex; align-items:center; justify-content:center;
  padding:0 40px; box-shadow:0 2px 10px var(--shadow-light);
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
}
.header-content{width:100%; max-width:1400px; display:flex; align-items:center; gap:20px;}
.header-logo{height:50px; width:auto; display:block;}
.header-title{
  color:var(--header-text); font-weight:800; font-size:2.5rem;
  letter-spacing:-1.5px; font-family:-apple-system,BlinkMacSystemFont,sans-serif; margin:0;
}

/* Streamlit 기본 chat message 숨김 */
[data-testid="stChatMessage"]{display:none !important;}

.chat-container{max-width:900px; margin:0 auto; padding:20px;}
.message-row{display:flex; margin-bottom:16px; align-items:flex-start;}
.message-row.user{flex-direction:row-reverse;}
.avatar{
  width:40px; height:40px; min-width:40px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  overflow:hidden; box-shadow:0 3px 10px var(--shadow-medium);
}
.avatar.user{margin-left:12px;}
.avatar.assistant{margin-right:12px;}
.avatar img{width:100%; height:100%; object-fit:cover; display:block;}

.message-bubble{
  max-width:70%; padding:12px 18px; border-radius:20px;
  font-size:15px; line-height:1.6; word-wrap:break-word; overflow-wrap:break-word;
  color:var(--text-primary);
}
.message-bubble.user{
  background:linear-gradient(135deg,var(--user-start) 0%, var(--user-end) 100%);
  color:white; border-top-right-radius:4px;
  box-shadow:0 3px 12px rgba(0,122,255,0.25);
}
.message-bubble.assistant{
  background-color:var(--bg-secondary);
  border-top-left-radius:4px;
  box-shadow:0 2px 8px var(--shadow-light);
  border:1px solid var(--border-color);
}

/* 말풍선 내부 표가 잘리지 않게 */
.message-bubble table{display:block; width:100%; overflow-x:auto; white-space:nowrap;}
.message-bubble th,.message-bubble td{padding:8px 10px; border:1px solid var(--border-color);}

/* 로딩 */
.loading-bubble{
  max-width:70%; padding:16px 18px; border-radius:20px; background-color:var(--bg-secondary);
  border-top-left-radius:4px; border:1px solid var(--border-color);
  display:flex; align-items:center; gap:6px;
}
.loading-dot{width:8px;height:8px;border-radius:50%;background:#8E8E93; animation:loadingPulse 1.4s ease-in-out infinite;}
.loading-dot:nth-child(2){animation-delay:.2s;}
.loading-dot:nth-child(3){animation-delay:.4s;}
@keyframes loadingPulse{0%,60%,100%{opacity:.3;transform:scale(.8)} 30%{opacity:1;transform:scale(1.1)}}

/* expander */
.streamlit-expanderHeader{
  background-color:var(--bg-secondary) !important;
  border-radius:16px !important;
  color:var(--text-primary) !important;
  border:1px solid var(--border-color) !important;
  padding:12px 16px !important;
  box-shadow:0 2px 6px var(--shadow-light) !important;
}
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

# ==================== Secrets 처리 ====================
try:
    URL = st.secrets.get("SUPABASE_URL", "https://qipphcdzlmqidhrjnjtt.supabase.co")
    KEY = st.secrets.get("SUPABASE_KEY", "")
    GENAI_KEY = st.secrets.get("GEMINI_API_KEY", "")
except Exception:
    URL = "https://qipphcdzlmqidhrjnjtt.supabase.co"
    KEY = ""
    GENAI_KEY = ""

@st.cache_resource
def init_supabase():
    return create_client(URL, KEY)

supabase: Client = init_supabase()
genai.configure(api_key=GENAI_KEY)

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
    patterns = [r"(\d{1,2})/(\d{1,2})", r"(\d{1,2})월\s*(\d{1,2})일", r"202[56]-(\d{1,2})-(\d{1,2})"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            m, d = match.groups()
            return f"2026-{int(m):02d}-{int(d):02d}"
    return None

# ==================== Hybrid 섹션 파서/Δ ====================
def split_report_sections(report_md: str) -> dict:
    if not report_md:
        return {"__FULL__": ""}
    parts = re.split(r"\n##\s+", report_md.strip())
    sections = {"__FULL__": report_md.strip()}
    for p in parts[1:]:
        lines = p.splitlines()
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        sections[title] = body
    return sections

def build_delta_table_md(validated_moves: list[dict] | None) -> str:
    if not validated_moves:
        return "*(변경량 데이터 없음)*"

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

        records.append({"date": from_date, "item": item, "line": from_line, "delta": -qty})
        records.append({"date": to_date, "item": item, "line": to_line, "delta": +qty})

    df = pd.DataFrame(records)
    if df.empty:
        return "*(변경량 데이터 없음)*"

    out = []
    for date in sorted(df["date"].unique()):
        day = df[df["date"] == date].copy()
        pivot = (
            day.pivot_table(index="item", columns="line", values="delta", aggfunc="sum", fill_value=0)
            .reindex(columns=["조립1", "조립2", "조립3"])
            .fillna(0)
        )
        # 마크다운 표 만들기
        out.append(f"#### 📅 {date} 기준 변경분")
        out.append("| item | 조립1 | 조립2 | 조립3 |")
        out.append("|---|---:|---:|---:|")
        for idx, row in pivot.iterrows():
            def fmt(v):
                v = int(v)
                return "" if v == 0 else f"{v:+,}"
            out.append(f"| {idx} | {fmt(row.get('조립1',0))} | {fmt(row.get('조립2',0))} | {fmt(row.get('조립3',0))} |")
        out.append("")
    return "\n".join(out).strip()

# ==================== 말풍선 렌더 (Legacy 0 영향) ====================
def render_bubble(role: str, md_text: str, engine: str | None = None):
    """
    engine == 'legacy' -> 절대 커스텀 변환하지 않음(legacy 0 영향)
    engine == 'hybrid' -> 말풍선 안에 markdown 그대로 넣되(표 포함), streamlit markdown이 아닌 HTML bubble에 넣기 위해
                        최소한의 escape + <br> 처리만 수행.
    """
    if not md_text:
        return

    # 아바타
    if role == "user":
        if user_avatar_base64:
            avatar = f'<img src="data:image/png;base64,{user_avatar_base64}" alt="user">'
        else:
            avatar = "🙂"
    else:
        if ai_avatar_base64:
            avatar = f'<img src="data:image/png;base64,{ai_avatar_base64}" alt="ai">'
        else:
            avatar = "🤖"

    if engine == "legacy":
        # ✅ legacy는 버블 대신 기본 markdown으로 그대로 출력 (0 영향)
        # 버블 UI를 쓰고 싶으면 legacy도 HTML 변환을 해야 하는데, 그 순간 "영향 0"이 깨져.
        st.markdown(md_text)
        return

    # hybrid/user는 버블 UI
    import html
    safe = html.escape(md_text)
    safe = safe.replace("\n", "<br>")
    bubble = f"""
    <div class="message-row {role}">
      <div class="avatar {role}">{avatar}</div>
      <div class="message-bubble {role}">{safe}</div>
    </div>
    """
    st.markdown(bubble, unsafe_allow_html=True)

def render_loading():
    avatar = f'<img src="data:image/png;base64,{ai_avatar_base64}" alt="ai">' if ai_avatar_base64 else "🤖"
    st.markdown(
        f"""
        <div class="message-row assistant">
          <div class="avatar assistant">{avatar}</div>
          <div class="loading-bubble">
            <div class="loading-dot"></div><div class="loading-dot"></div><div class="loading-dot"></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ==================== 세션 상태 ====================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "is_loading" not in st.session_state:
    st.session_state.is_loading = False
if "last_hybrid" not in st.session_state:
    st.session_state.last_hybrid = None

# ==================== 채팅 영역 ====================
st.markdown('<div class="chat-container">', unsafe_allow_html=True)

for msg in st.session_state.messages:
    if not isinstance(msg, dict):
        continue
    role = msg.get("role")
    content = msg.get("content", "")
    engine = msg.get("engine")  # legacy / hybrid / None
    render_bubble(role, content, engine=engine)

if st.session_state.is_loading:
    render_loading()

st.markdown("</div>", unsafe_allow_html=True)

# ==================== 입력 ====================
if prompt := st.chat_input("무엇을 도와드릴까요?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.is_loading = True
    st.rerun()

# ==================== 응답 생성 ====================
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
            or "추가" in prompt
        )

        try:
            if is_adjustment_mode:
                plan_df, hist_df, product_map, plt_map = fetch_data(target_date)
                if plan_df.empty:
                    answer = "❌ 데이터를 불러올 수 없습니다. 날짜를 확인해주세요."
                    st.session_state.last_hybrid = None
                    st.session_state.messages.append({"role": "assistant", "content": answer, "engine": "hybrid"})
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

                    report = ""
                    success = False
                    charts = None
                    status = ""
                    validated_moves = None

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

                    sections = split_report_sections(report)
                    action_key = next((k for k in sections.keys() if "최종 조치 계획" in k or "조치" in k), None)
                    action_body = sections.get(action_key, "").strip()

                    delta_md = build_delta_table_md(validated_moves)

                    # ✅ 말풍선에는 "조치계획 + Δ"까지만 넣고, 상세(검증/CAPA/원문)는 아래 탭에서
                    bubble_text = []
                    bubble_text.append(f"{'✅' if success else '⚠️'} [{('OK' if success else 'WARN')}] {status}")
                    bubble_text.append("")
                    bubble_text.append("🧾 **조치계획(이동 내역)**")
                    bubble_text.append(action_body if action_body else "*(조치계획 없음)*")
                    bubble_text.append("")
                    bubble_text.append("---")
                    bubble_text.append("📊 **생산계획 변경량 요약(Δ)**")
                    bubble_text.append(delta_md)
                    bubble_text.append("")
                    bubble_text.append("*(상세 보기 탭에서 검증 글 + CAPA 그래프 확인 가능)*")

                    st.session_state.messages.append(
                        {"role": "assistant", "content": "\n".join(bubble_text), "engine": "hybrid"}
                    )

                    st.session_state.last_hybrid = {
                        "status": status,
                        "success": bool(success),
                        "report_md": report,
                        "validated_moves": validated_moves,
                        "plan_df": plan_df,
                        "target_date": target_date,
                    }

            else:
                # ✅ legacy는 그대로 (0 영향)
                db_result = fetch_db_data_legacy(prompt, supabase)
                if "찾을 수 없습니다" in db_result or "오류" in db_result:
                    answer = db_result
                else:
                    answer = query_gemini_ai_legacy(prompt, db_result, GENAI_KEY)

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

# ==================== 상세 보기(탭) + CAPA 그래프 ====================
# ✅ 여기에서만 긴 검증 글(원문)을 보여줌. 말풍선에는 절대 토큰 노출 없음.
if not st.session_state.is_loading and st.session_state.last_hybrid:
    last = st.session_state.last_hybrid
    report_md = last.get("report_md", "")
    plan_df = last.get("plan_df")

    st.markdown("---")
    with st.expander("📌 상세 보기", expanded=False):
        tab1, tab2 = st.tabs(["🔎 검증/원문", "📊 CAPA 그래프"])

        with tab1:
            # hybrid 보고서 전체를 그대로 보여줌 (Streamlit markdown)
            # = 긴 검증 글/표/헤더 그대로 렌더
            st.markdown(report_md)

        with tab2:
            if isinstance(plan_df, pd.DataFrame) and not plan_df.empty and "qty_1차" in plan_df.columns:
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
                                name=line,
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
                    yaxis_title="수량(개)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    hovermode="x unified",
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=20, r=20, t=40, b=20),
                )

                st.plotly_chart(fig, use_container_width=True)

                st.markdown("##### 📋 CAPA 상세 데이터")
                st.dataframe(
                    daily_summary.style.format(
                        {"current_qty": "{:,.0f}", "max_capa": "{:,.0f}", "remaining_capa": "{:,.0f}"}
                    ),
                    use_container_width=True,
                )
            else:
                st.info("CAPA 그래프를 그릴 데이터가 없습니다.")

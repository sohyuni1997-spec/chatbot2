# app (3).py
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


# ✅ 너가 쓰던 파일명 우선, 없으면 assets 기본명 fallback
logo_base64 = (
    get_base64_of_bin_file("HSE.svg")
    or get_base64_of_bin_file("logo.svg")
    or get_base64_of_bin_file("logo.png")
)
ai_avatar_base64 = (
    get_base64_of_bin_file("ai 아바타.png")
    or get_base64_of_bin_file("ai_avatar.png")
)
user_avatar_base64 = (
    get_base64_of_bin_file("이력서 사진.v카툰.png")
    or get_base64_of_bin_file("user_avatar.png")
)


# ==================== CSS ====================
# ✅ 핵심: Hybrid는 st.chat_message를 쓸 거라서
#    [data-testid="stChatMessage"] 숨김은 절대 하면 안 됨!
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

/* Legacy 출력 영역을 구분하고 싶으면(선택)
.legacy-wrap { max-width: 900px; margin: 0 auto; }
*/

/* expander */
.streamlit-expanderHeader{
  background-color: #FFFFFF !important;
  border-radius:16px !important;
  border:1px solid #E5E5EA !important;
  padding:12px 16px !important;
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


# ==================== Secrets 처리 ====================
try:
    URL = st.secrets.get("SUPABASE_URL", "")
    KEY = st.secrets.get("SUPABASE_KEY", "")
    GENAI_KEY = st.secrets.get("GEMINI_API_KEY", "")
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


@st.cache_data(ttl=600)
def fetch_data(target_date: str | None = None):
    """
    하이브리드용 데이터 로드
    - legacy 경로 영향 없음
    """
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

            # 기존 로직 유지: T6는 전 라인 가능 처리
            for k in list(product_map.keys()):
                if "T6" in str(k).upper():
                    product_map[k] = ["조립1", "조립2", "조립3"]

        return plan_df, hist_df, product_map, plt_map

    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), {}, {}


def moves_to_delta_df(validated_moves: list[dict] | None) -> pd.DataFrame:
    """
    Δ(변경량) DataFrame 생성
    - 표 깨짐 방지: expander에서 st.dataframe으로만 보여주기 위한 데이터 준비
    """
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


# ==================== 렌더링 ====================
def render_message(msg: dict):
    """
    ✅ 핵심
    - legacy: st.markdown 그대로 (영향 0)
    - hybrid: st.chat_message + st.markdown (표/마크다운 완전 보장)
    """
    role = msg.get("role")
    engine = msg.get("engine")  # "legacy" | "hybrid"
    content = msg.get("content", "")

    if engine == "legacy":
        # ✅ legacy 0 영향: 기존 Streamlit markdown 렌더링 그대로
        st.markdown(content)
        return

    # ✅ hybrid는 chat_message로 렌더 (표/헤더/리스트 깨짐 방지)
    avatar = None
    if role == "assistant" and ai_avatar_base64:
        avatar = f"data:image/png;base64,{ai_avatar_base64}"
    elif role == "user" and user_avatar_base64:
        avatar = f"data:image/png;base64,{user_avatar_base64}"

    with st.chat_message(role, avatar=avatar):
        st.markdown(content)


# ==================== 세션 상태 ====================
if "messages" not in st.session_state:
    st.session_state.messages = []  # dict: {role, content, engine}
if "is_loading" not in st.session_state:
    st.session_state.is_loading = False
if "last_hybrid" not in st.session_state:
    st.session_state.last_hybrid = None


# ==================== 채팅 표시 ====================
for m in st.session_state.messages:
    if isinstance(m, dict):
        render_message(m)


# ==================== 입력 ====================
if prompt := st.chat_input("무엇을 도와드릴까요?"):
    # user 메시지는 hybrid로 표시 (원하면 legacy로도 가능하지만 일단 통일)
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
                answer = "❌ 데이터를 불러올 수 없습니다. 날짜/테이블을 확인해주세요."
                st.session_state.messages.append({"role": "assistant", "content": answer, "engine": "hybrid"})
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
                        success = False
                else:
                    report = str(result)
                    status = "생산계획 조정 결과를 파싱하지 못했습니다."
                    success = False

                # ✅ Hybrid 말풍선에서도 표가 “안 깨져야 한다” 요구 반영:
                #    => hybrid 답변은 chat_message + st.markdown 이므로 표가 깨지지 않음.
                #    (원하면 아래에서 report 전체 대신 status+핵심만 출력하도록 줄일 수도 있음)
                bubble_text = f"{'✅' if success else '⚠️'} {status}"
                st.session_state.messages.append({"role": "assistant", "content": bubble_text, "engine": "hybrid"})

                # 상세 보기 데이터 저장 (expander에서 표/Δ/검증/CAPA/원문)
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
        t1, t2, t3, t4, t5 = st.tabs(["🧾 조치계획/원문", "📊 Δ(표)", "🔎 검증", "📈 CAPA 그래프", "📄 전체 원문"])

        with t1:
            # Streamlit native markdown
            st.markdown(report_md)

        with t2:
            # Δ는 dataframe으로만 (표 깨짐 원천 차단)
            delta_df = moves_to_delta_df(validated_moves)
            if delta_df.empty:
                st.info("Δ(변경량) 데이터가 없습니다.")
            else:
                pivot = (
                    delta_df.pivot_table(
                        index=["date", "item"],
                        columns="line",
                        values="delta",
                        aggfunc="sum",
                        fill_value=0,
                    )
                    .reset_index()
                )
                # 컬럼 정렬/보강
                for col in ["조립1", "조립2", "조립3"]:
                    if col not in pivot.columns:
                        pivot[col] = 0
                pivot = pivot[["date", "item", "조립1", "조립2", "조립3"]]
                st.dataframe(pivot, use_container_width=True)

        with t3:
            # 검증/원문 (일단 report 전체를 그대로)
            st.markdown(report_md)

        with t4:
            # CAPA 그래프 + 상세 데이터
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

                for line, limit in CAPA_LIMITS.items():
                    fig.add_hline(
                        y=limit,
                        line_dash="dash",
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
                st.dataframe(daily, use_container_width=True)
            else:
                st.info("CAPA 그래프를 그릴 데이터가 없습니다.")

        with t5:
            # 전체 원문이 너무 길면 st.text가 더 안전할 때도 있음
            st.markdown(report_md)


# ==================== END ====================
pass

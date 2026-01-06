# app.py  (3) 버전: "뷰(표시)만" 남긴 최소 app
# ✅ 전제: hybrid_merged.py의 ask_professional_scheduler가 "구조화 결과(dict)"를 반환하도록 바뀐 상태
#    (즉, app.py에서 report 정규식 파싱/문구 치환/조치계획 파싱을 더 이상 하지 않음)
#
# ✅ legacy.py는 그대로 사용 (조회 모드 로직 그대로)
# ✅ secrets/환경변수로만 키 관리
# ✅ 오른쪽 30% 패널 가독성: KPI + 조정안 + (접기)상세
# ✅ 사이드바 접기(«) 버튼 제거

import os
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai

from legacy import fetch_db_data_legacy, query_gemini_ai_legacy
from hybrid_merged import ask_professional_scheduler


# ==================== 기본 설정 ====================
st.set_page_config(page_title="생산계획 통합 시스템", page_icon="🏭", layout="wide")

CAPA_LIMITS = {"조립1": 3300, "조립2": 3700, "조립3": 3600}
TEST_MODE = True
TODAY = datetime(2026, 1, 5).date() if TEST_MODE else datetime.now().date()


# ==================== Secrets / Env ====================
def _get_secret(key: str, default: str = "") -> str:
    try:
        v = st.secrets.get(key, None)
        if v:
            return str(v)
    except Exception:
        pass
    return str(os.getenv(key, default))


SUPABASE_URL = _get_secret("SUPABASE_URL", "")
SUPABASE_KEY = _get_secret("SUPABASE_KEY", "")
GENAI_KEY = _get_secret("GEMINI_API_KEY", "")


# ==================== Supabase / Gemini init ====================
@st.cache_resource
def init_supabase() -> Optional[Client]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        return None


supabase = init_supabase()

if GENAI_KEY:
    try:
        genai.configure(api_key=GENAI_KEY)
    except Exception:
        pass


# ==================== UI CSS (컴팩트 + 사이드바 토글 제거) ====================
st.markdown(
    """
<style>
.block-container { padding-top: 0.6rem; padding-bottom: 0.6rem; padding-left: 0.8rem; padding-right: 0.8rem; }
div[data-testid="stMetricValue"] { font-size: 1.15rem; }
div[data-testid="stMetricLabel"] { font-size: 0.8rem; }
div[data-testid="stMarkdownContainer"] p { margin-bottom: 0.35rem; }
div[data-testid="stExpander"] summary { font-weight: 650; }

/* 사이드바 접기(«) 버튼 제거 */
button[kind="header"] { display: none; }
</style>
""",
    unsafe_allow_html=True,
)


# ==================== Helpers ====================
@st.cache_data(ttl=600)
def fetch_data(target_date: Optional[str] = None):
    """target_date 기준 ±10일 범위 로드 + product_map/plt_map 생성"""
    if not supabase:
        return pd.DataFrame(), pd.DataFrame(), {}, {}

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

        plan_df = pd.DataFrame(plan_res.data)
        hist_res = supabase.table("production_investigation").select("*").execute()
        hist_df = pd.DataFrame(hist_res.data)

        if plan_df.empty:
            return plan_df, hist_df, {}, {}

        plan_df["name_clean"] = plan_df["product_name"].astype(str).str.replace(r"\s+", "", regex=True).str.strip()
        plt_map = plan_df.groupby("name_clean")["plt"].first().to_dict()
        product_map = plan_df.groupby("name_clean")["line"].unique().to_dict()
        for k in list(product_map.keys()):
            if "T6" in str(k).upper():
                product_map[k] = ["조립1", "조립2", "조립3"]

        return plan_df, hist_df, product_map, plt_map

    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), {}, {}


def extract_date(text: str) -> Optional[str]:
    """질문에서 날짜 추출 -> YYYY-MM-DD"""
    m = re.search(r"(202[0-9])-(\d{1,2})-(\d{1,2})", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"

    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        return f"{TODAY.year:04d}-{mo:02d}-{d:02d}"

    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        return f"{TODAY.year:04d}-{mo:02d}-{d:02d}"

    return None


def is_adjustment_mode(prompt: str, target_date: Optional[str]) -> bool:
    if not target_date:
        return False
    return (
        any(line in prompt for line in ["조립1", "조립2", "조립3"])
        or re.search(r"\d+\s*%", prompt) is not None
        or "CAPA" in prompt.upper()
        or any(k in prompt for k in ["줄여", "감축", "증량", "샘플", "추가", "생산", "공정감사", "감사"])
    )


def _badge(status: str):
    up = status.upper()
    if "OK" in up:
        st.success(status)
    elif "WARN" in up:
        st.warning(status)
    else:
        st.error(status)


def render_hybrid_view(result: Dict[str, Any]):
    """
    ✅ hybrid_merged.py가 반환한 구조화 result로만 화면 그리기
    기대 포맷 예시:
    result = {
      "status": "[OK] ...",
      "success": True,
      "title": "2026-01-21 조립1 하이브리드 분석 보고서",
      "kpi": {"current":2600,"target":2950,"need":350,"actual":375,"achv":107.1},
      "moves": [{"item":"WL LHD","qty":200,"plt":1,"from":"2026-01-21_조립2","to":"2026-01-21_조립1","reason":"..."}],
      "messages": ["⚠️ ...", "✅ ..."],
      "report_md": "원문(마크다운)",
      "capa": {"daily": [...]}  # optional
    }
    """
    status = str(result.get("status", "")).strip()
    title = str(result.get("title", "")).strip()
    kpi = result.get("kpi", {}) or {}
    moves = result.get("moves", []) or []
    messages = result.get("messages", []) or []
    report_md = result.get("report_md", "") or ""

    if status:
        _badge(status)
    if title:
        st.markdown(f"### 📊 {title}")

    # KPI (2x2)
    c1, c2 = st.columns(2)
    c1.metric("현재", f"{int(kpi.get('current')):,}개" if kpi.get("current") is not None else "-")
    c2.metric("목표", f"{int(kpi.get('target')):,}개" if kpi.get("target") is not None else "-")
    c3, c4 = st.columns(2)
    c3.metric("필요", f"{int(kpi.get('need')):,}개" if kpi.get("need") is not None else "-")
    c4.metric("달성률", f"{float(kpi.get('achv')):.1f}%" if kpi.get("achv") is not None else "-")

    st.divider()

    # 조정안
    st.subheader("🧾 최종 조정안")
    if moves:
        dfm = pd.DataFrame(moves)

        # 컬럼 표준화(없어도 안전)
        rename_map = {
            "item": "품목",
            "qty": "수량",
            "plt": "PLT",
            "from": "FROM",
            "to": "TO",
            "reason": "사유",
        }
        dfm = dfm.rename(columns=rename_map)

        show_cols = [c for c in ["품목", "수량", "PLT", "FROM", "TO"] if c in dfm.columns]
        if show_cols:
            st.dataframe(dfm[show_cols].head(8), use_container_width=True, hide_index=True)
        else:
            st.dataframe(dfm.head(8), use_container_width=True, hide_index=True)

        with st.expander("사유/전체 보기"):
            st.dataframe(dfm, use_container_width=True, hide_index=True)
    else:
        st.info("적용 가능한 조정안이 없습니다.")

    # 메시지/검증
    with st.expander("⚠️ 검증/메모"):
        if messages:
            for m in messages:
                st.markdown(f"- {m}")
        else:
            st.caption("표시할 메시지가 없습니다.")

    # 원문
    with st.expander("📄 원문 리포트"):
        if report_md:
            st.markdown(report_md)
        else:
            st.caption("원문 리포트가 제공되지 않았습니다.")


def render_capa_chart(plan_df: pd.DataFrame):
    """(기존 유지) CAPA 차트 — 기본은 접힘"""
    if plan_df.empty or "qty_1차" not in plan_df.columns:
        return

    with st.expander("📊 CAPA 사용 현황 (열기)"):
        daily_summary = plan_df.groupby(["plan_date", "line"])["qty_1차"].sum().reset_index()
        daily_summary.columns = ["plan_date", "line", "current_qty"]
        daily_summary["max_capa"] = daily_summary["line"].map(CAPA_LIMITS)
        daily_summary["remaining_capa"] = daily_summary["max_capa"] - daily_summary["current_qty"]

        chart_data = (
            daily_summary.pivot(index="plan_date", columns="line", values="current_qty")
            .fillna(0)
            .sort_index()
        )

        fig = go.Figure()
        colors = {"조립1": "#0066CC", "조립2": "#66B2FF", "조립3": "#FF6666"}

        for line in ["조립1", "조립2", "조립3"]:
            if line in chart_data.columns:
                fig.add_trace(
                    go.Bar(
                        name=f"{line}",
                        x=chart_data.index,
                        y=chart_data[line],
                        marker_color=colors.get(line),
                        hovertemplate="%{x}<br>수량: %{y:,}개",
                    )
                )

        for line, limit in CAPA_LIMITS.items():
            fig.add_hline(
                y=limit,
                line_dash="dash",
                line_color=colors.get(line, "#888"),
                annotation_text=f"{line} 한계: {limit:,}",
                annotation_position="right",
            )

        fig.update_layout(
            barmode="group",
            height=360,
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


# ==================== Sidebar ====================
with st.sidebar:
    st.title("🏭 생산계획 통합")
    st.caption("조회: 일반 질문 / 조정: 날짜+라인+% 또는 샘플/추가/감축/증량")

    st.divider()
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.warning("SUPABASE_URL / SUPABASE_KEY 가 필요합니다. (Settings → Secrets)")
    if not GENAI_KEY:
        st.warning("GEMINI_API_KEY 가 필요합니다. (Settings → Secrets)")

    st.markdown(
        """
**예시(조정)**
- `2026-01-23 조립1 공정감사로 1일 CAPA의 70%만 생산`
- `2026-01-21 조립1 (T6) 샘플 350개 추가`

**예시(조회)**
- `내일 조립2에 T6 계획 있어?`
"""
    )


# ==================== Main ====================
st.title("🏭 생산계획 통합 시스템")
st.caption("💡 조회는 일반 질문, 조정은 날짜+라인+% 또는 날짜+샘플/추가/감축/증량 등을 입력하세요")

if "messages" not in st.session_state:
    st.session_state.messages = []

# 과거 메시지 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("질문을 입력하세요")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    target_date = extract_date(prompt)
    adj_mode = is_adjustment_mode(prompt, target_date)

    with st.chat_message("assistant"):
        if adj_mode:
            if not supabase:
                st.error("❌ Supabase 연결이 없어 조정 모드를 실행할 수 없습니다. (secrets 설정 확인)")
                st.session_state.messages.append({"role": "assistant", "content": "❌ Supabase 미설정"})
            elif not GENAI_KEY:
                st.error("❌ GEMINI_API_KEY가 없어 조정 모드를 실행할 수 없습니다. (secrets 설정 확인)")
                st.session_state.messages.append({"role": "assistant", "content": "❌ GEMINI_API_KEY 미설정"})
            else:
                with st.spinner("🔍 하이브리드 분석 진행 중..."):
                    plan_df, hist_df, product_map, plt_map = fetch_data(target_date)

                    if plan_df.empty:
                        st.error("❌ 데이터를 불러올 수 없습니다. 날짜/DB 테이블/기간을 확인해주세요.")
                        st.session_state.messages.append({"role": "assistant", "content": "❌ 데이터 로드 실패"})
                    else:
                        # ✅ 여기서부터는 '구조화 결과'를 받아 그대로 표시
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

                        # (안전) 혹시 기존 튜플 반환이면 친절하게 안내
                        if not isinstance(result, dict):
                            st.error(
                                "❌ 현재 hybrid_merged.py가 dict를 반환하지 않고 있어요.\n\n"
                                "3) app.py는 hybrid 결과를 구조화(dict)로 받는 전제입니다.\n"
                                "먼저 hybrid_merged.py를 수정해서 dict를 반환하도록 바꿔야 해요."
                            )
                        else:
                            render_hybrid_view(result)

                    # (기존 유지) CAPA 차트
                    if not plan_df.empty:
                        render_capa_chart(plan_df)

        else:
            # ✅ legacy.py는 기존 흐름 그대로
            if not supabase:
                answer = "❌ Supabase 연결이 없어 조회 모드를 실행할 수 없습니다. (secrets 설정 확인)"
                st.error(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            else:
                with st.spinner("데이터 분석 중..."):
                    db_result = fetch_db_data_legacy(prompt, supabase)

                    if "찾을 수 없습니다" in db_result or "오류" in db_result:
                        answer = db_result
                    else:
                        if not GENAI_KEY:
                            answer = "❌ GEMINI_API_KEY가 없어 조회 모드에서 AI 답변을 생성할 수 없습니다."
                        else:
                            answer = query_gemini_ai_legacy(prompt, db_result, GENAI_KEY)

                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})

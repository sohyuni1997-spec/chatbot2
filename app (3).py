# app.py  (임베드/우측 30% 패널용: "뷰(표시)만" 남긴 최소 Streamlit 앱)
# - ✅ 목표: 다른 팀원이 만든 웹(좌측 70%) + 이 앱(우측 30%) 한 페이지 구성에 맞춘 레이아웃
# - ✅ 핵심: hybrid(엔진) 결과를 "정규식 파싱 없이" 안전하게 표시
# - ✅ hybrid.py가 dict를 반환하면 그대로 사용 / tuple(레거시)면 안전 래핑해서 표시
# - ✅ sidebar 사용 안 함 (접기 버튼 이슈 자체 제거)
# - ✅ secrets/환경변수로만 키 관리

import os
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, Union

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai

from legacy import fetch_db_data_legacy, query_gemini_ai_legacy
from hybrid import ask_professional_scheduler  # ✅ hybrid.py 사용


# ==================== 기본 설정 ====================
st.set_page_config(page_title="생산계획 패널", page_icon="🏭", layout="wide")

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


# ==================== UI CSS (우측 패널 가독성 최적화) ====================
st.markdown(
    """
<style>
/* 전체 패딩 최소화 */
.block-container { padding-top: 0.6rem; padding-bottom: 0.6rem; padding-left: 0.8rem; padding-right: 0.8rem; }

/* metric 컴팩트 */
div[data-testid="stMetricValue"] { font-size: 1.05rem; }
div[data-testid="stMetricLabel"] { font-size: 0.75rem; }

/* 문단 간격 */
div[data-testid="stMarkdownContainer"] p { margin-bottom: 0.35rem; }

/* expander 타이틀 강조 */
div[data-testid="stExpander"] summary { font-weight: 650; }

/* chat input 위 여백 줄이기 */
section[data-testid="stChatInput"] { padding-top: 0.25rem; }
</style>
""",
    unsafe_allow_html=True,
)


# ==================== Data Helpers ====================
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

        plan_df["name_clean"] = (
            plan_df["product_name"].astype(str).str.replace(r"\s+", "", regex=True).str.strip()
        )
        plt_map = plan_df.groupby("name_clean")["plt"].first().to_dict()
        product_map = plan_df.groupby("name_clean")["line"].unique().to_dict()

        # T6는 라인 제한 없이 이동 가능 처리
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
    """조정/조회 분기: 날짜가 있고, 라인/퍼센트/증감 키워드가 있으면 조정으로 간주"""
    if not target_date:
        return False
    return (
        any(line in prompt for line in ["조립1", "조립2", "조립3"])
        or re.search(r"\d+\s*%", prompt) is not None
        or "CAPA" in prompt.upper()
        or any(k in prompt for k in ["줄여", "감축", "증량", "샘플", "추가", "생산", "공정감사", "감사"])
    )


# ==================== Render Helpers (파싱 최소화/무파싱) ====================
def _badge(status: str):
    up = status.upper()
    if "OK" in up:
        st.success(status)
    elif "WARN" in up:
        st.warning(status)
    else:
        st.error(status)


def _wrap_legacy_tuple_to_dict(result: Tuple[Any, ...], fallback_title: str = "") -> Dict[str, Any]:
    """
    hybrid가 tuple (report, success, charts, status) 을 반환하는 레거시 케이스를
    dict UI에 맞게 '안전 래핑' (정규식 파싱 없음)
    """
    report = result[0] if len(result) > 0 else ""
    success = bool(result[1]) if len(result) > 1 else False
    charts = result[2] if len(result) > 2 else []
    status = result[3] if len(result) > 3 else ("[OK]" if success else "[WARN]")

    title = fallback_title or "하이브리드 분석 보고서"
    return {
        "status": str(status),
        "success": success,
        "title": title,
        "kpi": {},           # 레거시 tuple에서는 KPI를 파싱하지 않음(무파싱 정책)
        "moves": [],         # 레거시 tuple에서는 moves를 파싱하지 않음(무파싱 정책)
        "messages": [],
        "report_md": str(report),
        "charts": charts,
    }


def render_hybrid_view(result: Dict[str, Any]):
    """
    ✅ dict 기반 표시. (정규식 파싱 금지)
    기대 포맷 예:
    {
      "status": "...",
      "success": True/False,
      "title": "...",
      "kpi": {"current":..., "target":..., "need":..., "actual":..., "achv":...},
      "moves": [...],
      "messages": [...],
      "report_md": "...",
      "capa": {"daily":[...]}  # optional
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
        st.markdown(f"#### 📊 {title}")

    # KPI (있을 때만)
    if kpi:
        c1, c2 = st.columns(2)
        c1.metric("현재", f"{int(kpi.get('current')):,}개" if kpi.get("current") is not None else "-")
        c2.metric("목표", f"{int(kpi.get('target')):,}개" if kpi.get("target") is not None else "-")
        c3, c4 = st.columns(2)
        c3.metric("필요", f"{int(kpi.get('need')):,}개" if kpi.get("need") is not None else "-")
        c4.metric("달성률", f"{float(kpi.get('achv')):.1f}%" if kpi.get("achv") is not None else "-")
        st.divider()

    # 조정안(있을 때만)
    if moves:
        st.markdown("**🧾 최종 조정안**")
        dfm = pd.DataFrame(moves).copy()

        # 보여줄 컬럼 표준화(없어도 안전)
        rename_map = {"item": "품목", "qty": "수량", "plt": "PLT", "from": "FROM", "to": "TO"}
        dfm = dfm.rename(columns=rename_map)

        show_cols = [c for c in ["품목", "수량", "PLT", "FROM", "TO"] if c in dfm.columns]
        st.dataframe(dfm[show_cols].head(8) if show_cols else dfm.head(8),
                     use_container_width=True, hide_index=True)

        with st.expander("사유/전체 보기"):
            st.dataframe(dfm, use_container_width=True, hide_index=True)
    else:
        st.info("적용 가능한 조정안이 없습니다. (또는 엔진이 moves를 제공하지 않았습니다.)")

    # 메시지/검증 메모
    if messages:
        with st.expander("⚠️ 검증/메모"):
            for m in messages:
                st.markdown(f"- {m}")

    # 원문
    with st.expander("📄 원문 리포트"):
        if report_md:
            st.markdown(report_md)
        else:
            st.caption("원문 리포트가 제공되지 않았습니다.")


def render_capa_chart(plan_df: pd.DataFrame):
    """CAPA 차트 — 기본은 접힘"""
    if plan_df.empty or "qty_1차" not in plan_df.columns:
        return

    with st.expander("📊 CAPA 사용 현황"):
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
            height=320,
            xaxis_title="날짜",
            yaxis_title="수량 (개)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
            margin=dict(l=10, r=10, t=30, b=10),
        )

        st.plotly_chart(fig, use_container_width=True)

        with st.expander("📋 상세 데이터"):
            st.dataframe(
                daily_summary.style.format(
                    {"current_qty": "{:,.0f}", "max_capa": "{:,.0f}", "remaining_capa": "{:,.0f}"}
                ),
                use_container_width=True,
            )


# ==================== Layout: 좌 70% / 우 30% ====================
left, right = st.columns([7, 3], gap="large")

with left:
    st.markdown("### 🧩 (좌측) 팀원 웹 영역")
    st.caption("여기는 다른 팀원이 만든 웹이 들어갈 영역입니다. (예: iframe/컴포넌트/대시보드 등)")
    st.info("현재 app.py는 '우측 패널' 중심으로 작성되어 있습니다.")

with right:
    st.markdown("### 🏭 생산계획 패널")
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.warning("SUPABASE_URL / SUPABASE_KEY 가 필요합니다. (Settings → Secrets)")
    if not GENAI_KEY:
        st.warning("GEMINI_API_KEY 가 필요합니다. (Settings → Secrets)")

    st.caption("조회: 일반 질문 / 조정: 날짜+라인+% 또는 샘플/추가/감축/증량")

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
            # ==================== 조정 모드 ====================
            if adj_mode:
                if not supabase:
                    st.error("❌ Supabase 연결이 없어 조정 모드를 실행할 수 없습니다. (secrets 설정 확인)")
                    st.session_state.messages.append({"role": "assistant", "content": "❌ Supabase 미설정"})
                elif not GENAI_KEY:
                    st.error("❌ GEMINI_API_KEY가 없어 조정 모드를 실행할 수 없습니다. (secrets 설정 확인)")
                    st.session_state.messages.append({"role": "assistant", "content": "❌ GEMINI_API_KEY 미설정"})
                elif not target_date:
                    st.error("❌ 조정 모드는 날짜가 필요합니다. (예: 2026-01-21 조립1 CAPA 70%)")
                    st.session_state.messages.append({"role": "assistant", "content": "❌ 날짜 미검출"})
                else:
                    with st.spinner("🔍 하이브리드 분석 진행 중..."):
                        plan_df, hist_df, product_map, plt_map = fetch_data(target_date)

                        if plan_df.empty:
                            st.error("❌ 데이터를 불러올 수 없습니다. 날짜/DB 테이블/기간을 확인해주세요.")
                            st.session_state.messages.append({"role": "assistant", "content": "❌ 데이터 로드 실패"})
                        else:
                            # ✅ hybrid 실행 (dict면 그대로 / tuple이면 래핑)
                            result_raw = ask_professional_scheduler(
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
                                # return_dict=True,  # ← hybrid.py가 지원한다면 이 줄만 켜면 됨
                            )

                            if isinstance(result_raw, dict):
                                result = result_raw
                            elif isinstance(result_raw, (tuple, list)):
                                result = _wrap_legacy_tuple_to_dict(
                                    tuple(result_raw),
                                    fallback_title=f"{target_date} 하이브리드 분석 보고서",
                                )
                            else:
                                result = {"status": "[ERROR] 결과 타입 오류", "title": "", "report_md": str(result_raw)}

                            render_hybrid_view(result)

                            # CAPA 차트(옵션)
                            render_capa_chart(plan_df)

            # ==================== 조회 모드 (legacy 그대로) ====================
            else:
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

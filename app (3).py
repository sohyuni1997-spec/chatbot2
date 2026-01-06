# app.py  (최소 수정 반영 전체본)
# - ✅ 변경 포인트: render_hybrid_summary_ui() 안의 need_qty / moved_qty 정규식 2줄만 교체
#   need_qty  = _pick_int(r"필요 (?:감축|증량)량:\s*\*\*(\d[\d,]*)개\*\*", report)
#   moved_qty = _pick_int(r"실제 (?:감축|증량)량:\s*\*\*(\d[\d,]*)개\*\*", report)

import os
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple, Union

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
    if not target_date:
        return False
    return (
        any(line in prompt for line in ["조립1", "조립2", "조립3"])
        or re.search(r"\d+\s*%", prompt) is not None
        or "CAPA" in prompt.upper()
        or any(k in prompt for k in ["줄여", "감축", "증량", "샘플", "추가", "생산", "공정감사", "감사"])
    )


# ==================== Parsing Helpers ====================
def _pick_int(pattern: str, text: str, default: Optional[int] = None) -> Optional[int]:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return default
    s = m.group(1).replace(",", "").strip()
    try:
        return int(s)
    except Exception:
        return default


def _pick_float(pattern: str, text: str, default: Optional[float] = None) -> Optional[float]:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return default
    s = m.group(1).replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return default


def _badge(status: str):
    up = status.upper()
    if "OK" in up:
        st.success(status)
    elif "WARN" in up:
        st.warning(status)
    else:
        st.error(status)


def _parse_moves_from_report(report: str) -> List[Dict[str, Any]]:
    """
    조치계획(이동/조정안) 텍스트를 최대한 안전하게 파싱.
    (형식이 바뀔 수 있으니 실패해도 UI가 깨지지 않게 'best effort')
    """
    moves: List[Dict[str, Any]] = []

    # 예시 라인(가정):
    # - WL LHD: 200개 (1PLT) | 2026-01-21_조립2 -> 2026-01-21_조립1
    line_pat = re.compile(
        r"-\s*(?P<item>.+?)\s*:\s*(?P<qty>\d[\d,]*)\s*개.*?(?P<plt>\d+)\s*PLT.*?\|\s*(?P<from>\d{4}-\d{2}-\d{2}_[^ ]+)\s*->\s*(?P<to>\d{4}-\d{2}-\d{2}_[^ \n]+)",
        flags=re.IGNORECASE,
    )

    for m in line_pat.finditer(report):
        moves.append(
            {
                "품목": m.group("item").strip(),
                "수량": int(m.group("qty").replace(",", "")),
                "PLT": int(m.group("plt")),
                "FROM": m.group("from").strip(),
                "TO": m.group("to").strip(),
            }
        )
    return moves


# ==================== UI Renderers ====================
def render_hybrid_summary_ui(report: str):
    """
    기존(레거시) 하이브리드 보고서 텍스트 기반 UI
    - ✅ 이번 요청의 '최소 수정'은 need_qty / moved_qty 정규식 2줄만 변경
    """

    title = ""
    m = re.search(r"📊\s*(.+)", report)
    if m:
        title = m.group(1).strip()

    status = ""
    m = re.search(r"(\[[A-Z]+\][^\n]+)", report)
    if m:
        status = m.group(1).strip()

    if status:
        _badge(status)
    if title:
        st.markdown(f"### 📊 {title}")

    # KPI 파싱 (보고서 형식에 맞춰 best effort)
    current_qty = _pick_int(r"현재 생산량:\s*([\d,]+)개", report)
    target_qty = _pick_int(r"목표 생산량:\s*([\d,]+)개", report)

    # ✅✅✅ 여기 2줄이 '최소 수정' 반영 포인트입니다
    need_qty  = _pick_int(r"필요 (?:감축|증량)량:\s*\*\*(\d[\d,]*)개\*\*", report)
    moved_qty = _pick_int(r"실제 (?:감축|증량)량:\s*\*\*(\d[\d,]*)개\*\*", report)
    # ✅✅✅

    achv = _pick_float(r"달성률:\s*([\d.]+)\s*%", report)

    # KPI (2x2)
    c1, c2 = st.columns(2)
    c1.metric("현재", f"{current_qty:,}개" if current_qty is not None else "-")
    c2.metric("목표", f"{target_qty:,}개" if target_qty is not None else "-")
    c3, c4 = st.columns(2)
    c3.metric("필요", f"{need_qty:,}개" if need_qty is not None else "-")
    c4.metric("달성률", f"{achv:.1f}%" if achv is not None else "-")

    st.divider()

    # 조정안
    st.subheader("🧾 최종 조정안")
    moves = _parse_moves_from_report(report)
    if moves:
        dfm = pd.DataFrame(moves)
        show_cols = [c for c in ["품목", "수량", "PLT", "FROM", "TO"] if c in dfm.columns]
        st.dataframe(dfm[show_cols].head(8), use_container_width=True, hide_index=True)

        with st.expander("전체 보기"):
            st.dataframe(dfm, use_container_width=True, hide_index=True)
    else:
        st.info("조정안 파싱 결과가 없습니다. (보고서 형식이 바뀌었을 수 있어요)")

    # 검증/메모(있으면)
    with st.expander("⚠️ 검증/메모"):
        if moved_qty is not None and need_qty is not None:
            st.markdown(f"- 필요량: **{need_qty:,}개**")
            st.markdown(f"- 실제 조정량: **{moved_qty:,}개**")
        st.caption("기타 검증 메시지는 보고서 원문에서 확인하세요.")

    # 원문
    with st.expander("📄 원문 리포트"):
        st.markdown(report)


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
- `2026-01-21 조립1 CAPA 70%로 감축`

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
                        # hybrid_merged 반환 형태가 (dict / str / tuple) 섞여도 UI가 안죽게 방어
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

                        # 1) dict(구조화 결과)면 그대로 표시
                        if isinstance(result, dict):
                            # 최소한의 표시(구조화 결과 UI가 별도로 있으면 여기서 교체)
                            status = str(result.get("status", "")).strip()
                            title = str(result.get("title", "")).strip()
                            if status:
                                _badge(status)
                            if title:
                                st.markdown(f"### 📊 {title}")
                            # 원문/리포트가 있으면 레거시 요약 UI로도 표시 가능
                            report_md = result.get("report_md", "") or ""
                            if report_md:
                                render_hybrid_summary_ui(report_md)
                            else:
                                st.info("구조화 결과(dict)만 있고 report_md가 없어 요약 UI를 생략했습니다.")
                        # 2) 문자열이면 레거시 요약 UI
                        elif isinstance(result, str):
                            render_hybrid_summary_ui(result)
                        # 3) 튜플이면 (status, report) 같은 케이스로 처리
                        elif isinstance(result, (tuple, list)) and len(result) >= 1:
                            report = ""
                            # 가장 긴 str을 report로 간주
                            strs = [x for x in result if isinstance(x, str)]
                            if strs:
                                report = max(strs, key=len)
                            if report:
                                render_hybrid_summary_ui(report)
                            else:
                                st.error("❌ hybrid 결과를 해석할 수 없습니다. (tuple/list 안에 report 문자열이 없음)")
                        else:
                            st.error("❌ hybrid 결과 타입을 해석할 수 없습니다. (dict/str/tuple 예상)")

                    # CAPA 차트(기존 유지)
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

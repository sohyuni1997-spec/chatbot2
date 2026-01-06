# app.py
# ✅ 요구사항 반영
# - secrets(또는 환경변수)로만 키 관리 (코드에 하드코딩 키 없음)
# - legacy.py는 건드리지 않음 (호출/흐름 그대로)
# - 하이브리드(조정) 모드 UI만 “오른쪽 30% 패널”에 맞게 요약형으로 개선
# - 기존 CAPA 차트/상세 데이터 보기 유지

import os
import re
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai

# 분리된 모듈에서 함수 임포트 (legacy.py는 그대로 사용)
from legacy import fetch_db_data_legacy, query_gemini_ai_legacy
from hybrid_merged import ask_professional_scheduler


# ==================== 환경 설정 ====================
st.set_page_config(page_title="생산계획 통합 시스템", page_icon="🏭", layout="wide")

CAPA_LIMITS = {"조립1": 3300, "조립2": 3700, "조립3": 3600}
FROZEN_DAYS = 3
TEST_MODE = True
TODAY = datetime(2026, 1, 5).date() if TEST_MODE else datetime.now().date()


# ==================== Secrets / Env ====================
def _get_secret(key: str, default: str = "") -> str:
    """secrets 우선, 없으면 환경변수. 둘 다 없으면 default."""
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

if not SUPABASE_URL or not SUPABASE_KEY:
    st.sidebar.warning("Supabase secrets가 비어있어요. (SUPABASE_URL / SUPABASE_KEY)")
if not GENAI_KEY:
    st.sidebar.warning("Gemini secrets가 비어있어요. (GEMINI_API_KEY)")


# ==================== Supabase / Gemini init ====================
@st.cache_resource
def init_supabase() -> "Client | None":
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        return None


supabase: "Client | None" = init_supabase()

if GENAI_KEY:
    try:
        genai.configure(api_key=GENAI_KEY)
    except Exception:
        pass


# ==================== UI: 오른쪽 패널용 컴팩트 CSS ====================
st.markdown(
    """
<style>
/* 오른쪽 30% 패널 가독성용 컴팩트 */
.block-container { padding-top: 0.6rem; padding-bottom: 0.6rem; padding-left: 0.8rem; padding-right: 0.8rem; }
div[data-testid="stMetricValue"] { font-size: 1.15rem; }
div[data-testid="stMetricLabel"] { font-size: 0.8rem; }
div[data-testid="stMarkdownContainer"] p { margin-bottom: 0.35rem; }
div[data-testid="stExpander"] summary { font-weight: 650; }
</style>
""",
    unsafe_allow_html=True,
)


# ==================== 데이터 로드 ====================
@st.cache_data(ttl=600)
def fetch_data(target_date: str | None = None):
    """
    target_date 기준 ±10일 범위 데이터 로드
    - production_plan_2026_01
    - production_investigation
    """
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

        if not plan_df.empty:
            plan_df["name_clean"] = plan_df["product_name"].apply(
                lambda x: re.sub(r"\s+", "", str(x)).strip()
            )
            plt_map = plan_df.groupby("name_clean")["plt"].first().to_dict()
            product_map = plan_df.groupby("name_clean")["line"].unique().to_dict()
            for k in list(product_map.keys()):
                if "T6" in str(k).upper():
                    product_map[k] = ["조립1", "조립2", "조립3"]
            return plan_df, hist_df, product_map, plt_map

        return pd.DataFrame(), pd.DataFrame(), {}, {}

    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), {}, {}


def extract_date(text: str) -> str | None:
    """
    질문에서 날짜 추출 -> YYYY-MM-DD
    지원:
    - 1/23
    - 1월 23일
    - 2026-01-23 (또는 2025/2026)
    """
    # 2026-01-23
    m = re.search(r"(202[0-9])-(\d{1,2})-(\d{1,2})", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"

    # 1/23
    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        return f"{TODAY.year:04d}-{mo:02d}-{d:02d}"

    # 1월 23일
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        return f"{TODAY.year:04d}-{mo:02d}-{d:02d}"

    return None


# ==================== Hybrid UI helpers (표현만 개선) ====================
def _pick_int(pattern: str, text: str):
    m = re.search(pattern, text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def _pick_float(pattern: str, text: str):
    m = re.search(pattern, text)
    if not m:
        return None
    return float(m.group(1))


def _extract_moves_from_report(report: str) -> list[dict]:
    """
    hybrid_merged의 report 문자열에서 '최종 조치 계획'만 파싱
    (엔진 수정 없이 app만 바꾸기 위해 사용)
    """
    m = re.search(r"## 🧾 최종 조치 계획.*?\n(.*?)(?:\n## |\Z)", report, flags=re.S)
    if not m:
        return []

    body = m.group(1).strip()
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if lines and "승인된 조치 없음" in lines[0]:
        return []

    moves = []
    for ln in lines:
        ln2 = re.sub(r"^\d+\)\s*", "", ln)
        parts = [p.strip() for p in ln2.split("|")]
        if len(parts) < 4:
            continue

        item = parts[0]
        qty_plt = parts[1]
        route = parts[2]
        reason = parts[3]

        qty = _pick_int(r"(\d[\d,]*)개", qty_plt)
        plt = _pick_int(r"\((\d[\d,]*)PLT\)", qty_plt)

        from_loc, to_loc = None, None
        if "→" in route:
            from_loc, to_loc = [x.strip() for x in route.split("→", 1)]

        moves.append(
            {
                "품목": item,
                "수량": qty,
                "PLT": plt,
                "FROM": from_loc,
                "TO": to_loc,
                "사유": reason,
            }
        )
    return moves


def render_hybrid_summary_ui(report: str, status: str):
    """하이브리드 결과를 요약 UI로 표시 (원문은 expander)"""
    # 상태 배지
    if "OK" in status:
        st.success(status)
    elif "WARN" in status:
        st.warning(status)
    else:
        st.error(status)

    # KPI 파싱
    current_qty = _pick_int(r"현재 생산량:\s*\*\*(\d[\d,]*)개\*\*", report)
    target_qty = _pick_int(r"목표 생산량:\s*\*\*(\d[\d,]*)개\*\*", report)
    need_qty = _pick_int(r"필요 (감축|증량)량:\s*\*\*(\d[\d,]*)개\*\*", report)
    moved_qty = _pick_int(r"실제 (감축|증량)량:\s*\*\*(\d[\d,]*)개\*\*", report)
    achv = _pick_float(r"목표 달성률:\s*\*\*([\d\.]+)%\*\*", report)

    # KPI (2x2)
    c1, c2 = st.columns(2)
    c1.metric("현재", f"{current_qty:,}개" if current_qty is not None else "-")
    c2.metric("목표", f"{target_qty:,}개" if target_qty is not None else "-")

    c3, c4 = st.columns(2)
    c3.metric("필요", f"{need_qty:,}개" if need_qty is not None else "-")
    c4.metric("달성률", f"{achv:.1f}%" if achv is not None else "-")

    st.divider()

    # 조치 계획
    st.subheader("🧾 최종 조치 계획")
    moves = _extract_moves_from_report(report)
    if moves:
        dfm = pd.DataFrame(moves)
        show_cols = ["품목", "수량", "PLT", "FROM", "TO"]
        st.dataframe(dfm[show_cols].head(8), use_container_width=True, hide_index=True)

        with st.expander("사유/전체 보기"):
            st.dataframe(dfm, use_container_width=True, hide_index=True)
    else:
        st.info("승인된 조치가 없습니다.")

    # 검증/메모
    with st.expander("⚠️ 검증 메시지 / 메모"):
        v = re.search(r"## ✅ \[6단계\] Python 검증 결과\s*(.*?)(?:\n## |\Z)", report, flags=re.S)
        if v:
            st.markdown(v.group(0))
        else:
            st.markdown("검증 섹션을 찾지 못했습니다.")

    # 원문
    with st.expander("📄 원문 리포트 보기"):
        st.markdown(report)

    return current_qty, target_qty, need_qty, moved_qty, achv


# ==================== 메인 화면 ====================
st.title("🏭 생산계획 통합 시스템")
st.caption("💡 조회는 일반 질문, 조정은 날짜+라인+% 또는 날짜+샘플/추가/감축/증량 등을 입력하세요")

# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 기존 메시지 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 사용자 입력
prompt = st.chat_input("질문을 입력하세요")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    target_date = extract_date(prompt)

    # 조정 모드 조건: 날짜 + (라인명 또는 % 또는 CAPA/감축/증량 뉘앙스)
    is_adjustment_mode = target_date and (
        any(line in prompt for line in ["조립1", "조립2", "조립3"])
        or re.search(r"\d+\s*%", prompt)
        or "CAPA" in prompt.upper()
        or "줄여" in prompt
        or "감축" in prompt
        or "증량" in prompt
        or "샘플" in prompt
        or "추가" in prompt
        or "생산" in prompt
        or "공정감사" in prompt
        or "감사" in prompt
    )

    with st.chat_message("assistant"):
        if is_adjustment_mode:
            # ========== 조정 모드 (하이브리드 시스템) ==========
            if not supabase:
                answer = "❌ Supabase 연결이 없어 하이브리드 모드를 실행할 수 없습니다. (secrets 설정 확인)"
                st.error(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            elif not GENAI_KEY:
                answer = "❌ GEMINI_API_KEY가 없어 하이브리드 모드를 실행할 수 없습니다. (secrets 설정 확인)"
                st.error(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            else:
                with st.spinner("🔍 하이브리드 수사 진행 중... (요약 UI로 표시)"):
                    plan_df, hist_df, product_map, plt_map = fetch_data(target_date)

                    if plan_df.empty:
                        answer = "❌ 데이터를 불러올 수 없습니다. 날짜/DB 테이블/기간을 확인해주세요."
                        st.error(answer)
                        st.session_state.messages.append({"role": "assistant", "content": answer})
                    else:
                        try:
                            report, success, charts, status = ask_professional_scheduler(
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

                            # ✅ 여기서부터는 UI만 변경 (legacy 영향 없음)
                            current_qty, target_qty, need_qty, moved_qty, achv = render_hybrid_summary_ui(
                                report=report,
                                status=status,
                            )

                            # 대화 히스토리에는 “요약”만 저장 (원문은 UI에서 expander로)
                            summary_for_chat = (
                                f"{status}\n\n"
                                f"- 현재: {current_qty:,} / 목표: {target_qty:,}\n"
                                f"- 필요: {need_qty:,} / 실제: {moved_qty:,}\n"
                                f"- 달성률: {achv:.1f}%"
                            )
                            st.session_state.messages.append({"role": "assistant", "content": summary_for_chat})

                        except Exception as e:
                            answer = f"❌ **오류 발생**\n\n```\n{str(e)}\n```"
                            st.markdown(answer)
                            st.exception(e)
                            st.session_state.messages.append({"role": "assistant", "content": answer})

                # ====== (기존 유지) CAPA 차트 ======
                if not plan_df.empty and "qty_1차" in plan_df.columns:
                    st.markdown("---")
                    st.subheader("📊 CAPA 사용 현황")

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
                                    marker_color=colors.get(line, None),
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
                        height=400,
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

        else:
            # ========== 조회 모드 (레거시 챗봇) ==========
            # ✅ 아래 블록은 legacy.py 영향 없도록 그대로 유지
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
                        # legacy는 기존대로 Gemini 키를 사용
                        if not GENAI_KEY:
                            answer = "❌ GEMINI_API_KEY가 없어 조회 모드에서 AI 답변을 생성할 수 없습니다."
                        else:
                            answer = query_gemini_ai_legacy(prompt, db_result, GENAI_KEY)

                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})

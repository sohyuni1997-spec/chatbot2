import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from datetime import datetime, timedelta
import plotly.graph_objects as go
import re

# 분리된 모듈에서 함수 임포트
from legacy import fetch_db_data_legacy, query_gemini_ai_legacy
from hybrid import ask_professional_scheduler

# ==================== 환경 설정 ====================
st.set_page_config(page_title="생산계획 통합 시스템", page_icon="🏭", layout="wide")


# ==================== 유틸 ====================
def split_report_sections(report_md: str) -> dict:
    """
    하이브리드 리포트(md)를 "##" 헤더 기준으로 섹션 분리
    """
    sections = {}
    if not report_md:
        return sections

    lines = report_md.splitlines()
    current_title = "ROOT"
    buf = []

    for line in lines:
        if line.startswith("## "):
            # flush
            sections[current_title] = "\n".join(buf).strip()
            current_title = line.strip()
            buf = [line]
        else:
            buf.append(line)

    sections[current_title] = "\n".join(buf).strip()
    # ROOT가 비어있으면 제거
    if "ROOT" in sections and not sections["ROOT"]:
        sections.pop("ROOT", None)
    return sections


def render_datewise_delta_tables(validated_moves: list[dict] | None):
    """검증된 이동 내역(validated_moves)로 날짜별 변경량(Δ) 표를 세로로 나열"""
    if not validated_moves:
        st.caption("📊 변경량 표: 이동 내역이 없습니다.")
        return

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
        st.caption("📊 변경량 표: 표시할 데이터가 없습니다.")
        return

    for date in sorted(df["date"].unique()):
        day = df[df["date"] == date].copy()
        pivot = (
            day.pivot_table(index="item", columns="line", values="delta", aggfunc="sum", fill_value=0)
            .reindex(columns=["조립1", "조립2", "조립3"])
        )

        # 0은 빈칸으로
        pivot = pivot.replace({0: ""})
        pivot = pivot.loc[~(pivot == "").all(axis=1)]

        # ✅ 표시용 포맷: 증가는 +, 감소는 -
        def _fmt_delta(v):
            if v == "" or pd.isna(v):
                return ""
            try:
                iv = int(v)
            except Exception:
                return str(v)
            return f"{iv:+,}"

        pivot = pivot.applymap(_fmt_delta)

        st.markdown(f"#### 📅 {date} 기준 변경분")
        if pivot.empty:
            st.caption("(변경 없음)")
        else:
            st.dataframe(pivot, use_container_width=True)


def render_hybrid_details(report_md: str):
    """검증/CAPA/원문 같은 상세 정보는 '탭 1개'로 접어서 제공"""
    sections = split_report_sections(report_md)

    with st.expander("🔎 상세 보기", expanded=False):
        (detail_tab,) = st.tabs(["🔎 상세"])

        with detail_tab:
            # 검증
            st.markdown("## ✅ 검증 결과")
            verify_key = next(
                (k for k in sections.keys() if "Python 검증" in k or "검증 결과" in k or "검증" in k),
                None,
            )
            st.markdown(sections.get(verify_key, "검증 섹션이 없습니다."))

            st.markdown("---")

            # CAPA
            st.markdown("### 📊 CAPA 현황")
            capa_key = next((k for k in sections.keys() if "CAPA 현황" in k), None)
            st.markdown(sections.get(capa_key, "CAPA 섹션이 없습니다."))

            st.markdown("---")

            # 원문
            st.markdown("### 📄 원문 리포트")
            st.markdown(report_md)


# ==================== 데이터 로드 ====================
@st.cache_data(show_spinner=False)
def fetch_data(target_date: str):
    plan_df, hist_df, product_map, plt_map = fetch_db_data_legacy(target_date)
    return plan_df, hist_df, product_map, plt_map


# ==================== UI ====================
st.title("🏭 생산계획 통합 시스템")
st.caption("Legacy(자유 질의) + Hybrid(조정 모드) 통합")

colA, colB = st.columns([1, 1])
with colA:
    target_date = st.date_input("대상 생산일", value=datetime.today().date())
with colB:
    is_adjustment_mode = st.toggle("조정 모드(하이브리드 엔진)", value=True)

st.markdown("---")

if "messages" not in st.session_state:
    st.session_state.messages = []

# 이전 대화 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("질문을 입력하세요 (예: '2026-01-21 조립1 샘플 100개 추가' 또는 'CAPA 75%로 맞춰줘')")

if user_input:
    # 유저 메시지 저장/출력
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 어시스턴트 응답
    with st.chat_message("assistant"):
        if is_adjustment_mode:
            # ========== 조정 모드 ==========
            with st.spinner("🔍 생산계획 분석/조정 중..."):
                plan_df, hist_df, product_map, plt_map = fetch_data(target_date.strftime("%Y-%m-%d"))

                if plan_df.empty:
                    st.error("데이터를 불러올 수 없습니다. 날짜를 확인해주세요.")
                    st.session_state.messages.append(
                        {"role": "assistant", "content": "❌ 데이터를 불러올 수 없습니다. 날짜를 확인해주세요."}
                    )
                else:
                    try:
                        report, success, charts, status, validated_moves = ask_professional_scheduler(
                            question=user_input,
                            plan_df=plan_df,
                            hist_df=hist_df,
                            product_map=product_map,
                            plt_map=plt_map,
                            question_date=target_date.strftime("%Y-%m-%d"),
                            mode="hybrid",
                            today=datetime.today().date(),
                            capa_limits={"조립1": 3300, "조립2": 3700, "조립3": 3600},
                            genai_key=st.secrets.get("GEMINI_API_KEY", ""),
                        )

                        # 상단 상태
                        if success:
                            st.success(status)
                        else:
                            st.warning(status)

                        # 리포트: "최종 조치 계획" 섹션만 위로 보여주기
                        sections = split_report_sections(report)
                        plan_key = next((k for k in sections.keys() if "최종 조치 계획" in k), None)
                        action_body = sections.get(plan_key, report)

                        st.markdown(action_body)

                        st.markdown("---")

                        # ✅ 날짜별 Δ 표 출력 (여기서 + 표시됨)
                        st.subheader("📊 날짜별 변경량(Δ)")
                        render_datewise_delta_tables(validated_moves)

                        st.markdown("---")

                        # 상세보기
                        render_hybrid_details(report)

                        st.session_state.messages.append({"role": "assistant", "content": action_body})

                    except Exception as e:
                        err_msg = f"❌ 처리 중 오류: {str(e)}"
                        st.error(err_msg)
                        st.session_state.messages.append({"role": "assistant", "content": err_msg})

        else:
            # ========== Legacy 모드 ==========
            with st.spinner("🤖 AI 응답 생성 중..."):
                try:
                    answer = query_gemini_ai_legacy(user_input)
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                except Exception as e:
                    err_msg = f"❌ 처리 중 오류: {str(e)}"
                    st.error(err_msg)
                    st.session_state.messages.append({"role": "assistant", "content": err_msg})

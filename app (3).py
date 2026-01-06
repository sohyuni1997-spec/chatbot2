import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from datetime import datetime, timedelta
import plotly.graph_objects as go
import re

# 분리된 모듈에서 함수 임포트
from legacy import fetch_db_data_legacy, query_gemini_ai_legacy
from hybrid_merged import ask_professional_scheduler

# ==================== 환경 설정 ====================
st.set_page_config(page_title="생산계획 통합 시스템", page_icon="🏭", layout="wide")

# Secrets 처리 개선 (secrets 파일이 없어도 작동)
try:
    URL = st.secrets.get("SUPABASE_URL", "https://qipphcdzlmqidhrjnjtt.supabase.co")
    KEY = st.secrets.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFpcHBoY2R6bG1xaWRocmpuanR0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjY5NTIwMTIsImV4cCI6MjA4MjUyODAxMn0.AsuvjVGCLUJF_IPvQevYASaM6uRF2C6F-CjwC3eCNVk")
    GENAI_KEY = st.secrets.get("GEMINI_API_KEY", "AIzaSyAQaiwm46yOITEttdr0ify7duXCW3TwGRo")
except:
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

# ==================== 데이터 로드 ====================
@st.cache_data(ttl=600)
def fetch_data(target_date=None):
    try:
        if target_date:
            dt = datetime.strptime(target_date, '%Y-%m-%d')
            start_date = (dt - timedelta(days=10)).strftime('%Y-%m-%d')
            end_date = (dt + timedelta(days=10)).strftime('%Y-%m-%d')
            plan_res = supabase.table("production_plan_2026_01").select("*").gte("plan_date", start_date).lte("plan_date", end_date).execute()
        else:
            plan_res = supabase.table("production_plan_2026_01").select("*").execute()
        
        plan_df = pd.DataFrame(plan_res.data)
        hist_res = supabase.table("production_investigation").select("*").execute()
        hist_df = pd.DataFrame(hist_res.data)
        
        if not plan_df.empty:
            plan_df['name_clean'] = plan_df['product_name'].apply(lambda x: re.sub(r'\s+', '', str(x)).strip())
            plt_map = plan_df.groupby('name_clean')['plt'].first().to_dict()
            product_map = plan_df.groupby('name_clean')['line'].unique().to_dict()
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
    patterns = [r'(\d{1,2})/(\d{1,2})', r'(\d{1,2})월\s*(\d{1,2})일', r'202[56]-(\d{1,2})-(\d{1,2})']
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            m, d = match.groups()
            return f"2026-{int(m):02d}-{int(d):02d}"
    return None

# ==================== 메인 화면 ====================
st.title("🏭 생산계획 통합 시스템")
st.caption("💡 조회는 일반 질문, 조정은 날짜+라인+%를 입력하세요")

# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 기존 메시지 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 사용자 입력
if prompt := st.chat_input("질문을 입력하세요"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 날짜 추출하여 모드 자동 판별
    target_date = extract_date(prompt)
    
    # 조정 모드 조건: 날짜 + (라인명 또는 %)
    is_adjustment_mode = target_date and (
        any(line in prompt for line in ["조립1", "조립2", "조립3"]) or 
        re.search(r'\d+%', prompt) or
        "CAPA" in prompt.upper() or
        "줄여" in prompt or
        "생산하고" in prompt
    )
    
    with st.chat_message("assistant"):
        if is_adjustment_mode:
            # ========== 조정 모드 (하이브리드 시스템) ==========
            with st.spinner("🔍 하이브리드 수사 진행 중... (Python 분석 + AI 전략 + Python 검증)"):
                plan_df, hist_df, product_map, plt_map = fetch_data(target_date)
                
                if plan_df.empty:
                    answer = "❌ 데이터를 불러올 수 없습니다. 날짜를 확인해주세요."
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
                            genai_key=GENAI_KEY
                        )
                        
                        if success:
                            answer = f"✅ {status}\n\n{report}"
                        else:
                            answer = f"⚠️ {status}\n\n{report}"
                    except Exception as e:
                        answer = f"❌ **오류 발생**\n\n```\n{str(e)}\n```"
                        st.exception(e)
                
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
                
                # CAPA 차트 추가
                if not plan_df.empty and 'qty_1차' in plan_df.columns:
                    st.markdown("---")
                    st.subheader("📊 CAPA 사용 현황")
                    
                    daily_summary = plan_df.groupby(['plan_date', 'line'])['qty_1차'].sum().reset_index()
                    daily_summary.columns = ['plan_date', 'line', 'current_qty']
                    daily_summary['max_capa'] = daily_summary['line'].map(CAPA_LIMITS)
                    daily_summary['remaining_capa'] = daily_summary['max_capa'] - daily_summary['current_qty']
                    
                    chart_data = daily_summary.pivot(index='plan_date', columns='line', values='current_qty').fillna(0)
                    
                    fig = go.Figure()
                    colors = {'조립1': '#0066CC', '조립2': '#66B2FF', '조립3': '#FF6666'}
                    
                    for line in ['조립1', '조립2', '조립3']:
                        if line in chart_data.columns:
                            fig.add_trace(go.Bar(
                                name=f'{line}',
                                x=chart_data.index,
                                y=chart_data[line],
                                marker_color=colors[line],
                                hovertemplate='%{x}<br>수량: %{y:,}개'
                            ))
                    
                    for line, limit in CAPA_LIMITS.items():
                        fig.add_hline(
                            y=limit,
                            line_dash="dash",
                            line_color=colors[line],
                            annotation_text=f"{line} 한계: {limit:,}",
                            annotation_position="right"
                        )
                    
                    fig.update_layout(
                        barmode='group',
                        height=400,
                        xaxis_title='날짜',
                        yaxis_title='수량 (개)',
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        hovermode='x unified'
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                    
                    with st.expander("📋 상세 데이터 보기"):
                        st.dataframe(
                            daily_summary.style.format({
                                'current_qty': '{:,.0f}',
                                'max_capa': '{:,.0f}',
                                'remaining_capa': '{:,.0f}'
                            }),
                            use_container_width=True
                        )
        
        else:
            # ========== 조회 모드 (레거시 챗봇) ==========
            with st.spinner("데이터 분석 중..."):
                db_result = fetch_db_data_legacy(prompt, supabase)
                
                if "찾을 수 없습니다" in db_result or "오류" in db_result:
                    answer = db_result
                else:
                    answer = query_gemini_ai_legacy(prompt, db_result, GENAI_KEY)
                
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})

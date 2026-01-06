# legacy.py
import re
import json
import pandas as pd
import requests


# =============================================================================
# 0) 파싱 / 유틸
# =============================================================================

LEGACY_DEFAULT_YEAR = "2025"


def normalize_line_name(line_val):
    s = str(line_val).strip()
    if s == "1":
        return "조립1"
    if s == "2":
        return "조립2"
    if s == "3":
        return "조립3"
    if "조립" in s:
        return s
    return s


def normalize_date(date_val):
    if not date_val:
        return ""
    s = str(date_val).strip()
    # 'YYYY-MM-DD ...' 형태면 앞 10자리만
    if len(s) >= 10:
        return s[:10]
    return s


def extract_version(text: str) -> str:
    t = (text or "")
    if ("0차" in t) or ("초기" in t) or ("계획" in t):
        return "0차"
    return "최종"


def extract_date_info(text: str, default_year: str = LEGACY_DEFAULT_YEAR):
    """
    지원:
    - '9월 5일'
    - '9/5'
    - '2025-09-05'
    - '10월' (month만)
    """
    info = {"date": None, "month": None, "year": default_year}
    t = (text or "").strip()

    # YYYY-MM-DD
    m = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        y, mm, dd = m.groups()
        info["year"] = y
        info["month"] = int(mm)
        info["date"] = f"{int(y):04d}-{int(mm):02d}-{int(dd):02d}"
        return info

    # M월 D일
    m = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", t)
    if m:
        mm, dd = m.groups()
        info["month"] = int(mm)
        info["date"] = f"{int(info['year']):04d}-{int(mm):02d}-{int(dd):02d}"
        return info

    # M/D
    m = re.search(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b", t)
    if m:
        mm, dd = m.groups()
        info["month"] = int(mm)
        info["date"] = f"{int(info['year']):04d}-{int(mm):02d}-{int(dd):02d}"
        return info

    # 월만
    m = re.search(r"(\d{1,2})\s*월", t)
    if m:
        info["month"] = int(m.group(1))

    return info


def extract_product_keyword(text: str):
    """
    월간 총 생산량/비교/카파 조회 같은 곳에서 제품 키워드가 있으면 제외하려는 목적의
    아주 단순한 키워드 추출 (기존 방식 유지)
    """
    ignore_words = {
        "생산량", "알려줘", "비교해줘", "비교", "제품", "최종", "0차", "월", "일", "capa", "카파",
        "초과", "어떻게", "돼", "있어", "사례", "총",
        "fan", "motor", "flange", "팬", "모터", "플랜지",
    }
    words = (text or "").split()
    for w in words:
        clean_w = re.sub(r"[^a-zA-Z0-9가-힣]", "", w)
        if not clean_w:
            continue
        if clean_w.lower() in ignore_words:
            continue
        if re.match(r"\d+(월|일)", clean_w):
            continue
        return clean_w
    return None


# =============================================================================
# 1) ⭐ final_issue: 증산/간섭 유사사례
# =============================================================================

def detect_increase_case_intent(text: str) -> bool:
    """
    final_issue 기반 증산/간섭 유사사례 질문 의도 감지
    """
    keywords = [
        "늘려", "늘려야", "증산", "증량", "더", "추가", "확대",
        "긴급", "급하게", "땡겨", "당겨",
        "독점", "간섭", "선순위", "후순위",
        "유사", "사례", "예전", "과거",
    ]
    t = (text or "").strip()
    return any(k in t for k in keywords)


def extract_product_name(text: str):
    """
    'A제품', 'A 모델', 'A123' 등에서 제품명 후보 추출
    """
    if not text:
        return None

    patterns = [
        r"([A-Za-z0-9]+)\s*제품",
        r"([A-Za-z0-9]+)\s*모델",
        r"\b([A-Za-z0-9]{2,})\b",
    ]
    ignore = {"생산", "늘려", "늘려야", "사례", "유사", "과거", "긴급", "증산", "간섭", "선순위", "후순위"}

    for p in patterns:
        matches = re.findall(p, text)
        for m in matches:
            if m and m not in ignore:
                return m
    return None


def _final_issue_query(user_input: str, supabase, target_date: str | None):
    """
    조건:
    - final_issue 테이블
    - final_remark in ('⚠️ 품목간 간섭 (타 모델 독점)', '➕ 긴급 물량 증량')
    - field_role in ('선순위', '후순위')
    - 같은 날 선순위/후순위 둘 다 있는 날만
    출력:
    - date / item_name / plan_qty (final_remark 미표시)
    """
    product_name = extract_product_name(user_input)

    target_remarks = ["⚠️ 품목간 간섭 (타 모델 독점)", "➕ 긴급 물량 증량"]

    q = (
        supabase.table("final_issue")
        .select("date, item_name, plan_qty, final_remark, field_role")
        .in_("final_remark", target_remarks)
        .in_("field_role", ["선순위", "후순위"])
    )

    if target_date:
        q = q.eq("date", target_date)

    if product_name:
        q = q.ilike("item_name", f"%{product_name}%")

    res = q.execute()
    if not res.data:
        return None  # final_issue에서 못 찾으면 legacy의 다른 로직으로 계속

    df = pd.DataFrame(res.data)

    # 같은 날 선/후순위 동시 존재
    role_check = df.groupby("date")["field_role"].nunique().reset_index(name="role_count")
    valid_dates = role_check[role_check["role_count"] >= 2]["date"]
    df = df[df["date"].isin(valid_dates)].copy()

    if df.empty:
        return "final_issue에서 유사 사례는 있으나, 같은 날 선순위/후순위가 동시에 존재하는 케이스가 없습니다."

    df = df.sort_values(["date", "field_role", "item_name"])
    out = df[["date", "item_name", "plan_qty"]].copy()

    context_log = "[증산/간섭 과거 유사사례(final_issue)]\n"
    context_log += out.to_string(index=False)
    return context_log


# =============================================================================
# 2) Legacy DB 조회(25년 8~11)
# =============================================================================

def fetch_db_data_legacy(user_input: str, supabase):
    """
    app(3).py에서 호출:
        db_result = fetch_db_data_legacy(prompt, supabase)
    """
    info = extract_date_info(user_input, LEGACY_DEFAULT_YEAR)
    target_date = info["date"]
    target_month = info["month"]
    target_version = extract_version(user_input)
    product_key = extract_product_keyword(user_input)

    try:
        # =====================================================================
        # 0) ⭐ final_issue 증산/간섭 유사사례 (최우선)
        # =====================================================================
        if detect_increase_case_intent(user_input):
            fi = _final_issue_query(user_input, supabase, target_date)
            if fi is not None:
                return fi

        # =====================================================================
        # 1) 과거 이슈 사례 (production_issue_analysis_8_11)
        # =====================================================================
        if "사례" in user_input:
            issue_mapping = {
                "MDL1": {"keywords": ["먼저", "줄여", "순위", "교체"], "db_text": "생산순위 조정",
                         "title": "MDL1: 미달(생산순위 조정/모델 교체)"},
                "MDL2": {"keywords": ["감사", "정지", "설비", "라인전체"], "db_text": "라인전체이슈",
                         "title": "MDL2: 미달(라인전체이슈/설비)"},
                "MDL3": {"keywords": ["부품", "자재", "결품", "수급", "안되는"], "db_text": "자재결품",
                         "title": "MDL3: 미달(부품수급/자재결품)"},
                "PRP": {"keywords": ["선행", "미리", "당겨", "땡겨"], "db_text": "선행 생산",
                        "title": "PRP: 선행 생산(숙제 미리하기)"},
                "SMP": {"keywords": ["샘플", "긴급"], "db_text": "계획외 긴급 생산",
                        "title": "SMP: 계획외 긴급 생산"},
                "CCL": {"keywords": ["취소"], "db_text": "계획 취소",
                        "title": "CCL: 계획 취소/라인 가동중단"},
            }

            detected_code = None
            for code, meta in issue_mapping.items():
                if any(k in user_input for k in meta["keywords"]):
                    detected_code = code
                    break

            if detected_code:
                meta = issue_mapping[detected_code]
                query = supabase.table("production_issue_analysis_8_11") \
                    .select("품목명, 날짜, 계획_v0, 실적_v2, 누적차이_Gap, 최종_이슈분류")

                if detected_code == "MDL2":
                    query = query.or_("최종_이슈분류.ilike.%라인전체이슈%,최종_이슈분류.ilike.%설비%")
                elif detected_code == "MDL3":
                    query = query.or_("최종_이슈분류.ilike.%부품수급%,최종_이슈분류.ilike.%자재결품%")
                else:
                    query = query.ilike("최종_이슈분류", f"%{meta['db_text']}%")

                res = query.limit(3).execute()
                if res.data:
                    return (
                        "[CODE CASE FOUND]\n"
                        f"Code: {detected_code}\n"
                        f"Title: {meta['title']}\n"
                        f"Data: {json.dumps(res.data, ensure_ascii=False)}"
                    )
                return "관련된 과거 유사 사례를 찾을 수 없습니다."

        # =====================================================================
        # 2) 월간 총 생산량 브리핑 (두 달 이상 입력 & 제품키워드 없을 때)
        # =====================================================================
        found_months = re.findall(r"(\d{1,2})\s*월", user_input)
        found_months = sorted(list(set([int(m) for m in found_months])))

        if len(found_months) >= 2 and product_key is None:
            res = supabase.table("monthly_production") \
                .select("월, 총_생산량") \
                .in_("월", found_months) \
                .eq("버전", target_version) \
                .execute()

            if res.data:
                df = pd.DataFrame(res.data).sort_values(by="월")
                out = [f"[{target_version} 월간 총 생산량 브리핑]"]
                prev_val, prev_month = None, None
                for _, row in df.iterrows():
                    m = int(row["월"])
                    val = int(row["총_생산량"])
                    msg = f"{m}월: {val:,}"
                    if prev_val is not None:
                        diff = val - prev_val
                        if diff > 0:
                            msg += f" (전월({prev_month}월) 대비 {diff:,} 증가)"
                        elif diff < 0:
                            msg += f" (전월({prev_month}월) 대비 {abs(diff):,} 감소)"
                        else:
                            msg += " (변동 없음)"
                    out.append(f"- {msg}")
                    prev_val, prev_month = val, m
                return "\n".join(out)

            return "요청하신 월의 데이터가 monthly_production 테이블에 없습니다."

        # =====================================================================
        # 3) 단순 CAPA 조회 ("00월 CAPA 알려줘")
        # =====================================================================
        if target_month and ("capa" in user_input.lower() or "카파" in user_input) and "초과" not in user_input:
            res = supabase.table("daily_capa").select("*").eq("월", target_month).execute()
            if not res.data:
                return f"{target_month}월 CAPA 데이터가 없습니다."

            df = pd.DataFrame(res.data)
            # 컬럼명 '라인', 'CAPA' 또는 'capa' 대응
            if "라인" in df.columns:
                df["라인"] = df["라인"].apply(normalize_line_name)

            capa_col = None
            for c in ["CAPA", "capa", "Capa", "cApa"]:
                if c in df.columns:
                    capa_col = c
                    break
            if capa_col is None:
                return f"{target_month}월 CAPA 데이터는 있으나 CAPA 컬럼을 찾지 못했습니다."

            out = [f"[{target_month}월 CAPA 정보]"]
            for line in ["조립1", "조립2", "조립3"]:
                sub = df[df["라인"] == line] if "라인" in df.columns else pd.DataFrame()
                if not sub.empty:
                    val = sub.iloc[0][capa_col]
                    try:
                        val = int(val)
                    except Exception:
                        pass
                    out.append(f"- {line}: {val:,}" if isinstance(val, int) else f"- {line}: {val}")
            return "\n".join(out)

        # =====================================================================
        # 4) CAPA 초과 조회 ("00월 CAPA 초과한 날?")
        # =====================================================================
        if "초과" in user_input and target_month:
            res_prod = supabase.table("daily_total_production").select("*") \
                .eq("월", target_month).eq("버전", target_version).execute()

            if not res_prod.data:
                return f"{target_month}월 {target_version} 생산량 데이터가 없습니다."

            df_prod = pd.DataFrame(res_prod.data)
            if "라인" in df_prod.columns:
                df_prod["라인"] = df_prod["라인"].apply(normalize_line_name)
            if "날짜" in df_prod.columns:
                df_prod["날짜"] = df_prod["날짜"].apply(normalize_date)

            res_capa = supabase.table("daily_capa").select("*").eq("월", target_month).execute()
            if not res_capa.data:
                return f"{target_month}월 CAPA 데이터가 없습니다."

            df_capa = pd.DataFrame(res_capa.data)
            if "라인" in df_capa.columns:
                df_capa["라인"] = df_capa["라인"].apply(normalize_line_name)

            capa_col = None
            for c in ["CAPA", "capa", "Capa", "cApa"]:
                if c in df_capa.columns:
                    capa_col = c
                    break
            if capa_col is None:
                return f"{target_month}월 CAPA 데이터는 있으나 CAPA 컬럼을 찾지 못했습니다."

            capa_map = dict(zip(df_capa["라인"], df_capa[capa_col]))

            # daily_total_production의 총 생산량 컬럼명 대응
            qty_col = None
            for c in ["총_생산량", "총생산량", "total_qty", "qty"]:
                if c in df_prod.columns:
                    qty_col = c
                    break
            if qty_col is None:
                return f"{target_month}월 생산량 데이터는 있으나 총 생산량 컬럼을 찾지 못했습니다."

            df_prod["CAPA"] = df_prod["라인"].map(capa_map)

            # 숫자 변환 시도
            df_prod["CAPA_num"] = pd.to_numeric(df_prod["CAPA"], errors="coerce")
            df_prod["QTY_num"] = pd.to_numeric(df_prod[qty_col], errors="coerce")

            over = df_prod[(df_prod["CAPA_num"].notna()) & (df_prod["QTY_num"].notna()) & (df_prod["QTY_num"] > df_prod["CAPA_num"])]

            if over.empty:
                return f"{target_month}월 {target_version} 버전에서 CAPA를 초과한 날이 없습니다."

            # Context를 'CAPA 초과 리스트' 형태로 반환 (LLM이 표로 만들 수 있게)
            out = ["[CAPA 초과 리스트]"]
            for _, r in over.iterrows():
                out.append(
                    f"날짜: {r.get('날짜','')}, 라인: {r.get('라인','')}, CAPA: {int(r['CAPA_num']):,}, 총 생산량: {int(r['QTY_num']):,}"
                )
            return "\n".join(out)

        # =====================================================================
        # 5) 일별 생산량 조회 ("9월 5일 최종 생산량")
        # =====================================================================
        if target_date and ("생산" in user_input and "량" in user_input):
            res = supabase.table("daily_total_production").select("*") \
                .eq("날짜", target_date).eq("버전", target_version).execute()

            if res.data:
                df = pd.DataFrame(res.data)
                if "라인" in df.columns:
                    df["라인"] = df["라인"].apply(normalize_line_name)

                qty_col = None
                for c in ["총_생산량", "총생산량", "total_qty", "qty"]:
                    if c in df.columns:
                        qty_col = c
                        break

                if qty_col is None:
                    return f"{target_date} {target_version} 데이터는 있으나 총 생산량 컬럼을 찾지 못했습니다."

                out = [f"[{target_date} {target_version} 생산량]"]
                for _, row in df.iterrows():
                    line = row.get("라인", "")
                    qty = row.get(qty_col, 0)
                    try:
                        qty = int(qty)
                        out.append(f"- {line}: {qty:,}개")
                    except Exception:
                        out.append(f"- {line}: {qty}")
                return "\n".join(out)

            return f"{target_date} {target_version} 데이터가 없습니다."

        # =====================================================================
        # Fallback
        # =====================================================================
        return "질문을 이해하지 못했습니다. 예: '10월 CAPA 초과한 날?', '9월 10월 최종 총 생산량 브리핑', '9월 5일 최종 생산량', 'A제품 증산 사례'"

    except Exception as e:
        return f"오류 발생: {str(e)}"


# =============================================================================
# 3) Gemini 응답 생성 (legacy)
# =============================================================================

def query_gemini_ai_legacy(user_input: str, context: str, gemini_key: str) -> str:
    """
    app(3).py에서 호출:
        answer = query_gemini_ai_legacy(prompt, db_result, GENAI_KEY)
    """
    if not gemini_key:
        # 키가 없으면 그냥 컨텍스트 출력
        return context

    system_prompt = f"""
당신은 숙련된 생산계획 담당자입니다. 제공된 데이터(Context)를 기반으로 사용자의 질문에 답하세요.

[중요: CAPA 초과 답변 규칙]
Context에 '[CAPA 초과 리스트]'가 포함되어 있다면, 반드시 아래 형식의 마크다운 표(Table)로 출력하세요.

| 날짜 | 라인 | CAPA | 총 생산량 |
|---|---|---|---|
| ... | ... | ... | ... |

[중요: 이슈 코드 답변 규칙]
Context에 [CODE CASE FOUND]가 있다면:
1) 답변 최상단에 코드명과 제목을 # Heading 1로 적으세요.
2) 데이터(Data)를 바탕으로 표를 작성하세요: [날짜 | 품목명 | 계획(V0) | 실적(V2) | 차이(Gap)]

[일반 답변 규칙]
1) 숫자는 제공된 그대로 전달하세요.
2) 데이터가 없으면 없다고 하세요.
3) 간결하고 명확하게 답변하세요.

[Context Data]
{context}

[User Question]
{user_input}
""".strip()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={gemini_key}"
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": system_prompt}]}]}

    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        if response.status_code != 200:
            return context

        j = response.json()
        return j["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return context

import re
import html
import calendar as pycal
from datetime import date, datetime
import streamlit as st
import pandas as pd

# =========================
# 1. 컬럼명 및 기본 설정
# =========================
COL_QTY = "요청수량"
COL_YEAR = "년"
COL_MONTH = "월1"
COL_WEEK_LABEL = "주차"
COL_DONE = "작업완료"
COL_SHIP = "출고일자"
COL_LT2 = "리드타임"
COL_BP = "BP명"
COL_MAIN = "대표행"
COL_CUST1 = "거래처구분1"
COL_CUST2 = "거래처구분2"
COL_CLASS = "제품분류"
COL_ITEM_CODE = "품목코드"
COL_ITEM_NAME = "품목명"
COL_ORDER_DATE = "발주일자"
COL_ORDER_NO = "주문번호"

KEEP_CLASSES = ["B0", "B1"]
GSHEET_ID = "1jbWMgV3fudWCQ1qhG0lCysZGGFCo4loTIf-j3iuaqOI"
GSHEET_GID = "15468212"
HEADER_ROW_0BASED = 6

# =========================
# 2. Streamlit 설정 및 세션 초기화
# =========================
st.set_page_config(page_title="B2B 출고 대시보드", layout="wide")

# 세션 상태 초기화 (메뉴 버그 해결의 핵심)
if "nav_menu" not in st.session_state:
    st.session_state["nav_menu"] = "① 출고 캘린더"
if "cal_detail_data" not in st.session_state:
    st.session_state["cal_detail_data"] = None

# CSS 스타일 (색상 구분 및 레이아웃)
st.markdown("""
<style>
    .block-container {padding-top: 1.5rem;}
    /* 메뉴 버튼 스타일 */
    .nav-btn-active { border: 2px solid #ff4b4b !important; color: #ff4b4b !important; font-weight: bold; }
    
    /* 캘린더 디자인 */
    .cal-wrap { border:1px solid #e5e7eb; border-radius:12px; background:#fff; overflow:hidden; margin-top:10px;}
    .cal-head { display:grid; grid-template-columns: repeat(7, 1fr); background:#f9fafb; border-bottom:1px solid #e5e7eb; }
    .cal-head div { padding:12px; font-weight:800; text-align:center; color:#374151; font-size:0.9rem; }
    .cal-grid { display:grid; grid-template-columns: repeat(7, 1fr); }
    .cal-cell { min-height:130px; border-right:1px solid #f3f4f6; border-bottom:1px solid #f3f4f6; padding:8px; }
    .cal-day { font-weight:700; margin-bottom:8px; font-size:1rem; }
    
    /* KPI 카드 */
    .kpi-card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 1rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
    
    /* Pill 스타일 (해외-붉은색 / 국내-푸른색) */
    .stButton > button { line-height: 1.2; font-size: 12px; padding: 2px 5px; margin-bottom: 2px; width: 100%; text-align: left; }
    .over-pill { background-color: #fee2e2 !important; color: #b91c1c !important; border: 1px solid #fecaca !important; }
    .dom-pill { background-color: #e0f2fe !important; color: #0369a1 !important; border: 1px solid #bae6fd !important; }
</style>
""", unsafe_allow_html=True)

# =========================
# 3. 데이터 로드 및 전처리
# =========================
@st.cache_data(ttl=300)
def load_gsheet_data():
    csv_url = f"https://docs.google.com/spreadsheets/d/{GSHEET_ID}/export?format=csv&gid={GSHEET_GID}"
    df = pd.read_csv(csv_url, header=HEADER_ROW_0BASED)
    df.columns = df.columns.astype(str).str.strip()
    
    # 날짜 및 숫자 변환
    for c in [COL_SHIP, COL_DONE, COL_ORDER_DATE]:
        if c in df.columns: df[c] = pd.to_datetime(df[c], errors="coerce")
    if COL_QTY in df.columns:
        df[COL_QTY] = pd.to_numeric(df[COL_QTY].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
    
    # 제품분류 필터 (B0, B1 고정)
    if COL_CLASS in df.columns:
        df = df[df[COL_CLASS].astype(str).str.strip().isin(KEEP_CLASSES)].copy()
    
    # 대표행 여부
    df["_is_rep"] = df[COL_MAIN].fillna("").astype(str).str.upper().isin(["TRUE", "Y", "1"]) if COL_MAIN in df.columns else False
    
    # 월 라벨
    if all(c in df.columns for c in [COL_YEAR, COL_MONTH]):
        df["_month_label"] = df.apply(lambda r: f"{int(r[COL_YEAR])}년 {int(r[COL_MONTH])}월" if pd.notna(r[COL_YEAR]) else "", axis=1)
    
    return df

raw = load_gsheet_data()

# =========================
# 4. 상단 KPI 및 사이드바 필터
# =========================
st.title("📦 B2B 출고 대시보드")
st.sidebar.header("필터 설정")

cust1_list = sorted(raw[COL_CUST1].dropna().unique())
sel_cust1 = st.sidebar.selectbox("거래처구분1", ["전체"] + cust1_list)

filtered_df = raw.copy()
if sel_cust1 != "전체":
    filtered_df = filtered_df[filtered_df[COL_CUST1] == sel_cust1]

# KPI 카드 렌더링
k1, k2, k3, k4 = st.columns(4)
with k1: st.metric("총 출고수량(합)", f"{int(filtered_df[COL_QTY].sum()):,}")
with k2: st.metric("총 출고건수", f"{int(filtered_df['_is_rep'].sum()):,}")
with k3: st.metric("최근 작업완료일", str(filtered_df[COL_DONE].max().date()) if not filtered_df[COL_DONE].dropna().empty else "-")
with k4: 
    overseas_lt = filtered_df[filtered_df[COL_CUST1]=="해외B2B"][COL_LT2].dropna()
    st.metric("리드타임 평균(해외)", f"{overseas_lt.mean():.1f}일" if not overseas_lt.empty else "-")

st.divider()

# =========================
# 5. 핵심: 메뉴 내비게이션 (버튼형으로 전면 교체)
# =========================
# 버튼을 사용하여 페이지 전환 버그를 원천 차단합니다.
menu_names = ["① 출고 캘린더", "② SKU별 조회", "③ 주차요약", "④ 월간요약", "⑤ 국가별 조회", "⑥ BP명별 조회"]
cols = st.columns(6)

for i, name in enumerate(menu_names):
    if cols[i].button(name, use_container_width=True, type="primary" if st.session_state["nav_menu"] == name else "secondary"):
        st.session_state["nav_menu"] = name
        st.session_state["cal_detail_data"] = None # 메뉴 이동 시 상세 내역 초기화
        st.rerun()

st.subheader(f"📍 {st.session_state['nav_menu']}")

# =========================
# 6. 각 메뉴별 렌더링 로직
# =========================

# --- ① 출고 캘린더 ---
if st.session_state["nav_menu"] == "① 출고 캘린더":
    
    # 상세 내역 보기 모드 (페이지 전환)
    if st.session_state["cal_detail_data"]:
        dt = st.session_state["cal_detail_data"]["date"]
        bp = st.session_state["cal_detail_data"]["bp"]
        
        if st.button("⬅ 캘린더로 돌아가기"):
            st.session_state["cal_detail_data"] = None
            st.rerun()
            
        st.markdown(f"### 📦 {dt} / {bp} 상세 내역")
        detail_view = filtered_df[(filtered_df[COL_SHIP].dt.date == pd.to_datetime(dt).date()) & (filtered_df[COL_BP] == bp)]
        st.dataframe(detail_view[[COL_SHIP, COL_DONE, COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY]], use_container_width=True, hide_index=True)

    else:
        # 캘린더 본체
        c1, c2 = st.columns([1, 1])
        with c1: cal_y = st.number_input("연도", 2024, 2030, 2026)
        with c2: cal_m = st.number_input("월", 1, 12, 2)
        
        # 날짜 계산 (일요일 시작 기준)
        first_day = date(cal_y, cal_m, 1)
        start_blank = (first_day.weekday() + 1) % 7
        last_day = pycal.monthrange(cal_y, cal_m)[1]
        
        # 일자별 데이터 집계
        month_df = filtered_df[filtered_df[COL_SHIP].dt.month == cal_m].copy()
        month_df["_d"] = month_df[COL_SHIP].dt.date
        day_gp = month_df.groupby(["_d", COL_BP, COL_CUST1])[COL_QTY].sum().reset_index()

        # 캘린더 HTML/CSS 렌더링
        st.markdown('<div class="cal-wrap"><div class="cal-head"><div>Sun</div><div>Mon</div><div>Tue</div><div>Wed</div><div>Thu</div><div>Fri</div><div>Sat</div></div><div class="cal-grid">', unsafe_allow_html=True)
        
        # 빈 칸 (이전 달)
        for _ in range(start_blank):
            st.markdown('<div class="cal-cell" style="background:#f9fafb;"></div>', unsafe_allow_html=True)
            
        # 날짜별 셀
        for d in range(1, last_day + 1):
            cur_date = date(cal_y, cal_m, d)
            st.markdown(f'<div class="cal-cell"><div class="cal-day">{d}</div>', unsafe_allow_html=True)
            
            # 셀 내부 BP 버튼 생성
            day_data = day_gp[day_gp["_d"] == cur_date]
            for _, row in day_data.iterrows():
                p_style = "over-pill" if row[COL_CUST1] == "해외B2B" else "dom-pill"
                # 버튼 클릭 시 세션에 정보를 넣고 리런 (새 창이 아닌 전환)
                if st.button(f"{row[COL_BP]} ({int(row[COL_QTY]):,})", key=f"cal-{cur_date}-{row[COL_BP]}", help="상세내역 보기"):
                    st.session_state["cal_detail_data"] = {"date": str(cur_date), "bp": row[COL_BP]}
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div></div>', unsafe_allow_html=True)

# --- ② SKU별 조회 ---
elif st.session_state["nav_menu"] == "② SKU별 조회":
    sku_input = st.text_input("검색할 품목코드를 입력하세요.")
    if sku_input:
        res = filtered_df[filtered_df[COL_ITEM_CODE].str.contains(sku_input, na=False, case=False)]
        st.dataframe(res, use_container_width=True)
    else:
        st.info("조회할 SKU 코드를 입력해주세요.")

# --- ③ 주차요약 ---
elif st.session_state["nav_menu"] == "③ 주차요약":
    if COL_WEEK_LABEL in filtered_df.columns:
        weeks = sorted(filtered_df[COL_WEEK_LABEL].dropna().unique(), reverse=True)
        sel_w = st.selectbox("주차 선택", weeks)
        st.dataframe(filtered_df[filtered_df[COL_WEEK_LABEL] == sel_w], use_container_width=True)
    else:
        st.warning("데이터에 주차 정보가 없습니다.")

# --- ④ 월간요약 ---
elif st.session_state["nav_menu"] == "④ 월간요약":
    if "_month_label" in filtered_df.columns:
        months = sorted(filtered_df["_month_label"].dropna().unique(), reverse=True)
        sel_m = st.selectbox("월 선택", months)
        st.write(f"### {sel_m} 출고 현황")
        m_summary = filtered_df[filtered_df["_month_label"] == sel_m].groupby(COL_BP)[COL_QTY].sum().sort_values(ascending=False)
        st.bar_chart(m_summary)
    else:
        st.warning("데이터에 월 정보가 없습니다.")

# --- ⑤ 국가별 조회 ---
elif st.session_state["nav_menu"] == "⑤ 국가별 조회":
    if COL_CUST2 in filtered_df.columns:
        country_sum = filtered_df.groupby(COL_CUST2)[COL_QTY].sum().sort_values(ascending=False)
        st.dataframe(country_sum, use_container_width=True)
    else:
        st.warning("데이터에 국가(거래처구분2) 정보가 없습니다.")

# --- ⑥ BP명별 조회 ---
elif st.session_state["nav_menu"] == "⑥ BP명별 조회":
    bp_list = sorted(filtered_df[COL_BP].dropna().unique())
    sel_bp = st.selectbox("조회할 BP를 선택하세요.", bp_list)
    st.dataframe(filtered_df[filtered_df[COL_BP] == sel_bp], use_container_width=True)

st.sidebar.divider()
st.sidebar.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

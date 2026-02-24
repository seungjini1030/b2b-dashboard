import re
import html
import calendar as pycal
from datetime import date, datetime
from urllib.parse import quote, unquote
import streamlit as st
import pandas as pd

# ==========================================
# 1. 컬럼명 표준화 및 설정 (원본 로직 100% 유지)
# ==========================================
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

CATEGORY_COL_CANDIDATES = ["카테고리 라인", "카테고리라인", "카테고리", "카테고리(Line)", "카테고리_LINE", "Category Line", "Category"]
KEEP_CLASSES = ["B0", "B1"]
LT_ONLY_CUST1 = "해외B2B"
SPIKE_FACTOR = 1.3  # +30%

GSHEET_ID = "1jbWMgV3fudWCQ1qhG0lCysZGGFCo4loTIf-j3iuaqOI"
GSHEET_GID = "15468212"
HEADER_ROW_0BASED = 6

# ==========================================
# 2. Streamlit 설정 및 세션 초기화 (버그 해결 핵심)
# ==========================================
st.set_page_config(page_title="B2B 출고 대시보드 (Google Sheet 기반)", layout="wide")

if "nav_menu" not in st.session_state:
    st.session_state["nav_menu"] = "① 출고 캘린더"
if "cal_detail" not in st.session_state:
    st.session_state["cal_detail"] = None

# CSS Style (기존 디자인 보존 + 캘린더 커스텀)
st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2.5rem;}
.kpi-wrap {display:flex; gap:0.75rem; flex-wrap:wrap; margin: 0.25rem 0 0.75rem 0;}
.kpi-card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 14px; padding: 0.9rem; min-width: 180px; flex: 1; box-shadow: 0 1px 0 rgba(0,0,0,0.02); }
.kpi-value {font-size:1.35rem; font-weight:700; color:#111827;}

/* 캘린더 UI */
.cal-wrap { border:1px solid #e5e7eb; border-radius:14px; background:#fff; overflow:hidden; }
.cal-head { display:grid; grid-template-columns: repeat(7, 1fr); background:#f9fafb; border-bottom:1px solid #e5e7eb; text-align:center; }
.cal-head div { padding:10px; font-weight:900; color:#111827; }
.cal-grid { display:grid; grid-template-columns: repeat(7, 1fr); }
.cal-cell { min-height:150px; border-right:1px solid #e5e7eb; border-bottom:1px solid #e5e7eb; padding:8px; }
.cal-day { font-weight:900; color:#111827; margin-bottom:6px; }

/* Pill 버튼 (해외:붉은색계열 / 국내:푸른색계열) */
.stButton > button { line-height: 1.2 !important; padding: 2px 8px !important; text-align: left !important; font-size: 11px !important; width: 100% !important; margin-bottom: 3px !important; border-radius: 12px !important; }
.over-pill-btn > div > button { background-color: #fee2e2 !important; color: #b91c1c !important; border: 1px solid #fecaca !important; }
.dom-pill-btn > div > button { background-color: #e0f2fe !important; color: #1d4ed8 !important; border: 1px solid #bae6fd !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 분석 유틸리티 함수 (기존 원본 로직 100% 복구)
# ==========================================
def _fmt_int(x): return f"{int(round(float(x))):,}"
def fmt_date(dtval): return pd.to_datetime(dtval).strftime("%Y-%m-%d") if pd.notna(dtval) else "-"
def _fmt_delta(diff):
    d = int(round(float(diff)))
    return f"{d:+,} {'▲' if d>0 else '▼' if d<0 else '-'}"

@st.cache_data(ttl=300)
def load_raw_from_gsheet():
    csv_url = f"https://docs.google.com/spreadsheets/d/{GSHEET_ID}/export?format=csv&gid={GSHEET_GID}"
    df = pd.read_csv(csv_url, header=HEADER_ROW_0BASED)
    df.columns = df.columns.astype(str).str.strip()
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")]
    for c in [COL_SHIP, COL_DONE, COL_ORDER_DATE]:
        if c in df.columns: df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in [COL_QTY, COL_LT2]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
    if COL_CLASS in df.columns:
        df = df[df[COL_CLASS].astype(str).str.strip().isin(KEEP_CLASSES)].copy()
    df["_is_rep"] = df[COL_MAIN].fillna("").astype(str).str.upper().isin(["TRUE", "Y", "1", "YES"])
    if COL_YEAR in df.columns and COL_MONTH in df.columns:
        df["_month_label"] = df.apply(lambda r: f"{int(r[COL_YEAR])}년 {int(r[COL_MONTH])}월" if pd.notna(r[COL_YEAR]) else None, axis=1)
    def get_wk(r):
        dt = r[COL_SHIP] if pd.notna(r[COL_SHIP]) else r[COL_DONE]
        return f"{dt.year}년 {dt.month}월 {(dt.day-1)//7+1}주차" if pd.notna(dt) else None
    df["_week_label"] = df.apply(get_wk, axis=1)
    return df

# --- [기존 분석용 함수: 코멘트, Top10, 리포트 생성기 등] ---
def sku_comment_mom(sku_month):
    if len(sku_month) < 2: return []
    m = sku_month.sort_values("_month_key")
    prev, cur = m.iloc[-2], m.iloc[-1]
    pct = (cur['qty']/prev['qty']-1)*100 if prev['qty']>0 else 0
    return [f"{prev['_month_label']} 대비 {cur['_month_label']} 출고량 **{'상승' if pct>0 else '하락'} ({pct:+.0f}%)** · {_fmt_int(prev['qty'])} → {_fmt_int(cur['qty'])}"]

def build_item_top10_with_bp(df):
    if df.empty: return pd.DataFrame()
    top10 = df.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY].sum().reset_index().sort_values(COL_QTY, ascending=False).head(10)
    top10.insert(0, "순위", range(1, len(top10)+1))
    return top10

def build_spike_report(cur_df, prev_df):
    cur_sku = cur_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY].sum().reset_index(name="현재")
    prev_sku = prev_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY].sum().reset_index(name="이전")
    m = cur_sku.merge(prev_sku, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="left").fillna(0)
    spike = m[(m["이전"] > 0) & (m["현재"] >= m["이전"] * SPIKE_FACTOR)].copy()
    spike["증가배수"] = (spike["현재"] / spike["이전"]).round(2)
    return spike.sort_values("현재", ascending=False)

def render_numbered_block(title, items):
    if not items: return
    st.markdown(f"**{title}**")
    for i, line in enumerate(items, start=1): st.write(f"{i}) {line}")

# ==========================================
# 4. 데이터 로드 및 사이드바
# ==========================================
raw = load_raw_from_gsheet()
st.sidebar.header("필터")
cust1_list = sorted(raw[COL_CUST1].dropna().unique())
sel_cust1 = st.sidebar.selectbox("거래처구분1", ["전체"] + cust1_list, key="f_cust1")

filtered_df = raw.copy()
if sel_cust1 != "전체":
    filtered_df = filtered_df[filtered_df[COL_CUST1] == sel_cust1]

# KPI 카드
k1, k2, k3, k4 = st.columns(4)
k1.metric("총 출고수량", f"{int(filtered_df[COL_QTY].sum()):,}")
k2.metric("총 출고건수", f"{int(filtered_df['_is_rep'].sum()):,}")
k3.metric("최근 작업일", str(filtered_df[COL_DONE].max().date()) if not filtered_df[COL_DONE].dropna().empty else "-")
k4.metric("평균 LT(해외)", f"{filtered_df[filtered_df[COL_CUST1]=='해외B2B'][COL_LT2].mean():.1f}일")

st.divider()

# ==========================================
# 5. [수정] 메뉴 내비게이션 (버튼형으로 전환)
# ==========================================
menu_options = ["① 출고 캘린더", "② SKU별 조회", "③ 주차요약", "④ 월간요약", "⑤ 국가별 조회", "⑥ BP명별 조회"]
cols = st.columns(6)

for i, m_name in enumerate(menu_options):
    if cols[i].button(m_name, use_container_width=True, type="primary" if st.session_state["nav_menu"] == m_name else "secondary"):
        st.session_state["nav_menu"] = m_name
        st.session_state["cal_detail"] = None
        st.rerun()

# ==========================================
# 6. 메뉴별 상세 구현 (원본 로직 완전 복구)
# ==========================================

# --- ① 출고 캘린더 ---
if st.session_state["nav_menu"] == "① 출고 캘린더":
    if st.session_state["cal_detail"]:
        # 상세 보기
        det = st.session_state["cal_detail"]
        if st.button("⬅ 캘린더로 돌아가기"):
            st.session_state["cal_detail"] = None
            st.rerun()
        st.subheader(f"📦 {det['date']} / {det['bp']} 상세 내역")
        dt_obj = pd.to_datetime(det['date']).date()
        target = filtered_df[(filtered_df[COL_SHIP].dt.date == dt_obj) & (filtered_df[COL_BP] == det['bp'])]
        st.dataframe(target[[COL_SHIP, COL_DONE, COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY]], use_container_width=True, hide_index=True)
    else:
        st.subheader("📅 출고 일자별 캘린더")
        cy, cm = st.columns(2)
        sel_y = cy.number_input("연도", 2024, 2030, 2026)
        sel_m = cm.number_input("월", 1, 12, 2)
        
        # [수정] 요일 정렬 보정
        f_day = date(int(sel_y), int(sel_m), 1)
        start_padding = (f_day.weekday() + 1) % 7
        days_num = pycal.monthrange(int(sel_y), int(sel_m))[1]
        
        m_df = filtered_df[filtered_df[COL_SHIP].dt.month == sel_m].copy()
        m_df["_d"] = m_df[COL_SHIP].dt.date
        cal_gp = m_df.groupby(["_d", COL_BP, COL_CUST1])[COL_QTY].sum().reset_index()

        st.markdown('<div class="cal-wrap"><div class="cal-head"><div>Sun</div><div>Mon</div><div>Tue</div><div>Wed</div><div>Thu</div><div>Fri</div><div>Sat</div></div><div class="cal-grid">', unsafe_allow_html=True)
        for _ in range(start_padding): st.markdown('<div class="cal-cell" style="background:#f9fafb;"></div>', unsafe_allow_html=True)
        for d in range(1, days_num + 1):
            cur_d = date(int(sel_y), int(sel_m), d)
            st.markdown(f'<div class="cal-cell"><div class="cal-day">{d}</div>', unsafe_allow_html=True)
            day_items = cal_gp[cal_gp["_d"] == cur_d]
            for _, row in day_items.iterrows():
                css = "over-pill-btn" if row[COL_CUST1] == "해외B2B" else "dom-pill-btn"
                st.markdown(f'<div class="{css}">', unsafe_allow_html=True)
                if st.button(f"{row[COL_BP]} ({int(row[COL_QTY]):,})", key=f"c-{cur_d}-{row[COL_BP]}"):
                    st.session_state["cal_detail"] = {"date": str(cur_d), "bp": row[COL_BP]}
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div></div>', unsafe_allow_html=True)

# --- ② SKU별 조회 ---
elif st.session_state["nav_menu"] == "② SKU별 조회":
    st.subheader("SKU별 상세 분석")
    sku_q = st.text_input("품목코드 검색")
    if sku_q:
        sku_df = filtered_df[filtered_df[COL_ITEM_CODE].str.contains(sku_q, na=False, case=False)]
        if not sku_df.empty:
            st.info(f"품목명: {sku_df[COL_ITEM_NAME].iloc[0]}")
            m_sum = sku_df.groupby("_month_label")[COL_QTY].sum().reset_index().rename(columns={COL_QTY:'qty'})
            def parse_mk(l): return int(re.search(r"(\d+)년\s*(\d+)월", str(l)).group(1))*100 + int(re.search(r"(\d+)년\s*(\d+)월", str(l)).group(2))
            m_sum["_month_key"] = m_sum["_month_label"].apply(parse_mk)
            render_numbered_block("월간 추이 코멘트", sku_comment_mom(m_sum))
            st.dataframe(sku_df.sort_values(COL_SHIP, ascending=False))
    st.divider()
    st.markdown("### 누적 SKU Top 10")
    st.dataframe(build_item_top10_with_bp(filtered_df), use_container_width=True, hide_index=True)

# --- ③ 주차요약 ---
elif st.session_state["nav_menu"] == "③ 주차요약":
    st.subheader("주차별 출고 요약")
    weeks = sorted(filtered_df["_week_label"].dropna().unique())
    if weeks:
        sel_w = st.selectbox("주차 선택", weeks, index=len(weeks)-1)
        w_df = filtered_df[filtered_df["_week_label"] == sel_w]
        prev_w = weeks[weeks.index(sel_w)-1] if weeks.index(sel_w) > 0 else None
        if prev_w:
            p_df = filtered_df[filtered_df["_week_label"] == prev_w]
            c_o = w_df[COL_ORDER_NO].nunique() if COL_ORDER_NO in w_df.columns else 0
            p_o = p_df[COL_ORDER_NO].nunique() if COL_ORDER_NO in p_df.columns else 0
            render_numbered_block("전주 대비 KPI", [f"발주건수: {c_o}건 ({_fmt_delta(c_o-p_o)}) / 출고수량: {_fmt_int(w_df[COL_QTY].sum())}개 ({_fmt_delta(w_df[COL_QTY].sum()-p_df[COL_QTY].sum())})"])
            st.markdown("#### 🚀 전주 대비 급증 SKU (+30%↑)")
            st.dataframe(build_spike_report(w_df, p_df), hide_index=True)
        st.bar_chart(w_df.groupby(COL_BP)[COL_QTY].sum())

# --- ④ 월간요약 ---
elif st.session_state["nav_menu"] == "④ 월간요약":
    st.subheader("월간 성과 리포트")
    months = sorted(filtered_df["_month_label"].dropna().unique())
    if months:
        sel_m = st.selectbox("월 선택", months, index=len(months)-1)
        m_df = filtered_df[filtered_df["_month_label"] == sel_m]
        st.metric(f"{sel_m} 총 출고량", f"{int(m_df[COL_QTY].sum()):,}개")
        if st.button("📝 슬랙 리포트 텍스트 생성"):
            report = f"*{sel_m} B2B 출고 현황*\n- 총 출고: {int(m_df[COL_QTY].sum()):,}개\n- 주요 BP: {', '.join(m_df.groupby(COL_BP)[COL_QTY].sum().nlargest(3).index)}"
            st.code(report)

# --- ⑤ 국가별 조회 ---
elif st.session_state["nav_menu"] == "⑤ 국가별 조회":
    st.subheader("국가별(거래처구분2) 통계")
    country_df = filtered_df.groupby(COL_CUST2).agg({COL_QTY: "sum", COL_LT2: "mean"}).reset_index()
    st.dataframe(country_df.sort_values(COL_QTY, ascending=False), hide_index=True)

# --- ⑥ BP명별 조회 ---
elif st.session_state["nav_menu"] == "⑥ BP명별 조회":
    st.subheader("BP별 출고 실적")
    bps = sorted(filtered_df[COL_BP].unique())
    sel_bp = st.selectbox("BP 선택", bps)
    st.dataframe(filtered_df[filtered_df[COL_BP] == sel_bp].sort_values(COL_SHIP, ascending=False), hide_index=True)

# 하단 캡션 (기존 문구 복구)
st.divider()
st.caption("※ 모든 집계는 Google Sheet RAW 기반이며, 제품분류(B0/B1) 고정 + 선택한 필터 범위 내에서 계산됩니다.")

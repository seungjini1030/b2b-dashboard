# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반) — v2.2 optimized
# 메뉴: ①출고캘린더 ②SKU별조회 ③주차요약 ④월간요약(리포트)
#       ⑤국가별조회 ⑥BP명별조회 ⑦트렌드분석 ⑧부족예상재고
# ==========================================
import re
import html
import hashlib
import calendar as pycal
from datetime import date, timedelta
from typing import Optional
import numpy as np
import streamlit as st
import pandas as pd
try:
    import plotly.express as px
except ImportError:
    px = None
    st.warning("plotly 패키지가 없습니다. requirements.txt에 plotly를 추가해 주세요.", icon="⚠️")
# =========================
# 컬럼명 표준화 (RAW 기준)
# =========================
COL_QTY = "요청수량"
COL_YEAR = "년"
COL_MONTH = "월1"
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
CATEGORY_COL_CANDIDATES = [
    "카테고리 라인", "카테고리라인", "카테고리", "카테고리(Line)", "카테고리_LINE",
    "Category Line", "Category"
]
KEEP_CLASSES = ["B0", "B1"]
LT_ONLY_CUST1 = "해외B2B"
SPIKE_FACTOR = 1.3
# ✅ 월간 리포트 Top 개수 정책(고정 Top5)
REPORT_TOP_N = 5
# =========================
# Google Sheet 설정
# =========================
GSHEET_ID = "1jbWMgV3fudWCQ1qhG0lCysZGGFCo4loTIf-j3iuaqOI"
GSHEET_GID = "15468212"       # SAP 탭
GSHEET_GID_INV = "525131304"  # 상품카테고리&입고일 탭 (현재고/입고일)
HEADER_ROW_0BASED = 6
USECOLS = [
    COL_QTY, COL_YEAR, COL_MONTH,
    COL_DONE, COL_SHIP, COL_LT2,
    COL_BP, COL_MAIN,
    COL_CUST1, COL_CUST2,
    COL_CLASS,
    COL_ITEM_CODE, COL_ITEM_NAME,
    COL_ORDER_DATE, COL_ORDER_NO,
]
DTYPE_MAP = {
    COL_YEAR: "string",
    COL_MONTH: "string",
    COL_BP: "string",
    COL_MAIN: "string",
    COL_CUST1: "string",
    COL_CUST2: "string",
    COL_CLASS: "string",
    COL_ITEM_CODE: "string",
    COL_ITEM_NAME: "string",
    COL_ORDER_NO: "string",
}
st.set_page_config(page_title="B2B 출고 대시보드 (Google Sheet 기반)", layout="wide")
def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()
BASE_CSS = """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2.5rem;}
h1, h2, h3 {letter-spacing: -0.2px;}
.kpi-wrap {display:flex; gap:0.75rem; flex-wrap:wrap; margin: 0.25rem 0 0.75rem 0;}
.kpi-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 0.9rem 0.95rem;
  min-width: 180px;
  flex: 1 1 180px;
  box-shadow: 0 1px 0 rgba(0,0,0,0.02);
}
.kpi-title {color:#6b7280; font-size:0.9rem; margin-bottom:0.35rem;}
.kpi-value {font-size:1.35rem; font-weight:700; color:#111827; line-height:1.2;}
.kpi-big {font-size:1.55rem; font-weight:800; color:#111827; line-height:1.15;}
.kpi-muted {color:#6b7280; font-size:0.85rem; margin-top:0.15rem; white-space:normal; word-break:break-word;}
.pretty-table-wrap {margin-top: 0.25rem;}
.table-frame{
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  overflow: hidden;
  background: #fff;
}
.table-scroll{
  height: 520px;
  overflow: auto;
  position: relative;
}
table.pretty-table{
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  background: #fff;
  font-size: 0.93rem;
}
.pretty-table thead th{
  position: -webkit-sticky;
  position: sticky;
  top: 0;
  background: #f9fafb;
  color:#111827;
  text-align: left;
  padding: 10px 10px;
  border-bottom: 1px solid #e5e7eb;
  z-index: 10;
  white-space: nowrap;
  box-shadow: 0 1px 0 rgba(0,0,0,0.06);
}
.pretty-table tbody td{
  padding: 10px 10px;
  border-bottom: 1px solid #f3f4f6;
  vertical-align: top;
}
.pretty-table tbody tr:nth-child(even) td {background: #fcfcfd;}
.pretty-table tbody tr:hover td {background: #f7fbff;}
.wrap {white-space: normal; word-break: break-word; line-height: 1.25rem;}
.mono {font-variant-numeric: tabular-nums;}
.comment-block { margin: 0.6rem 0 1.05rem 0; }
.comment-title{
  font-weight: 900;
  font-size: 1.06rem;
  margin: 0.2rem 0 0.25rem 0;
}
.comment{ margin: 0.08rem 0 0 0; line-height: 1.55; }
.cal-note {color:#6b7280; font-size:0.9rem; margin-top:0.2rem;}
.cal-week-summary {
  background: linear-gradient(135deg, #e0f2fe 0%, #dbeafe 100%);
  border: 1px solid #93c5fd;
  border-radius: 6px;
  padding: 6px 8px;
  margin: 4px 0;
  font-size: 0.78rem;
  line-height: 1.4;
}
.cal-week-summary .ws-title {
  font-weight: 700;
  color: #1e40af;
  margin-bottom: 3px;
  font-size: 0.8rem;
}
.cal-week-summary .ws-row {
  display: flex;
  justify-content: space-between;
  color: #1e3a5f;
}
.cal-week-summary .ws-label { color: #475569; }
.cal-week-summary .ws-val { font-weight: 600; font-variant-numeric: tabular-nums; }
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)
# =========================
# Utils
# =========================
def _filter_cust1(df: pd.DataFrame, cust1_value: str) -> pd.DataFrame:
    """거래처구분1 필터 헬퍼 — 반복 패턴 통합"""
    if df is None or df.empty or COL_CUST1 not in df.columns:
        return df if df is not None else pd.DataFrame()
    return df[df[COL_CUST1].astype(str).str.strip() == cust1_value]

def make_btn_key(*parts) -> str:
    raw = "|".join([str(p) for p in parts])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()
def to_bool_true(s: pd.Series) -> pd.Series:
    x = s.fillna("").astype(str).str.strip().str.upper()
    return x.isin(["TRUE", "T", "1", "Y", "YES"])
def safe_dt(df: pd.DataFrame, col: str) -> None:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")
def safe_num(df: pd.DataFrame, col: str) -> None:
    if col in df.columns:
        s = df[col].astype(str).str.replace(",", "", regex=False).str.strip()
        s = s.replace({"": None, "nan": None, "None": None})
        df[col] = pd.to_numeric(s, errors="coerce")
def uniq_sorted(df: pd.DataFrame, col: str):
    if df is None or df.empty or col not in df.columns:
        return []
    return sorted(df[col].dropna().astype(str).unique().tolist())

def render_download_buttons(df: pd.DataFrame, filename_prefix: str, key_suffix: str = ""):
    """CSV 다운로드 버튼 렌더링 (② SKU별 조회, ⑤ 국가별 조회, ⑥ BP명별 조회용)"""
    if df is None or df.empty:
        return
    csv_data = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 CSV 다운로드",
        data=csv_data,
        file_name=f"{filename_prefix}_{date.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True,
        key=f"dl_csv_{filename_prefix}_{key_suffix}",
    )
def fmt_date(dtval) -> str:
    if pd.isna(dtval):
        return "-"
    return pd.to_datetime(dtval).strftime("%Y-%m-%d")
def need_cols(df: pd.DataFrame, cols: list[str], title: str = "필요 컬럼 누락"):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        st.warning(f"{title}: {missing}")
        return False
    return True
def normalize_text_cols(df: pd.DataFrame, cols: list[str]) -> None:
    for c in cols:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
def safe_selectbox(label: str, options: list[str], key: str, default="전체"):
    if not options:
        options = [default]
    if key not in st.session_state:
        st.session_state[key] = default
    if st.session_state[key] not in options:
        st.session_state[key] = default if default in options else options[0]
    return st.selectbox(label, options, key=key)
def _escape(x) -> str:
    if pd.isna(x):
        return ""
    return html.escape(str(x))
def _fmt_int(x) -> str:
    try:
        return f"{int(round(float(x))):,}"
    except Exception:
        return "0"
def _fmt_num_for_table(v) -> str:
    if pd.isna(v):
        return ""
    try:
        if isinstance(v, (int,)) and not isinstance(v, bool):
            return f"{v:,}"
        if isinstance(v, float):
            if float(v).is_integer():
                return f"{int(v):,}"
            return f"{v:,.2f}"
        vv = float(v)
        if vv.is_integer():
            return f"{int(vv):,}"
        return f"{vv:,.2f}"
    except Exception:
        return str(v)
def render_pretty_table(
    df: pd.DataFrame,
    height: int = 520,
    wrap_cols=None,
    number_cols=None,
    max_rows: int = 500,
):
    wrap_cols = set(wrap_cols or [])
    number_cols = set(number_cols or [])
    if df is None or df.empty:
        st.info("표시할 데이터가 없습니다.")
        return
    if len(df) > max_rows:
        st.caption(f"행이 많아({len(df):,}행) DataFrame 뷰로 표시합니다.")
        st.dataframe(df, use_container_width=True, height=height)
        return
    cols = list(df.columns)
    colgroup = "<colgroup>" + "".join(["<col>" for _ in cols]) + "</colgroup>"
    thead = "<thead><tr>" + "".join([f"<th>{_escape(c)}</th>" for c in cols]) + "</tr></thead>"
    tbody_rows = []
    for _, row in df.iterrows():
        tds = []
        for c in cols:
            v = row[c]
            cls = []
            if c in wrap_cols:
                cls.append("wrap")
            if c in number_cols:
                cls.append("mono")
                v_disp = _fmt_num_for_table(v)
            else:
                v_disp = "" if pd.isna(v) else str(v)
            class_attr = f' class="{" ".join(cls)}"' if cls else ""
            tds.append(f"<td{class_attr}>{_escape(v_disp)}</td>")
        tbody_rows.append("<tr>" + "".join(tds) + "</tr>")
    tbody = "<tbody>" + "".join(tbody_rows) + "</tbody>"
    st.markdown(
        f"""
        <div class="pretty-table-wrap">
          <div class="table-frame">
            <div class="table-scroll" style="height:{int(height)}px;">
              <table class="pretty-table">
                {colgroup}
                {thead}
                {tbody}
              </table>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )
def render_pivot_table(
    df: pd.DataFrame,
    height: int = 520,
    first_col_width: int = 90,
    data_col_width: int = 110,
):
    """피벗 테이블 전용 렌더러 — 열 너비 균일, 헤더 줄바꿈, 숫자 우정렬"""
    if df is None or df.empty:
        st.info("표시할 데이터가 없습니다.")
        return
    cols = list(df.columns)
    # colgroup: 첫 열은 좁게, 나머지는 균일
    cg_parts = [f'<col style="width:{first_col_width}px; min-width:{first_col_width}px;">']
    cg_parts += [
        f'<col style="width:{data_col_width}px; min-width:{data_col_width}px;">'
        for _ in cols[1:]
    ]
    colgroup = "<colgroup>" + "".join(cg_parts) + "</colgroup>"
    # 헤더: 데이터 열은 줄바꿈 허용
    th_first = (
        f'<th style="width:{first_col_width}px; min-width:{first_col_width}px;'
        f' white-space:nowrap;">{_escape(cols[0])}</th>'
    )
    th_rest = "".join([
        f'<th style="width:{data_col_width}px; min-width:{data_col_width}px;'
        f' white-space:normal; word-break:break-all; text-align:center; line-height:1.3;">'
        f'{_escape(c)}</th>'
        for c in cols[1:]
    ])
    thead = f"<thead><tr>{th_first}{th_rest}</tr></thead>"
    # 바디
    tbody_rows = []
    for _, row in df.iterrows():
        tds = []
        for i, c in enumerate(cols):
            v = row[c]
            if i == 0:
                v_disp = "" if pd.isna(v) else str(v)
                tds.append(f'<td style="white-space:nowrap; font-weight:500;">{_escape(v_disp)}</td>')
            else:
                v_disp = _fmt_num_for_table(v)
                tds.append(
                    f'<td class="mono" style="text-align:right; width:{data_col_width}px;">'
                    f'{_escape(v_disp)}</td>'
                )
        tbody_rows.append("<tr>" + "".join(tds) + "</tr>")
    tbody = "<tbody>" + "".join(tbody_rows) + "</tbody>"
    total_width = first_col_width + data_col_width * (len(cols) - 1)
    st.markdown(
        f"""
        <div class="pretty-table-wrap">
          <div class="table-frame">
            <div class="table-scroll" style="height:{int(height)}px; overflow-x:auto;">
              <table class="pretty-table" style="table-layout:fixed; min-width:{total_width}px; width:100%;">
                {colgroup}
                {thead}
                {tbody}
              </table>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_numbered_block(title: str, items: list[str]):
    if not items:
        return
    st.markdown(
        f"""
        <div class="comment-block">
          <div class="comment-title">{html.escape(title)}</div>
        """,
        unsafe_allow_html=True
    )
    for i, line in enumerate(items, start=1):
        st.markdown(f"""<div class="comment">{i}) {line}</div>""", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
def format_done_range(done_min, done_max) -> str:
    if pd.isna(done_min) and pd.isna(done_max):
        return "-"
    dmin = pd.to_datetime(done_min, errors="coerce")
    dmax = pd.to_datetime(done_max, errors="coerce")
    if pd.isna(dmin) and pd.isna(dmax):
        return "-"
    if pd.isna(dmin):
        return fmt_date(dmax)
    if pd.isna(dmax):
        return fmt_date(dmin)
    if dmin.date() == dmax.date():
        return fmt_date(dmin)
    return f"{fmt_date(dmin)} ~ {fmt_date(dmax)}"
# =========================
# Label helpers
# =========================
def parse_month_label_key(label: str) -> tuple[int, int]:
    y = m = 0
    try:
        my = re.search(r"(\d{4})\s*년", str(label))
        mm = re.search(r"(\d+)\s*월", str(label))
        if my:
            y = int(my.group(1))
        if mm:
            m = int(mm.group(1))
    except Exception:
        pass
    return (y, m)
def month_key_num_from_label(label: str) -> Optional[int]:
    y, m = parse_month_label_key(label)
    if y <= 0 or m <= 0:
        return None
    return y * 100 + m
# =========================
# TopN breakdown (대용량 최적화)
# =========================
def build_bp_list_map_for_items(df_period: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    if df_period.empty or items.empty:
        return pd.DataFrame(columns=[COL_ITEM_CODE, COL_ITEM_NAME, "BP명(요청수량)"])
    key_df = items[[COL_ITEM_CODE, COL_ITEM_NAME]].drop_duplicates()
    sub = df_period.merge(key_df, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="inner")
    if sub.empty:
        return pd.DataFrame(columns=[COL_ITEM_CODE, COL_ITEM_NAME, "BP명(요청수량)"])
    bp_break = (
        sub.groupby([COL_ITEM_CODE, COL_ITEM_NAME, COL_BP], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .rename(columns={COL_QTY: "BP요청수량"})
    )
    def format_bp_list(x: pd.DataFrame) -> str:
        x = x.sort_values("BP요청수량", ascending=False, na_position="last")
        out = []
        for _, r in x.iterrows():
            bp = str(r[COL_BP]).strip()
            q = r["BP요청수량"]
            q = 0 if pd.isna(q) else q
            out.append(f"{bp}({int(round(float(q))):,})")
        return "/ ".join(out)
    return (
        bp_break.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)
        .apply(format_bp_list)
        .reset_index(name="BP명(요청수량)")
    )
def build_item_topn_with_bp(df_period: pd.DataFrame, n: int) -> pd.DataFrame:
    if df_period.empty:
        return pd.DataFrame(columns=["순위", COL_ITEM_CODE, COL_ITEM_NAME, "요청수량_합", "BP명(요청수량)"])
    topn = (
        df_period.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index(name="요청수량_합")
        .sort_values("요청수량_합", ascending=False, na_position="last")
        .head(n)
        .copy()
    )
    bp_map = build_bp_list_map_for_items(df_period, topn)
    topn = topn.merge(bp_map, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="left")
    topn.insert(0, "순위", range(1, len(topn) + 1))
    topn["요청수량_합"] = pd.to_numeric(topn["요청수량_합"], errors="coerce").fillna(0).round(0).astype("Int64")
    topn["BP명(요청수량)"] = topn["BP명(요청수량)"].fillna("")
    return topn[["순위", COL_ITEM_CODE, COL_ITEM_NAME, "요청수량_합", "BP명(요청수량)"]]
def build_spike_report_only(cur_df: pd.DataFrame, prev_df: pd.DataFrame) -> pd.DataFrame:
    cols = [COL_ITEM_CODE, COL_ITEM_NAME, "이전_요청수량", "현재_요청수량", "증가배수", "BP명(요청수량)"]
    if cur_df.empty:
        return pd.DataFrame(columns=cols)
    cur_sku = (
        cur_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index(name="현재_요청수량")
    )
    prev_sku = (
        prev_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index(name="이전_요청수량")
    ) if not prev_df.empty else pd.DataFrame(columns=[COL_ITEM_CODE, COL_ITEM_NAME, "이전_요청수량"])
    cmp = cur_sku.merge(prev_sku, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="left")
    cmp["이전_요청수량"] = pd.to_numeric(cmp["이전_요청수량"], errors="coerce").fillna(0)
    cmp["현재_요청수량"] = pd.to_numeric(cmp["현재_요청수량"], errors="coerce").fillna(0)
    cmp["증가배수"] = cmp.apply(
        lambda r: (r["현재_요청수량"] / r["이전_요청수량"]) if r["이전_요청수량"] > 0 else pd.NA,
        axis=1
    )
    spike = cmp[(cmp["이전_요청수량"] > 0) & (cmp["현재_요청수량"] >= cmp["이전_요청수량"] * SPIKE_FACTOR)].copy()
    if spike.empty:
        spike["BP명(요청수량)"] = ""
        return spike[cols]
    bp_map = build_bp_list_map_for_items(cur_df, spike[[COL_ITEM_CODE, COL_ITEM_NAME]])
    spike = spike.merge(bp_map, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="left")
    spike["현재_요청수량"] = pd.to_numeric(spike["현재_요청수량"], errors="coerce").fillna(0).round(0).astype("Int64")
    spike["이전_요청수량"] = pd.to_numeric(spike["이전_요청수량"], errors="coerce").fillna(0).round(0).astype("Int64")
    spike["증가배수"] = pd.to_numeric(spike["증가배수"], errors="coerce").round(2)
    spike["BP명(요청수량)"] = spike["BP명(요청수량)"].fillna("")
    spike = spike.sort_values("현재_요청수량", ascending=False, na_position="last")
    return spike[cols]
# =========================
# 재고 데이터 로드 (상품카테고리&입고일 탭)
# =========================
@st.cache_data(ttl=1800, show_spinner=False)
def load_inventory_from_gsheet() -> pd.DataFrame:
    """상품카테고리&입고일 탭에서 현재고/입고일 데이터 로드 (H-M열)"""
    csv_url = f"https://docs.google.com/spreadsheets/d/{GSHEET_ID}/export?format=csv&gid={GSHEET_GID_INV}"
    try:
        inv_raw = pd.read_csv(csv_url, header=1)
    except Exception:
        return pd.DataFrame(columns=["품목코드", "품목이름", "현재고", "1차입고일", "1차입고수량"])
    # H-M열 = 인덱스 7~12 (0-based) — 실제 컬럼명으로 매핑
    if inv_raw.shape[1] < 13:
        return pd.DataFrame(columns=["품목코드", "품목이름", "현재고", "1차입고일", "1차입고수량"])
    # H열(idx7)=품목 코드, I열(idx8)=품목 이름, J열(idx9)=현재고, K열(idx10)=1차 입고, L열(idx11)=1차 수량
    inv = inv_raw.iloc[:, [7, 8, 9, 10, 11]].copy()
    inv.columns = ["품목코드", "품목이름", "현재고", "1차입고일", "1차입고수량"]
    # 빈 행 제거
    inv = inv.dropna(subset=["품목코드"])
    inv["품목코드"] = inv["품목코드"].astype(str).str.strip()
    inv = inv[inv["품목코드"].str.len() > 0].copy()
    # 숫자 변환
    for c in ["현재고", "1차입고수량"]:
        inv[c] = inv[c].astype(str).str.replace(",", "", regex=False).str.strip()
        inv[c] = pd.to_numeric(inv[c], errors="coerce").fillna(0)
    # 날짜 변환
    inv["1차입고일"] = pd.to_datetime(inv["1차입고일"], errors="coerce")
    return inv
# =========================
# 부족 예상 재고 알람 분석
# =========================
def build_shortage_alert(
    raw_df: pd.DataFrame,
    inv_df: pd.DataFrame,
    lookback_days: int = 90,
    alert_threshold_days: int = 30,
) -> pd.DataFrame:
    """
    30%+ 증가 품목을 대상으로 재고 소진일수를 계산하여 부족 예상 알람 생성.
    - 소진일수 = 현재고 / 최근 일평균출고량
    - alert_threshold_days 이하이면 알람 대상
    """
    cols_out = [
        COL_ITEM_CODE, COL_ITEM_NAME, "현재고", "최근일평균출고",
        "소진예상일수", "소진예상일", "1차입고일", "1차입고수량",
        "입고전소진여부", "위험등급", "이전월출고", "현재월출고", "증가배수",
    ]
    if raw_df is None or raw_df.empty or inv_df is None or inv_df.empty:
        return pd.DataFrame(columns=cols_out)
    # 해외B2B만 필터
    overseas = _filter_cust1(raw_df, LT_ONLY_CUST1).copy()
    if overseas.empty:
        return pd.DataFrame(columns=cols_out)
    # 현재월/이전월 기준 설정
    today = date.today()
    cur_ym = today.strftime("%Y-%m")
    prev_month = today.replace(day=1) - timedelta(days=1)
    prev_ym = prev_month.strftime("%Y-%m")
    # 월별 출고 집계
    if "_ship_ym" not in overseas.columns:
        return pd.DataFrame(columns=cols_out)
    cur_data = overseas[overseas["_ship_ym"].astype(str) == cur_ym]
    prev_data = overseas[overseas["_ship_ym"].astype(str) == prev_ym]
    # 30% 이상 증가 품목 탐지 (기존 spike 로직 활용)
    spike = build_spike_report_only(cur_data, prev_data)
    if spike.empty:
        return pd.DataFrame(columns=cols_out)
    # 최근 N일 일평균 출고량 계산
    cutoff = today - timedelta(days=lookback_days)
    ship_dates = pd.to_datetime(overseas["_ship_date"], errors="coerce")
    recent = overseas[ship_dates.notna() & (ship_dates >= pd.Timestamp(cutoff))].copy()
    if recent.empty:
        return pd.DataFrame(columns=cols_out)
    daily_avg = (
        recent.groupby(COL_ITEM_CODE, dropna=False)[COL_QTY]
        .sum()
        .reset_index(name="_total_qty")
    )
    daily_avg["_total_qty"] = pd.to_numeric(daily_avg["_total_qty"], errors="coerce").fillna(0)
    actual_days = max((today - cutoff).days, 1)
    daily_avg["최근일평균출고"] = (daily_avg["_total_qty"] / actual_days).round(1)
    # spike 품목과 재고 데이터 조인
    alert = spike[[COL_ITEM_CODE, COL_ITEM_NAME, "이전_요청수량", "현재_요청수량", "증가배수"]].copy()
    alert = alert.rename(columns={"이전_요청수량": "이전월출고", "현재_요청수량": "현재월출고"})
    # inv_df의 컬럼명을 COL_ITEM_CODE와 통일 후 on= 으로 병합 (suffix 문제 방지)
    inv_merge = inv_df.rename(columns={"품목코드": COL_ITEM_CODE})[[COL_ITEM_CODE, "현재고", "1차입고일", "1차입고수량"]].copy()
    alert = alert.merge(inv_merge, on=COL_ITEM_CODE, how="left")
    alert = alert.merge(daily_avg[[COL_ITEM_CODE, "최근일평균출고"]], on=COL_ITEM_CODE, how="left")
    # 소진일수 계산
    alert["현재고"] = pd.to_numeric(alert["현재고"], errors="coerce").fillna(0)
    alert["최근일평균출고"] = pd.to_numeric(alert["최근일평균출고"], errors="coerce").fillna(0)
    alert["소진예상일수"] = alert.apply(
        lambda r: round(r["현재고"] / r["최근일평균출고"], 1) if r["최근일평균출고"] > 0 else float("inf"),
        axis=1,
    )
    alert["소진예상일"] = alert["소진예상일수"].apply(
        lambda d: (today + timedelta(days=int(d))).strftime("%Y-%m-%d") if d != float("inf") and d < 365 else "-"
    )
    # 입고 전 소진 여부
    alert["입고전소진여부"] = alert.apply(
        lambda r: (
            "예" if (
                pd.notna(r.get("1차입고일")) and r["소진예상일"] != "-"
                and pd.to_datetime(r["소진예상일"], errors="coerce") is not pd.NaT
                and pd.to_datetime(r["소진예상일"], errors="coerce") < r["1차입고일"]
            ) else ("입고예정없음" if pd.isna(r.get("1차입고일")) else "아니오")
        ),
        axis=1,
    )
    # 위험등급 분류
    def _risk_level(r):
        days = r["소진예상일수"]
        if days == float("inf"):
            return "안전"
        if days <= 7:
            return "긴급"
        if days <= 14:
            return "위험"
        if days <= alert_threshold_days:
            return "주의"
        return "안전"
    alert["위험등급"] = alert.apply(_risk_level, axis=1)
    # 안전 등급 제외하고 위험도순 정렬
    risk_order = {"긴급": 0, "위험": 1, "주의": 2, "안전": 3}
    alert["_risk_sort"] = alert["위험등급"].map(risk_order)
    alert = alert.sort_values(["_risk_sort", "소진예상일수"], ascending=[True, True])
    alert = alert.drop(columns=["_risk_sort"], errors="ignore")
    # 유효 컬럼만 반환
    for c in cols_out:
        if c not in alert.columns:
            alert[c] = pd.NA
    return alert[cols_out]
# =========================
# Slack 메시지 포맷 (부족 예상 재고)
# =========================
def build_shortage_slack_message(alert_df: pd.DataFrame) -> str:
    """부족 예상 재고 알람 데이터를 Slack 메시지 포맷으로 변환"""
    if alert_df is None or alert_df.empty:
        return "부족 예상 재고 알람: 현재 알람 대상 품목이 없습니다."
    today_str = date.today().strftime("%Y-%m-%d")
    lines = [f"{'='*40}", f"부족 예상 재고 알람 ({today_str})", f"{'='*40}", ""]
    # 위험등급별 그룹핑
    for grade in ["긴급", "위험", "주의"]:
        sub = alert_df[alert_df["위험등급"] == grade]
        if sub.empty:
            continue
        emoji = {"긴급": "🔴", "위험": "🟠", "주의": "🟡"}.get(grade, "⚪")
        lines.append(f"{emoji} [{grade}] {len(sub)}건")
        lines.append("-" * 30)
        for _, r in sub.iterrows():
            code = str(r.get(COL_ITEM_CODE, ""))
            name = str(r.get(COL_ITEM_NAME, ""))
            stock = int(r.get("현재고", 0))
            days = r.get("소진예상일수", float("inf"))
            days_str = f"{days:.0f}일" if days != float("inf") else "-"
            depl = str(r.get("소진예상일", "-"))
            inc_date = r.get("1차입고일")
            inc_str = inc_date.strftime("%m/%d") if pd.notna(inc_date) else "미정"
            inc_qty = int(r.get("1차입고수량", 0))
            before = str(r.get("입고전소진여부", "-"))
            rate = r.get("증가배수", pd.NA)
            rate_str = f"x{rate:.1f}" if pd.notna(rate) else "-"
            lines.append(f"  {code} | {name[:20]}")
            lines.append(f"    현재고: {stock:,} | 소진예상: {days_str} ({depl})")
            lines.append(f"    입고: {inc_str} ({inc_qty:,}개) | 입고전소진: {before}")
            lines.append(f"    월간증가: {rate_str}")
            lines.append("")
    total = len(alert_df[alert_df["위험등급"] != "안전"])
    lines.append(f"총 {total}건 알람 | 기준: 최근90일 평균출고 기반")
    return "\n".join(lines)
# =========================
# 주차/월간 자동 코멘트 helpers
# =========================
def _delta_arrow(diff: float) -> str:
    if pd.isna(diff) or abs(diff) < 1e-12:
        return "-"
    return "▲" if diff > 0 else "▼"
def _delta_text(diff: float) -> str:
    if pd.isna(diff):
        return "-"
    try:
        d = int(round(float(diff)))
        return f"{d:+,}"
    except Exception:
        return "-"
def _fmt_delta(diff: float) -> str:
    return f"{_delta_text(diff)} {_delta_arrow(diff)}"
def _clean_nunique(series: pd.Series) -> int:
    if series is None:
        return 0
    s = series.astype(str).str.strip()
    s = s.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    return int(s.dropna().nunique())
def _get_order_cnt(df: pd.DataFrame) -> int:
    if df is None or df.empty or COL_ORDER_NO not in df.columns:
        return 0
    return _clean_nunique(df[COL_ORDER_NO])
# _get_ship_cnt는 _get_order_cnt와 동일 로직이므로 별칭으로 통합
_get_ship_cnt = _get_order_cnt
def _get_qty(df: pd.DataFrame) -> int:
    if df is None or df.empty or COL_QTY not in df.columns:
        return 0
    return int(round(float(pd.to_numeric(df[COL_QTY], errors="coerce").fillna(0).sum()), 0))
def _get_lt_mean(df: pd.DataFrame) -> float:
    if df is None or df.empty or COL_LT2 not in df.columns:
        return float("nan")
    s = pd.to_numeric(df[COL_LT2], errors="coerce").dropna()
    if s.empty:
        return float("nan")
    return float(s.mean())
def _find_category_col(df: pd.DataFrame):
    for c in CATEGORY_COL_CANDIDATES:
        if c in df.columns:
            return c
    return None
def category_top_comment(cur_df: pd.DataFrame, top_n: int = 2) -> list[str]:
    if cur_df is None or cur_df.empty or COL_QTY not in cur_df.columns:
        return []
    cat_col = _find_category_col(cur_df)
    if not cat_col:
        return []
    tmp = cur_df.copy()
    tmp[cat_col] = tmp[cat_col].astype(str).str.strip()
    g = tmp.groupby(cat_col, dropna=False)[COL_QTY].sum(min_count=1).sort_values(ascending=False).head(top_n)
    if g.empty:
        return []
    desc = ", ".join([f"{idx}({_fmt_int(val)})" for idx, val in g.items()])
    return [f"카테고리 TOP{top_n}: {desc}"]
def concentration_comment(cur_df: pd.DataFrame) -> list[str]:
    if cur_df is None or cur_df.empty or COL_QTY not in cur_df.columns:
        return []
    total = float(pd.to_numeric(cur_df[COL_QTY], errors="coerce").fillna(0).sum())
    if total <= 0:
        return []
    out = []
    if COL_BP in cur_df.columns:
        g = cur_df.groupby(COL_BP, dropna=False)[COL_QTY].sum(min_count=1).sort_values(ascending=False)
        if not g.empty:
            top_bp = str(g.index[0]).strip()
            top_bp_qty = float(pd.to_numeric(g.iloc[0], errors="coerce") or 0)
            out.append(f"Top BP 집중도: 1위 {top_bp}({_fmt_int(top_bp_qty)}) {top_bp_qty/total*100:.0f}%")
    if all(c in cur_df.columns for c in [COL_ITEM_CODE, COL_ITEM_NAME]):
        g2 = cur_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY].sum(min_count=1).sort_values(ascending=False)
        if not g2.empty:
            (top_code, top_name) = g2.index[0]
            top_qty = float(pd.to_numeric(g2.iloc[0], errors="coerce") or 0)
            out.append(f"Top SKU 집중도: 1위 {str(top_code).strip()} / {str(top_name).strip()}({_fmt_int(top_qty)}) {top_qty/total*100:.0f}%")
    return out[:2]
def undated_ship_risk_comment(cur_df: pd.DataFrame) -> list[str]:
    if cur_df is None or cur_df.empty or COL_SHIP not in cur_df.columns or COL_QTY not in cur_df.columns:
        return []
    total_qty = float(pd.to_numeric(cur_df[COL_QTY], errors="coerce").fillna(0).sum())
    if total_qty <= 0:
        return []
    ship_dt = pd.to_datetime(cur_df[COL_SHIP], errors="coerce")
    miss = cur_df[ship_dt.isna()].copy()
    miss_qty = float(pd.to_numeric(miss[COL_QTY], errors="coerce").fillna(0).sum()) if not miss.empty else 0.0
    if miss_qty <= 0:
        return []
    return [f"출고일 미정 수량: {_fmt_int(miss_qty)} ({miss_qty/total_qty*100:.0f}%)"]
def period_kpi_delta_comment(cur_df: pd.DataFrame, prev_df: pd.DataFrame) -> list[str]:
    cur_order = _get_order_cnt(cur_df); prev_order = _get_order_cnt(prev_df)
    cur_ship = _get_ship_cnt(cur_df);  prev_ship = _get_ship_cnt(prev_df)
    cur_qty = _get_qty(cur_df);        prev_qty = _get_qty(prev_df)
    cur_lt = _get_lt_mean(cur_df);     prev_lt = _get_lt_mean(prev_df)
    order_part = f"발주건수 {cur_order}건 ({_fmt_delta(cur_order - prev_order)})"
    ship_part = f"출고건수 {cur_ship}건 ({_fmt_delta(cur_ship - prev_ship)})"
    qty_part = f"출고수량 {cur_qty:,}개 ({_fmt_delta(cur_qty - prev_qty)})"
    if (not pd.isna(cur_lt)) and (not pd.isna(prev_lt)):
        lt_part = f"평균 리드타임 {cur_lt:.1f}일 ({_fmt_delta(cur_lt - prev_lt)})"
    elif (not pd.isna(cur_lt)) and pd.isna(prev_lt):
        lt_part = f"평균 리드타임 {cur_lt:.1f}일 (직전기간 데이터 부족)"
    else:
        lt_part = "평균 리드타임 -"
    return [f"직전기간 대비: {order_part} / {ship_part} / {qty_part} / {lt_part}"]
# =========================
# Load + Prepare (RAW + cal_agg)
# =========================
@st.cache_data(ttl=1800, show_spinner=False)
def load_prepared_from_gsheet() -> tuple[pd.DataFrame, pd.DataFrame]:
    csv_url = f"https://docs.google.com/spreadsheets/d/{GSHEET_ID}/export?format=csv&gid={GSHEET_GID}"
    try:
        df = pd.read_csv(
            csv_url,
            header=HEADER_ROW_0BASED,
            usecols=USECOLS,
            dtype=DTYPE_MAP,
        )
    except Exception:
        df = pd.read_csv(csv_url, header=HEADER_ROW_0BASED)
    df.columns = df.columns.astype(str).str.strip()
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")]
    for c in [COL_SHIP, COL_DONE, COL_ORDER_DATE]:
        safe_dt(df, c)
    for c in [COL_QTY, COL_LT2, "리드타임1"]:
        safe_num(df, c)
    if (COL_LT2 not in df.columns) or (df[COL_LT2].dropna().empty):
        if all(c in df.columns for c in [COL_DONE, COL_ORDER_DATE]):
            df[COL_LT2] = (df[COL_DONE] - df[COL_ORDER_DATE]).dt.days
            safe_num(df, COL_LT2)
    normalize_text_cols(df, [COL_BP, COL_ITEM_CODE, COL_ITEM_NAME, COL_CUST1, COL_CUST2, COL_CLASS, COL_MAIN, COL_ORDER_NO])
    if COL_CLASS in df.columns:
        df = df[df[COL_CLASS].astype(str).str.strip().isin(KEEP_CLASSES)].copy()
    df["_is_rep"] = to_bool_true(df[COL_MAIN]) if COL_MAIN in df.columns else False
    ship_dt = pd.to_datetime(df[COL_SHIP], errors="coerce") if COL_SHIP in df.columns else pd.Series(pd.NaT, index=df.index)
    done_dt = pd.to_datetime(df[COL_DONE], errors="coerce") if COL_DONE in df.columns else pd.Series(pd.NaT, index=df.index)
    base_dt = ship_dt.fillna(done_dt)
    wk = ((base_dt.dt.day - 1) // 7 + 1).astype("Int64")
    mask = base_dt.notna() & wk.notna()
    y_int = base_dt.dt.year.astype("Int64")
    m_int = base_dt.dt.month.astype("Int64")
    df["_week_label"] = pd.NA
    df.loc[mask, "_week_label"] = (
        y_int.astype(str) + "년 " +
        m_int.astype(str) + "월 " +
        wk.astype(str) + "주차"
    )
    df["_week_key_num"] = pd.NA
    df.loc[mask, "_week_key_num"] = (y_int * 10000 + m_int * 100 + wk).astype("Int64")
    if (COL_YEAR in df.columns) and (COL_MONTH in df.columns):
        y = pd.to_numeric(df[COL_YEAR], errors="coerce").astype("Int64")
        m = pd.to_numeric(df[COL_MONTH], errors="coerce").astype("Int64")
        mmask = y.notna() & m.notna()
        df["_month_label"] = pd.NA
        df.loc[mmask, "_month_label"] = y.astype(str) + "년 " + m.astype(str) + "월"
        df["_month_key_num"] = pd.NA
        df.loc[mmask, "_month_key_num"] = (y * 100 + m).astype("Int64")
    else:
        df["_month_label"] = pd.NA
        df["_month_key_num"] = pd.NA
    df["_ship_date"] = ship_dt.dt.date
    df["_ship_ym"] = ship_dt.dt.strftime("%Y-%m")
    cal_src = df.dropna(subset=["_ship_date"]).copy()
    if cal_src.empty:
        cal_agg = pd.DataFrame(columns=["_ship_ym", "_ship_date", COL_BP, COL_CUST1, COL_CUST2, "qty_sum"])
    else:
        cal_agg = (
            cal_src.groupby(["_ship_ym", "_ship_date", COL_BP, COL_CUST1, COL_CUST2], dropna=False)[COL_QTY]
            .sum(min_count=1)
            .reset_index()
            .rename(columns={COL_QTY: "qty_sum"})
        )
        cal_agg["qty_sum"] = pd.to_numeric(cal_agg["qty_sum"], errors="coerce").fillna(0).round(0).astype("Int64")
    return df, cal_agg
# =========================
# KPI
# =========================
def compute_kpis(df_view: pd.DataFrame):
    total_qty = float(pd.to_numeric(df_view[COL_QTY], errors="coerce").fillna(0).sum()) if (df_view is not None and COL_QTY in df_view.columns) else 0.0
    total_cnt = _clean_nunique(df_view[COL_ORDER_NO]) if (df_view is not None and not df_view.empty and COL_ORDER_NO in df_view.columns) else 0
    latest_done = df_view[COL_DONE].max() if (df_view is not None and COL_DONE in df_view.columns) else pd.NaT
    avg_lt2_overseas = None
    if df_view is not None and all(c in df_view.columns for c in [COL_CUST1, COL_LT2]):
        overseas = _filter_cust1(df_view, LT_ONLY_CUST1)
        if not overseas.empty and not overseas[COL_LT2].dropna().empty:
            avg_lt2_overseas = float(overseas[COL_LT2].dropna().mean())
    top_bp_qty_name = "-"
    top_bp_qty_val = "-"
    if df_view is not None and (not df_view.empty) and all(c in df_view.columns for c in [COL_BP, COL_QTY]):
        g = df_view.groupby(COL_BP, dropna=False)[COL_QTY].sum().sort_values(ascending=False)
        if not g.empty:
            top_bp_qty_name = str(g.index[0])
            top_bp_qty_val = f"{float(pd.to_numeric(g.iloc[0], errors='coerce') or 0):,.0f}"
    top_bp_cnt_name = "-"
    top_bp_cnt_val = "-"
    if df_view is not None and (not df_view.empty) and all(c in df_view.columns for c in [COL_BP, COL_ORDER_NO]):
        tmp = df_view[[COL_BP, COL_ORDER_NO]].copy()
        tmp["_ord"] = tmp[COL_ORDER_NO].astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
        tmp = tmp.dropna(subset=["_ord"])
        if not tmp.empty:
            g2 = tmp.groupby(COL_BP)["_ord"].nunique().sort_values(ascending=False)
            if not g2.empty:
                top_bp_cnt_name = str(g2.index[0])
                top_bp_cnt_val = f"{int(g2.iloc[0]):,}"
    return {
        "total_qty": total_qty,
        "total_cnt": int(total_cnt),
        "latest_done": latest_done,
        "avg_lt2_overseas": avg_lt2_overseas,
        "top_bp_qty_name": top_bp_qty_name,
        "top_bp_qty_val": top_bp_qty_val,
        "top_bp_cnt_name": top_bp_cnt_name,
        "top_bp_cnt_val": top_bp_cnt_val,
    }
# =========================
# Calendar (same-tab routing)
# =========================
def init_calendar_state():
    st.session_state.setdefault("cal_view", "calendar")  # calendar | detail
    st.session_state.setdefault("cal_ym", "")
    st.session_state.setdefault("cal_selected_date", None)
    st.session_state.setdefault("cal_selected_bp", "")
    st.session_state.setdefault("cal_expanded", set())
def ym_to_year_month(ym: str) -> tuple[int, int]:
    try:
        y, m = ym.split("-")
        return int(y), int(m)
    except Exception:
        today = date.today()
        return today.year, today.month
def add_months(ym: str, delta: int) -> str:
    y, m = ym_to_year_month(ym)
    m2 = m + delta
    while m2 <= 0:
        y -= 1
        m2 += 12
    while m2 >= 13:
        y += 1
        m2 -= 12
    return f"{y:04d}-{m2:02d}"
def build_day_map_from_cal_agg(cal_agg: pd.DataFrame, ym: str) -> dict[date, list[dict]]:
    if cal_agg is None or cal_agg.empty:
        return {}
    sub = cal_agg[cal_agg["_ship_ym"].astype(str) == str(ym)].copy()
    if sub.empty:
        return {}
    total = (
        sub.groupby(["_ship_date", COL_BP], dropna=False)["qty_sum"]
        .sum()
        .reset_index()
        .rename(columns={"qty_sum": "qty_total"})
    )
    pick = (
        sub.sort_values("qty_sum", ascending=False)
        .drop_duplicates(subset=["_ship_date", COL_BP], keep="first")[["_ship_date", COL_BP, COL_CUST1]]
        .copy()
    )
    pick[COL_CUST1] = pick[COL_CUST1].fillna("").astype(str).str.strip()
    merged = total.merge(pick, on=["_ship_date", COL_BP], how="left")
    merged["qty_total"] = pd.to_numeric(merged["qty_total"], errors="coerce").fillna(0).round(0).astype("Int64")
    merged[COL_CUST1] = merged[COL_CUST1].fillna("").astype(str)
    out: dict[date, list[dict]] = {}
    for d, grp in merged.groupby("_ship_date"):
        grp = grp.sort_values("qty_total", ascending=False, na_position="last")
        out[d] = [
            {"bp": str(r[COL_BP]).strip(), "qty": int(r["qty_total"]) if pd.notna(r["qty_total"]) else 0, "cust1": str(r[COL_CUST1]).strip()}
            for _, r in grp.iterrows()
        ]
    return out
# =========================
# Weekly summary for calendar (해외B2B)
# =========================
def compute_weekly_summary_for_calendar(raw_df: pd.DataFrame, ym: str) -> dict:
    """해외B2B 주간 평균 리드타임 + 출고수량을 계산하여 {sunday_date: {avg_lt, total_qty, ship_count}} 형태로 반환"""
    if raw_df is None or raw_df.empty:
        return {}
    y, m = ym_to_year_month(ym)
    # 해외B2B만 필터
    overseas = _filter_cust1(raw_df, LT_ONLY_CUST1).copy()
    if overseas.empty:
        return {}
    # 출고일자 기준 필터
    if "_ship_date" not in overseas.columns:
        return {}
    overseas = overseas.dropna(subset=["_ship_date"])
    if overseas.empty:
        return {}
    # 캘린더 주차 구성 (일요일 시작)
    cal = pycal.Calendar(firstweekday=6)
    weeks = cal.monthdayscalendar(y, m)
    result = {}
    for wk in weeks:
        # 주의 실제 날짜 범위 계산
        non_zero = [(pos, day_num) for pos, day_num in enumerate(wk) if day_num > 0]
        if not non_zero:
            continue
        pos0, day0 = non_zero[0]
        ref_date = date(y, m, day0)
        sunday = ref_date - timedelta(days=pos0)
        saturday = sunday + timedelta(days=6)
        # 해당 주 데이터 필터
        wk_data = overseas[
            (overseas["_ship_date"] >= sunday) &
            (overseas["_ship_date"] <= saturday)
        ]
        if wk_data.empty:
            result[sunday] = {"avg_lt": None, "total_qty": 0, "ship_count": 0}
            continue
        # 출고수량 합계
        total_qty = float(pd.to_numeric(wk_data[COL_QTY], errors="coerce").fillna(0).sum())
        # 출고 건수 (BP 기준 고유 건수)
        ship_count = int(wk_data[COL_BP].nunique()) if COL_BP in wk_data.columns else 0
        # 평균 리드타임 (COL_LT2)
        avg_lt = None
        if COL_LT2 in wk_data.columns:
            lt_vals = pd.to_numeric(wk_data[COL_LT2], errors="coerce").dropna()
            if not lt_vals.empty:
                avg_lt = float(lt_vals.mean())
        result[sunday] = {"avg_lt": avg_lt, "total_qty": total_qty, "ship_count": ship_count}
    return result
def _sunday_to_week_label(sunday: date, cal_year: int = 0, cal_month: int = 0) -> str:
    """일요일 날짜 → '2026년 6월 3주차' 형식 라벨 계산 (③주차요약 연동용)
    캘린더 표시 월(cal_year/cal_month)이 주어지면 해당 월에 속하는 날짜 기준으로 계산"""
    # 일요일~토요일 범위에서 캘린더 월에 속하는 날짜를 우선 사용
    for offset in range(7):
        d = sunday + timedelta(days=offset)
        if cal_year > 0 and cal_month > 0:
            if d.year == cal_year and d.month == cal_month:
                wk = (d.day - 1) // 7 + 1
                return f"{d.year}년 {d.month}월 {wk}주차"
        else:
            wk = (d.day - 1) // 7 + 1
            return f"{d.year}년 {d.month}월 {wk}주차"
    # fallback: 일요일 기준
    wk = (sunday.day - 1) // 7 + 1
    return f"{sunday.year}년 {sunday.month}월 {wk}주차"

def _render_weekly_summary_html(ws: dict) -> str:
    """캘린더 주간요약 HTML 블록 생성 (중복 제거용 헬퍼)"""
    lt_str = f"{ws['avg_lt']:.1f}일" if ws['avg_lt'] is not None else "-"
    qty_str = f"{ws['total_qty']:,.0f}" if ws['total_qty'] else "0"
    bp_str = f"{ws['ship_count']}개사" if ws['ship_count'] else "-"
    return (
        '<div class="cal-week-summary">'
        '<div class="ws-title">✈ 해외B2B 주간</div>'
        f'<div class="ws-row"><span class="ws-label">평균 LT</span><span class="ws-val">{lt_str}</span></div>'
        f'<div class="ws-row"><span class="ws-label">출고수량</span><span class="ws-val">{qty_str}</span></div>'
        f'<div class="ws-row"><span class="ws-label">거래처</span><span class="ws-val">{bp_str}</span></div>'
        '</div>'
    )

def render_month_calendar(cal_agg_filtered: pd.DataFrame, ym: str, raw_df: pd.DataFrame = None):
    y, m = ym_to_year_month(ym)
    day_map = build_day_map_from_cal_agg(cal_agg_filtered, ym)
    prev_ym = add_months(ym, -1)
    next_ym = add_months(ym, +1)
    c1, c2, c3 = st.columns([1.2, 2.2, 1.2], vertical_alignment="center")
    with c1:
        if st.button("◀ 이전달", key=f"cal_prev_{ym}", use_container_width=True):
            st.session_state["cal_ym"] = prev_ym
            st.session_state["cal_view"] = "calendar"
            safe_rerun()
    with c2:
        st.markdown(f"### {y}년 {m}월 출고 캘린더")
        st.markdown('<div class="cal-note">※ BP 버튼 클릭 시 상세 화면으로 이동합니다. (같은 탭)</div>', unsafe_allow_html=True)
    with c3:
        if st.button("다음달 ▶", key=f"cal_next_{ym}", use_container_width=True):
            st.session_state["cal_ym"] = next_ym
            st.session_state["cal_view"] = "calendar"
            safe_rerun()
    weekdays = ["일", "월", "화", "수", "목", "금", "토"]
    header_cols = st.columns(7)
    for i, w in enumerate(weekdays):
        with header_cols[i]:
            st.markdown(f"**{w}**")
    # ── 해외B2B 주간 요약 계산 ──
    weekly_summary = compute_weekly_summary_for_calendar(raw_df, ym) if raw_df is not None else {}
    cal = pycal.Calendar(firstweekday=6)
    weeks = cal.monthdayscalendar(y, m)
    expanded: set[date] = st.session_state.get("cal_expanded", set())
    for wk in weeks:
        # 해당 주의 일요일 날짜 계산 (주간요약 매핑용)
        wk_sunday = None
        non_zero = [(pos, dn) for pos, dn in enumerate(wk) if dn > 0]
        if non_zero:
            pos0, day0 = non_zero[0]
            ref_d = date(y, m, day0)
            wk_sunday = ref_d - timedelta(days=pos0)
        cols = st.columns(7, gap="small")
        for i, day_num in enumerate(wk):
            with cols[i]:
                if day_num == 0:
                    # ── 일요일(i==0)이고 빈 셀이지만 주간요약은 표시 ──
                    if i == 0 and wk_sunday and wk_sunday in weekly_summary:
                        with st.container(border=True):
                            st.markdown("&nbsp;")
                            st.markdown(_render_weekly_summary_html(weekly_summary[wk_sunday]), unsafe_allow_html=True)
                            wk_label = _sunday_to_week_label(wk_sunday, y, m)
                            if wk_label and st.button("📊 주차요약 →", key=f"ws_nav_{wk_sunday}", use_container_width=True):
                                st.session_state["nav_menu"] = "③ 주차요약"
                                st.session_state["wk_sel_week"] = wk_label
                                safe_rerun()
                    else:
                        st.container(border=True).markdown("&nbsp;")
                    continue
                d = date(y, m, day_num)
                events = day_map.get(d, [])
                is_expanded = d in expanded
                show_n = len(events) if is_expanded else min(3, len(events))
                hidden = max(0, len(events) - show_n)
                with st.container(border=True):
                    st.markdown(f"**{day_num}**")
                    # ── 일요일(i==0): 주간요약 표시 ──
                    if i == 0 and wk_sunday and wk_sunday in weekly_summary:
                        st.markdown(_render_weekly_summary_html(weekly_summary[wk_sunday]), unsafe_allow_html=True)
                        wk_label = _sunday_to_week_label(wk_sunday, y, m)
                        if wk_label and st.button("📊 주차요약 →", key=f"ws_nav_d_{wk_sunday}", use_container_width=True):
                            st.session_state["nav_menu"] = "③ 주차요약"
                            st.session_state["wk_sel_week"] = wk_label
                            safe_rerun()
                    for idx in range(show_n):
                        e = events[idx]
                        bp = e.get("bp", "")
                        qsum = int(e.get("qty", 0))
                        cust1 = (e.get("cust1", "") or "").strip()
                        tag = "🟦" if cust1 == "해외B2B" else "🟩" if cust1 == "국내B2B" else "⬜"
                        label = f"{tag} {bp} ({qsum:,})"
                        k = "cal_bp_" + make_btn_key(ym, d.isoformat(), bp, idx)
                        if st.button(label, key=k, use_container_width=True):
                            st.session_state["cal_selected_date"] = d
                            st.session_state["cal_selected_bp"] = bp
                            st.session_state["cal_view"] = "detail"
                            safe_rerun()
                    if hidden > 0 and (not is_expanded):
                        if st.button(f"+{hidden}건 더 보기", key="cal_more_" + make_btn_key(ym, d.isoformat()), use_container_width=True):
                            expanded.add(d)
                            st.session_state["cal_expanded"] = expanded
                            safe_rerun()
                    if is_expanded and len(events) > 3:
                        if st.button("접기", key="cal_less_" + make_btn_key(ym, d.isoformat()), use_container_width=True):
                            expanded.discard(d)
                            st.session_state["cal_expanded"] = expanded
                            safe_rerun()
# =========================
# Calendar detail view
# =========================
def render_calendar_detail(raw_df: pd.DataFrame, selected_date, selected_bp: str):
    """캘린더 상세 화면 — 선택 날짜 × BP의 품목코드/품목명/요청수량/출고일자 표시"""
    # 뒤로가기 버튼
    if st.button("◀ 캘린더로 돌아가기", key="cal_detail_back", type="secondary"):
        st.session_state["cal_view"] = "calendar"
        safe_rerun()

    st.subheader(f"📋 출고 상세 내역")
    st.caption(f"출고일자: {selected_date}  |  BP명: {selected_bp}")

    if raw_df is None or raw_df.empty:
        st.info("데이터가 없습니다.")
        return

    if not all(c in raw_df.columns for c in [COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY]):
        st.warning("품목코드/품목명/요청수량 컬럼이 없습니다.")
        return

    # ── 날짜 + BP 필터 ──
    detail_df = raw_df.copy()

    if "_ship_date" in detail_df.columns:
        detail_df = detail_df[detail_df["_ship_date"] == selected_date].copy()
    elif COL_SHIP in detail_df.columns:
        detail_df = detail_df[
            pd.to_datetime(detail_df[COL_SHIP], errors="coerce").dt.date == selected_date
        ].copy()

    if COL_BP in detail_df.columns:
        detail_df = detail_df[
            detail_df[COL_BP].astype(str).str.strip() == str(selected_bp).strip()
        ].copy()

    if detail_df.empty:
        st.info("해당 날짜/BP의 상세 데이터가 없습니다.")
        return

    # ── KPI 카드 ──
    total_qty = int(pd.to_numeric(detail_df[COL_QTY], errors="coerce").fillna(0).sum())
    row_cnt = len(detail_df)
    cust1_val = ""
    if COL_CUST1 in detail_df.columns:
        mode_s = detail_df[COL_CUST1].dropna().astype(str).str.strip()
        if not mode_s.empty:
            cust1_val = mode_s.mode().iloc[0]

    st.markdown(
        f"""
        <div class="kpi-wrap">
          <div class="kpi-card">
            <div class="kpi-title">출고일자</div>
            <div class="kpi-value">{html.escape(str(selected_date))}</div>
          </div>
          <div class="kpi-card" style="flex: 2 1 220px;">
            <div class="kpi-title">BP명</div>
            <div class="kpi-value" style="word-break:break-word;">{html.escape(str(selected_bp))}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-title">거래처구분</div>
            <div class="kpi-value">{html.escape(cust1_val) if cust1_val else "-"}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-title">총 요청수량</div>
            <div class="kpi-big">{total_qty:,}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-title">RAW 행수</div>
            <div class="kpi-value">{row_cnt:,}건</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    # ── 표시 컬럼 구성 ──
    out_df = detail_df.copy()

    # 출고일자 문자열화
    if COL_SHIP in out_df.columns:
        out_df["출고일자"] = out_df[COL_SHIP].apply(fmt_date)
        out_df = out_df.drop(columns=[COL_SHIP])
    elif "_ship_date" in out_df.columns:
        out_df["출고일자"] = out_df["_ship_date"].apply(
            lambda x: str(x) if pd.notna(x) else "-"
        )

    # 요청수량 정수화
    if COL_QTY in out_df.columns:
        out_df[COL_QTY] = (
            pd.to_numeric(out_df[COL_QTY], errors="coerce")
            .fillna(0).round(0).astype("Int64")
        )

    # 출력 컬럼 순서: 품목코드 / 품목명 / 요청수량 / 출고일자
    col_order = [COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY, "출고일자"]
    out_df = out_df[[c for c in col_order if c in out_df.columns]]

    # 출고일자 → 정렬
    if "출고일자" in out_df.columns:
        out_df = out_df.sort_values("출고일자", ascending=True)

    tbl_h = min(80 + len(out_df) * 44, 600)
    render_pretty_table(
        out_df,
        height=tbl_h,
        wrap_cols=[COL_ITEM_NAME],
        number_cols=[COL_QTY],
    )

# =========================
# 메뉴 UX 통일: 메뉴별 state reset
# =========================
def reset_state_for_menu(menu: str):
    if menu == "① 출고 캘린더":
        st.session_state["cal_view"] = "calendar"
        st.session_state["cal_selected_date"] = None
        st.session_state["cal_selected_bp"] = ""
        st.session_state["cal_expanded"] = set()
        st.session_state["cal_ym"] = ""
    elif menu == "② SKU별 조회":
        for k in ["sku_query", "sku_candidate_pick", "sku_show_all_history", "sku_ignore_month_filter"]:
            if k in st.session_state:
                del st.session_state[k]
    elif menu == "③ 주차요약":
        if "wk_sel_week" in st.session_state:
            del st.session_state["wk_sel_week"]
    elif menu == "④ 월간요약":
        if "m_sel_month" in st.session_state:
            del st.session_state["m_sel_month"]
        if "monthly_report_text" in st.session_state:
            del st.session_state["monthly_report_text"]
def init_nav_state():
    st.session_state.setdefault("nav_menu", "① 출고 캘린더")
    st.session_state.setdefault("_prev_nav_menu", st.session_state["nav_menu"])
# =========================
# 월간 리포트 생성 helpers
# =========================
def _sum_qty(df: pd.DataFrame) -> int:
    if df is None or df.empty or COL_QTY not in df.columns:
        return 0
    return int(round(float(pd.to_numeric(df[COL_QTY], errors="coerce").fillna(0).sum()), 0))
def _top_bp_lines(df: pd.DataFrame, top_n: int = REPORT_TOP_N) -> list[str]:
    if df is None or df.empty or (COL_BP not in df.columns) or (COL_QTY not in df.columns):
        return []
    g = df.groupby(COL_BP, dropna=False)[COL_QTY].sum(min_count=1).sort_values(ascending=False).head(top_n)
    return [f"{str(bp).strip()}({_fmt_int(q)})" for bp, q in g.items()]
def _overseas_stock_type_from_item_name(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return "공용재고"
    pat = r"\b(CN|EU|MO|JP|Mo)\b(?:\s*(?:N\d+|OFF))*\s*$"
    if re.search(pat, s, flags=re.IGNORECASE):
        return "전용재고"
    return "공용재고"
def _extract_overseas_country(name: str) -> str:
    """품목명에서 해외 출하 국가 코드 추출: JP / CN / EU / MO / 공용"""
    s = (name or "").strip()
    if not s:
        return "공용"
    m = re.search(r"\b(CN|EU|MO|JP|Mo)\b", s, flags=re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return "공용"
def _new_bp_detail_lines_whole_history(
    all_df: pd.DataFrame,
    cur_df: pd.DataFrame,
    cust1_value: str,
    cur_month_label: str,
    top_n: int = REPORT_TOP_N
) -> list[str]:
    if cur_df is None or cur_df.empty or COL_BP not in cur_df.columns:
        return ["- 없음"]
    cur = _filter_cust1(cur_df, cust1_value).copy()
    if cur.empty:
        return ["- 없음"]
    cur["__bp"] = cur[COL_BP].astype(str).str.strip()
    cur = cur[cur["__bp"].notna() & (cur["__bp"] != "")]
    if cur.empty:
        return ["- 없음"]
    others = all_df.copy()
    if "_month_label" in others.columns:
        others = others[others["_month_label"].astype(str) != str(cur_month_label)].copy()
    others = _filter_cust1(others, cust1_value).copy()
    other_bps = set(others[COL_BP].dropna().astype(str).str.strip().tolist()) if not others.empty else set()
    new_cur = cur[~cur["__bp"].isin(other_bps)].copy()
    if new_cur.empty:
        return ["- 없음"]
    if cust1_value == "해외B2B":
        new_cur["__country"] = new_cur.get(COL_CUST2, "").fillna("").astype(str).str.strip()
        agg = new_cur.groupby(["__bp", "__country"], dropna=False).agg(
            sku_cnt=(COL_ITEM_CODE, lambda s: s.astype(str).str.strip().replace({"": pd.NA}).dropna().nunique()),
            qty_sum=(COL_QTY, "sum")
        ).reset_index()
        agg["qty_sum"] = pd.to_numeric(agg["qty_sum"], errors="coerce").fillna(0)
        agg = agg.sort_values(["qty_sum"], ascending=False).head(top_n)
        out = []
        for _, r in agg.iterrows():
            bp = str(r["__bp"]).strip()
            ctry = str(r["__country"]).strip()
            sku = int(r["sku_cnt"]) if pd.notna(r["sku_cnt"]) else 0
            qty = float(r["qty_sum"]) if pd.notna(r["qty_sum"]) else 0
            tail = f"({ctry})" if ctry else ""
            out.append(f"- {bp}{tail} : 총 {sku}SKU / {_fmt_int(qty)}개")
        return out
    agg = new_cur.groupby("__bp", dropna=False).agg(
        sku_cnt=(COL_ITEM_CODE, lambda s: s.astype(str).str.strip().replace({"": pd.NA}).dropna().nunique()),
        qty_sum=(COL_QTY, "sum")
    ).reset_index()
    agg["qty_sum"] = pd.to_numeric(agg["qty_sum"], errors="coerce").fillna(0)
    agg = agg.sort_values(["qty_sum"], ascending=False).head(top_n)
    out = []
    for _, r in agg.iterrows():
        bp = str(r["__bp"]).strip()
        sku = int(r["sku_cnt"]) if pd.notna(r["sku_cnt"]) else 0
        qty = float(r["qty_sum"]) if pd.notna(r["qty_sum"]) else 0
        out.append(f"- {bp}: 총 {sku}SKU / {_fmt_int(qty)}개")
    return out
def _top_sku_with_bp_lines(df: pd.DataFrame, top_n: int = REPORT_TOP_N, bp_top_k: int = 2) -> list[str]:
    if df is None or df.empty or not all(c in df.columns for c in [COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY, COL_BP]):
        return []
    sku = (
        df.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1).reset_index()
        .rename(columns={COL_QTY: "qty"})
    )
    sku["qty"] = pd.to_numeric(sku["qty"], errors="coerce").fillna(0)
    sku = sku.sort_values("qty", ascending=False).head(top_n)
    out = []
    for _, r in sku.iterrows():
        code = str(r[COL_ITEM_CODE]).strip()
        name = str(r[COL_ITEM_NAME]).strip()
        qty = float(r["qty"]) if pd.notna(r["qty"]) else 0
        sub = df[df[COL_ITEM_CODE].astype(str).str.strip() == code].copy()
        bp_g = sub.groupby(COL_BP, dropna=False)[COL_QTY].sum(min_count=1).sort_values(ascending=False).head(bp_top_k)
        bp_txt = "/ ".join([f"{str(bp).strip()}({_fmt_int(v)})" for bp, v in bp_g.items()])
        if bp_txt:
            out.append(f"- {code} {name} : {_fmt_int(qty)}개 → {bp_txt}")
        else:
            out.append(f"- {code} {name} : {_fmt_int(qty)}개")
    return out
def _top_sku_with_bp_lines_overseas_split_stock(df_overseas: pd.DataFrame, top_n_each: int = REPORT_TOP_N) -> list[str]:
    if df_overseas is None or df_overseas.empty:
        return ["- 없음"]
    tmp = df_overseas.copy()
    tmp["__stock_type"] = tmp[COL_ITEM_NAME].astype(str).apply(_overseas_stock_type_from_item_name)
    out: list[str] = []
    for stock in ["공용재고", "전용재고"]:
        sub = tmp[tmp["__stock_type"] == stock].copy()
        out.append(f"- {stock}")
        lines = _top_sku_with_bp_lines(sub, top_n=top_n_each, bp_top_k=2)
        if lines:
            out.extend(["  " + ln for ln in lines])
        else:
            out.append("  - 없음")
    return out
# ✅✅✅ (에러 수정 핵심) pd.NA 제거 + np.nan 벡터화
def _sku_mom_compare_table(cur_df: pd.DataFrame, prev_df: pd.DataFrame) -> pd.DataFrame:
    if cur_df is None:
        cur_df = pd.DataFrame()
    if prev_df is None:
        prev_df = pd.DataFrame()
    cur = (
        cur_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1).reset_index().rename(columns={COL_QTY: "cur_qty"})
    ) if (not cur_df.empty) else pd.DataFrame(columns=[COL_ITEM_CODE, COL_ITEM_NAME, "cur_qty"])
    prev = (
        prev_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1).reset_index().rename(columns={COL_QTY: "prev_qty"})
    ) if (not prev_df.empty) else pd.DataFrame(columns=[COL_ITEM_CODE, COL_ITEM_NAME, "prev_qty"])
    cur["cur_qty"] = pd.to_numeric(cur.get("cur_qty", 0), errors="coerce").fillna(0.0)
    prev["prev_qty"] = pd.to_numeric(prev.get("prev_qty", 0), errors="coerce").fillna(0.0)
    cmp = cur.merge(prev, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="outer")
    cmp["cur_qty"] = pd.to_numeric(cmp.get("cur_qty", 0), errors="coerce").fillna(0.0)
    cmp["prev_qty"] = pd.to_numeric(cmp.get("prev_qty", 0), errors="coerce").fillna(0.0)
    cmp["diff_qty"] = cmp["cur_qty"] - cmp["prev_qty"]
    cmp["pct"] = np.where(cmp["prev_qty"] > 0, (cmp["cur_qty"] / cmp["prev_qty"]) - 1.0, np.nan)
    cmp["abs_diff"] = cmp["diff_qty"].abs().astype(float)
    cmp["abs_pct_sort"] = pd.to_numeric(np.abs(cmp["pct"]), errors="coerce").fillna(-1.0)
    return cmp
def _sku_mom_top_lines_by_pct(cur_df: pd.DataFrame, prev_df: pd.DataFrame, top_n: int = REPORT_TOP_N) -> list[str]:
    cmp = _sku_mom_compare_table(cur_df, prev_df)
    cmp2 = cmp[cmp["abs_pct_sort"] >= 0].copy()
    if cmp2.empty:
        return ["- 없음"]
    cmp2 = cmp2.sort_values(["abs_pct_sort", "abs_diff"], ascending=False).head(top_n)
    out = []
    for _, r in cmp2.iterrows():
        code = str(r[COL_ITEM_CODE]).strip()
        name = str(r[COL_ITEM_NAME]).strip()
        pq = float(r["prev_qty"])
        cq = float(r["cur_qty"])
        pct = float(r["pct"]) * 100
        out.append(f"- {code} {name} : {pct:+.0f}% ({_fmt_int(pq)} → {_fmt_int(cq)})")
    return out
def _sku_mom_top_lines_by_diff(cur_df: pd.DataFrame, prev_df: pd.DataFrame, top_n: int = REPORT_TOP_N) -> list[str]:
    cmp = _sku_mom_compare_table(cur_df, prev_df)
    if cmp.empty:
        return ["- 없음"]
    cmp2 = cmp.sort_values(["abs_diff"], ascending=False).head(top_n)
    out = []
    for _, r in cmp2.iterrows():
        code = str(r[COL_ITEM_CODE]).strip()
        name = str(r[COL_ITEM_NAME]).strip()
        pq = float(r["prev_qty"])
        cq = float(r["cur_qty"])
        diff = float(r["diff_qty"])
        out.append(f"- {code} {name} : {diff:+,.0f}개 ({_fmt_int(pq)} → {_fmt_int(cq)})")
    return out
def _spike_sku_lines(cur_df: pd.DataFrame, prev_df: pd.DataFrame, top_n: int = REPORT_TOP_N) -> list[str]:
    spike_df = build_spike_report_only(cur_df, prev_df)
    if spike_df is None or spike_df.empty:
        return ["- 없음"]
    spike_df = spike_df.copy()
    spike_df["pct_tmp"] = spike_df.apply(
        lambda r: ((float(r["현재_요청수량"]) / float(r["이전_요청수량"]) - 1) * 100)
        if (pd.notna(r["이전_요청수량"]) and float(r["이전_요청수량"]) > 0) else np.nan,
        axis=1
    )
    spike_df = spike_df.sort_values(["pct_tmp", "현재_요청수량"], ascending=False).head(top_n)
    out = []
    for _, r in spike_df.iterrows():
        code = str(r[COL_ITEM_CODE]).strip()
        name = str(r[COL_ITEM_NAME]).strip()
        prev_q = int(r["이전_요청수량"]) if pd.notna(r["이전_요청수량"]) else 0
        cur_q = int(r["현재_요청수량"]) if pd.notna(r["현재_요청수량"]) else 0
        pct = r["pct_tmp"]
        pct_s = f"(약 {pct:+.0f}%)" if pd.notna(pct) else ""
        bp_map = str(r.get("BP명(요청수량)", "") or "").strip()
        tail = f" → {bp_map}" if bp_map else ""
        out.append(f"- {code} {name} : {_fmt_int(prev_q)} → {_fmt_int(cur_q)} {pct_s}{tail}")
    return out


# ✅ v2.1 — 증감 방향 표시 헬퍼
def _pct_change_str(cur_val: float, prev_val: float) -> str:
    """전월 대비 증감률 문자열 생성 (▲/▼ 포함)"""
    if prev_val <= 0:
        return "(전월 데이터 부족)"
    pct = (cur_val / prev_val - 1) * 100
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "→")
    return f"({arrow} {abs(pct):.1f}%)"


def build_monthly_share_report(
    all_df: pd.DataFrame,
    sel_month_label: str,
    cur_df: pd.DataFrame,
    prev_df: pd.DataFrame,
    next_df: Optional[pd.DataFrame] = None,
) -> str:
    # ✅ v2.1 — 유니코드 이모지 사용 + 총괄 요약 추가

    # ── 총괄 수치 산출 ──
    total_cur_qty = _sum_qty(cur_df)
    total_prev_qty = _sum_qty(prev_df)
    overseas_cur = _filter_cust1(cur_df, "해외B2B") if (cur_df is not None and not cur_df.empty) else pd.DataFrame()
    domestic_cur = _filter_cust1(cur_df, "국내B2B") if (cur_df is not None and not cur_df.empty) else pd.DataFrame()
    overseas_prev = _filter_cust1(prev_df, "해외B2B") if (prev_df is not None and not prev_df.empty) else pd.DataFrame()
    domestic_prev = _filter_cust1(prev_df, "국내B2B") if (prev_df is not None and not prev_df.empty) else pd.DataFrame()

    ovs_cur_qty = _sum_qty(overseas_cur)
    ovs_prev_qty = _sum_qty(overseas_prev)
    dom_cur_qty = _sum_qty(domestic_cur)
    dom_prev_qty = _sum_qty(domestic_prev)

    # 비율
    ovs_pct = (ovs_cur_qty / total_cur_qty * 100) if total_cur_qty > 0 else 0
    dom_pct = (dom_cur_qty / total_cur_qty * 100) if total_cur_qty > 0 else 0

    head = [
        f"📦 {sel_month_label} B2B 출고 현황 공유드립니다 😊",
        "(SAP 현황 기준이며, 자료에 오차 범위가 있을 수 있습니다)",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 총괄 요약",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"- 총 출고수량: {_fmt_int(total_cur_qty)}개 {_pct_change_str(total_cur_qty, total_prev_qty)}",
        f"  ├ 해외B2B: {_fmt_int(ovs_cur_qty)}개 ({ovs_pct:.0f}%) {_pct_change_str(ovs_cur_qty, ovs_prev_qty)}",
        f"  └ 국내B2B: {_fmt_int(dom_cur_qty)}개 ({dom_pct:.0f}%) {_pct_change_str(dom_cur_qty, dom_prev_qty)}",
        "",
    ]

    def section_for(cust1_value: str, title: str, sched_top_bp_n: int):
        sub_cur = _filter_cust1(cur_df, cust1_value).copy()
        sub_prev = _filter_cust1(prev_df, cust1_value).copy() if (prev_df is not None) else pd.DataFrame()
        lines: list[str] = []
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"*{title}*")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")

        # 1) 신규 업체
        lines.append("✅ 신규 업체 첫 출고")
        lines.extend(_new_bp_detail_lines_whole_history(
            all_df=all_df,
            cur_df=cur_df,
            cust1_value=cust1_value,
            cur_month_label=sel_month_label,
            top_n=REPORT_TOP_N
        ))
        lines.append("")

        # 2) 출고량 증감 요약
        cq = _sum_qty(sub_cur)
        pq = _sum_qty(sub_prev)
        diff = cq - pq
        lines.append("✅ 출고량 증감 요약")
        if pq > 0:
            pct = (cq / pq - 1) * 100
            arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "→")
            lines.append(f"- 출고수량: {_fmt_int(pq)} → {_fmt_int(cq)}개 ({arrow} {abs(diff):,}개, {abs(pct):.1f}%)")
        else:
            lines.append(f"- 출고수량: {_fmt_int(cq)}개 (전월 데이터 부족으로 증감 산정 불가)")
        top_bps = _top_bp_lines(sub_cur, top_n=REPORT_TOP_N)
        lines.append("- 주요 출고 업체 : " + (" / ".join(top_bps) if top_bps else "-"))
        lines.append("")

        # 3) 특정 SKU 대량 출고
        lines.append("✅ 특정 SKU 대량 출고 (Top)")
        if cust1_value == "해외B2B":
            lines.extend(_top_sku_with_bp_lines_overseas_split_stock(sub_cur, top_n_each=REPORT_TOP_N))
        else:
            top_skus = _top_sku_with_bp_lines(sub_cur, top_n=REPORT_TOP_N, bp_top_k=2)
            lines.extend(top_skus if top_skus else ["- 없음"])
        lines.append("")

        # 4) 전월 대비 주요 SKU 증감
        lines.append("✅ 전월 대비 주요 SKU 증감")
        lines.append(f"  [증감률 Top{REPORT_TOP_N}]")
        pct_lines = _sku_mom_top_lines_by_pct(sub_cur, sub_prev, top_n=REPORT_TOP_N)
        lines.extend(["  " + x for x in pct_lines])
        lines.append(f"  [증감수량 Top{REPORT_TOP_N}]")
        diff_lines = _sku_mom_top_lines_by_diff(sub_cur, sub_prev, top_n=REPORT_TOP_N)
        lines.extend(["  " + x for x in diff_lines])
        lines.append("")

        # 5) 전월 대비 출고량 증가 SKU (급증)
        lines.append("⚠️ 전월 대비 출고량 급증 SKU (+30% 이상)")
        lines.extend(_spike_sku_lines(sub_cur, sub_prev, top_n=REPORT_TOP_N))
        lines.append("")

        # 6) 차월 간략 일정
        lines.append("🗓️ 차월 간략 일정 (대량 출고 중심)")
        if next_df is None or next_df.empty:
            lines.append(f"- {title} 차월 데이터 없음")
            lines.append("")
            return lines
        sub_next = _filter_cust1(next_df, cust1_value).copy()
        if sub_next.empty:
            lines.append(f"- {title} 차월 데이터 없음")
            lines.append("")
            return lines
        bp_sched = _top_bp_lines(sub_next, top_n=sched_top_bp_n)
        if not bp_sched:
            lines.append(f"- {title} 차월 데이터 없음")
            lines.append("")
            return lines
        lines.append(f"- {title} 차월 대량 출고(Top{len(bp_sched)})")
        for bp_txt in bp_sched:
            bp_name = bp_txt.split("(")[0].strip()
            bp_sub = sub_next[sub_next[COL_BP].astype(str).str.strip() == bp_name].copy()
            sku_sched = _top_sku_with_bp_lines(bp_sub, top_n=1, bp_top_k=1)
            if sku_sched:
                sku_line = sku_sched[0].lstrip("- ").strip()
                lines.append(f"  • {bp_name}: {sku_line}")
            else:
                lines.append(f"  • {bp_txt}")
        lines.append("")
        return lines
    overseas = section_for("해외B2B", "해외B2B", sched_top_bp_n=REPORT_TOP_N)
    domestic = section_for("국내B2B", "국내B2B", sched_top_bp_n=REPORT_TOP_N)
    return "\n".join(head + overseas + domestic).strip()
# =========================
# Main
# =========================
st.title("📦 B2B 출고 대시보드")
st.caption("Google Sheet RAW 기반 | 제품분류 B0/B1 고정 | 필터(거래처구분1/2/월/BP) 반영")
init_nav_state()
# ✅ Refresh handler (전부 초기화 정책)
if st.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    for k in list(st.session_state.keys()):
        if k.startswith(("cal_", "f_", "sku_", "wk_", "m_")) or k in ("monthly_report_text", "_prev_nav_menu", "nav_menu"):
            del st.session_state[k]
    st.session_state["nav_menu"] = "① 출고 캘린더"
    st.session_state["_prev_nav_menu"] = "① 출고 캘린더"
    reset_state_for_menu("① 출고 캘린더")
    st.session_state["f_cust1"] = "전체"
    st.session_state["f_cust2"] = "전체"
    st.session_state["f_month"] = "전체"
    st.session_state["f_bp"] = "전체"
    safe_rerun()
with st.spinner("Google Sheet RAW 로딩/전처리 중..."):
    try:
        raw, cal_agg = load_prepared_from_gsheet()
    except Exception as e:
        st.error("Google Sheet에서 RAW 데이터를 불러오지 못했습니다.")
        st.code(str(e))
        st.stop()
# 재고 데이터 로드 (상품카테고리&입고일 탭)
with st.spinner("재고/입고 데이터 로딩 중..."):
    try:
        inv_data = load_inventory_from_gsheet()
    except Exception:
        inv_data = pd.DataFrame(columns=["품목코드", "품목이름", "현재고", "1차입고일", "1차입고수량"])
# =========================
# Sidebar filters
# =========================
st.sidebar.header("필터")
st.sidebar.caption("제품분류 고정: B0, B1")
st.session_state.setdefault("f_cust1", "전체")
st.session_state.setdefault("f_cust2", "전체")
st.session_state.setdefault("f_month", "전체")
st.session_state.setdefault("f_bp", "전체")
cust1_list = uniq_sorted(raw, COL_CUST1)
with st.sidebar.form("filters_form", border=True):
    sel_cust1 = safe_selectbox("거래처구분1", ["전체"] + cust1_list, key="f_cust1")
    pool1 = raw.copy()
    if sel_cust1 != "전체" and COL_CUST1 in pool1.columns:
        pool1 = pool1[pool1[COL_CUST1].astype(str).str.strip() == sel_cust1]
    cust2_list = uniq_sorted(pool1, COL_CUST2)
    sel_cust2 = safe_selectbox("거래처구분2", ["전체"] + cust2_list, key="f_cust2")
    pool2 = pool1.copy()
    if sel_cust2 != "전체" and COL_CUST2 in pool2.columns:
        pool2 = pool2[pool2[COL_CUST2].astype(str).str.strip() == sel_cust2]
    month_labels = []
    if "_month_label" in pool2.columns and "_month_key_num" in pool2.columns:
        tmp = pool2[["_month_label", "_month_key_num"]].dropna().drop_duplicates("_month_label").copy()
        tmp["_month_key_num"] = pd.to_numeric(tmp["_month_key_num"], errors="coerce")
        tmp = tmp.dropna(subset=["_month_key_num"]).sort_values("_month_key_num")
        month_labels = tmp["_month_label"].astype(str).tolist()
    sel_month_label = safe_selectbox("월", ["전체"] + month_labels, key="f_month")
    pool3 = pool2.copy()
    if sel_month_label != "전체":
        pool3 = pool3[pool3["_month_label"].astype(str) == str(sel_month_label)]
    bp_list = uniq_sorted(pool3, COL_BP)
    _ = safe_selectbox("BP명", ["전체"] + bp_list, key="f_bp")
    st.form_submit_button("✅ 필터 적용", use_container_width=True)
# ✅ view 구성
pool1 = raw.copy()
if st.session_state["f_cust1"] != "전체":
    pool1 = pool1[pool1[COL_CUST1].astype(str).str.strip() == st.session_state["f_cust1"]]
pool2 = pool1.copy()
if st.session_state["f_cust2"] != "전체":
    pool2 = pool2[pool2[COL_CUST2].astype(str).str.strip() == st.session_state["f_cust2"]]
pool3 = pool2.copy()
if st.session_state["f_month"] != "전체":
    pool3 = pool3[pool3["_month_label"].astype(str) == str(st.session_state["f_month"])]
df_view = pool3.copy()
if st.session_state["f_bp"] != "전체":
    df_view = df_view[df_view[COL_BP].astype(str).str.strip() == st.session_state["f_bp"]]

# ✅ v2.1 — pool2_with_bp: 월 필터 제외, 나머지 필터 적용 (③주차/④월간 비교용)
pool2_with_bp = pool2.copy()
if st.session_state["f_bp"] != "전체":
    pool2_with_bp = pool2_with_bp[pool2_with_bp[COL_BP].astype(str).str.strip() == st.session_state["f_bp"]]

k = compute_kpis(df_view)
st.markdown(
    f"""
    <div class="kpi-wrap">
      <div class="kpi-card">
        <div class="kpi-title">총 출고수량(합)</div>
        <div class="kpi-value">{k['total_qty']:,.0f}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">총 출고건수(합) <span style="color:#6b7280;font-size:0.85rem;">(주문번호 distinct)</span></div>
        <div class="kpi-value">{k['total_cnt']:,}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">최근 작업완료일</div>
        <div class="kpi-value">{fmt_date(k['latest_done'])}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">리드타임 평균 (해외B2B)</div>
        <div class="kpi-value">{(f"{k['avg_lt2_overseas']:.1f}일" if k['avg_lt2_overseas'] is not None else "-")}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">출고수량 TOP BP</div>
        <div class="kpi-big">{html.escape(k['top_bp_qty_val'])}</div>
        <div class="kpi-muted">{html.escape(k['top_bp_qty_name'])}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">출고건수 TOP BP <span style="color:#6b7280;font-size:0.85rem;">(주문번호 distinct)</span></div>
        <div class="kpi-big">{html.escape(k['top_bp_cnt_val'])}</div>
        <div class="kpi-muted">{html.escape(k['top_bp_cnt_name'])}</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True
)
st.caption("※ 리드타임 지표는 해외B2B(거래처구분1=해외B2B)만을 대상으로 계산됩니다.")
st.divider()
# =========================
# Navigation
# =========================
nav = st.radio(
    "메뉴",
    ["① 출고 캘린더", "② SKU별 조회", "③ 주차요약", "④ 월간요약", "⑤ 국가별 조회", "⑥ BP명별 조회", "⑦ 트렌드 분석", "⑧ 부족예상재고"],
    horizontal=True,
    key="nav_menu"
)
prev_nav = st.session_state.get("_prev_nav_menu", None)
if prev_nav != nav:
    reset_state_for_menu(nav)
    st.session_state["_prev_nav_menu"] = nav
# =========================
# ① 출고 캘린더
# =========================
if nav == "① 출고 캘린더":
    init_calendar_state()
    cal_pool = cal_agg.copy()
    if st.session_state["f_cust1"] != "전체":
        cal_pool = cal_pool[cal_pool[COL_CUST1].astype(str).str.strip() == st.session_state["f_cust1"]]
    if st.session_state["f_cust2"] != "전체":
        cal_pool = cal_pool[cal_pool[COL_CUST2].astype(str).str.strip() == st.session_state["f_cust2"]]
    if st.session_state["f_bp"] != "전체":
        cal_pool = cal_pool[cal_pool[COL_BP].astype(str).str.strip() == st.session_state["f_bp"]]
    if st.session_state["cal_ym"].strip() == "":
        if (cal_pool is not None) and (not cal_pool.empty) and "_ship_ym" in cal_pool.columns:
            st.session_state["cal_ym"] = cal_pool["_ship_ym"].dropna().astype(str).max()
        else:
            st.session_state["cal_ym"] = date.today().strftime("%Y-%m")
    ym = st.session_state["cal_ym"]

    # ── 뷰 분기: calendar ↔ detail ──
    if st.session_state.get("cal_view") == "detail":
        sel_date = st.session_state.get("cal_selected_date")
        sel_bp   = st.session_state.get("cal_selected_bp", "")
        if sel_date is None or not sel_bp:
            # 상태 이상 → 캘린더로 복귀
            st.session_state["cal_view"] = "calendar"
            safe_rerun()
        else:
            render_calendar_detail(raw, sel_date, sel_bp)
    else:
        st.subheader("출고 캘린더 (월별)")
        render_month_calendar(cal_pool, ym, raw_df=raw)
# =========================
# ② SKU별 조회
# =========================
elif nav == "② SKU별 조회":
    st.subheader("SKU별 조회")

    if not need_cols(df_view, [COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY], "SKU별 조회"):
        st.stop()

    # ── 월 필터 무시 옵션 ──
    ignore_month = st.checkbox(
        "📅 월 필터 무시하고 전체 기간 조회",
        value=st.session_state.get("sku_ignore_month_filter", False),
        key="sku_ignore_month_filter",
        help="사이드바의 '월' 필터를 무시하고 전체 기간 데이터를 기준으로 조회합니다."
    )

    if ignore_month:
        # 월 필터만 빼고 나머지(거래처구분1/2, BP) 필터는 그대로 적용
        d_sku = pool2_with_bp.copy()
        st.caption("⚠️ 월 필터를 무시하고 전체 기간을 조회 중입니다.")
    else:
        d_sku = df_view.copy()

    if d_sku.empty:
        st.info("표시할 데이터가 없습니다. 필터 조건을 확인해 주세요.")
        st.stop()

    # ── 품목코드 풀 ──
    sku_pool = d_sku[[COL_ITEM_CODE, COL_ITEM_NAME]].copy()
    sku_pool[COL_ITEM_CODE] = sku_pool[COL_ITEM_CODE].astype(str).str.strip()
    sku_pool[COL_ITEM_NAME] = sku_pool[COL_ITEM_NAME].astype(str).str.strip()
    sku_pool = (
        sku_pool
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
        .dropna(subset=[COL_ITEM_CODE])
        .drop_duplicates(subset=[COL_ITEM_CODE])
        .reset_index(drop=True)
    )

    # ── 검색 입력 ──
    col_search, col_info = st.columns([2, 3])
    with col_search:
        sku_query = st.text_input(
            "🔍 품목코드 검색",
            placeholder="품목코드 일부를 입력하세요...",
            key="sku_query"
        )
    with col_info:
        total_sku_cnt = sku_pool[COL_ITEM_CODE].nunique()
        st.markdown(
            f"""
            <div style="padding-top:1.85rem; color:#6b7280; font-size:0.9rem;">
              현재 필터 기준 총 <b>{total_sku_cnt:,}개</b> SKU
            </div>
            """,
            unsafe_allow_html=True
        )

    if not sku_query.strip():
        st.info("품목코드(또는 품목명 일부)를 입력하면 해당 SKU의 상세 정보를 확인할 수 있습니다.")
        st.stop()

    # ── 검색 실행 (품목코드 우선, 없으면 품목명) ──
    q = sku_query.strip()
    matched = sku_pool[sku_pool[COL_ITEM_CODE].str.contains(q, case=False, na=False)].copy()
    searched_by = "품목코드"
    if matched.empty:
        matched = sku_pool[sku_pool[COL_ITEM_NAME].str.contains(q, case=False, na=False)].copy()
        searched_by = "품목명"

    if matched.empty:
        st.warning(f"'{q}' 에 해당하는 품목코드 또는 품목명이 없습니다.")
        st.stop()

    if searched_by == "품목명":
        st.caption(f"품목코드에서 찾지 못해 품목명으로 검색했습니다. ({len(matched)}건 발견)")

    # ── 복수 결과 선택 ──
    if len(matched) > 1:
        options = (matched[COL_ITEM_CODE] + "  |  " + matched[COL_ITEM_NAME]).tolist()
        st.caption(f"검색 결과 {len(matched)}건 — 아래에서 조회할 SKU를 선택해 주세요.")
        sel_option = st.selectbox("검색 결과 선택", options, key="sku_candidate_pick")
        sel_code = sel_option.split("  |  ")[0].strip()
    else:
        sel_code = matched[COL_ITEM_CODE].iloc[0]

    # ── 선택 SKU 데이터 필터 ──
    sku_df = d_sku[d_sku[COL_ITEM_CODE].astype(str).str.strip() == sel_code].copy()

    if sku_df.empty:
        st.info("해당 SKU의 데이터가 없습니다.")
        st.stop()

    sel_name_series = sku_df[COL_ITEM_NAME].dropna() if COL_ITEM_NAME in sku_df.columns else pd.Series([], dtype=str)
    sel_name = str(sel_name_series.iloc[0]) if not sel_name_series.empty else "-"
    total_qty = int(round(float(pd.to_numeric(sku_df[COL_QTY], errors="coerce").fillna(0).sum()), 0))
    # 주문번호 기준 중복 제외 건수
    order_cnt = _clean_nunique(sku_df[COL_ORDER_NO]) if COL_ORDER_NO in sku_df.columns else 0

    # ── KPI 카드 ──
    st.markdown(
        f"""
        <div class="kpi-wrap">
          <div class="kpi-card">
            <div class="kpi-title">품목코드</div>
            <div class="kpi-value">{html.escape(str(sel_code))}</div>
          </div>
          <div class="kpi-card" style="flex: 2 1 260px;">
            <div class="kpi-title">품목명</div>
            <div class="kpi-value" style="font-size:1.1rem; word-break:break-word;">{html.escape(str(sel_name))}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-title">총 요청수량 (합)</div>
            <div class="kpi-big">{total_qty:,}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-title">출고건수 <span style="color:#6b7280;font-size:0.82rem;">(주문번호 distinct)</span></div>
            <div class="kpi-value">{order_cnt:,}건</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.divider()

    # ── 출고처(BP명)별 요청수량 ──
    st.subheader("📦 출고처(BP명)별 요청수량")

    if COL_BP not in sku_df.columns:
        st.info("BP명 컬럼이 없습니다.")
    else:
        bp_base = sku_df.copy()

        # 출고일자 + BP명 단위로 집계 (출고일자 오름차순)
        has_ship = COL_SHIP in bp_base.columns and "_ship_date" in bp_base.columns

        if has_ship:
            grp_cols = ["_ship_date", COL_BP]
        else:
            grp_cols = [COL_BP]

        bp_summary = (
            bp_base.groupby(grp_cols, dropna=False)[COL_QTY]
            .sum(min_count=1)
            .reset_index()
            .rename(columns={COL_QTY: "요청수량_합"})
        )
        bp_summary["요청수량_합"] = (
            pd.to_numeric(bp_summary["요청수량_합"], errors="coerce")
            .fillna(0).round(0).astype("Int64")
        )

        # 출고일자 문자열 변환 및 오름차순 정렬
        if has_ship:
            bp_summary["출고일자"] = bp_summary["_ship_date"].apply(
                lambda x: str(x) if pd.notna(x) else ""
            )
            bp_summary = bp_summary.drop(columns=["_ship_date"])
            bp_summary = bp_summary.sort_values(["출고일자", COL_BP], ascending=[False, True])
        else:
            bp_summary = bp_summary.sort_values(COL_BP)

        # 거래처구분1 최빈값 매핑
        if COL_CUST1 in bp_base.columns:
            cust1_map = (
                bp_base.groupby(COL_BP, dropna=False)[COL_CUST1]
                .agg(lambda s: s.dropna().mode().iloc[0] if not s.dropna().empty else "")
                .reset_index()
                .rename(columns={COL_CUST1: "거래처구분1"})
            )
            bp_summary = bp_summary.merge(cust1_map, on=COL_BP, how="left")

        # 전체 대비 비율
        total_bp_qty = float(bp_summary["요청수량_합"].sum())
        if total_bp_qty > 0:
            bp_summary["비율(%)"] = (
                bp_summary["요청수량_합"].astype(float) / total_bp_qty * 100
            ).round(1)
        else:
            bp_summary["비율(%)"] = 0.0

        col_order = ["출고일자", COL_BP, "거래처구분1", "요청수량_합", "비율(%)"]
        bp_summary = bp_summary[[c for c in col_order if c in bp_summary.columns]]

        tbl_height = min(80 + len(bp_summary) * 44, 520)
        render_pretty_table(
            bp_summary,
            height=tbl_height,
            wrap_cols=[COL_BP, "거래처구분1"],
            number_cols=["요청수량_합", "비율(%)"]
        )
        render_download_buttons(bp_summary, f"SKU_{sel_code}_출고처별", key_suffix="sku_bp")

        # ── 월별 × BP명 채널 출고 현황 (피벗) ──
        if "_ship_ym" in sku_df.columns:
            st.divider()
            st.subheader("📊 월별 채널(BP명) 출고 현황")
            st.caption("각 셀: 해당 월·해당 BP의 요청수량 합계 / 마지막 행: 합계")

            pivot_src = sku_df.dropna(subset=["_ship_ym"]).copy()
            pivot_src["_ship_ym"] = pivot_src["_ship_ym"].astype(str).str.strip()
            pivot_src = pivot_src[pivot_src["_ship_ym"] != ""]

            if pivot_src.empty:
                st.info("월별 채널 데이터가 없습니다.")
            else:
                # _ship_ym 은 이미 "YYYY-MM" 형식 → 정렬만 하면 됨
                pivot_long = (
                    pivot_src
                    .groupby(["_ship_ym", COL_BP], dropna=False)[COL_QTY]
                    .sum(min_count=1)
                    .reset_index()
                    .rename(columns={COL_QTY: "qty"})
                )
                pivot_long["qty"] = (
                    pd.to_numeric(pivot_long["qty"], errors="coerce")
                    .fillna(0).round(0).astype(int)
                )
                wide = pivot_long.pivot_table(
                    index="_ship_ym",
                    columns=COL_BP,
                    values="qty",
                    aggfunc="sum",
                    fill_value=0,
                ).reset_index()
                wide.columns.name = None

                # YYYY-MM 오름차순 정렬 후 컬럼명 변경
                wide = wide.sort_values("_ship_ym").reset_index(drop=True)
                wide = wide.rename(columns={"_ship_ym": "월"})

                # 합계 행 추가
                num_cols = [c for c in wide.columns if c != "월"]
                total_row = {"월": "합계"}
                for c in num_cols:
                    total_row[c] = int(wide[c].sum())
                wide = pd.concat([wide, pd.DataFrame([total_row])], ignore_index=True)

                pivot_height = min(80 + len(wide) * 44, 520)
                render_pivot_table(
                    wide,
                    height=pivot_height,
                    first_col_width=80,
                    data_col_width=115,
                )

    # ── 월별 요청수량 추이 ──
    if "_month_label" in sku_df.columns and "_month_key_num" in sku_df.columns:
        st.divider()
        st.subheader("📅 월별 요청수량 추이")

        month_summary = (
            sku_df.groupby(["_month_label", "_month_key_num"], dropna=False)[COL_QTY]
            .sum(min_count=1)
            .reset_index()
            .rename(columns={COL_QTY: "요청수량_합"})
        )
        month_summary["_month_key_num"] = pd.to_numeric(
            month_summary["_month_key_num"], errors="coerce"
        )
        month_summary = (
            month_summary
            .dropna(subset=["_month_key_num"])
            .sort_values("_month_key_num")
        )
        month_summary["요청수량_합"] = (
            pd.to_numeric(month_summary["요청수량_합"], errors="coerce")
            .fillna(0).round(0).astype("Int64")
        )
        month_summary = (
            month_summary
            .rename(columns={"_month_label": "월"})
            .drop(columns=["_month_key_num"])
        )

        tbl_height_m = min(80 + len(month_summary) * 44, 420)
        render_pretty_table(
            month_summary,
            height=tbl_height_m,
            wrap_cols=["월"],
            number_cols=["요청수량_합"]
        )
        render_download_buttons(month_summary, f"SKU_{sel_code}_월별추이", key_suffix="sku_month")
        # 월별 바 차트
        if len(month_summary) > 1:
            chart_ms = month_summary.copy()
            chart_ms["요청수량_합"] = pd.to_numeric(chart_ms["요청수량_합"], errors="coerce").fillna(0)
            fig_sku_m = px.bar(
                chart_ms, x="월", y="요청수량_합",
                title=f"{sel_code} 월별 요청수량 추이",
                labels={"요청수량_합": "요청수량"},
                color_discrete_sequence=["#3b82f6"],
            )
            fig_sku_m.update_layout(height=320, margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig_sku_m, use_container_width=True)

# =========================
# ③ 주차요약
# ✅ v2.1 — pool2_with_bp 사용으로 전주 비교 버그 수정
# =========================
elif nav == "③ 주차요약":
    st.subheader("주차요약")
    # ✅ v2.1: 월 필터를 무시하고 전체 기간 사용 (전주 비교를 위해)
    d = pool2_with_bp.copy()
    if d.empty:
        st.info("표시할 데이터가 없습니다.")
        st.stop()
    if "_week_label" not in d.columns or "_week_key_num" not in d.columns:
        st.warning("주차 라벨/키 컬럼이 없습니다.")
        st.stop()
    tmp = d[["_week_label", "_week_key_num"]].dropna(subset=["_week_label", "_week_key_num"]).drop_duplicates("_week_label").copy()
    tmp["_week_key_num"] = pd.to_numeric(tmp["_week_key_num"], errors="coerce")
    tmp = tmp.dropna(subset=["_week_key_num"]).sort_values("_week_key_num")
    week_list = tmp["_week_label"].astype(str).tolist()
    if not week_list:
        st.info("주차 목록이 없습니다.")
        st.stop()
    sel_week = st.selectbox("주차 선택", week_list, index=len(week_list) - 1, key="wk_sel_week")
    wdf = d[d["_week_label"].astype(str) == str(sel_week)].copy()
    cur_idx = week_list.index(sel_week) if sel_week in week_list else None
    prev_wdf = pd.DataFrame()
    prev_week = None
    if cur_idx is not None and cur_idx > 0:
        prev_week = week_list[cur_idx - 1]
        prev_wdf = d[d["_week_label"].astype(str) == str(prev_week)].copy()
    comment_items = []
    comment_items += period_kpi_delta_comment(cur_df=wdf, prev_df=prev_wdf)
    comment_items += category_top_comment(wdf, top_n=2)
    comment_items += concentration_comment(wdf)
    comment_items += undated_ship_risk_comment(wdf)
    render_numbered_block("주간 특이사항 (자동 코멘트)", comment_items)
    if prev_week:
        st.caption(f"※ 비교 기준: 선택 주차({sel_week}) vs 전주({prev_week})")
    else:
        st.caption("※ 사이드바 월 필터와 무관하게 전체 기간 내 주차를 비교합니다.")
    # ── 최근 12주 출고 추이 바 차트 ──
    st.divider()
    st.subheader("📊 최근 12주 출고 추이")
    wk_agg_src = d.copy()
    wk_agg_src["_week_key_num"] = pd.to_numeric(wk_agg_src["_week_key_num"], errors="coerce")
    wk_agg_src = wk_agg_src.dropna(subset=["_week_label", "_week_key_num"])
    wk_agg = (
        wk_agg_src.groupby(["_week_label", "_week_key_num"], dropna=False)[COL_QTY]
        .sum(min_count=1).reset_index().rename(columns={COL_QTY: "요청수량"})
    )
    wk_agg["요청수량"] = pd.to_numeric(wk_agg["요청수량"], errors="coerce").fillna(0)
    wk_agg = wk_agg.sort_values("_week_key_num").tail(12)
    if not wk_agg.empty:
        bar_colors = ["#ef4444" if lbl == sel_week else "#3b82f6" for lbl in wk_agg["_week_label"]]
        fig_wk = px.bar(
            wk_agg, x="_week_label", y="요청수량",
            title="최근 12주 요청수량 추이 (빨간색: 선택 주차)",
            labels={"_week_label": "주차", "요청수량": "요청수량"},
        )
        fig_wk.update_traces(marker_color=bar_colors)
        fig_wk.update_layout(height=340, margin=dict(l=0, r=0, t=40, b=0),
                              xaxis_tickangle=-30)
        st.plotly_chart(fig_wk, use_container_width=True)
    # ── 상위 BP 3개 / 상위 SKU 3개 ──
    st.divider()
    wk_top_col1, wk_top_col2 = st.columns(2)
    with wk_top_col1:
        st.subheader("🏢 상위 BP Top3")
        if wdf.empty or COL_BP not in wdf.columns or COL_QTY not in wdf.columns:
            st.info("데이터가 없습니다.")
        else:
            bp_top3 = (
                wdf.groupby(COL_BP, dropna=False)[COL_QTY]
                .sum(min_count=1).reset_index()
                .rename(columns={COL_QTY: "요청수량_합"})
            )
            bp_top3["요청수량_합"] = pd.to_numeric(bp_top3["요청수량_합"], errors="coerce").fillna(0).round(0).astype("Int64")
            bp_top3 = bp_top3.sort_values("요청수량_합", ascending=False).head(3)
            bp_top3.insert(0, "순위", range(1, len(bp_top3) + 1))
            render_pretty_table(bp_top3, height=200, wrap_cols=[COL_BP], number_cols=["요청수량_합"])
    with wk_top_col2:
        st.subheader("📦 상위 SKU Top3")
        if wdf.empty or not all(c in wdf.columns for c in [COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY]):
            st.info("데이터가 없습니다.")
        else:
            sku_top3 = (
                wdf.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
                .sum(min_count=1).reset_index()
                .rename(columns={COL_QTY: "요청수량_합"})
            )
            sku_top3["요청수량_합"] = pd.to_numeric(sku_top3["요청수량_합"], errors="coerce").fillna(0).round(0).astype("Int64")
            sku_top3 = sku_top3.sort_values("요청수량_합", ascending=False).head(3)
            sku_top3.insert(0, "순위", range(1, len(sku_top3) + 1))
            render_pretty_table(sku_top3, height=200, wrap_cols=[COL_ITEM_NAME], number_cols=["요청수량_합"])
    st.divider()
    st.subheader("전주 대비 급증 SKU 리포트 (+30% 이상 증가)")
    if prev_week is None:
        st.info("전주 비교를 위해서는 선택 주차 이전의 주차 데이터가 필요합니다.")
    else:
        spike_df = build_spike_report_only(wdf, prev_wdf)
        render_pretty_table(
            spike_df,
            height=520,
            wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"],
            number_cols=["이전_요청수량", "현재_요청수량", "증가배수"],
        )
# =========================
# ④ 월간요약 (리포트 생성 포함)
# ✅ v2.1 — pool2_with_bp 사용으로 전월 비교 버그 수정
# =========================
elif nav == "④ 월간요약":
    st.subheader("월간요약")
    # ✅ v2.1: 월 필터를 무시하고 전체 기간 사용 (전월 비교를 위해)
    d = pool2_with_bp.copy()
    if d.empty:
        st.info("표시할 데이터가 없습니다.")
        st.stop()
    if "_month_label" not in d.columns or "_month_key_num" not in d.columns:
        st.warning("월 라벨/키 컬럼이 없습니다.")
        st.stop()
    tmp = d[["_month_label", "_month_key_num"]].dropna(subset=["_month_label", "_month_key_num"]).drop_duplicates("_month_label").copy()
    tmp["_month_key_num"] = pd.to_numeric(tmp["_month_key_num"], errors="coerce")
    tmp = tmp.dropna(subset=["_month_key_num"]).sort_values("_month_key_num")
    month_list = tmp["_month_label"].astype(str).tolist()
    if not month_list:
        st.info("월 목록이 없습니다. RAW의 '년', '월1' 컬럼을 확인해 주세요.")
        st.stop()

    # ✅ v2.1: 사이드바 월 필터가 있으면 해당 월을 기본 선택값으로 설정
    default_month_idx = len(month_list) - 1
    if st.session_state.get("f_month", "전체") != "전체":
        sidebar_month = st.session_state["f_month"]
        if sidebar_month in month_list:
            default_month_idx = month_list.index(sidebar_month)

    sel_month = st.selectbox("월 선택", month_list, index=default_month_idx, key="m_sel_month")
    mdf = d[d["_month_label"].astype(str) == str(sel_month)].copy()
    cur_idx = month_list.index(sel_month) if sel_month in month_list else None
    prev_mdf = pd.DataFrame()
    prev_month = None
    if cur_idx is not None and cur_idx > 0:
        prev_month = month_list[cur_idx - 1]
        prev_mdf = d[d["_month_label"].astype(str) == str(prev_month)].copy()
    next_mdf = pd.DataFrame()
    next_month = None
    if cur_idx is not None and cur_idx < len(month_list) - 1:
        next_month = month_list[cur_idx + 1]
        next_mdf = d[d["_month_label"].astype(str) == str(next_month)].copy()
    comment_items = []
    comment_items += period_kpi_delta_comment(cur_df=mdf, prev_df=prev_mdf)
    comment_items += category_top_comment(mdf, top_n=2)
    comment_items += concentration_comment(mdf)
    comment_items += undated_ship_risk_comment(mdf)
    render_numbered_block("월간 특이사항 (자동 코멘트)", comment_items)
    if prev_month:
        st.caption(f"※ 비교 기준: 선택 월({sel_month}) vs 전월({prev_month})")
    else:
        st.caption("※ 사이드바 월 필터와 무관하게 전체 기간 내 월을 비교합니다.")
    # ── 월별 누적 바 차트 (해외B2B / 국내B2B) ──
    if "_ship_ym" in d.columns and COL_CUST1 in d.columns:
        m_chart_src = d.dropna(subset=["_ship_ym"]).copy()
        m_chart_src["_ship_ym"] = m_chart_src["_ship_ym"].astype(str).str.strip()
        m_chart_src = m_chart_src[m_chart_src["_ship_ym"] != ""]
        m_chart_data = (
            m_chart_src.groupby(["_ship_ym", COL_CUST1], dropna=False)[COL_QTY]
            .sum(min_count=1).reset_index().rename(columns={COL_QTY: "요청수량"})
        )
        m_chart_data = m_chart_data[m_chart_data[COL_CUST1].isin(["해외B2B", "국내B2B"])].copy()
        m_chart_data["요청수량"] = pd.to_numeric(m_chart_data["요청수량"], errors="coerce").fillna(0)
        m_chart_data = m_chart_data.sort_values("_ship_ym")
        if not m_chart_data.empty:
            st.subheader("📊 월별 출고수량 추이 (해외B2B / 국내B2B)")
            fig_m = px.bar(
                m_chart_data, x="_ship_ym", y="요청수량", color=COL_CUST1,
                barmode="stack",
                labels={"_ship_ym": "월", "요청수량": "요청수량", COL_CUST1: "구분"},
                color_discrete_map={"해외B2B": "#3b82f6", "국내B2B": "#10b981"},
            )
            fig_m.update_layout(
                height=380, margin=dict(l=0, r=0, t=20, b=80),
                legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
                xaxis=dict(type="category"),
            )
            st.plotly_chart(fig_m, use_container_width=True)
    st.markdown("### 📝 월간 리포트 생성")
    cbtn1, cbtn2 = st.columns([1.2, 1.0], vertical_alignment="center")
    with cbtn1:
        if st.button("📝 월간 리포트 생성", use_container_width=True, key="btn_make_monthly_report"):
            report = build_monthly_share_report(
                all_df=raw,
                sel_month_label=sel_month,
                cur_df=mdf,
                prev_df=prev_mdf,
                next_df=(next_mdf if (next_month is not None and not next_mdf.empty) else None),
            )
            st.session_state["monthly_report_text"] = report
            safe_rerun()
    with cbtn2:
        if st.button("🧹 리포트 지우기", use_container_width=True, key="btn_clear_monthly_report"):
            if "monthly_report_text" in st.session_state:
                del st.session_state["monthly_report_text"]
            safe_rerun()
    if st.session_state.get("monthly_report_text", "").strip():
        st.caption("아래 텍스트를 그대로 복사해서 슬랙/내부 공유에 사용하세요. (유니코드 이모지 적용)")
        st.text_area(
            "월간 공유용 리포트",
            value=st.session_state["monthly_report_text"],
            height=520,
        )
    st.divider()
    st.subheader("전월 대비 급증 SKU 리포트 (+30% 이상 증가)")
    if prev_month is None:
        st.info("전월 비교를 위해서는 선택 월 이전의 월 데이터가 필요합니다.")
    else:
        spike_df = build_spike_report_only(mdf, prev_mdf)
        render_pretty_table(
            spike_df,
            height=520,
            wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"],
            number_cols=["이전_요청수량", "현재_요청수량", "증가배수"],
        )
# =========================
# ⑤ 국가별 조회
# =========================
elif nav == "⑤ 국가별 조회":
    st.subheader("국가별 조회 (거래처구분2 기준)")
    if not need_cols(df_view, [COL_CUST2, COL_QTY, COL_LT2, COL_ORDER_NO], "국가별 조회"):
        st.stop()
    base = df_view.copy()
    out = base.groupby(COL_CUST2, dropna=False).agg(
        요청수량_합=(COL_QTY, "sum"),
        평균_리드타임_작업완료기준=(COL_LT2, "mean"),
        리드타임_중간값_작업완료기준=(COL_LT2, "median"),
        p90_tmp=(COL_LT2, lambda s: s.quantile(0.9)),
        집계행수_표본=(COL_CUST2, "size"),
    ).reset_index()
    out = out.rename(columns={"p90_tmp": "리드타임 느린 상위10% 기준(P90)"})
    tmp2 = base[[COL_CUST2, COL_ORDER_NO]].copy()
    tmp2["_ord"] = tmp2[COL_ORDER_NO].astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    rep_cnt = tmp2.dropna(subset=["_ord"]).groupby(COL_CUST2)["_ord"].nunique()
    out["출고건수"] = out[COL_CUST2].astype(str).map(rep_cnt).fillna(0).astype(int)
    for c in ["평균_리드타임_작업완료기준", "리드타임_중간값_작업완료기준", "리드타임 느린 상위10% 기준(P90)"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").round(2)
    out["요청수량_합"] = pd.to_numeric(out["요청수량_합"], errors="coerce").fillna(0).round(0).astype("Int64")
    out["집계행수_표본"] = pd.to_numeric(out["집계행수_표본"], errors="coerce").fillna(0).astype("Int64")
    out = out.sort_values("요청수량_합", ascending=False, na_position="last")
    render_pretty_table(out, height=520, wrap_cols=[COL_CUST2], number_cols=["요청수량_합", "출고건수", "집계행수_표본"])
    render_download_buttons(out, "국가별_조회", key_suffix="country")
    st.caption("※ P90은 '느린 상위 10%' 경계값(리드타임이 큰 구간)입니다.")
# =========================
# ⑥ BP명별 조회
# =========================
elif nav == "⑥ BP명별 조회":
    st.subheader("BP명별 조회")
    if not need_cols(df_view, [COL_BP, COL_QTY, COL_LT2, COL_ORDER_NO], "BP명별 조회"):
        st.stop()
    base = df_view.copy()
    out = base.groupby(COL_BP, dropna=False).agg(
        요청수량_합=(COL_QTY, "sum"),
        평균_리드타임_작업완료기준=(COL_LT2, "mean"),
        리드타임_중간값_작업완료기준=(COL_LT2, "median"),
        최근_출고일=(COL_SHIP, "max"),
        최근_작업완료일=(COL_DONE, "max"),
        집계행수_표본=(COL_BP, "size"),
    ).reset_index()
    tmp3 = base[[COL_BP, COL_ORDER_NO]].copy()
    tmp3["_ord"] = tmp3[COL_ORDER_NO].astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    rep_cnt2 = tmp3.dropna(subset=["_ord"]).groupby(COL_BP)["_ord"].nunique()
    out["출고건수"] = out[COL_BP].astype(str).map(rep_cnt2).fillna(0).astype(int)
    out["요청수량_합"] = pd.to_numeric(out["요청수량_합"], errors="coerce").fillna(0).round(0).astype("Int64")
    for c in ["평균_리드타임_작업완료기준", "리드타임_중간값_작업완료기준"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").round(2)
    out["최근_출고일"] = out["최근_출고일"].apply(fmt_date)
    out["최근_작업완료일"] = out["최근_작업완료일"].apply(fmt_date)
    out["집계행수_표본"] = pd.to_numeric(out["집계행수_표본"], errors="coerce").fillna(0).astype("Int64")
    out = out.sort_values("요청수량_합", ascending=False, na_position="last")
    render_pretty_table(out, height=520, wrap_cols=[COL_BP], number_cols=["요청수량_합", "출고건수", "집계행수_표본"])
    render_download_buttons(out, "BP명별_조회", key_suffix="bp")
# =========================
# ⑦ 트렌드 분석
# =========================
elif nav == "⑦ 트렌드 분석":
    st.subheader("트렌드 분석")
    st.caption("※ 트렌드 분석은 월 필터를 무시하고 전체 기간 기준으로 표시됩니다. (거래처구분1/2, BP 필터는 반영)")

    # 트렌드용 베이스: 월 필터 제외, 나머지 필터 적용
    trend_base = pool2_with_bp.copy()

    if trend_base.empty or "_ship_ym" not in trend_base.columns:
        st.info("표시할 데이터가 없습니다.")
        st.stop()

    trend_base = trend_base.dropna(subset=["_ship_ym"]).copy()
    trend_base["_ship_ym"] = trend_base["_ship_ym"].astype(str).str.strip()
    trend_base = trend_base[trend_base["_ship_ym"] != ""]

    TREND_TOP_N = 10
    COLOR_OVERSEAS = "#3b82f6"
    COLOR_DOMESTIC = "#10b981"
    COUNTRY_COLORS = {"JP": "#f59e0b", "CN": "#ef4444", "EU": "#8b5cf6", "MO": "#ec4899", "공용": "#3b82f6"}

    # ────────────────────────────────────────────
    # 섹션 1 · 전체 월별 출고 추이
    # ────────────────────────────────────────────
    st.subheader("📈 섹션 1 · 전체 월별 출고 추이")
    s1_data = (
        trend_base.groupby(["_ship_ym", COL_CUST1], dropna=False)[COL_QTY]
        .sum(min_count=1).reset_index().rename(columns={COL_QTY: "요청수량"})
    )
    s1_data = s1_data[s1_data[COL_CUST1].isin(["해외B2B", "국내B2B"])].copy()
    s1_data["요청수량"] = pd.to_numeric(s1_data["요청수량"], errors="coerce").fillna(0)
    s1_data = s1_data.sort_values("_ship_ym")
    if s1_data.empty:
        st.info("해외B2B / 국내B2B 데이터가 없습니다.")
    else:
        st.caption("월별 출고수량 추이 (해외B2B / 국내B2B)")
        fig1 = px.bar(
            s1_data, x="_ship_ym", y="요청수량", color=COL_CUST1,
            barmode="stack",
            labels={"_ship_ym": "월", "요청수량": "요청수량", COL_CUST1: "구분"},
            color_discrete_map={"해외B2B": COLOR_OVERSEAS, "국내B2B": COLOR_DOMESTIC},
        )
        fig1.update_layout(
            height=420, margin=dict(l=0, r=0, t=20, b=80),
            legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
            xaxis=dict(type="category"),
        )
        st.plotly_chart(fig1, use_container_width=True)

    # ────────────────────────────────────────────
    # 섹션 2 · Top10 BP 월별 추이
    # ────────────────────────────────────────────
    st.divider()
    st.subheader("🏢 섹션 2 · Top10 BP 월별 추이")
    tab_s2_ovs, tab_s2_dom = st.tabs(["🟦 해외B2B", "🟩 국내B2B"])
    for _tab2, _cust1_2 in [(tab_s2_ovs, "해외B2B"), (tab_s2_dom, "국내B2B")]:
        with _tab2:
            sub2 = _filter_cust1(trend_base, _cust1_2).copy()
            if sub2.empty:
                st.info(f"{_cust1_2} 데이터가 없습니다.")
                continue
            top_bps2 = (
                sub2.groupby(COL_BP, dropna=False)[COL_QTY].sum()
                .sort_values(ascending=False).head(TREND_TOP_N).index.tolist()
            )
            s2_data = (
                sub2[sub2[COL_BP].isin(top_bps2)]
                .groupby(["_ship_ym", COL_BP], dropna=False)[COL_QTY]
                .sum(min_count=1).reset_index().rename(columns={COL_QTY: "요청수량"})
            )
            s2_data["요청수량"] = pd.to_numeric(s2_data["요청수량"], errors="coerce").fillna(0)
            s2_data = s2_data.sort_values("_ship_ym")
            if s2_data.empty:
                st.info("데이터가 없습니다.")
                continue
            st.caption(f"{_cust1_2} Top{TREND_TOP_N} BP 월별 요청수량 추이")
            fig2 = px.line(
                s2_data, x="_ship_ym", y="요청수량", color=COL_BP,
                labels={"_ship_ym": "월", "요청수량": "요청수량", COL_BP: "BP명"},
                markers=True,
            )
            fig2.update_layout(
                height=460, margin=dict(l=0, r=0, t=20, b=100),
                legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
                xaxis=dict(type="category"),
            )
            st.plotly_chart(fig2, use_container_width=True)
            st.caption(f"※ 전체 기간 기준 요청수량 Top{TREND_TOP_N} BP")

    # ────────────────────────────────────────────
    # 섹션 3 · Top10 SKU 월별 추이
    # ────────────────────────────────────────────
    st.divider()
    st.subheader("📦 섹션 3 · Top10 SKU 월별 추이")
    tab_s3_ovs, tab_s3_dom = st.tabs(["🟦 해외B2B (JP/CN/EU/MO/공용 구분)", "🟩 국내B2B"])

    with tab_s3_ovs:
        sub3_o = _filter_cust1(trend_base, "해외B2B").copy()
        if sub3_o.empty:
            st.info("해외B2B 데이터가 없습니다.")
        else:
            sub3_o["__country"] = sub3_o[COL_ITEM_NAME].astype(str).apply(_extract_overseas_country)
            top_skus_o = (
                sub3_o.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY].sum()
                .sort_values(ascending=False).head(TREND_TOP_N).reset_index()
            )
            top_codes_o = top_skus_o[COL_ITEM_CODE].tolist()
            sub3_o_top = sub3_o[sub3_o[COL_ITEM_CODE].isin(top_codes_o)].copy()
            sku_label_o = (
                sub3_o_top.drop_duplicates(subset=[COL_ITEM_CODE])
                .assign(lbl=lambda x: x[COL_ITEM_CODE] + " [" + x["__country"] + "]")
                .set_index(COL_ITEM_CODE)["lbl"].to_dict()
            )
            s3_o = (
                sub3_o_top.groupby(["_ship_ym", COL_ITEM_CODE, "__country"], dropna=False)[COL_QTY]
                .sum(min_count=1).reset_index().rename(columns={COL_QTY: "요청수량"})
            )
            s3_o["요청수량"] = pd.to_numeric(s3_o["요청수량"], errors="coerce").fillna(0)
            s3_o["SKU"] = s3_o[COL_ITEM_CODE].map(sku_label_o).fillna(s3_o[COL_ITEM_CODE])
            s3_o = s3_o.sort_values("_ship_ym")
            if not s3_o.empty:
                st.caption(f"해외B2B Top{TREND_TOP_N} SKU 월별 추이 (국가 구분)")
                fig3_o = px.bar(
                    s3_o, x="_ship_ym", y="요청수량", color="__country",
                    barmode="stack",
                    labels={"_ship_ym": "월", "요청수량": "요청수량", "__country": "국가"},
                    color_discrete_map=COUNTRY_COLORS,
                    custom_data=["SKU"],
                )
                fig3_o.update_traces(
                    hovertemplate="<b>%{customdata[0]}</b><br>월: %{x}<br>요청수량: %{y:,}<extra></extra>"
                )
                fig3_o.update_layout(
                    height=460, margin=dict(l=0, r=0, t=20, b=80),
                    legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
                    xaxis=dict(type="category"),
                )
                st.plotly_chart(fig3_o, use_container_width=True)
                if st.checkbox(f"해외B2B SKU별 라인 추이 보기", key="chk_sku_line_ovs"):
                    st.caption(f"해외B2B Top{TREND_TOP_N} SKU 라인 추이")
                    fig3_o2 = px.line(
                        s3_o, x="_ship_ym", y="요청수량", color="SKU",
                        labels={"_ship_ym": "월", "요청수량": "요청수량"},
                        markers=True,
                    )
                    fig3_o2.update_layout(
                        height=440, margin=dict(l=0, r=0, t=20, b=100),
                        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
                        xaxis=dict(type="category"),
                    )
                    st.plotly_chart(fig3_o2, use_container_width=True)

    with tab_s3_dom:
        sub3_d = _filter_cust1(trend_base, "국내B2B").copy()
        if sub3_d.empty:
            st.info("국내B2B 데이터가 없습니다.")
        else:
            top_skus_d = (
                sub3_d.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY].sum()
                .sort_values(ascending=False).head(TREND_TOP_N).reset_index()
            )
            top_codes_d = top_skus_d[COL_ITEM_CODE].tolist()
            sub3_d_top = sub3_d[sub3_d[COL_ITEM_CODE].isin(top_codes_d)].copy()
            sku_label_d = (
                sub3_d_top.drop_duplicates(subset=[COL_ITEM_CODE])
                .assign(lbl=lambda x: x[COL_ITEM_CODE] + "  " + x[COL_ITEM_NAME].astype(str).str[:14])
                .set_index(COL_ITEM_CODE)["lbl"].to_dict()
            )
            s3_d = (
                sub3_d_top.groupby(["_ship_ym", COL_ITEM_CODE], dropna=False)[COL_QTY]
                .sum(min_count=1).reset_index().rename(columns={COL_QTY: "요청수량"})
            )
            s3_d["요청수량"] = pd.to_numeric(s3_d["요청수량"], errors="coerce").fillna(0)
            s3_d["SKU"] = s3_d[COL_ITEM_CODE].map(sku_label_d).fillna(s3_d[COL_ITEM_CODE])
            s3_d = s3_d.sort_values("_ship_ym")
            if not s3_d.empty:
                st.caption(f"국내B2B Top{TREND_TOP_N} SKU 월별 추이")
                fig3_d = px.bar(
                    s3_d, x="_ship_ym", y="요청수량", color="SKU",
                    barmode="stack",
                    labels={"_ship_ym": "월", "요청수량": "요청수량"},
                )
                fig3_d.update_layout(
                    height=460, margin=dict(l=0, r=0, t=20, b=100),
                    legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
                    xaxis=dict(type="category"),
                )
                st.plotly_chart(fig3_d, use_container_width=True)
                if st.checkbox("국내B2B SKU별 라인 추이 보기", key="chk_sku_line_dom"):
                    st.caption(f"국내B2B Top{TREND_TOP_N} SKU 라인 추이")
                    fig3_d2 = px.line(
                        s3_d, x="_ship_ym", y="요청수량", color="SKU",
                        labels={"_ship_ym": "월", "요청수량": "요청수량"},
                        markers=True,
                    )
                    fig3_d2.update_layout(
                        height=440, margin=dict(l=0, r=0, t=20, b=100),
                        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
                        xaxis=dict(type="category"),
                    )
                    st.plotly_chart(fig3_d2, use_container_width=True)

    # ────────────────────────────────────────────
    # 섹션 4 · Top3 BP 집중도 변화
    # ────────────────────────────────────────────
    st.divider()
    st.subheader("🎯 섹션 4 · Top3 BP 집중도 변화")
    st.caption("전체 기간 기준 Top3 BP가 월별 전체 출고수량에서 차지하는 비율(%) — 공급 집중 리스크 모니터링")
    tab_s4_ovs, tab_s4_dom = st.tabs(["🟦 해외B2B", "🟩 국내B2B"])
    for _tab4, _cust1_4 in [(tab_s4_ovs, "해외B2B"), (tab_s4_dom, "국내B2B")]:
        with _tab4:
            sub4 = _filter_cust1(trend_base, _cust1_4).copy()
            if sub4.empty:
                st.info(f"{_cust1_4} 데이터가 없습니다.")
                continue
            top3_bps = (
                sub4.groupby(COL_BP, dropna=False)[COL_QTY].sum()
                .sort_values(ascending=False).head(3).index.tolist()
            )
            monthly_total4 = (
                sub4.groupby("_ship_ym", dropna=False)[COL_QTY]
                .sum().reset_index().rename(columns={COL_QTY: "total"})
            )
            monthly_total4["total"] = pd.to_numeric(monthly_total4["total"], errors="coerce").fillna(0)
            s4_bp = (
                sub4[sub4[COL_BP].isin(top3_bps)]
                .groupby(["_ship_ym", COL_BP], dropna=False)[COL_QTY]
                .sum(min_count=1).reset_index().rename(columns={COL_QTY: "bp_qty"})
            )
            s4_bp["bp_qty"] = pd.to_numeric(s4_bp["bp_qty"], errors="coerce").fillna(0)
            s4_data = s4_bp.merge(monthly_total4, on="_ship_ym", how="left")
            s4_data["비율(%)"] = (s4_data["bp_qty"] / s4_data["total"].replace(0, float("nan")) * 100).round(1)
            s4_data = s4_data.sort_values("_ship_ym")
            if s4_data.empty:
                st.info("데이터가 없습니다.")
                continue
            st.caption(f"{_cust1_4} Top3 BP 집중도 변화 (%)")
            fig4 = px.line(
                s4_data, x="_ship_ym", y="비율(%)", color=COL_BP,
                labels={"_ship_ym": "월", "비율(%)": "비율(%)", COL_BP: "BP명"},
                markers=True,
            )
            fig4.update_layout(
                height=400, margin=dict(l=0, r=0, t=20, b=80),
                yaxis=dict(ticksuffix="%", range=[0, 105]),
                legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
                xaxis=dict(type="category"),
            )
            st.plotly_chart(fig4, use_container_width=True)
            st.caption(f"※ Top3 BP: {' / '.join(top3_bps)}")

# =========================
# ⑧ 부족 예상 재고
# =========================
elif nav == "⑧ 부족예상재고":
    st.subheader("⑧ 부족 예상 재고 알람 (해외B2B)")
    st.caption("※ 해외B2B 기준 | 전월 대비 30% 이상 출고 증가 품목 대상 | 최근 90일 평균출고 기반 소진일수 산출")

    if inv_data.empty:
        st.warning("재고/입고 데이터를 불러올 수 없습니다. (상품카테고리&입고일 탭 확인 필요)")
    else:
        # 설정 옵션
        with st.expander("분석 설정", expanded=False):
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                lookback = st.slider("일평균 출고 계산 기간 (일)", 30, 180, 90, step=10, key="shortage_lookback")
            with col_s2:
                threshold = st.slider("알람 기준 소진일수 (일)", 7, 60, 30, step=7, key="shortage_threshold")

        # 알람 분석 실행
        alert_result = build_shortage_alert(raw, inv_data, lookback_days=lookback, alert_threshold_days=threshold)

        # 요약 KPI
        if alert_result.empty or alert_result[alert_result["위험등급"] != "안전"].empty:
            st.success("현재 부족 예상 알람 대상 품목이 없습니다.")
        else:
            alert_active = alert_result[alert_result["위험등급"] != "안전"]
            n_urgent = len(alert_active[alert_active["위험등급"] == "긴급"])
            n_warn = len(alert_active[alert_active["위험등급"] == "위험"])
            n_caution = len(alert_active[alert_active["위험등급"] == "주의"])

            kpi_cols = st.columns(4)
            with kpi_cols[0]:
                st.metric("총 알람 품목", f"{len(alert_active)}건")
            with kpi_cols[1]:
                st.metric("🔴 긴급 (7일 이내)", f"{n_urgent}건")
            with kpi_cols[2]:
                st.metric("🟠 위험 (14일 이내)", f"{n_warn}건")
            with kpi_cols[3]:
                st.metric("🟡 주의 (30일 이내)", f"{n_caution}건")

            st.divider()

            # 위험등급별 탭 표시
            tab_all, tab_urgent, tab_warn, tab_caution = st.tabs(["전체", "🔴 긴급", "🟠 위험", "🟡 주의"])

            def _render_alert_table(df_sub):
                if df_sub.empty:
                    st.info("해당 등급의 알람 품목이 없습니다.")
                    return
                display_df = df_sub.copy()
                # 포맷팅
                display_df["현재고"] = display_df["현재고"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")
                display_df["최근일평균출고"] = display_df["최근일평균출고"].apply(lambda x: f"{x:,.1f}" if pd.notna(x) else "-")
                display_df["소진예상일수"] = display_df["소진예상일수"].apply(lambda x: f"{x:.0f}일" if x != float("inf") else "-")
                display_df["이전월출고"] = display_df["이전월출고"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")
                display_df["현재월출고"] = display_df["현재월출고"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "-")
                display_df["증가배수"] = display_df["증가배수"].apply(lambda x: f"x{x:.1f}" if pd.notna(x) else "-")
                display_df["1차입고일"] = display_df["1차입고일"].apply(lambda x: x.strftime("%Y-%m-%d") if pd.notna(x) else "미정")
                display_df["1차입고수량"] = display_df["1차입고수량"].apply(lambda x: f"{int(x):,}" if pd.notna(x) and x > 0 else "-")
                display_cols = [
                    COL_ITEM_CODE, COL_ITEM_NAME, "위험등급", "현재고", "최근일평균출고",
                    "소진예상일수", "소진예상일", "1차입고일", "1차입고수량",
                    "입고전소진여부", "이전월출고", "현재월출고", "증가배수",
                ]
                display_df = display_df[[c for c in display_cols if c in display_df.columns]]
                # 위험등급 색상 표시
                def _color_risk(val):
                    if val == "긴급":
                        return "background-color: #fee2e2; color: #991b1b; font-weight: bold;"
                    elif val == "위험":
                        return "background-color: #ffedd5; color: #9a3412; font-weight: bold;"
                    elif val == "주의":
                        return "background-color: #fef9c3; color: #854d0e; font-weight: bold;"
                    return ""
                # applymap deprecated (pandas 2.1+) → map 사용
                _style_fn = getattr(display_df.style, "map", None) or display_df.style.applymap
                styled = _style_fn(_color_risk, subset=["위험등급"] if "위험등급" in display_df.columns else [])
                st.dataframe(styled, use_container_width=True, hide_index=True)

            with tab_all:
                _render_alert_table(alert_active)
            with tab_urgent:
                _render_alert_table(alert_active[alert_active["위험등급"] == "긴급"])
            with tab_warn:
                _render_alert_table(alert_active[alert_active["위험등급"] == "위험"])
            with tab_caution:
                _render_alert_table(alert_active[alert_active["위험등급"] == "주의"])

            st.divider()

            # Slack 공유 기능
            st.subheader("Slack 공유")
            slack_msg = build_shortage_slack_message(alert_active)
            with st.expander("Slack 메시지 미리보기", expanded=False):
                st.code(slack_msg, language=None)
            col_copy, col_info = st.columns([1, 2])
            with col_copy:
                st.download_button(
                    "📋 Slack 메시지 다운로드",
                    data=slack_msg,
                    file_name=f"shortage_alert_{date.today().strftime('%Y%m%d')}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )
            with col_info:
                st.caption("다운로드한 텍스트를 Slack 채널에 붙여넣기 하세요.")

        # 재고 현황 전체 테이블 (참고용)
        with st.expander("📦 전체 재고 현황 (상품카테고리&입고일 탭)", expanded=False):
            if not inv_data.empty:
                inv_display = inv_data.copy()
                inv_display["현재고"] = inv_display["현재고"].apply(lambda x: f"{int(x):,}" if pd.notna(x) and x > 0 else "0")
                inv_display["1차입고일"] = inv_display["1차입고일"].apply(lambda x: x.strftime("%Y-%m-%d") if pd.notna(x) else "-")
                inv_display["1차입고수량"] = inv_display["1차입고수량"].apply(lambda x: f"{int(x):,}" if pd.notna(x) and x > 0 else "-")
                st.dataframe(inv_display, use_container_width=True, hide_index=True)
            else:
                st.info("재고 데이터가 없습니다.")

st.caption("※ 모든 집계는 Google Sheet RAW 기반이며, 제품분류(B0/B1) 고정 + 선택한 필터 범위 내에서 계산됩니다.")

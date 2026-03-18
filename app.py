# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반)
#
# ✅ 새로고침 정책: 데이터/탭/화면/필터/리포트/내부상태 "모두 초기화"
# ✅ 월간요약(④): 월간 리포트 생성(슬랙 공유용) 기능 포함
#   - 신규업체: 전체 히스토리(선택 월 제외) 대비 신규
#   - 해외 Top SKU: 공용재고 vs 전용재고(CN/EU/Mo/JP) 분리 (N1/N2/OFF 무시)
#   - 전월 대비 주요 SKU 증감: "증감률 Top5" + "증감수량 Top5"
#   - 리포트 내 Top 개수: 전부 Top5 고정
#
# ✅ 에러 수정(중요)
# - _sku_mom_compare_table: pd.NA -> float 변환(TypeError) 방지
#   => np.nan + 벡터화(np.where)로 변경
#
# ✅ ② SKU별 조회 추가
# - 품목코드 검색(부분일치) → 품목코드/품목명/총 요청수량 KPI 카드
# - 출고처(BP명)별 요청수량 합계 + 비율 테이블
# - 월별 요청수량 추이 테이블
# - 월 필터 무시 옵션(전체 기간 조회)
# ==========================================
import re
import html
import hashlib
import calendar as pycal
from datetime import date
from typing import Optional
import numpy as np
import streamlit as st
import pandas as pd
import plotly.express as px
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
GSHEET_GID = "15468212"
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
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)
# =========================
# Utils
# =========================
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
def _get_ship_cnt(df: pd.DataFrame) -> int:
    if df is None or df.empty or COL_ORDER_NO not in df.columns:
        return 0
    return _clean_nunique(df[COL_ORDER_NO])
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
        overseas = df_view[df_view[COL_CUST1].astype(str).str.strip() == LT_ONLY_CUST1]
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
def render_month_calendar(cal_agg_filtered: pd.DataFrame, ym: str):
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
    cal = pycal.Calendar(firstweekday=6)
    weeks = cal.monthdayscalendar(y, m)
    expanded: set[date] = st.session_state.get("cal_expanded", set())
    for wk in weeks:
        cols = st.columns(7, gap="small")
        for i, day_num in enumerate(wk):
            with cols[i]:
                if day_num == 0:
                    st.container(border=True).markdown("&nbsp;")
                    continue
                d = date(y, m, day_num)
                events = day_map.get(d, [])
                is_expanded = d in expanded
                show_n = len(events) if is_expanded else min(3, len(events))
                hidden = max(0, len(events) - show_n)
                with st.container(border=True):
                    st.markdown(f"**{day_num}**")
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
        code = m.group(1).upper()
        return code if code != "MO" else "MO"
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
    cur = cur_df[cur_df[COL_CUST1].astype(str).str.strip() == cust1_value].copy()
    if cur.empty:
        return ["- 없음"]
    cur["__bp"] = cur[COL_BP].astype(str).str.strip()
    cur = cur[cur["__bp"].notna() & (cur["__bp"] != "")]
    if cur.empty:
        return ["- 없음"]
    others = all_df.copy()
    if "_month_label" in others.columns:
        others = others[others["_month_label"].astype(str) != str(cur_month_label)].copy()
    others = others[others[COL_CUST1].astype(str).str.strip() == cust1_value].copy()
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
def build_monthly_share_report(
    all_df: pd.DataFrame,
    sel_month_label: str,
    cur_df: pd.DataFrame,
    prev_df: pd.DataFrame,
    next_df: Optional[pd.DataFrame] = None,
) -> str:
    head = [
        f"{sel_month_label} B2B 현황 공유 드립니다.:blush: (SAP현황에 따라 자료는 오차 범위가 있을 수 있습니다!)",
        "",
    ]
    def section_for(cust1_value: str, title: str, sched_top_bp_n: int):
        sub_cur = cur_df[cur_df[COL_CUST1].astype(str).str.strip() == cust1_value].copy()
        sub_prev = prev_df[prev_df[COL_CUST1].astype(str).str.strip() == cust1_value].copy() if (prev_df is not None) else pd.DataFrame()
        lines: list[str] = []
        lines.append(f"*{title}*")
        lines.append(":white_check_mark: 신규 업체 첫 출고")
        lines.extend(_new_bp_detail_lines_whole_history(
            all_df=all_df,
            cur_df=cur_df,
            cust1_value=cust1_value,
            cur_month_label=sel_month_label,
            top_n=REPORT_TOP_N
        ))
        lines.append("")
        cq = _sum_qty(sub_cur)
        pq = _sum_qty(sub_prev)
        diff = cq - pq
        lines.append(":white_check_mark: 출고량 증감 요약")
        if pq > 0:
            lines.append(f"- 출고수량 전월 대비 {diff:+,}개({_fmt_int(pq)} → {_fmt_int(cq)})")
        else:
            lines.append(f"- 출고수량: {_fmt_int(cq)}개 (전월 데이터 0/부족으로 증감 산정 불가)")
        top_bps = _top_bp_lines(sub_cur, top_n=REPORT_TOP_N)
        lines.append("- 주요 출고 업체 : " + (" / ".join(top_bps) if top_bps else "-"))
        lines.append("")
        lines.append(":white_check_mark: 특정 SKU 대량 출고 (Top)")
        if cust1_value == "해외B2B":
            lines.extend(_top_sku_with_bp_lines_overseas_split_stock(sub_cur, top_n_each=REPORT_TOP_N))
        else:
            top_skus = _top_sku_with_bp_lines(sub_cur, top_n=REPORT_TOP_N, bp_top_k=2)
            lines.extend(top_skus if top_skus else ["- 없음"])
        lines.append("")
        lines.append(":white_check_mark: 전월 대비 주요 SKU 증감")
        lines.append(f"- 증감률 Top{REPORT_TOP_N}")
        pct_lines = _sku_mom_top_lines_by_pct(sub_cur, sub_prev, top_n=REPORT_TOP_N)
        lines.extend(["  " + x for x in pct_lines])
        lines.append(f"- 증감수량 Top{REPORT_TOP_N}")
        diff_lines = _sku_mom_top_lines_by_diff(sub_cur, sub_prev, top_n=REPORT_TOP_N)
        lines.extend(["  " + x for x in diff_lines])
        lines.append("")
        lines.append(":white_check_mark: 전월 대비 출고량 증가 SKU")
        lines.extend(_spike_sku_lines(sub_cur, sub_prev, top_n=REPORT_TOP_N))
        lines.append("")
        lines.append(":spiral_calendar_pad: 차월 간략 일정(대량 출고 중심)")
        if next_df is None or next_df.empty:
            lines.append(f"- {title} 차월 데이터 없음")
            lines.append("")
            return lines
        sub_next = next_df[next_df[COL_CUST1].astype(str).str.strip() == cust1_value].copy()
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
    ["① 출고 캘린더", "② SKU별 조회", "③ 주차요약", "④ 월간요약", "⑤ 국가별 조회", "⑥ BP명별 조회", "⑦ 트렌드 분석"],
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
    st.subheader("출고 캘린더 (월별)")
    render_month_calendar(cal_pool, ym)
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
        base_sku = raw.copy()
        if st.session_state["f_cust1"] != "전체":
            base_sku = base_sku[base_sku[COL_CUST1].astype(str).str.strip() == st.session_state["f_cust1"]]
        if st.session_state["f_cust2"] != "전체":
            base_sku = base_sku[base_sku[COL_CUST2].astype(str).str.strip() == st.session_state["f_cust2"]]
        if st.session_state["f_bp"] != "전체":
            base_sku = base_sku[base_sku[COL_BP].astype(str).str.strip() == st.session_state["f_bp"]]
        d_sku = base_sku.copy()
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
    row_cnt = len(sku_df)

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
            <div class="kpi-title">RAW 데이터 행수</div>
            <div class="kpi-value">{row_cnt:,}건</div>
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
# =========================
elif nav == "③ 주차요약":
    st.subheader("주차요약")
    d = df_view.copy()
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
# =========================
elif nav == "④ 월간요약":
    st.subheader("월간요약")
    d = df_view.copy()
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
    sel_month = st.selectbox("월 선택", month_list, index=len(month_list) - 1, key="m_sel_month")
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
            fig_m = px.bar(
                m_chart_data, x="_ship_ym", y="요청수량", color=COL_CUST1,
                barmode="stack",
                title="월별 출고수량 추이 (해외B2B / 국내B2B)",
                labels={"_ship_ym": "월", "요청수량": "요청수량", COL_CUST1: "구분"},
                color_discrete_map={"해외B2B": "#3b82f6", "국내B2B": "#10b981"},
            )
            fig_m.update_layout(
                height=360, margin=dict(l=0, r=0, t=40, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
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
        st.caption("아래 텍스트를 그대로 복사해서 내부 공유에 사용하세요.")
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
# =========================
# ⑦ 트렌드 분석
# =========================
elif nav == "⑦ 트렌드 분석":
    st.subheader("트렌드 분석")
    st.caption("※ 트렌드 분석은 월 필터를 무시하고 전체 기간 기준으로 표시됩니다. (거래처구분1/2, BP 필터는 반영)")

    # 트렌드용 베이스: 월 필터 제외, 나머지 필터 적용
    trend_base = raw.copy()
    if st.session_state["f_cust1"] != "전체":
        trend_base = trend_base[trend_base[COL_CUST1].astype(str).str.strip() == st.session_state["f_cust1"]]
    if st.session_state["f_cust2"] != "전체":
        trend_base = trend_base[trend_base[COL_CUST2].astype(str).str.strip() == st.session_state["f_cust2"]]
    if st.session_state["f_bp"] != "전체":
        trend_base = trend_base[trend_base[COL_BP].astype(str).str.strip() == st.session_state["f_bp"]]

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
        fig1 = px.bar(
            s1_data, x="_ship_ym", y="요청수량", color=COL_CUST1,
            barmode="stack",
            title="월별 출고수량 추이 (해외B2B / 국내B2B)",
            labels={"_ship_ym": "월", "요청수량": "요청수량", COL_CUST1: "구분"},
            color_discrete_map={"해외B2B": COLOR_OVERSEAS, "국내B2B": COLOR_DOMESTIC},
        )
        fig1.update_layout(
            height=400, margin=dict(l=0, r=0, t=40, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
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
            sub2 = trend_base[trend_base[COL_CUST1].astype(str).str.strip() == _cust1_2].copy()
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
            fig2 = px.line(
                s2_data, x="_ship_ym", y="요청수량", color=COL_BP,
                title=f"{_cust1_2} Top{TREND_TOP_N} BP 월별 요청수량 추이",
                labels={"_ship_ym": "월", "요청수량": "요청수량", COL_BP: "BP명"},
                markers=True,
            )
            fig2.update_layout(
                height=440, margin=dict(l=0, r=0, t=40, b=0),
                legend=dict(orientation="v", x=1.01, y=1),
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
        sub3_o = trend_base[trend_base[COL_CUST1].astype(str).str.strip() == "해외B2B"].copy()
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
                fig3_o = px.bar(
                    s3_o, x="_ship_ym", y="요청수량", color="__country",
                    barmode="stack",
                    title=f"해외B2B Top{TREND_TOP_N} SKU 월별 추이 (국가 구분)",
                    labels={"_ship_ym": "월", "요청수량": "요청수량", "__country": "국가"},
                    color_discrete_map=COUNTRY_COLORS,
                    custom_data=["SKU"],
                )
                fig3_o.update_traces(
                    hovertemplate="<b>%{customdata[0]}</b><br>월: %{x}<br>요청수량: %{y:,}<extra></extra>"
                )
                fig3_o.update_layout(height=440, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig3_o, use_container_width=True)
                if st.checkbox(f"해외B2B SKU별 라인 추이 보기", key="chk_sku_line_ovs"):
                    fig3_o2 = px.line(
                        s3_o, x="_ship_ym", y="요청수량", color="SKU",
                        title=f"해외B2B Top{TREND_TOP_N} SKU 라인 추이",
                        labels={"_ship_ym": "월", "요청수량": "요청수량"},
                        markers=True,
                    )
                    fig3_o2.update_layout(height=420, margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(fig3_o2, use_container_width=True)

    with tab_s3_dom:
        sub3_d = trend_base[trend_base[COL_CUST1].astype(str).str.strip() == "국내B2B"].copy()
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
                fig3_d = px.bar(
                    s3_d, x="_ship_ym", y="요청수량", color="SKU",
                    barmode="stack",
                    title=f"국내B2B Top{TREND_TOP_N} SKU 월별 추이",
                    labels={"_ship_ym": "월", "요청수량": "요청수량"},
                )
                fig3_d.update_layout(height=440, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig3_d, use_container_width=True)
                if st.checkbox("국내B2B SKU별 라인 추이 보기", key="chk_sku_line_dom"):
                    fig3_d2 = px.line(
                        s3_d, x="_ship_ym", y="요청수량", color="SKU",
                        title=f"국내B2B Top{TREND_TOP_N} SKU 라인 추이",
                        labels={"_ship_ym": "월", "요청수량": "요청수량"},
                        markers=True,
                    )
                    fig3_d2.update_layout(height=420, margin=dict(l=0, r=0, t=40, b=0))
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
            sub4 = trend_base[trend_base[COL_CUST1].astype(str).str.strip() == _cust1_4].copy()
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
            fig4 = px.line(
                s4_data, x="_ship_ym", y="비율(%)", color=COL_BP,
                title=f"{_cust1_4} Top3 BP 집중도 변화 (%)",
                labels={"_ship_ym": "월", "비율(%)": "비율(%)", COL_BP: "BP명"},
                markers=True,
            )
            fig4.update_layout(
                height=380, margin=dict(l=0, r=0, t=40, b=0),
                yaxis=dict(ticksuffix="%", range=[0, 105]),
            )
            st.plotly_chart(fig4, use_container_width=True)
            st.caption(f"※ Top3 BP: {' / '.join(top3_bps)}")

st.caption("※ 모든 집계는 Google Sheet RAW 기반이며, 제품분류(B0/B1) 고정 + 선택한 필터 범위 내에서 계산됩니다.")

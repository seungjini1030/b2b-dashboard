# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반)
# - ✅ ⑤ SKU별 조회 확장:
#   1) (왼쪽 필터 범위 기준) SKU Top10 (요청수량 기준) + BP명(요청수량)
#      - 월=전체 : 누적 Top10
#      - 월=특정 : 해당 월 Top10
#   2) SKU 단건 조회(검색) + 전체 히스토리 보기 토글 + 요청수량 합산(미니 KPI)
# - ✅ 요청수량/집계값 천단위 콤마 표시
# - ✅ 새로고침 시 메인(①)로 리셋
# ==========================================

import re
import streamlit as st
import pandas as pd
import html
from datetime import date

# =========================
# 컬럼명 표준화 (RAW 기준)
# =========================
COL_QTY = "요청수량"
COL_YEAR = "년"
COL_MONTH = "월1"
COL_WEEK_LABEL = "주차"
COL_DONE = "작업완료"
COL_SHIP = "출고일자"          # ✅ SKU조회에서 '출고예정일'로 표시(공백=미정)
COL_LT2 = "리드타임2"
COL_BP = "BP명"
COL_MAIN = "대표행"
COL_CUST1 = "거래처구분1"
COL_CUST2 = "거래처구분2"
COL_CLASS = "제품분류"
COL_ITEM_CODE = "품목코드"
COL_ITEM_NAME = "품목명"
COL_ORDER_DATE = "발주일자"

KEEP_CLASSES = ["B0", "B1"]
LT_ONLY_CUST1 = "해외B2B"
SPIKE_FACTOR = 1.3  # 전주/전월 대비 +30%

# =========================
# Google Sheet 설정
# =========================
GSHEET_ID = "1jbWMgV3fudWCQ1qhG0lCysZGGFCo4loTIf-j3iuaqOI"
GSHEET_GID = "15468212"
HEADER_ROW_0BASED = 6

# =========================
# Streamlit 설정
# =========================
st.set_page_config(page_title="B2B 출고 대시보드 (Google Sheet 기반)", layout="wide")

# -------------------------
# UI Style
# -------------------------
BASE_CSS = """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2.5rem;}
h1, h2, h3 {letter-spacing: -0.2px;}
.small-note {color:#6b7280; font-size: 0.9rem;}

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

/* ✅ SKU 화면용 미니 KPI (회색 박스) */
.mini-kpi-wrap{display:flex; gap:0.6rem; flex-wrap:wrap; margin:0.55rem 0 0.25rem 0;}
.mini-kpi{
  background:#f9fafb;
  border:1px solid #e5e7eb;
  border-radius:12px;
  padding:0.55rem 0.7rem;
  display:flex;
  align-items:baseline;
  gap:0.55rem;
}
.mini-kpi .t{color:#6b7280; font-size:0.9rem;}
.mini-kpi .v{color:#111827; font-size:1.05rem; font-weight:800; font-variant-numeric: tabular-nums;}

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
  color: #111827;
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
hr {margin: 1.2rem 0;}
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)

# -------------------------
# Utils
# -------------------------
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
    if col not in df.columns:
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

def _escape(x) -> str:
    if pd.isna(x):
        return ""
    return html.escape(str(x))

def _fmt_num_for_table(v) -> str:
    """숫자면 천단위 콤마(필요 시 소수 2자리), 아니면 문자열"""
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
    wrap_cols: list[str] | None = None,
    col_width_px: dict[str, int] | None = None,
    number_cols: list[str] | None = None,
):
    wrap_cols = wrap_cols or []
    col_width_px = col_width_px or {}
    number_cols = number_cols or []

    if df is None or df.empty:
        st.info("표시할 데이터가 없습니다.")
        return

    cols = list(df.columns)

    colgroup = "<colgroup>"
    for c in cols:
        w = col_width_px.get(c)
        colgroup += f'<col style="width:{int(w)}px;">' if w else "<col>"
    colgroup += "</colgroup>"

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
                v_disp = _fmt_num_for_table(v)  # ✅ 콤마 포맷
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

def render_mini_kpi(label: str, value: str):
    st.markdown(
        f"""
        <div class="mini-kpi-wrap">
          <div class="mini-kpi">
            <div class="t">{html.escape(label)}</div>
            <div class="v">{html.escape(value)}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

# -------------------------
# Label helpers (RAW 기반)
# -------------------------
def make_month_label(year: int, month: int) -> str:
    return f"{int(year)}년 {int(month)}월"

def build_week_label_from_raw_row(row: pd.Series) -> str | None:
    if COL_WEEK_LABEL not in row or pd.isna(row[COL_WEEK_LABEL]):
        return None

    wk_raw = str(row[COL_WEEK_LABEL]).strip()
    if wk_raw == "" or wk_raw.lower() == "nan":
        return None

    if re.search(r"\d{4}\s*년", wk_raw) and ("주차" in wk_raw) and ("월" in wk_raw):
        return wk_raw.replace("  ", " ").strip()

    m_w = re.search(r"(\d+)\s*주차", wk_raw)
    if not m_w:
        return None
    wk_num = int(m_w.group(1))

    m_m = re.search(r"(\d+)\s*월", wk_raw)
    if m_m:
        month_num = int(m_m.group(1))
    else:
        if COL_MONTH not in row or pd.isna(row[COL_MONTH]):
            return None
        month_num = int(pd.to_numeric(row[COL_MONTH], errors="coerce"))

    if COL_YEAR not in row or pd.isna(row[COL_YEAR]):
        return None
    year_num = int(pd.to_numeric(row[COL_YEAR], errors="coerce"))

    if year_num <= 0 or month_num <= 0 or wk_num <= 0:
        return None

    return f"{year_num}년 {month_num}월 {wk_num}주차"

def parse_week_label_key(label: str) -> tuple[int, int, int]:
    y = m = w = 0
    try:
        my = re.search(r"(\d{4})\s*년", label)
        mm = re.search(r"(\d+)\s*월", label)
        mw = re.search(r"(\d+)\s*주차", label)
        if my: y = int(my.group(1))
        if mm: m = int(mm.group(1))
        if mw: w = int(mw.group(1))
    except Exception:
        pass
    return (y, m, w)

def parse_month_label_key(label: str) -> tuple[int, int]:
    y = m = 0
    try:
        my = re.search(r"(\d{4})\s*년", label)
        mm = re.search(r"(\d+)\s*월", label)
        if my: y = int(my.group(1))
        if mm: m = int(mm.group(1))
    except Exception:
        pass
    return (y, m)

# -------------------------
# BP list helpers
# -------------------------
def build_bp_list_map(df_period: pd.DataFrame) -> pd.DataFrame:
    """(품목코드,품목명)별로 BP명(요청수량) 문자열 생성"""
    if df_period.empty:
        return pd.DataFrame(columns=[COL_ITEM_CODE, COL_ITEM_NAME, "BP명(요청수량)"])

    bp_break = (
        df_period.groupby([COL_ITEM_CODE, COL_ITEM_NAME, COL_BP], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .rename(columns={COL_QTY: "BP요청수량"})
    )

    def format_bp_list(sub: pd.DataFrame) -> str:
        sub = sub.sort_values("BP요청수량", ascending=False, na_position="last")
        out = []
        for _, r in sub.iterrows():
            bp = str(r.get(COL_BP, "")).strip()
            q = r.get("BP요청수량", 0)
            if pd.isna(q):
                q = 0
            out.append(f"{bp}({int(round(q, 0)):,})")
        return ", ".join(out)

    return (
        bp_break.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)
        .apply(format_bp_list)
        .reset_index(name="BP명(요청수량)")
    )

def build_item_top5_with_bp(df_period: pd.DataFrame) -> pd.DataFrame:
    if df_period.empty:
        return pd.DataFrame(columns=["순위", COL_ITEM_CODE, COL_ITEM_NAME, "요청수량_합", "BP명(요청수량)"])

    top5 = (
        df_period.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .rename(columns={COL_QTY: "요청수량_합"})
        .sort_values("요청수량_합", ascending=False, na_position="last")
        .head(5)
        .copy()
    )

    bp_map = build_bp_list_map(df_period)
    top5 = top5.merge(bp_map, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="left")
    top5.insert(0, "순위", range(1, len(top5) + 1))
    top5["요청수량_합"] = top5["요청수량_합"].fillna(0).round(0).astype(int)
    top5["BP명(요청수량)"] = top5["BP명(요청수량)"].fillna("")
    return top5[["순위", COL_ITEM_CODE, COL_ITEM_NAME, "요청수량_합", "BP명(요청수량)"]]

def build_item_top10_with_bp(df_period: pd.DataFrame) -> pd.DataFrame:
    """✅ SKU Top10(요청수량 기준) + BP명(요청수량)"""
    if df_period.empty:
        return pd.DataFrame(columns=["순위", COL_ITEM_CODE, COL_ITEM_NAME, "요청수량_합", "BP명(요청수량)"])

    top10 = (
        df_period.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .rename(columns={COL_QTY: "요청수량_합"})
        .sort_values("요청수량_합", ascending=False, na_position="last")
        .head(10)
        .copy()
    )

    bp_map = build_bp_list_map(df_period)
    top10 = top10.merge(bp_map, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="left")
    top10.insert(0, "순위", range(1, len(top10) + 1))
    top10["요청수량_합"] = top10["요청수량_합"].fillna(0).round(0).astype(int)
    top10["BP명(요청수량)"] = top10["BP명(요청수량)"].fillna("")
    return top10[["순위", COL_ITEM_CODE, COL_ITEM_NAME, "요청수량_합", "BP명(요청수량)"]]

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
    cmp["이전_요청수량"] = cmp["이전_요청수량"].fillna(0)

    cmp["증가배수"] = cmp.apply(
        lambda r: (r["현재_요청수량"] / r["이전_요청수량"]) if r["이전_요청수량"] > 0 else None,
        axis=1
    )

    spike = cmp[(cmp["이전_요청수량"] > 0) & (cmp["현재_요청수량"] >= cmp["이전_요청수량"] * SPIKE_FACTOR)].copy()

    bp_map = build_bp_list_map(cur_df)
    spike = spike.merge(bp_map, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="left")

    spike = spike.sort_values("현재_요청수량", ascending=False, na_position="last")
    spike["현재_요청수량"] = spike["현재_요청수량"].fillna(0).round(0).astype(int)
    spike["이전_요청수량"] = spike["이전_요청수량"].fillna(0).round(0).astype(int)
    spike["증가배수"] = spike["증가배수"].round(2)
    spike["BP명(요청수량)"] = spike["BP명(요청수량)"].fillna("")
    return spike[cols]

# -------------------------
# Load RAW from Google Sheet (CSV export)
# -------------------------
@st.cache_data(ttl=300)
def load_raw_from_gsheet() -> pd.DataFrame:
    csv_url = f"https://docs.google.com/spreadsheets/d/{GSHEET_ID}/export?format=csv&gid={GSHEET_GID}"
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

    normalize_text_cols(
        df,
        [COL_BP, COL_ITEM_CODE, COL_ITEM_NAME, COL_CUST1, COL_CUST2, COL_WEEK_LABEL, COL_CLASS, COL_MAIN]
    )

    if COL_MAIN in df.columns:
        df["_is_rep"] = to_bool_true(df[COL_MAIN])
    else:
        df["_is_rep"] = False

    if COL_WEEK_LABEL in df.columns and df[COL_WEEK_LABEL].astype(str).str.strip().replace("nan", "").ne("").any():
        df["_week_label"] = df.apply(build_week_label_from_raw_row, axis=1)
    else:
        def make_week_label_from_shipdate(ship_date: pd.Timestamp) -> str | None:
            if pd.isna(ship_date):
                return None
            y = int(ship_date.year)
            m = int(ship_date.month)
            d = int(ship_date.day)
            wk = (d - 1) // 7 + 1
            return f"{y}년 {m}월 {wk}주차"
        df["_week_label"] = df[COL_SHIP].apply(make_week_label_from_shipdate) if COL_SHIP in df.columns else None

    if (COL_YEAR in df.columns) and (COL_MONTH in df.columns):
        y = pd.to_numeric(df[COL_YEAR], errors="coerce")
        m = pd.to_numeric(df[COL_MONTH], errors="coerce")
        df["_month_label"] = [
            make_month_label(yy, mm) if pd.notna(yy) and pd.notna(mm) else None
            for yy, mm in zip(y, m)
        ]
    else:
        df["_month_label"] = None

    return df

# -------------------------
# Main
# -------------------------
st.title("📦 B2B 출고 대시보드")
st.caption("Google Sheet RAW 기반 | 제품분류 B0/B1 고정 | 필터(거래처구분1/2/월/BP) 반영")

# ✅ 새로고침: 캐시 + 메뉴/화면 상태 리셋
if st.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    reset_keys = [
        "nav_menu", "wk_sel_week", "m_sel_month",
        "sku_query", "sku_candidate_pick", "sku_show_all_history",
        "f_cust1", "f_cust2", "f_month", "f_bp"
    ]
    for k in reset_keys:
        if k in st.session_state:
            del st.session_state[k]
    st.session_state["nav_menu"] = "① 주차 Top10"
    st.rerun()

try:
    raw = load_raw_from_gsheet().copy()
except Exception as e:
    st.error("Google Sheet에서 RAW 데이터를 불러오지 못했습니다.")
    st.code(str(e))
    st.stop()

# 제품분류 B0/B1 고정
if COL_CLASS in raw.columns:
    raw = raw[raw[COL_CLASS].astype(str).str.strip().isin(KEEP_CLASSES)].copy()
else:
    st.warning(f"'{COL_CLASS}' 컬럼이 없어 제품분류(B0/B1) 고정 필터를 적용할 수 없습니다.")

# =========================
# Sidebar filters (cascading)
# =========================
st.sidebar.header("필터")
st.sidebar.caption("제품분류 고정: B0, B1")

cust1_list = uniq_sorted(raw, COL_CUST1)
sel_cust1 = st.sidebar.selectbox("거래처구분1", ["전체"] + cust1_list, index=0, key="f_cust1")

pool1 = raw.copy()
if sel_cust1 != "전체" and COL_CUST1 in pool1.columns:
    pool1 = pool1[pool1[COL_CUST1].astype(str).str.strip() == sel_cust1]

cust2_list = uniq_sorted(pool1, COL_CUST2)
sel_cust2 = st.sidebar.selectbox("거래처구분2", ["전체"] + cust2_list, index=0, key="f_cust2")

pool2 = pool1.copy()
if sel_cust2 != "전체" and COL_CUST2 in pool2.columns:
    pool2 = pool2[pool2[COL_CUST2].astype(str).str.strip() == sel_cust2]

# ✅ 월 필터: "년+월"
month_labels = []
if "_month_label" in pool2.columns:
    month_labels = [x for x in pool2["_month_label"].dropna().astype(str).unique().tolist() if x.strip() != ""]
    month_labels = list(dict.fromkeys(month_labels))
    month_labels = sorted(month_labels, key=parse_month_label_key)

sel_month_label = st.sidebar.selectbox("월", ["전체"] + month_labels, index=0, key="f_month")

pool3 = pool2.copy()
if sel_month_label != "전체":
    if "_month_label" in pool3.columns:
        pool3 = pool3[pool3["_month_label"].astype(str) == str(sel_month_label)]

bp_list = uniq_sorted(pool3, COL_BP)
sel_bp = st.sidebar.selectbox("BP명", ["전체"] + bp_list, index=0, key="f_bp")

df_view = pool3.copy()
if sel_bp != "전체" and COL_BP in df_view.columns:
    df_view = df_view[df_view[COL_BP].astype(str).str.strip() == sel_bp]

df_rep = df_view[df_view["_is_rep"]].copy()

# =========================
# KPI cards
# =========================
total_qty = df_view[COL_QTY].fillna(0).sum() if COL_QTY in df_view.columns else None
total_cnt = int(df_rep.shape[0])
latest_done = df_view[COL_DONE].max() if COL_DONE in df_view.columns else None

avg_lt2_overseas = None
if all(c in df_view.columns for c in [COL_CUST1, COL_LT2]):
    overseas = df_view[df_view[COL_CUST1].astype(str).str.strip() == LT_ONLY_CUST1]
    if not overseas.empty and not overseas[COL_LT2].dropna().empty:
        avg_lt2_overseas = float(overseas[COL_LT2].dropna().mean())

top_bp_qty_name = "-"
top_bp_qty_val = "-"
if all(c in df_view.columns for c in [COL_BP, COL_QTY]) and not df_view.empty:
    g = df_view.groupby(COL_BP, dropna=False)[COL_QTY].sum().sort_values(ascending=False)
    if not g.empty:
        top_bp_qty_name = str(g.index[0])
        top_bp_qty_val = f"{float(g.iloc[0]):,.0f}"

top_bp_cnt_name = "-"
top_bp_cnt_val = "-"
if COL_BP in df_rep.columns and not df_rep.empty:
    g2 = df_rep.groupby(COL_BP).size().sort_values(ascending=False)
    if not g2.empty:
        top_bp_cnt_name = str(g2.index[0])
        top_bp_cnt_val = f"{int(g2.iloc[0]):,}"

st.markdown(
    f"""
    <div class="kpi-wrap">
      <div class="kpi-card">
        <div class="kpi-title">총 출고수량(합)</div>
        <div class="kpi-value">{(f"{total_qty:,.0f}" if total_qty is not None else "-")}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">총 출고건수(합)</div>
        <div class="kpi-value">{total_cnt:,}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">최근 작업완료일</div>
        <div class="kpi-value">{fmt_date(latest_done)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">리드타임2 평균 (해외B2B)</div>
        <div class="kpi-value">{(f"{avg_lt2_overseas:.1f}일" if avg_lt2_overseas is not None else "-")}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">출고수량 TOP BP</div>
        <div class="kpi-big">{html.escape(top_bp_qty_val)}</div>
        <div class="kpi-muted">{html.escape(top_bp_qty_name)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">출고건수 TOP BP</div>
        <div class="kpi-big">{html.escape(top_bp_cnt_val)}</div>
        <div class="kpi-muted">{html.escape(top_bp_cnt_name)}</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True
)
st.caption("※ 리드타임2 지표는 해외B2B(거래처구분1=해외B2B)만을 대상으로 계산됩니다.")
st.divider()

# =========================
# Navigation
# =========================
nav = st.radio(
    "메뉴",
    ["① 주차 Top10", "② 월 Top10", "③ 국가별 조회", "④ BP명별 조회", "⑤ SKU별 조회"],
    horizontal=True,
    key="nav_menu"
)

# =========================
# ① 주차 Top10
# =========================
if nav == "① 주차 Top10":
    st.subheader("주차 선택 → Top 10 (BP/품목코드/품목명/요청수량)")

    d = df_view.copy()
    if not need_cols(d, [COL_QTY, COL_BP, COL_ITEM_CODE, COL_ITEM_NAME], "주차 Top10"):
        st.stop()

    week_list = [x for x in d["_week_label"].dropna().astype(str).unique().tolist() if x.strip() != ""]
    week_list = sorted(week_list, key=parse_week_label_key)

    if not week_list:
        st.info("주차 목록이 없습니다. (RAW의 '주차' 값이 비어있거나 컬럼이 없는지 확인)")
        st.stop()

    sel_week = st.selectbox("주차 선택", week_list, index=len(week_list) - 1, key="wk_sel_week")
    wdf = d[d["_week_label"].astype(str) == str(sel_week)].copy()

    top10 = (
        wdf.groupby([COL_BP, COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .sort_values(COL_QTY, ascending=False, na_position="last")
        .head(10)
        .copy()
    )
    top10.insert(0, "순위", range(1, len(top10) + 1))
    top10[COL_QTY] = top10[COL_QTY].fillna(0).round(0).astype(int)

    render_pretty_table(
        top10,
        height=420,
        wrap_cols=[COL_BP, COL_ITEM_NAME],
        col_width_px={"순위": 60, COL_BP: 240, COL_ITEM_CODE: 120, COL_ITEM_NAME: 360, COL_QTY: 120},
        number_cols=[COL_QTY],
    )
    st.caption("※ Top10은 선택 주차 내 ‘요청수량 합’ 기준으로 가장 많이 출고된 (BP+품목) 10개입니다.")

    st.divider()

    st.subheader("주차 선택 → 품목 Top 5 (품목 기준) + BP명(복수)")
    top5_item = build_item_top5_with_bp(wdf)

    render_pretty_table(
        top5_item,
        height=360,
        wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"],
        col_width_px={"순위": 60, COL_ITEM_CODE: 130, COL_ITEM_NAME: 360, "요청수량_합": 120, "BP명(요청수량)": 520},
        number_cols=["요청수량_합"],
    )
    st.caption("※ 품목 Top5는 선택 주차 내 ‘품목 기준 요청수량 합’ TOP5이며, BP명은 해당 품목에 포함된 BP를 (BP별 수량)과 함께 나열합니다.")

    st.divider()

    st.subheader("전주 대비 급증 SKU 리포트 (+30% 이상 증가)")
    cur_idx = week_list.index(sel_week) if sel_week in week_list else None
    if cur_idx is None or cur_idx == 0:
        st.info("전주 비교를 위해서는 선택 주차 이전의 주차 데이터가 필요합니다.")
    else:
        prev_week = week_list[cur_idx - 1]
        prev_wdf = d[d["_week_label"].astype(str) == str(prev_week)].copy()

        spike_df = build_spike_report_only(wdf, prev_wdf)

        st.caption(
            f"※ 비교 기준: 선택 주차({sel_week}) vs 전주({prev_week}) | "
            f"급증 정의: 현재 요청수량 ≥ 전주 요청수량 × {SPIKE_FACTOR} (전주 대비 +30% 이상 증가)"
        )

        render_pretty_table(
            spike_df,
            height=520,
            wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"],
            col_width_px={
                COL_ITEM_CODE: 130, COL_ITEM_NAME: 360,
                "이전_요청수량": 120, "현재_요청수량": 120,
                "증가배수": 90, "BP명(요청수량)": 520
            },
            number_cols=["이전_요청수량", "현재_요청수량", "증가배수"],
        )

# =========================
# ② 월 Top10
# =========================
elif nav == "② 월 Top10":
    st.subheader("월 선택 → Top 10 (BP/품목코드/품목명/요청수량)")

    d = df_view.copy()
    if not need_cols(d, [COL_QTY, COL_BP, COL_ITEM_CODE, COL_ITEM_NAME], "월 Top10"):
        st.stop()

    month_list = [x for x in d["_month_label"].dropna().astype(str).unique().tolist() if x.strip() != ""]
    month_list = list(dict.fromkeys(month_list))
    month_list = sorted(month_list, key=parse_month_label_key)

    if not month_list:
        st.info("월 목록이 없습니다. RAW의 '년', '월1' 컬럼을 확인해 주세요.")
        st.stop()

    sel_month_label2 = st.selectbox("월 선택", month_list, index=len(month_list) - 1, key="m_sel_month")
    mdf = d[d["_month_label"].astype(str) == str(sel_month_label2)].copy()

    top10 = (
        mdf.groupby([COL_BP, COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .sort_values(COL_QTY, ascending=False, na_position="last")
        .head(10)
        .copy()
    )
    top10.insert(0, "순위", range(1, len(top10) + 1))
    top10[COL_QTY] = top10[COL_QTY].fillna(0).round(0).astype(int)

    render_pretty_table(
        top10,
        height=420,
        wrap_cols=[COL_BP, COL_ITEM_NAME],
        col_width_px={"순위": 60, COL_BP: 240, COL_ITEM_CODE: 120, COL_ITEM_NAME: 360, COL_QTY: 120},
        number_cols=[COL_QTY],
    )
    st.caption("※ Top10은 선택 월 내에서 ‘요청수량 합’ 기준으로 가장 많이 출고된 (BP+품목) 10개입니다.")

    st.divider()

    st.subheader("월 선택 → 품목 Top 5 (품목 기준) + BP명(복수)")
    top5_item = build_item_top5_with_bp(mdf)

    render_pretty_table(
        top5_item,
        height=360,
        wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"],
        col_width_px={"순위": 60, COL_ITEM_CODE: 130, COL_ITEM_NAME: 360, "요청수량_합": 120, "BP명(요청수량)": 520},
        number_cols=["요청수량_합"],
    )
    st.caption("※ 품목 Top5는 선택 월 내 ‘품목 기준 요청수량 합’ TOP5이며, BP명은 해당 품목에 포함된 BP를 (BP별 수량)과 함께 나열합니다.")

    st.divider()

    st.subheader("전월 대비 급증 SKU 리포트 (+30% 이상 증가)")
    cur_idx = month_list.index(sel_month_label2) if sel_month_label2 in month_list else None
    if cur_idx is None or cur_idx == 0:
        st.info("전월 비교를 위해서는 선택 월 이전의 월 데이터가 필요합니다.")
    else:
        prev_month_label = month_list[cur_idx - 1]
        prev_mdf = d[d["_month_label"].astype(str) == str(prev_month_label)].copy()

        spike_df = build_spike_report_only(mdf, prev_mdf)

        st.caption(
            f"※ 비교 기준: 선택 월({sel_month_label2}) vs 전월({prev_month_label}) | "
            f"급증 정의: 현재 요청수량 ≥ 전월 요청수량 × {SPIKE_FACTOR} (전월 대비 +30% 이상 증가)"
        )

        render_pretty_table(
            spike_df,
            height=520,
            wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"],
            col_width_px={
                COL_ITEM_CODE: 130, COL_ITEM_NAME: 360,
                "이전_요청수량": 120, "현재_요청수량": 120,
                "증가배수": 90, "BP명(요청수량)": 520
            },
            number_cols=["이전_요청수량", "현재_요청수량", "증가배수"],
        )

# =========================
# ③ 국가별 조회 (국가 KPI)
# =========================
elif nav == "③ 국가별 조회":
    st.subheader("국가별 조회 (거래처구분2 기준)")

    if not need_cols(df_view, [COL_CUST2, COL_QTY, COL_LT2], "국가별 조회"):
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

    rep_cnt = base[base["_is_rep"]].groupby(COL_CUST2).size()
    out["출고건수"] = out[COL_CUST2].astype(str).map(rep_cnt).fillna(0).astype(int)

    out = out[
        [COL_CUST2, "요청수량_합", "평균_리드타임_작업완료기준", "리드타임_중간값_작업완료기준",
         "리드타임 느린 상위10% 기준(P90)", "출고건수", "집계행수_표본"]
    ]

    for c in ["평균_리드타임_작업완료기준", "리드타임_중간값_작업완료기준", "리드타임 느린 상위10% 기준(P90)"]:
        out[c] = out[c].round(2)

    out = out.sort_values("요청수량_합", ascending=False, na_position="last")

    render_pretty_table(
        out,
        height=520,
        wrap_cols=[COL_CUST2],
        col_width_px={COL_CUST2: 200, "요청수량_합": 120, "출고건수": 90, "집계행수_표본": 110},
        number_cols=["요청수량_합", "출고건수", "집계행수_표본"],
    )
    st.caption("※ P90은 ‘느린 상위 10%’ 경계값(리드타임이 큰 구간)입니다.")

# =========================
# ④ BP명별 조회 (BP KPI)
# =========================
elif nav == "④ BP명별 조회":
    st.subheader("BP명별 조회")

    if not need_cols(df_view, [COL_BP, COL_QTY, COL_LT2], "BP명별 조회"):
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

    rep_cnt = base[base["_is_rep"]].groupby(COL_BP).size()
    out["출고건수"] = out[COL_BP].astype(str).map(rep_cnt).fillna(0).astype(int)

    out["최근_출고일"] = out["최근_출고일"].apply(fmt_date)
    out["최근_작업완료일"] = out["최근_작업완료일"].apply(fmt_date)

    for c in ["평균_리드타임_작업완료기준", "리드타임_중간값_작업완료기준"]:
        out[c] = out[c].round(2)

    out = out[
        [COL_BP, "요청수량_합", "평균_리드타임_작업완료기준", "리드타임_중간값_작업완료기준",
         "최근_출고일", "최근_작업완료일", "출고건수", "집계행수_표본"]
    ].sort_values("요청수량_합", ascending=False, na_position="last")

    render_pretty_table(
        out,
        height=520,
        wrap_cols=[COL_BP],
        col_width_px={COL_BP: 280, "요청수량_합": 120, "출고건수": 90, "집계행수_표본": 110},
        number_cols=["요청수량_합", "출고건수", "집계행수_표본"],
    )

# =========================
# ⑤ SKU별 조회
# =========================
elif nav == "⑤ SKU별 조회":
    st.subheader("SKU별 조회")

    if not need_cols(df_view, [COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY, COL_SHIP, COL_BP], "SKU별 조회"):
        st.stop()

    # -------------------------------------------------
    # ✅ (왼쪽 필터 범위 기준) SKU Top10 + BP Breakdown
    #   - 월=전체: 누적 Top10
    #   - 월=특정: 해당 월 Top10 (df_view가 이미 월로 필터됨)
    # -------------------------------------------------
    period_title = "누적 SKU Top10 (요청수량 기준)" if sel_month_label == "전체" else f"{sel_month_label} SKU Top10 (요청수량 기준)"
    st.subheader(period_title)

    top10_sku = build_item_top10_with_bp(df_view.copy())
    render_pretty_table(
        top10_sku,
        height=420,
        wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"],
        col_width_px={"순위": 60, COL_ITEM_CODE: 130, COL_ITEM_NAME: 360, "요청수량_합": 120, "BP명(요청수량)": 520},
        number_cols=["요청수량_합"],
    )
    st.caption("※ BP명(요청수량)은 해당 SKU의 출고처별 수량 합계입니다. (왼쪽 필터 범위 기준)")

    st.divider()

    # -------------------------------------------------
    # ✅ 단건 SKU 검색/조회
    # -------------------------------------------------
    show_all_history = st.checkbox("전체 히스토리 보기", value=True, key="sku_show_all_history")

    base = df_view.copy()
    base[COL_ITEM_CODE] = base[COL_ITEM_CODE].astype(str).str.strip()
    base[COL_ITEM_NAME] = base[COL_ITEM_NAME].astype(str).str.strip()

    q = st.text_input(
        "품목코드 검색 (부분검색 가능)",
        value="",
        placeholder="예: B5SN005A1",
        key="sku_query"
    )

    if not q.strip():
        st.info("상단에 품목코드를 입력하면, 해당 SKU의 출고일자/BP명/요청수량이 표시됩니다.")
        st.stop()

    q_norm = q.strip().upper()

    candidates = (
        base[base[COL_ITEM_CODE].str.upper().str.contains(re.escape(q_norm), na=False)][[COL_ITEM_CODE, COL_ITEM_NAME]]
        .dropna(subset=[COL_ITEM_CODE])
        .drop_duplicates(subset=[COL_ITEM_CODE])
        .sort_values(COL_ITEM_CODE)
        .reset_index(drop=True)
    )

    if candidates.empty:
        st.warning("해당 품목코드가 현재 필터 범위에서 조회되지 않습니다.")
        st.stop()

    if len(candidates) > 1:
        cand_map = dict(zip(candidates[COL_ITEM_CODE], candidates[COL_ITEM_NAME]))
        sel_code = st.selectbox(
            "검색 결과에서 선택",
            candidates[COL_ITEM_CODE].tolist(),
            key="sku_candidate_pick",
            format_func=lambda x: f"{x} / {cand_map.get(x, '')}".strip()
        )
    else:
        sel_code = candidates.iloc[0][COL_ITEM_CODE]

    d = base[base[COL_ITEM_CODE] == sel_code].copy()

    item_name = "-"
    nn = d[COL_ITEM_NAME].dropna()
    if not nn.empty:
        item_name = str(nn.iloc[0]).strip()

    st.markdown(f"- **품목코드:** {html.escape(sel_code)}")
    st.markdown(f"- **품목명:** {html.escape(item_name)}")

    d[COL_SHIP] = d[COL_SHIP].replace("", pd.NA)

    # ✅ OFF 로직은 "왼쪽 월 필터가 전체일 때만" 적용
    month_filter_is_all = (sel_month_label == "전체")
    if (not show_all_history) and month_filter_is_all:
        today_ts = pd.Timestamp(date.today())
        ship_dt = pd.to_datetime(d[COL_SHIP], errors="coerce")
        d = d[(ship_dt.isna()) | (ship_dt >= today_ts)].copy()

    def ship_to_label(x):
        if pd.isna(x):
            return "미정"
        return fmt_date(x)

    d["출고예정일"] = d[COL_SHIP].apply(ship_to_label)

    out = (
        d.groupby(["출고예정일", COL_BP], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .rename(columns={COL_BP: "BP명", COL_QTY: "요청수량"})
    )
    out["요청수량"] = out["요청수량"].fillna(0).round(0).astype(int)

    # ✅ 요청수량 합산(현재 화면에 표시되는 결과 기준)
    total_sku_qty = int(out["요청수량"].fillna(0).sum()) if not out.empty else 0
    render_mini_kpi("요청수량 합산", f"{total_sku_qty:,}")

    out["_sort_date"] = pd.to_datetime(out["출고예정일"], errors="coerce")
    out = out.sort_values(
        by=["_sort_date", "출고예정일", "요청수량"],
        ascending=[True, True, False],
        na_position="last"
    ).drop(columns=["_sort_date"])

    render_pretty_table(
        out[["출고예정일", "BP명", "요청수량"]],
        height=520,
        wrap_cols=["BP명"],
        col_width_px={"출고예정일": 140, "BP명": 420, "요청수량": 120},
        number_cols=["요청수량"],   # ✅ 콤마 표시
    )

# =========================
# Footer
# =========================
st.caption(
    "※ 모든 집계는 Google Sheet RAW 기반이며, 제품분류(B0/B1) 고정 + 선택한 필터(거래처구분1/2/월/BP) 범위 내에서 계산됩니다."
)

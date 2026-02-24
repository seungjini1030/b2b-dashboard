# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반)
# - ✅ 메뉴 순서: ① 출고캘린더 -> ② SKU별 조회 -> ③ 주차요약 -> ④ 월간요약 -> ⑤ 국가별 조회 -> ⑥ BP명별 조회
# - ✅ 출고캘린더
#    * 캘린더 안 네모박스에 BP명 리스트 표시 + 클릭 시 상세페이지로 전환
#    * 해외/국내 구분은 상단 "활성화 버튼(필터)"로만 (범례/동그라미 제거)
#    * "+N건" 클릭 시 그날 전체 펼치기 + "접기"
# ==========================================

import re
import html
import calendar as pycal
from datetime import date
import pandas as pd
import streamlit as st

# =========================
# 컬럼명 표준화 (RAW 기준)
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

CATEGORY_COL_CANDIDATES = [
    "카테고리 라인", "카테고리라인", "카테고리", "카테고리(Line)", "카테고리_LINE", "Category Line", "Category"
]

KEEP_CLASSES = ["B0", "B1"]
LT_ONLY_CUST1 = "해외B2B"
SPIKE_FACTOR = 1.3  # +30%

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
.wrap {white-space: normal; word-break: break-word; line-height:1.25rem;}
.mono {font-variant-numeric: tabular-nums;}
hr {margin: 1.2rem 0;}

/* ✅ 코멘트 UI */
.comment-block { margin: 0.6rem 0 1.05rem 0; }
.comment-title{
  font-weight: 900;
  font-size: 1.06rem;
  margin: 0.2rem 0 0.25rem 0;
}
.comment{
  margin: 0.08rem 0 0 0;
  line-height: 1.55;
}

/* ✅ Calendar */
.cal-wrap{
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  overflow: hidden;
  background:#fff;
}
.cal-head{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap: 0.75rem;
  padding: 0.85rem 0.95rem;
  border-bottom: 1px solid #eef2f7;
  background:#fff;
}
.cal-title{
  font-size: 1.1rem;
  font-weight: 900;
  color:#111827;
}
.cal-grid{
  padding: 0.8rem 0.8rem 0.9rem 0.8rem;
}
.cal-dow{
  display:grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
  margin-bottom: 8px;
}
.cal-dow div{
  color:#6b7280;
  font-size:0.85rem;
  font-weight:700;
  padding: 0 6px;
}
.cal-weeks{
  display:grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
}
.cal-day{
  border: 1px solid #eef2f7;
  border-radius: 12px;
  min-height: 120px;
  padding: 8px 8px 10px 8px;
  background:#fff;
}
.cal-day.muted{
  background:#fafafa;
  color:#9ca3af;
}
.cal-date{
  display:flex;
  align-items:center;
  justify-content:space-between;
  margin-bottom:6px;
  font-weight:800;
  color:#111827;
}
.cal-events{
  display:flex;
  flex-direction:column;
  gap:6px;
}

/* ✅ 상단 해외/국내 활성화 버튼(필터) */
.filter-row{
  display:flex;
  gap:10px;
  align-items:center;
  margin: 6px 0 2px 0;
}
.badge{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  padding:6px 10px;
  border-radius: 999px;
  border:1px solid #e5e7eb;
  background:#fff;
  font-weight:800;
  font-size:0.9rem;
  color:#111827;
}
.badge.on.over{ border-color:#c4b5fd; background:#f5f3ff; }  /* purple-ish */
.badge.on.dom{ border-color:#93c5fd; background:#eff6ff; }   /* blue-ish */
.badge.off{ color:#6b7280; background:#f9fafb; }
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
# Label helpers
# -------------------------
def make_month_label(year: int, month: int) -> str:
    return f"{int(year)}년 {int(month)}월"

def parse_week_label_key(label: str) -> tuple[int, int, int]:
    y = m = w = 0
    try:
        my = re.search(r"(\d{4})\s*년", str(label))
        mm = re.search(r"(\d+)\s*월", str(label))
        mw = re.search(r"(\d+)\s*주차", str(label))
        if my: y = int(my.group(1))
        if mm: m = int(mm.group(1))
        if mw: w = int(mw.group(1))
    except Exception:
        pass
    return (y, m, w)

def parse_month_label_key(label: str) -> tuple[int, int]:
    y = m = 0
    try:
        my = re.search(r"(\d{4})\s*년", str(label))
        mm = re.search(r"(\d+)\s*월", str(label))
        if my: y = int(my.group(1))
        if mm: m = int(mm.group(1))
    except Exception:
        pass
    return (y, m)

def week_label_from_date(dt: pd.Timestamp) -> str | None:
    if pd.isna(dt):
        return None
    y = int(dt.year)
    m = int(dt.month)
    d = int(dt.day)
    wk = (d - 1) // 7 + 1
    return f"{y}년 {m}월 {wk}주차"

def build_week_label_from_row_safe(row: pd.Series) -> str | None:
    ship_dt = row.get(COL_SHIP, pd.NaT)
    done_dt = row.get(COL_DONE, pd.NaT)
    base_dt = ship_dt if pd.notna(ship_dt) else done_dt
    if pd.notna(base_dt):
        return week_label_from_date(pd.to_datetime(base_dt, errors="coerce"))
    return None

def week_key_num_from_label(label: str) -> int | None:
    y, m, w = parse_week_label_key(label)
    if y <= 0 or m <= 0 or w <= 0:
        return None
    return y * 10000 + m * 100 + w

def month_key_num_from_label(label: str) -> int | None:
    y, m = parse_month_label_key(label)
    if y <= 0 or m <= 0:
        return None
    return y * 100 + m

# -------------------------
# Load RAW
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
        [COL_BP, COL_ITEM_CODE, COL_ITEM_NAME, COL_CUST1, COL_CUST2, COL_WEEK_LABEL, COL_CLASS, COL_MAIN, COL_ORDER_NO]
    )

    df["_is_rep"] = to_bool_true(df[COL_MAIN]) if COL_MAIN in df.columns else False
    df["_week_label"] = df.apply(build_week_label_from_row_safe, axis=1)

    if (COL_YEAR in df.columns) and (COL_MONTH in df.columns):
        y = pd.to_numeric(df[COL_YEAR], errors="coerce")
        m = pd.to_numeric(df[COL_MONTH], errors="coerce")
        df["_month_label"] = [
            make_month_label(yy, mm) if pd.notna(yy) and pd.notna(mm) else None
            for yy, mm in zip(y, m)
        ]
    else:
        df["_month_label"] = None

    df["_week_key_num"] = df["_week_label"].apply(lambda x: week_key_num_from_label(x) if pd.notna(x) else None)
    df["_month_key_num"] = df["_month_label"].apply(lambda x: month_key_num_from_label(x) if pd.notna(x) else None)

    return df

# =========================
# ✅ Calendar helpers
# =========================
def _ym_add(year: int, month: int, delta: int) -> tuple[int, int]:
    y = int(year)
    m = int(month) + int(delta)
    while m <= 0:
        y -= 1
        m += 12
    while m >= 13:
        y += 1
        m -= 12
    return y, m

def build_calendar_base(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    if not need_cols(df, [COL_BP, COL_QTY, COL_CUST1, COL_ITEM_CODE, COL_ITEM_NAME], "출고캘린더"):
        return pd.DataFrame()

    tmp = df.copy()
    ship_dt = pd.to_datetime(tmp[COL_SHIP], errors="coerce") if COL_SHIP in tmp.columns else pd.Series([pd.NaT] * len(tmp))
    done_dt = pd.to_datetime(tmp[COL_DONE], errors="coerce") if COL_DONE in tmp.columns else pd.Series([pd.NaT] * len(tmp))

    tmp["_cal_date"] = ship_dt
    tmp.loc[tmp["_cal_date"].isna(), "_cal_date"] = done_dt[tmp["_cal_date"].isna()]

    tmp["_cal_date"] = pd.to_datetime(tmp["_cal_date"], errors="coerce").dt.date
    tmp = tmp[tmp["_cal_date"].notna()].copy()

    tmp[COL_QTY] = pd.to_numeric(tmp[COL_QTY], errors="coerce").fillna(0)
    tmp[COL_CUST1] = tmp[COL_CUST1].astype(str).str.strip()
    tmp[COL_BP] = tmp[COL_BP].astype(str).str.strip()
    return tmp

def cal_day_bp_summary(cal_df: pd.DataFrame, day: date) -> pd.DataFrame:
    sub = cal_df[cal_df["_cal_date"] == day].copy()
    if sub.empty:
        return pd.DataFrame(columns=[COL_CUST1, COL_BP, "qty_sum"])
    g = (
        sub.groupby([COL_CUST1, COL_BP], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .rename(columns={COL_QTY: "qty_sum"})
        .sort_values(["qty_sum"], ascending=False)
    )
    return g

def set_cal_detail(day: date, cust1: str, bp: str):
    st.session_state["cal_page"] = "detail"
    st.session_state["cal_sel_day"] = str(day)
    st.session_state["cal_sel_cust1"] = str(cust1)
    st.session_state["cal_sel_bp"] = str(bp)
    st.rerun()

def cal_detail_df(cal_df: pd.DataFrame, day: date, cust1: str, bp: str) -> pd.DataFrame:
    sub = cal_df[
        (cal_df["_cal_date"] == day) &
        (cal_df[COL_CUST1].astype(str).str.strip() == str(cust1).strip()) &
        (cal_df[COL_BP].astype(str).str.strip() == str(bp).strip())
    ].copy()
    return sub

def _cal_day_key(day: date) -> str:
    return day.strftime("%Y-%m-%d")

def _toggle_cal_day_expand(day: date):
    k = "cal_expanded_days"
    if k not in st.session_state:
        st.session_state[k] = {}
    key = _cal_day_key(day)
    st.session_state[k][key] = (not bool(st.session_state[k].get(key, False)))
    st.rerun()

def _is_cal_day_expanded(day: date) -> bool:
    k = "cal_expanded_days"
    if k not in st.session_state:
        return False
    return bool(st.session_state[k].get(_cal_day_key(day), False))

# =========================
# Main
# =========================
st.title("📦 B2B 출고 대시보드")
st.caption("Google Sheet RAW 기반 | 제품분류 B0/B1 고정 | 필터(거래처구분1/2/월/BP) 반영")

# ✅ 새로고침: 기본 메뉴를 '① 출고캘린더'로
if st.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    reset_keys = [
        "nav_menu",
        "wk_sel_week", "m_sel_month",
        "sku_query", "sku_candidate_pick", "sku_show_all_history",
        "f_cust1", "f_cust2", "f_month", "f_bp",
        "sku_ignore_month_filter",
        "cal_page", "cal_year", "cal_month", "cal_sel_day", "cal_sel_cust1", "cal_sel_bp",
        "cal_expanded_days",
        "cal_filter_over", "cal_filter_dom",
    ]
    for k in reset_keys:
        if k in st.session_state:
            del st.session_state[k]
    st.session_state["nav_menu"] = "① 출고캘린더"
    st.rerun()

try:
    raw = load_raw_from_gsheet().copy()
except Exception as e:
    st.error("Google Sheet에서 RAW 데이터를 불러오지 못했습니다.")
    st.code(str(e))
    st.stop()

if COL_CLASS in raw.columns:
    raw = raw[raw[COL_CLASS].astype(str).str.strip().isin(KEEP_CLASSES)].copy()
else:
    st.warning(f"'{COL_CLASS}' 컬럼이 없어 제품분류(B0/B1) 고정 필터를 적용할 수 없습니다.")

# =========================
# Sidebar filters
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

month_labels = []
if "_month_label" in pool2.columns:
    month_labels = [x for x in pool2["_month_label"].dropna().astype(str).unique().tolist() if x.strip() != ""]
    month_labels = list(dict.fromkeys(month_labels))
    month_labels = sorted(month_labels, key=parse_month_label_key)

sel_month_label = st.sidebar.selectbox("월", ["전체"] + month_labels, index=0, key="f_month")

pool3 = pool2.copy()
if sel_month_label != "전체":
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
        <div class="kpi-title">리드타임 평균 (해외B2B)</div>
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
st.caption("※ 리드타임 지표는 해외B2B(거래처구분1=해외B2B)만을 대상으로 계산됩니다.")
st.divider()

# =========================
# Navigation (✅ 캘린더가 ①)
# =========================
nav = st.radio(
    "메뉴",
    ["① 출고캘린더", "② SKU별 조회", "③ 주차요약", "④ 월간요약", "⑤ 국가별 조회", "⑥ BP명별 조회"],
    horizontal=True,
    key="nav_menu"
)

# =========================
# ① 출고캘린더
# =========================
if nav == "① 출고캘린더":
    st.subheader("출고캘린더")

    # 캘린더는 거래처구분1/2만 반영: pool2 사용
    cal_scope = pool2.copy()
    cal_df = build_calendar_base(cal_scope)
    if cal_df.empty:
        st.info("캘린더로 표시할 데이터가 없습니다. (출고일자/작업완료일이 있는 행이 필요)")
        st.stop()

    max_day = pd.to_datetime(cal_df["_cal_date"]).max()
    if "cal_year" not in st.session_state or "cal_month" not in st.session_state:
        st.session_state["cal_year"] = int(max_day.year) if pd.notna(max_day) else int(date.today().year)
        st.session_state["cal_month"] = int(max_day.month) if pd.notna(max_day) else int(date.today().month)

    if "cal_page" not in st.session_state:
        st.session_state["cal_page"] = "calendar"

    if "cal_expanded_days" not in st.session_state:
        st.session_state["cal_expanded_days"] = {}

    # ✅ 해외/국내 활성화 필터 (버튼 토글)
    if "cal_filter_over" not in st.session_state:
        st.session_state["cal_filter_over"] = True
    if "cal_filter_dom" not in st.session_state:
        st.session_state["cal_filter_dom"] = True

    f1, f2, _sp = st.columns([1, 1, 8])
    with f1:
        if st.button("해외B2B", key="btn_toggle_over"):
            st.session_state["cal_filter_over"] = not st.session_state["cal_filter_over"]
            st.rerun()
        over_on = st.session_state["cal_filter_over"]
        st.markdown(
            f'<div class="badge {"on over" if over_on else "off"}">해외B2B {"ON" if over_on else "OFF"}</div>',
            unsafe_allow_html=True
        )
    with f2:
        if st.button("국내B2B", key="btn_toggle_dom"):
            st.session_state["cal_filter_dom"] = not st.session_state["cal_filter_dom"]
            st.rerun()
        dom_on = st.session_state["cal_filter_dom"]
        st.markdown(
            f'<div class="badge {"on dom" if dom_on else "off"}">국내B2B {"ON" if dom_on else "OFF"}</div>',
            unsafe_allow_html=True
        )

    # 필터 적용
    allowed = []
    if st.session_state["cal_filter_over"]:
        allowed.append("해외B2B")
    if st.session_state["cal_filter_dom"]:
        allowed.append("국내B2B")
    if allowed:
        cal_df2 = cal_df[cal_df[COL_CUST1].isin(allowed)].copy()
    else:
        cal_df2 = cal_df.iloc[0:0].copy()  # 아무것도 선택 안되면 빈 데이터

    st.caption("※ 캘린더는 좌측 필터 중 ‘거래처구분1/2’만 반영합니다. (월/BP 필터는 캘린더 내부 월 이동을 위해 적용하지 않음)")
    st.divider()

    # -------------------------
    # Detail page
    # -------------------------
    if st.session_state.get("cal_page") == "detail":
        try:
            sel_day = pd.to_datetime(st.session_state.get("cal_sel_day")).date()
        except Exception:
            sel_day = None
        sel_cust1 = st.session_state.get("cal_sel_cust1", "")
        sel_bp2 = st.session_state.get("cal_sel_bp", "")

        c_top = st.columns([1, 7, 2])
        with c_top[0]:
            if st.button("← 돌아가기", key="btn_cal_back"):
                st.session_state["cal_page"] = "calendar"
                st.rerun()
        with c_top[1]:
            st.markdown(f"### {fmt_date(sel_day)} · {html.escape(str(sel_bp2))}")
            st.caption(f"구분: {html.escape(str(sel_cust1))}")

        if sel_day is None:
            st.warning("선택된 날짜가 올바르지 않습니다.")
            st.stop()

        detail = cal_detail_df(cal_df2, sel_day, sel_cust1, sel_bp2)
        if detail.empty:
            st.info("상세 내역이 없습니다. (해외/국내 필터 상태를 확인해 주세요)")
            st.stop()

        ship_dt = pd.to_datetime(detail[COL_SHIP], errors="coerce") if COL_SHIP in detail.columns else pd.Series([pd.NaT])
        done_dt = pd.to_datetime(detail[COL_DONE], errors="coerce") if COL_DONE in detail.columns else pd.Series([pd.NaT])
        ship_min = ship_dt.min() if ship_dt.notna().any() else pd.NaT
        done_max = done_dt.max() if done_dt.notna().any() else pd.NaT
        qty_sum = int(round(detail[COL_QTY].fillna(0).sum(), 0))

        k1, k2, k3 = st.columns(3)
        k1.metric("출고일자", fmt_date(ship_min))
        k2.metric("작업완료", fmt_date(done_max))
        k3.metric("요청수량합", f"{qty_sum:,}")

        st.divider()

        item = (
            detail.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
            .sum(min_count=1)
            .reset_index()
            .rename(columns={COL_QTY: "요청수량"})
            .sort_values("요청수량", ascending=False, na_position="last")
        )
        item["요청수량"] = pd.to_numeric(item["요청수량"], errors="coerce").fillna(0).round(0).astype(int)

        render_pretty_table(
            item[[COL_ITEM_CODE, COL_ITEM_NAME, "요청수량"]],
            height=520,
            wrap_cols=[COL_ITEM_NAME],
            col_width_px={COL_ITEM_CODE: 140, COL_ITEM_NAME: 520, "요청수량": 120},
            number_cols=["요청수량"],
        )
        st.caption("※ 상세는 선택한 날짜/구분(해외B2B/국내B2B)/BP 기준으로 집계됩니다.")

    # -------------------------
    # Calendar page
    # -------------------------
    else:
        year = int(st.session_state["cal_year"])
        month = int(st.session_state["cal_month"])

        left, mid, right = st.columns([1.2, 4.8, 1.2])
        with left:
            if st.button("◀", key="cal_prev"):
                ny, nm = _ym_add(year, month, -1)
                st.session_state["cal_year"], st.session_state["cal_month"] = ny, nm
                st.rerun()
        with mid:
            st.markdown(
                f"""
                <div class="cal-wrap">
                  <div class="cal-head">
                    <div class="cal-title">{year}년 {month}월</div>
                  </div>
                """,
                unsafe_allow_html=True
            )
        with right:
            if st.button("▶", key="cal_next"):
                ny, nm = _ym_add(year, month, +1)
                st.session_state["cal_year"], st.session_state["cal_month"] = ny, nm
                st.rerun()

        st.divider()

        first_weekday, days_in_month = pycal.monthrange(year, month)  # Monday=0
        blanks_before = first_weekday
        total_cells = blanks_before + days_in_month
        blanks_after = (7 - (total_cells % 7)) % 7
        total = total_cells + blanks_after

        st.markdown(
            """
            <div class="cal-grid">
              <div class="cal-dow">
                <div>월</div><div>화</div><div>수</div><div>목</div><div>금</div><div>토</div><div>일</div>
              </div>
            """,
            unsafe_allow_html=True
        )

        for idx in range(0, total, 7):
            cols = st.columns(7)
            for j in range(7):
                cell = idx + j
                with cols[j]:
                    day_num = cell - blanks_before + 1
                    in_month = (1 <= day_num <= days_in_month)

                    if not in_month:
                        st.markdown('<div class="cal-day muted"><div class="cal-date"><span>-</span></div></div>', unsafe_allow_html=True)
                        continue

                    cur_day = date(year, month, day_num)
                    day_key = _cal_day_key(cur_day)
                    expanded = _is_cal_day_expanded(cur_day)

                    st.markdown(
                        f"""
                        <div class="cal-day">
                          <div class="cal-date">
                            <span>{day_num}</span>
                          </div>
                          <div class="cal-events">
                        """,
                        unsafe_allow_html=True
                    )

                    summary = cal_day_bp_summary(cal_df2, cur_day)
                    if summary.empty:
                        st.markdown("</div></div>", unsafe_allow_html=True)
                        continue

                    max_show = 4
                    show = summary.copy() if expanded else summary.head(max_show).copy()

                    # ✅ 셀 안에 BP명 "그대로" 들어가게: 버튼 라벨 = BP명 (표식 제거)
                    # 클릭 시 상세 페이지로 전환
                    for r_i, r in show.iterrows():
                        cust1 = str(r.get(COL_CUST1, "")).strip()
                        bp = str(r.get(COL_BP, "")).strip()

                        # 버튼 텍스트는 BP명만
                        if st.button(bp, key=f"calbtn_{day_key}_{cust1}_{bp}_{r_i}"):
                            set_cal_detail(cur_day, cust1, bp)

                    # ✅ +N건 / 접기
                    if (not expanded) and (len(summary) > max_show):
                        if st.button(f"+{len(summary) - max_show}건", key=f"calmore_{day_key}"):
                            _toggle_cal_day_expand(cur_day)
                    elif expanded and (len(summary) > max_show):
                        if st.button("접기", key=f"calfold_{day_key}"):
                            _toggle_cal_day_expand(cur_day)

                    st.markdown("</div></div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

# =========================
# 이하 ②~⑥ 기존 기능(원래 코드 유지) — 이 아래는 너가 주신 최신본 그대로 붙여도 돼.
# 지금 메시지 길이 때문에 "캘린더 수정에 영향 없는 기존 ②~⑥ 전체"까지 완전 동일하게 재출력하면 너무 길어져서,
# 네가 직전에 쓰던 코드에서 nav 이름만 바꿔주고 if nav == "...": 분기명만 새로 맞춰주면 동작해.
# =========================

st.caption("※ 모든 집계는 Google Sheet RAW 기반이며, 제품분류(B0/B1) 고정 + 선택한 필터 범위 내에서 계산됩니다.")

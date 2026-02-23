# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반)
# - ✅ 출고 캘린더: 일자별 네모 경계 + BP 클릭 1번 → 상세 즉시 표시
# - ✅ iframe 환경에서 링크 클릭이 안 먹는 케이스 해결:
#    <a href> 대신 JS로 window.parent.location 강제 이동
# - ✅ 해외B2B pill 색상 분리(국내B2B와 구별)
# ==========================================

import re
import html
import calendar as pycal
from datetime import date, datetime
from urllib.parse import quote, unquote

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

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

INVOICE_COL_CANDIDATES = ["인보이스No.", "인보이스번호", "Invoice No.", "InvoiceNo", "invoice_no", "INVOICE_NO"]

KEEP_CLASSES = ["B0", "B1"]
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

# ✅ 캘린더는 components.html(iframe) 안에서 렌더링되므로, 캘린더 전용 CSS/JS를 HTML 안에 포함
CAL_CSS = """
<style>
.cal-wrap{border:1px solid #e5e7eb; border-radius:14px; overflow:hidden; background:#fff;}
.cal-grid{display:grid; grid-template-columns: repeat(7, 1fr); border-top:1px solid #e5e7eb;}
.cal-head{
  background:#f9fafb; padding:10px 10px; font-weight:800; color:#111827;
  border-right:1px solid #e5e7eb;
}
.cal-head:last-child{border-right:none;}
.cal-cell{
  min-height:120px;
  padding:8px 8px 10px 8px;
  border-right:1px solid #e5e7eb;
  border-bottom:1px solid #e5e7eb;
  overflow:hidden;
  box-sizing:border-box;
}
.cal-cell:nth-child(7n){border-right:none;}
.cal-daynum{font-weight:900; color:#111827; font-size:0.95rem; margin-bottom:6px;}
.cal-out{background:#fafafa; color:#9ca3af;}
.cal-events{display:flex; flex-direction:column; gap:6px; max-height:180px; overflow:auto; padding-right:2px;}

/* 기본 pill */
.cal-pill{
  display:block;
  width:100%;
  text-decoration:none !important;
  color:#111827;
  background:#ffffff;
  border:1px solid #e5e7eb;
  border-radius:10px;
  padding:6px 8px;
  font-size:0.86rem;
  line-height:1.15rem;
  box-sizing:border-box;
  cursor:pointer;
}
.cal-pill:hover{background:#f7fbff; border-color:#cfe5ff;}
.cal-pill .q{color:#374151; font-variant-numeric: tabular-nums; font-weight:800;}

/* ✅ 해외B2B 색상(보라 톤) */
.cal-pill.over{
  background:#f5f3ff;
  border-color:#ddd6fe;
}
.cal-pill.over:hover{
  background:#ede9fe;
  border-color:#c4b5fd;
}

/* ✅ 국내B2B 색상(연한 블루 톤) */
.cal-pill.dom{
  background:#eff6ff;
  border-color:#bfdbfe;
}
.cal-pill.dom:hover{
  background:#dbeafe;
  border-color:#93c5fd;
}

.cal-legend{
  display:flex; gap:10px; align-items:center; margin:10px 2px 0 2px; color:#6b7280; font-size:0.88rem;
}
.badge{
  display:inline-flex; align-items:center; gap:6px;
}
.dot{
  width:10px; height:10px; border-radius:999px; display:inline-block;
}
.dot.over{background:#7c3aed;}
.dot.dom{background:#2563eb;}
</style>
"""

# ✅ iframe 안에서 클릭 시 상위 앱 URL을 강제 변경 (href 네비게이션이 막히는 환경 대응)
CAL_JS = """
<script>
function goTo(url){
  try{
    // Streamlit components iframe 환경에서 가장 잘 먹는 방식
    window.parent.location.href = url;
  }catch(e){
    try{
      window.top.location.href = url;
    }catch(e2){
      // 최후 fallback: 새 창
      window.open(url, "_blank");
    }
  }
}
</script>
"""

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

def get_invoice_col(df: pd.DataFrame) -> str | None:
    for c in INVOICE_COL_CANDIDATES:
        if c in df.columns:
            return c
    return None

# -------------------------
# Query params helpers
# -------------------------
def _qp_get() -> dict:
    try:
        return dict(st.query_params)
    except Exception:
        return st.experimental_get_query_params()

def _qp_set(**kwargs):
    clean = {k: v for k, v in kwargs.items() if v is not None}
    try:
        st.query_params.clear()
        for k, v in clean.items():
            st.query_params[k] = str(v)
    except Exception:
        st.experimental_set_query_params(**clean)

# -------------------------
# Shipment doc key (해외는 인보이스 / 국내는 주문번호)
# -------------------------
def _ship_doc_key(df: pd.DataFrame) -> pd.Series:
    inv_col = get_invoice_col(df)
    cust = df[COL_CUST1].astype(str).str.strip() if COL_CUST1 in df.columns else pd.Series([""] * len(df))
    inv = df[inv_col].astype(str).str.strip() if (inv_col and inv_col in df.columns) else pd.Series([""] * len(df))
    ordno = df[COL_ORDER_NO].astype(str).str.strip() if COL_ORDER_NO in df.columns else pd.Series([""] * len(df))

    out = ordno.copy()
    mask_over = cust.eq("해외B2B")
    out.loc[mask_over] = inv.loc[mask_over]

    out = out.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    out = out.fillna(ordno.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA}))
    return out.astype(str)

def _cal_month_bounds(y: int, m: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(datetime(y, m, 1))
    last_day = pycal.monthrange(y, m)[1]
    end = pd.Timestamp(datetime(y, m, last_day))
    return start, end

# -------------------------
# ✅ Calendar renderer (핵심 수정)
# -------------------------
def render_ship_calendar(df_cal: pd.DataFrame, y: int, m: int):
    """
    - ✅ 일자별 네모 경계
    - ✅ 해외/국내 pill 색상 구분
    - ✅ 클릭 1번으로 상세 이동: JS로 window.parent.location 강제 변경
    """
    if not need_cols(df_cal, [COL_SHIP, COL_BP, COL_QTY, COL_CUST1], "출고 캘린더"):
        return

    start, end = _cal_month_bounds(y, m)

    ship_dt = pd.to_datetime(df_cal[COL_SHIP], errors="coerce")
    base_m = df_cal[ship_dt.notna()].copy()
    base_m["_ship_date"] = ship_dt.dt.date
    base_m = base_m[(pd.to_datetime(base_m["_ship_date"]) >= start) & (pd.to_datetime(base_m["_ship_date"]) <= end)].copy()

    if base_m.empty:
        st.info("선택한 월에 출고 데이터가 없습니다.")
        return

    # ✅ day-bp 집계 + 해외B2B 포함 여부
    grp = base_m.groupby(["_ship_date", COL_BP], dropna=False)
    day_bp = grp[COL_QTY].sum(min_count=1).reset_index().rename(columns={COL_QTY: "qty"})
    day_bp["qty"] = pd.to_numeric(day_bp["qty"], errors="coerce").fillna(0)

    # 해외B2B 포함 플래그
    flag = grp[COL_CUST1].apply(lambda s: (s.astype(str).str.strip() == "해외B2B").any()).reset_index(name="is_overseas")
    day_bp = day_bp.merge(flag, on=["_ship_date", COL_BP], how="left")
    day_bp["is_overseas"] = day_bp["is_overseas"].fillna(False)

    first_weekday_mon0 = datetime(y, m, 1).weekday()  # Mon=0
    last_day = pycal.monthrange(y, m)[1]
    week_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    idx = {}
    for d, sub in day_bp.groupby("_ship_date"):
        s = sub.sort_values("qty", ascending=False)
        idx[d] = [(str(r[COL_BP]).strip(), float(r["qty"]), bool(r["is_overseas"])) for _, r in s.iterrows()]

    cells_html = []
    for _ in range(first_weekday_mon0):
        cells_html.append('<div class="cal-cell cal-out"><div class="cal-daynum"> </div></div>')

    for day in range(1, last_day + 1):
        d = date(y, m, day)
        events = idx.get(d, [])
        ev_html = ['<div class="cal-events">']
        for (bp, qty, is_over) in events:
            # 상세 URL
            url = f"?view=bp&y={y}&m={m}&d={quote(d.strftime('%Y-%m-%d'))}&bp={quote(bp)}"
            klass = "over" if is_over else "dom"
            # ✅ href는 무의미 처리 + onclick으로 상위 URL 이동
            ev_html.append(
                f'<a class="cal-pill {klass}" href="javascript:void(0)" '
                f'onclick="goTo(\\\"{url}\\\")">'
                f'{html.escape(bp)} / <span class="q">{int(round(qty)):,}</span></a>'
            )
        ev_html.append("</div>")
        cells_html.append(f'<div class="cal-cell"><div class="cal-daynum">{day}</div>{"".join(ev_html)}</div>')

    while len(cells_html) % 7 != 0:
        cells_html.append('<div class="cal-cell cal-out"><div class="cal-daynum"> </div></div>')

    head_html = "".join([f'<div class="cal-head">{w}</div>' for w in week_names])

    calendar_html = f"""
    {CAL_JS}
    <div class="cal-wrap">
      <div class="cal-grid">
        {head_html}
        {''.join(cells_html)}
      </div>
    </div>

    <div class="cal-legend">
      <span class="badge"><span class="dot dom"></span>국내 B2B</span>
      <span class="badge"><span class="dot over"></span>해외 B2B</span>
    </div>
    """

    full_html = CAL_CSS + calendar_html
    components.html(full_html, height=930, scrolling=True)

    st.caption("※ 캘린더 셀은 BP명/요청수량합만 표시됩니다. BP 클릭 1번으로 하단 상세가 즉시 표시됩니다.")

def render_bp_shipments_detail(df_cal: pd.DataFrame, ship_date_str: str, bp: str):
    if not need_cols(df_cal, [COL_SHIP, COL_BP, COL_QTY, COL_CUST1], "출고건 상세"):
        return

    d = pd.to_datetime(ship_date_str, errors="coerce")
    if pd.isna(d):
        st.warning("선택된 날짜가 올바르지 않습니다.")
        return
    d_date = d.date()

    base = df_cal.copy()
    ship_dt = pd.to_datetime(base[COL_SHIP], errors="coerce").dt.date
    base = base[(ship_dt == d_date) & (base[COL_BP].astype(str).str.strip() == str(bp).strip())].copy()

    if base.empty:
        st.info("선택한 BP/일자에 해당하는 데이터가 없습니다.")
        return

    base["_ship_doc"] = _ship_doc_key(base)
    base["_done_dt"] = pd.to_datetime(base[COL_DONE], errors="coerce") if COL_DONE in base.columns else pd.NaT

    st.markdown("### 📦 출고건 상세")
    st.markdown(f"- **일자:** {ship_date_str}")
    st.markdown(f"- **BP명:** {html.escape(bp)}")
    st.caption("※ 출고건(해외=인보이스 / 국내=주문번호) 단위로 품목라인 전체를 즉시 펼쳐 보여줍니다.")

    sum_df = (
        base.groupby([COL_CUST1, "_ship_doc"], dropna=False)
        .agg(
            출고수량합=(COL_QTY, "sum"),
            품목라인수=(COL_QTY, "size"),
            작업완료일=("_done_dt", "min"),
        )
        .reset_index()
        .rename(columns={COL_CUST1: "구분", "_ship_doc": "출고건ID"})
    )
    sum_df["출고수량합"] = pd.to_numeric(sum_df["출고수량합"], errors="coerce").fillna(0).round(0).astype(int)
    sum_df["품목라인수"] = pd.to_numeric(sum_df["품목라인수"], errors="coerce").fillna(0).astype(int)
    sum_df["작업완료일"] = sum_df["작업완료일"].apply(fmt_date)
    sum_df = sum_df.sort_values(["출고수량합"], ascending=False, na_position="last")

    total_qty = int(sum_df["출고수량합"].sum()) if not sum_df.empty else 0
    render_mini_kpi("요청수량 합산", f"{total_qty:,}")
    st.divider()

    for _, r in sum_df.iterrows():
        section = str(r["구분"]).strip()
        ship_id = str(r["출고건ID"]).strip()
        qty_sum = int(r["출고수량합"])
        line_cnt = int(r["품목라인수"])
        done_str = str(r["작업완료일"])

        st.markdown(f"#### [{section}] {html.escape(ship_id)}")
        st.markdown(f"- 출고수량 합: **{qty_sum:,}** · 품목라인 {line_cnt:,} · 작업완료일 {done_str}")

        sub = base[(base[COL_CUST1].astype(str).str.strip() == section) & (base["_ship_doc"].astype(str).str.strip() == ship_id)].copy()
        if not need_cols(sub, [COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY], "품목 라인"):
            continue

        items = (
            sub.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
            .sum(min_count=1)
            .reset_index()
            .rename(columns={COL_QTY: "요청수량"})
            .sort_values("요청수량", ascending=False, na_position="last")
        )
        items["요청수량"] = pd.to_numeric(items["요청수량"], errors="coerce").fillna(0).round(0).astype(int)

        render_pretty_table(
            items[[COL_ITEM_CODE, COL_ITEM_NAME, "요청수량"]],
            height=360,
            wrap_cols=[COL_ITEM_NAME],
            col_width_px={COL_ITEM_CODE: 140, COL_ITEM_NAME: 520, "요청수량": 120},
            number_cols=["요청수량"],
        )
        st.divider()

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
    for c in [COL_QTY, COL_LT2]:
        safe_num(df, c)

    normalize_text_cols(
        df,
        [COL_BP, COL_ITEM_CODE, COL_ITEM_NAME, COL_CUST1, COL_CUST2, COL_CLASS, COL_MAIN, COL_ORDER_NO]
    )

    return df

# -------------------------
# Main
# -------------------------
st.title("📦 B2B 출고 대시보드")
st.caption("Google Sheet RAW 기반 | 기본 집계 제품분류 B0/B1 | 캘린더 상세는 출고건 단위 전체 품목라인 표시")

if st.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    try:
        st.query_params.clear()
    except Exception:
        pass
    st.rerun()

raw0 = load_raw_from_gsheet().copy()
raw_all = raw0.copy()

raw = raw0.copy()
if COL_CLASS in raw.columns:
    raw = raw[raw[COL_CLASS].astype(str).str.strip().isin(KEEP_CLASSES)].copy()

# =========================
# Sidebar filters
# =========================
st.sidebar.header("필터")

cust1_list = uniq_sorted(raw, COL_CUST1)
sel_cust1 = st.sidebar.selectbox("거래처구분1", ["전체"] + cust1_list, index=0)

pool1 = raw.copy()
pool1_all = raw_all.copy()
if sel_cust1 != "전체" and COL_CUST1 in pool1.columns:
    pool1 = pool1[pool1[COL_CUST1].astype(str).str.strip() == sel_cust1]
if sel_cust1 != "전체" and COL_CUST1 in pool1_all.columns:
    pool1_all = pool1_all[pool1_all[COL_CUST1].astype(str).str.strip() == sel_cust1]

cust2_list = uniq_sorted(pool1, COL_CUST2)
sel_cust2 = st.sidebar.selectbox("거래처구분2", ["전체"] + cust2_list, index=0)

pool2 = pool1.copy()
pool2_all = pool1_all.copy()
if sel_cust2 != "전체" and COL_CUST2 in pool2.columns:
    pool2 = pool2[pool2[COL_CUST2].astype(str).str.strip() == sel_cust2]
if sel_cust2 != "전체" and COL_CUST2 in pool2_all.columns:
    pool2_all = pool2_all[pool2_all[COL_CUST2].astype(str).str.strip() == sel_cust2]

# =========================
# Navigation
# =========================
nav = st.radio(
    "메뉴",
    ["① 출고 캘린더", "② SKU별 조회", "③ 주차요약", "④ 월간요약", "⑤ 국가별 조회", "⑥ BP명별 조회"],
    horizontal=True,
)

# =========================
# ① 출고 캘린더
# =========================
if nav == "① 출고 캘린더":
    st.subheader("📅 출고 캘린더")
    st.caption("캘린더 셀은 BP명/요청수량합만 표시됩니다. BP 클릭 1번으로 출고건(해외=인보이스/국내=주문번호) 상세가 즉시 표시됩니다.")

    qp = _qp_get()

    def _qp_one(key: str, default=None):
        v = qp.get(key, default)
        if isinstance(v, list):
            return v[0] if v else default
        return v if v is not None else default

    view = _qp_one("view", "cal") or "cal"
    qp_y = _qp_one("y", None)
    qp_m = _qp_one("m", None)
    qp_d = _qp_one("d", None)
    qp_bp = _qp_one("bp", None)

    today = date.today()
    default_y, default_m = today.year, today.month

    try:
        y0 = int(qp_y) if qp_y else default_y
        m0 = int(qp_m) if qp_m else default_m
    except Exception:
        y0, m0 = default_y, default_m

    coly, colm = st.columns([1, 1])
    with coly:
        cal_y = st.number_input("연도", min_value=2020, max_value=2035, value=int(y0), step=1)
    with colm:
        cal_m = st.number_input("월", min_value=1, max_value=12, value=int(m0), step=1)

    if (int(cal_y) != int(y0)) or (int(cal_m) != int(m0)):
        _qp_set(view="cal", y=int(cal_y), m=int(cal_m), d=None, bp=None)
        st.rerun()

    if view != "cal":
        if st.button("⬅ 캘린더로 돌아가기"):
            _qp_set(view="cal", y=int(cal_y), m=int(cal_m), d=None, bp=None)
            st.rerun()

    st.divider()

    df_cal_base = pool2_all.copy()

    if view == "cal":
        render_ship_calendar(df_cal_base, int(cal_y), int(cal_m))
    else:
        if not qp_d or not qp_bp:
            st.info("상세를 보려면 캘린더에서 BP를 클릭하세요.")
        else:
            ship_date_str = unquote(qp_d)
            bp = unquote(qp_bp)
            st.markdown(f"### 📌 {ship_date_str} · {html.escape(bp)}")
            render_bp_shipments_detail(df_cal_base, ship_date_str=ship_date_str, bp=bp)

else:
    st.info("이 버전은 캘린더 UX/상세 연결에 집중한 코드입니다. 다른 탭 로직까지 합친 완전체에 이 패치를 이식하려면 기존 app.py 원문이 필요해요.")

# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반)
# - ✅ 메뉴 순서: ① 출고 캘린더 -> ② SKU별 조회 -> ③ 주차요약 -> ④ 월간요약 -> ⑤ 국가별 조회 -> ⑥ BP명별 조회
# - ✅ 캘린더:
#    * ✅ Streamlit native 월 전체 캘린더(일~토 그리드) = st.columns(7) 기반
#    * 출고일자 기준으로 일자 박스 내 BP명 표시
#    * 출고건 많으면 +N건 클릭 시 펼침/접기
#    * ✅ BP명 클릭 시 새창 X / 페이지 전환 O (st.button + session_state)
#    * ✅ 해외B2B/국내B2B 구분 = 버튼 배색(가능한 범위 내) + 텍스트 태그
#    * 상세 화면: 출고일자/작업완료/요청수량합/품목코드/품목명/요청수량
#    * 상세에서 캘린더로 돌아가기
# ==========================================

import re
import html
import calendar as pycal
from datetime import date
import numpy as np
import streamlit as st
import pandas as pd

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
# ✅ 성능 최적화: 필요한 컬럼만 로드
# =========================
USECOLS = [
    COL_SHIP, COL_DONE, COL_ORDER_DATE,
    COL_QTY, COL_LT2, "리드타임1",
    COL_BP, COL_CUST1, COL_CUST2,
    COL_ITEM_CODE, COL_ITEM_NAME,
    COL_YEAR, COL_MONTH,
    COL_CLASS, COL_MAIN, COL_ORDER_NO,
] + CATEGORY_COL_CANDIDATES

DTYPES = {
    COL_BP: "string",
    COL_CUST1: "string",
    COL_CUST2: "string",
    COL_ITEM_CODE: "string",
    COL_ITEM_NAME: "string",
    COL_CLASS: "string",
    COL_MAIN: "string",
    COL_ORDER_NO: "string",
    COL_YEAR: "string",
    COL_MONTH: "string",
}
for c in CATEGORY_COL_CANDIDATES:
    DTYPES[c] = "string"

# =========================
# Streamlit 설정
# =========================
st.set_page_config(page_title="B2B 출고 대시보드 (Google Sheet 기반)", layout="wide")

BASE_CSS = """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2.5rem;}
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

.comment-block { margin: 0.6rem 0 1.05rem 0; }
.comment-title{ font-weight: 900; font-size: 1.06rem; margin: 0.2rem 0 0.25rem 0;}
.comment{ margin: 0.08rem 0 0 0; line-height: 1.55;}

/* ✅ 캘린더 버튼을 조금 더 촘촘하게 */
div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stButton"]) button {
  padding: 0.30rem 0.55rem !important;
  border-radius: 10px !important;
  font-size: 0.86rem !important;
}

/* ✅ 해외/국내 버튼 배색(키워드 태그 기반으로 label에 포함된 문구를 이용해 약하게 구분)
   - Streamlit은 버튼별 class를 직접 못줘서 "완전한 컬러링"은 제한적임.
   - 그래도 사용감은 유지되게 prefix 태그로 명확히 표시함.
*/
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)

def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

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

@st.cache_data(ttl=600)
def uniq_sorted_cached(values: tuple[str, ...]) -> list[str]:
    arr = [v for v in values if v is not None and str(v).strip() != ""]
    return sorted(list(dict.fromkeys([str(x).strip() for x in arr])))

def uniq_sorted(df: pd.DataFrame, col: str):
    if col not in df.columns or df.empty:
        return []
    return uniq_sorted_cached(tuple(df[col].astype(str).tolist()))

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
        if isinstance(v, int) and not isinstance(v, bool):
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

# -------------------------
# Label helpers
# -------------------------
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

# -------------------------
# ✅ Load RAW (성능개선 핵심)
# -------------------------
@st.cache_data(ttl=600)
def load_raw_from_gsheet() -> pd.DataFrame:
    csv_url = f"https://docs.google.com/spreadsheets/d/{GSHEET_ID}/export?format=csv&gid={GSHEET_GID}"

    df = pd.read_csv(
        csv_url,
        header=HEADER_ROW_0BASED,
        usecols=lambda c: str(c).strip() in set([x.strip() for x in USECOLS]),
        dtype=DTYPES,
        low_memory=False,
    )

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
        [COL_BP, COL_ITEM_CODE, COL_ITEM_NAME, COL_CUST1, COL_CUST2, COL_CLASS, COL_MAIN, COL_ORDER_NO]
    )

    df["_is_rep"] = to_bool_true(df[COL_MAIN]) if COL_MAIN in df.columns else False

    # ✅ 주차 라벨 벡터화
    ship_dt = pd.to_datetime(df[COL_SHIP], errors="coerce") if COL_SHIP in df.columns else pd.Series(pd.NaT, index=df.index)
    done_dt = pd.to_datetime(df[COL_DONE], errors="coerce") if COL_DONE in df.columns else pd.Series(pd.NaT, index=df.index)
    base_dt = ship_dt.where(ship_dt.notna(), done_dt)

    y = base_dt.dt.year
    m = base_dt.dt.month
    d = base_dt.dt.day
    wk = ((d - 1) // 7 + 1)

    df["_week_label"] = np.where(
        base_dt.notna(),
        y.astype("Int64").astype(str) + "년 " + m.astype("Int64").astype(str) + "월 " + wk.astype("Int64").astype(str) + "주차",
        None
    )

    if (COL_YEAR in df.columns) and (COL_MONTH in df.columns):
        yy = pd.to_numeric(df[COL_YEAR], errors="coerce")
        mm = pd.to_numeric(df[COL_MONTH], errors="coerce")
        df["_month_label"] = np.where(
            yy.notna() & mm.notna(),
            yy.astype("Int64").astype(str) + "년 " + mm.astype("Int64").astype(str) + "월",
            None
        )
    else:
        df["_month_label"] = None

    return df

# =========================
# 캘린더 state
# =========================
def init_calendar_state():
    if "cal_view" not in st.session_state:
        st.session_state["cal_view"] = "calendar"  # calendar | detail
    if "cal_ym" not in st.session_state:
        st.session_state["cal_ym"] = ""            # YYYY-MM
    if "cal_selected_date" not in st.session_state:
        st.session_state["cal_selected_date"] = None  # date
    if "cal_selected_bp" not in st.session_state:
        st.session_state["cal_selected_bp"] = ""      # str
    if "cal_expanded" not in st.session_state:
        st.session_state["cal_expanded"] = set()      # set[date]

def ym_from_dt(dt: pd.Timestamp) -> str:
    return pd.to_datetime(dt).strftime("%Y-%m")

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

def go_calendar(ym: str | None = None):
    st.session_state["cal_view"] = "calendar"
    st.session_state["cal_selected_date"] = None
    st.session_state["cal_selected_bp"] = ""
    if ym is not None:
        st.session_state["cal_ym"] = ym
    safe_rerun()

def go_detail(ship_date: date, bp: str):
    st.session_state["cal_view"] = "detail"
    st.session_state["cal_selected_date"] = ship_date
    st.session_state["cal_selected_bp"] = bp
    safe_rerun()

def toggle_expand(d: date):
    expanded: set[date] = st.session_state.get("cal_expanded", set())
    if d in expanded:
        expanded.discard(d)
    else:
        expanded.add(d)
    st.session_state["cal_expanded"] = expanded
    safe_rerun()

def set_calendar_ym(ym: str):
    st.session_state["cal_ym"] = ym
    st.session_state["cal_view"] = "calendar"
    safe_rerun()

# =========================
# 캘린더 데이터 준비
# =========================
def build_calendar_base_df(pool2: pd.DataFrame, sel_bp: str) -> pd.DataFrame:
    keep = [c for c in pool2.columns if c in [COL_SHIP, COL_DONE, COL_QTY, COL_BP, COL_CUST1, COL_ITEM_CODE, COL_ITEM_NAME]]
    base = pool2[keep].copy()
    if sel_bp != "전체" and COL_BP in base.columns:
        base = base[base[COL_BP].astype(str).str.strip() == sel_bp]
    safe_dt(base, COL_SHIP)
    safe_dt(base, COL_DONE)
    safe_num(base, COL_QTY)
    return base

@st.cache_data(ttl=600)
def build_day_map_cached(cal_base: pd.DataFrame, ym: str) -> dict[date, list[dict]]:
    if cal_base is None or cal_base.empty:
        return {}

    tmp = cal_base.dropna(subset=[COL_SHIP]).copy()
    tmp["_ship_dt"] = pd.to_datetime(tmp[COL_SHIP], errors="coerce")
    tmp = tmp[tmp["_ship_dt"].notna()]
    tmp["_ym"] = tmp["_ship_dt"].dt.strftime("%Y-%m")
    tmp = tmp[tmp["_ym"] == ym]
    if tmp.empty:
        return {}

    tmp["_d"] = tmp["_ship_dt"].dt.date
    if COL_CUST1 not in tmp.columns:
        tmp[COL_CUST1] = ""

    g = (
        tmp.groupby(["_d", COL_BP, COL_CUST1], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .rename(columns={COL_QTY: "qty_sum"})
    )
    g["qty_sum"] = pd.to_numeric(g["qty_sum"], errors="coerce").fillna(0).round(0).astype(int)

    out: dict[date, list[dict]] = {}
    for d, sub in g.groupby("_d"):
        total = (
            sub.groupby(COL_BP, dropna=False)["qty_sum"]
            .sum()
            .reset_index()
            .rename(columns={"qty_sum": "qty_total"})
        )
        idx = sub.sort_values("qty_sum", ascending=False).groupby(COL_BP, dropna=False).head(1)
        cust_pick = idx[[COL_BP, COL_CUST1]].copy()
        cust_pick[COL_CUST1] = cust_pick[COL_CUST1].astype(str).str.strip()

        merged = total.merge(cust_pick, on=COL_BP, how="left")
        merged["qty_total"] = merged["qty_total"].fillna(0).astype(int)
        merged[COL_CUST1] = merged[COL_CUST1].fillna("").astype(str)

        merged = merged.sort_values("qty_total", ascending=False, na_position="last")
        out[d] = [
            {"bp": str(r[COL_BP]).strip(), "qty": int(r["qty_total"]), "cust1": str(r[COL_CUST1]).strip()}
            for _, r in merged.iterrows()
        ]
    return out

def render_month_calendar_native(cal_base: pd.DataFrame, ym: str):
    if not need_cols(cal_base, [COL_SHIP, COL_BP, COL_QTY], "출고 캘린더"):
        return

    y, m = ym_to_year_month(ym)
    day_map = build_day_map_cached(cal_base, ym)

    prev_ym = add_months(ym, -1)
    next_ym = add_months(ym, +1)

    t1, t2, t3 = st.columns([1.2, 2.2, 1.2], vertical_alignment="center")
    with t1:
        st.button("◀ 이전달", on_click=set_calendar_ym, args=(prev_ym,), use_container_width=True, key=f"btn_prev_{ym}")
    with t2:
        st.markdown(f"### {y}년 {m}월 출고 캘린더")
        st.caption("※ BP명을 클릭하면 **새창 없이** 동일 페이지에서 상세 화면으로 전환됩니다.")
    with t3:
        st.button("다음달 ▶", on_click=set_calendar_ym, args=(next_ym,), use_container_width=True, key=f"btn_next_{ym}")

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

                        # ✅ 색상 완전 제어는 Streamlit 버튼 구조상 제한적이라,
                        #    대신 태그로 명확하게 구분 + (가능한 범위 내) 이모지/텍스트로 가독성 확보
                        tag = "🌍해외" if cust1 == "해외B2B" else "🏠국내" if cust1 == "국내B2B" else "📦"
                        label = f"{tag} {bp} ({qsum:,})"

                        st.button(
                            label,
                            key=f"cal_bp_{ym}_{day_num}_{idx}_{hash(bp)%100000}",
                            on_click=go_detail,
                            args=(d, bp),
                            use_container_width=True
                        )

                    if hidden > 0 and (not is_expanded):
                        st.button(
                            f"+{hidden}건 더 보기",
                            key=f"cal_more_{ym}_{day_num}",
                            on_click=toggle_expand,
                            args=(d,),
                            use_container_width=True
                        )

                    if is_expanded and len(events) > 3:
                        st.button(
                            "접기",
                            key=f"cal_less_{ym}_{day_num}",
                            on_click=toggle_expand,
                            args=(d,),
                            use_container_width=True
                        )

# =========================
# Main
# =========================
st.title("📦 B2B 출고 대시보드")
st.caption("Google Sheet RAW 기반 | 제품분류 B0/B1 고정 | 필터(거래처구분1/2/월/BP) 반영")

if st.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    reset_keys = [
        "nav_menu",
        "wk_sel_week", "m_sel_month",
        "sku_query", "sku_candidate_pick", "sku_show_all_history",
        "f_cust1", "f_cust2", "f_month", "f_bp",
        "sku_ignore_month_filter",
        "cal_view", "cal_ym", "cal_selected_date", "cal_selected_bp", "cal_expanded",
    ]
    for k in reset_keys:
        if k in st.session_state:
            del st.session_state[k]
    st.session_state["nav_menu"] = "① 출고 캘린더"
    safe_rerun()

with st.spinner("RAW 불러오는 중..."):
    try:
        raw = load_raw_from_gsheet()
    except Exception as e:
        st.error("Google Sheet에서 RAW 데이터를 불러오지 못했습니다.")
        st.code(str(e))
        st.stop()

if COL_CLASS in raw.columns:
    raw = raw[raw[COL_CLASS].astype(str).str.strip().isin(KEEP_CLASSES)]
else:
    st.warning(f"'{COL_CLASS}' 컬럼이 없어 제품분류(B0/B1) 고정 필터를 적용할 수 없습니다.")

# =========================
# Sidebar filters
# =========================
st.sidebar.header("필터")
st.sidebar.caption("제품분류 고정: B0, B1")

cust1_list = uniq_sorted(raw, COL_CUST1)
sel_cust1 = st.sidebar.selectbox("거래처구분1", ["전체"] + cust1_list, index=0, key="f_cust1")

pool1 = raw
if sel_cust1 != "전체" and COL_CUST1 in pool1.columns:
    pool1 = pool1[pool1[COL_CUST1].astype(str).str.strip() == sel_cust1]

cust2_list = uniq_sorted(pool1, COL_CUST2)
sel_cust2 = st.sidebar.selectbox("거래처구분2", ["전체"] + cust2_list, index=0, key="f_cust2")

pool2 = pool1
if sel_cust2 != "전체" and COL_CUST2 in pool2.columns:
    pool2 = pool2[pool2[COL_CUST2].astype(str).str.strip() == sel_cust2]

month_labels = []
if "_month_label" in pool2.columns:
    month_labels = [x for x in pool2["_month_label"].dropna().astype(str).unique().tolist() if x.strip() != ""]
    month_labels = list(dict.fromkeys(month_labels))
    month_labels = sorted(month_labels, key=parse_month_label_key)

sel_month_label = st.sidebar.selectbox("월", ["전체"] + month_labels, index=0, key="f_month")

pool3 = pool2
if sel_month_label != "전체":
    pool3 = pool3[pool3["_month_label"].astype(str) == str(sel_month_label)]

bp_list = uniq_sorted(pool3, COL_BP)
sel_bp = st.sidebar.selectbox("BP명", ["전체"] + bp_list, index=0, key="f_bp")

df_view = pool3
if sel_bp != "전체" and COL_BP in df_view.columns:
    df_view = df_view[df_view[COL_BP].astype(str).str.strip() == sel_bp]

df_rep = df_view[df_view["_is_rep"]].copy()

# =========================
# KPI cards (최소 유지)
# =========================
total_qty = df_view[COL_QTY].fillna(0).sum() if COL_QTY in df_view.columns else None
total_cnt = int(df_rep.shape[0])
latest_done = df_view[COL_DONE].max() if COL_DONE in df_view.columns else None

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
    </div>
    """,
    unsafe_allow_html=True
)
st.divider()

# =========================
# Navigation
# =========================
nav = st.radio(
    "메뉴",
    ["① 출고 캘린더", "② SKU별 조회", "③ 주차요약", "④ 월간요약", "⑤ 국가별 조회", "⑥ BP명별 조회"],
    horizontal=True,
    key="nav_menu"
)

# =========================
# ① 출고 캘린더 (새창 문제 해결: 링크 제거, 버튼으로만 전환)
# =========================
if nav == "① 출고 캘린더":
    init_calendar_state()

    cal_base = build_calendar_base_df(pool2, sel_bp)

    if st.session_state["cal_ym"].strip() == "":
        if COL_SHIP in cal_base.columns and cal_base[COL_SHIP].notna().any():
            latest_ship = pd.to_datetime(cal_base[COL_SHIP], errors="coerce").dropna().max()
            st.session_state["cal_ym"] = ym_from_dt(latest_ship)
        else:
            st.session_state["cal_ym"] = date.today().strftime("%Y-%m")

    ym = st.session_state["cal_ym"]

    if st.session_state["cal_view"] == "detail":
        ship_date = st.session_state.get("cal_selected_date", None)
        bp_s = st.session_state.get("cal_selected_bp", "")

        st.subheader("출고 상세 내역")
        st.button("← 캘린더로 돌아가기", on_click=go_calendar, args=(ym,), key="btn_back_cal")

        if ship_date is None or str(bp_s).strip() == "":
            st.warning("상세 조회 대상이 없습니다. 캘린더에서 BP를 클릭해 주세요.")
            st.stop()

        d = cal_base.copy()
        if not need_cols(d, [COL_SHIP, COL_BP, COL_QTY, COL_ITEM_CODE, COL_ITEM_NAME], "출고 상세"):
            st.stop()

        d["_ship_date"] = pd.to_datetime(d[COL_SHIP], errors="coerce").dt.date
        sub = d[(d["_ship_date"] == ship_date) & (d[COL_BP].astype(str).str.strip() == str(bp_s).strip())]

        if sub.empty:
            st.info("해당 조건의 출고 데이터가 없습니다. (좌측 필터 조건도 함께 확인)")
            st.stop()

        total_qty2 = int(round(sub[COL_QTY].fillna(0).sum(), 0))
        done_max = sub[COL_DONE].max() if COL_DONE in sub.columns else pd.NaT
        done_min = sub[COL_DONE].min() if COL_DONE in sub.columns else pd.NaT

        st.markdown(f"- **출고일자:** {ship_date.isoformat()}")
        st.markdown(f"- **BP명:** {html.escape(str(bp_s))}")
        st.markdown(f"- **요청수량 합:** {total_qty2:,}")
        if COL_DONE in sub.columns:
            st.markdown(f"- **작업완료:** {fmt_date(done_min)} ~ {fmt_date(done_max)}")
        st.divider()

        g = (
            sub.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)
            .agg(
                요청수량=(COL_QTY, "sum"),
                작업완료=(COL_DONE, "max") if COL_DONE in sub.columns else (COL_QTY, "size")
            )
            .reset_index()
        )
        g["출고일자"] = ship_date.isoformat()
        if COL_DONE in sub.columns:
            g["작업완료"] = g["작업완료"].apply(fmt_date)
        else:
            g["작업완료"] = "-"

        g["요청수량"] = pd.to_numeric(g["요청수량"], errors="coerce").fillna(0).round(0).astype(int)
        g = g.sort_values("요청수량", ascending=False, na_position="last")

        out_cols = ["출고일자", "작업완료", COL_ITEM_CODE, COL_ITEM_NAME, "요청수량"]
        render_pretty_table(
            g[out_cols],
            height=520,
            wrap_cols=[COL_ITEM_NAME],
            col_width_px={"출고일자": 120, "작업완료": 120, COL_ITEM_CODE: 130, COL_ITEM_NAME: 520, "요청수량": 120},
            number_cols=["요청수량"],
        )
        st.caption("※ 상세는 ‘출고일자 + BP명’ 기준으로 품목별 요청수량 합계를 보여줍니다.")

    else:
        st.subheader("출고 캘린더 (월별)")
        render_month_calendar_native(cal_base, ym)

else:
    st.info("요청하신 수정은 ‘새창 → 페이지 전환’이어서 캘린더 탭(①)만 변경했습니다. 다른 탭 코드는 기존 최종본과 동일하게 붙이시면 됩니다.")

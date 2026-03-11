# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반) - 최종 정리본 (옵션 A)
#
# ✅ 적용사항
# 1) 쿼리파라미터 내비게이션 제거
# 2) 새탭 방지: 캘린더 BP 클릭/이전달/다음달/더보기/접기/뒤로가기 => st.button + session_state
# 3) 10만행 대비: df.apply(axis=1) 제거(주차 벡터화) + 캘린더용 집계(cal_agg) 캐시 생성
# 4) 캘린더 표기: 태그(🟦 해외 / 🟩 국내)
#
# ✅ 출고건수
# - 출고건수 = 주문번호(distinct) 기준 통일
#
# ✅ UX 통일
# - 메뉴(①~⑥) 이동 시: 각 메뉴는 항상 '메인 화면'으로 초기화
#   (단, 기존 버전에서는 왼쪽 필터 f_* 값은 유지였으나)
#
# ✅ (요청 반영) "데이터 새로고침" 정책
# - 새로고침 클릭 시: 데이터/탭/화면/필터/내부상태 "모두 초기화"
# - st.radio 선택(빨간점)도 ①로 강제 고정되도록 nav_menu를 명시 세팅
#
# ✅ 표기 개선
# - 캘린더 상세: 작업완료가 단일 날짜면 "YYYY-MM-DD"로만 표시
#
# ✅ 에러 수정
# - 주차 라벨의 2026.0년/3.0월 문제 제거(연/월을 Int64로 변환 후 문자열화)
# - IntCastingNaNError 방지: astype(int) 최소화 + Int64(Nullable) 캐스팅/ fillna 보강
# ==========================================

import re
import html
import hashlib
import calendar as pycal
from datetime import date

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
    "카테고리 라인", "카테고리라인", "카테고리", "카테고리(Line)", "카테고리_LINE",
    "Category Line", "Category"
]

KEEP_CLASSES = ["B0", "B1"]
LT_ONLY_CUST1 = "해외B2B"
SPIKE_FACTOR = 1.3


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
def make_month_label(year: int, month: int) -> str:
    return f"{int(year)}년 {int(month)}월"


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


# =========================
# SKU 자동 코멘트
# =========================
def _fmt_int(x) -> str:
    try:
        return f"{int(round(float(x))):,}"
    except Exception:
        return "0"


def sku_comment_mom(sku_month: pd.DataFrame) -> list[str]:
    if sku_month is None or sku_month.empty:
        return []
    m = sku_month.sort_values("_month_key")
    if len(m) < 2:
        return []
    prev = m.iloc[-2]
    cur = m.iloc[-1]
    prev_q = float(prev["qty"]) if pd.notna(prev["qty"]) else 0.0
    cur_q = float(cur["qty"]) if pd.notna(cur["qty"]) else 0.0
    if prev_q <= 0:
        return [f"최근 월({cur['_month_label']}) 출고수량 {_fmt_int(cur_q)} (직전월({prev['_month_label']}) 데이터 0/부족으로 증감률 산정 불가)"]
    pct = (cur_q / prev_q - 1) * 100
    direction = "상승" if pct > 0 else "하락" if pct < 0 else "변동 없음"
    return [f"{prev['_month_label']} 대비 {cur['_month_label']} 출고량 **{direction} ({pct:+.0f}%)** · {_fmt_int(prev_q)} → {_fmt_int(cur_q)}"]


def sku_comment_trend(sku_month: pd.DataFrame) -> list[str]:
    if sku_month is None or sku_month.empty:
        return []
    m = sku_month.sort_values("_month_key")
    if len(m) < 3:
        return []

    last3 = m.iloc[-3:].copy()
    q0, q1, q2 = [float(x) if pd.notna(x) else 0.0 for x in last3["qty"].tolist()]
    l0, l1, l2 = last3["_month_label"].astype(str).tolist()

    if q0 < q1 < q2:
        return [f"최근 3개월({l0} → {l2}) 기준: 출고량 **지속 상승** ( {_fmt_int(q0)} → {_fmt_int(q2)} )"]
    if q0 > q1 > q2:
        return [f"최근 3개월({l0} → {l2}) 기준: 출고량 **지속 하락** ( {_fmt_int(q0)} → {_fmt_int(q2)} )"]

    return [f"최근 3개월({l0} → {l2}) 기준: **변동(혼조)**"]


def sku_comment_bp_spike(df_sku: pd.DataFrame, spike_factor=1.5, top_n=3) -> list[str]:
    if df_sku.empty or (COL_BP not in df_sku.columns) or (COL_QTY not in df_sku.columns):
        return []
    if "_month_label" not in df_sku.columns:
        return []

    m = (
        df_sku.dropna(subset=["_month_label"])
        .groupby([COL_BP, "_month_label"], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .rename(columns={COL_QTY: "m_qty"})
    )
    if m.empty:
        return []

    m["_month_key"] = m["_month_label"].astype(str).apply(parse_month_label_key)

    spikes = []
    for bp, sub in m.groupby(COL_BP, dropna=False):
        sub = sub.sort_values("_month_key")
        if len(sub) < 2:
            continue

        for _, r in sub.iterrows():
            cur_month = r["_month_label"]
            cur_qty = float(r["m_qty"]) if pd.notna(r["m_qty"]) else 0.0
            others = sub[sub["_month_label"] != cur_month]["m_qty"].astype(float)
            baseline = float(others.mean()) if len(others) > 0 else 0.0
            if baseline <= 0:
                continue
            if cur_qty < baseline * spike_factor:
                continue
            pct = (cur_qty / baseline - 1) * 100
            spikes.append({"bp": str(bp), "month": str(cur_month), "pct": pct, "qty": cur_qty, "baseline": baseline})

    if not spikes:
        return []

    spikes = sorted(spikes, key=lambda x: x["pct"], reverse=True)[:top_n]
    return [f"{s['bp']} ({s['month']}) 평균 대비 **{s['pct']:+.0f}%** · {_fmt_int(s['baseline'])} → {_fmt_int(s['qty'])}" for s in spikes]


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
    # ✅ 출고건수 = 주문번호 distinct
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

    # ✅ dt.year/dt.month NaT 섞이면 float(2026.0) 되는 문제 방지
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

    # ✅ 출고건수 = 주문번호 distinct
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
# Main
# =========================
st.title("📦 B2B 출고 대시보드")
st.caption("Google Sheet RAW 기반 | 제품분류 B0/B1 고정 | 필터(거래처구분1/2/월/BP) 반영")

# ✅ nav 기본값 보장
init_nav_state()

# =========================
# ✅ Refresh handler (전부 초기화 정책)
# =========================
if st.button("🔄 데이터 새로고침"):
    st.cache_data.clear()

    # 상태 정리(필터/캘린더/각 메뉴 내부 상태 등)
    for k in list(st.session_state.keys()):
        if k.startswith(("cal_", "f_", "sku_", "wk_", "m_")) or k in ("monthly_report_text",):
            del st.session_state[k]

    # ✅ (핵심) 탭/화면 ①로 강제 초기화 (라디오 빨간점 포함)
    st.session_state["nav_menu"] = "① 출고 캘린더"
    st.session_state["_prev_nav_menu"] = "① 출고 캘린더"
    reset_state_for_menu("① 출고 캘린더")

    # ✅ (요청 반영) 필터도 “무조건 전체”로 강제 초기화 4줄
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
    ["① 출고 캘린더", "② SKU별 조회", "③ 주차요약", "④ 월간요약", "⑤ 국가별 조회", "⑥ BP명별 조회"],
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

    if st.session_state["cal_view"] == "detail":
        ship_date = st.session_state.get("cal_selected_date")
        bp_s = st.session_state.get("cal_selected_bp", "")

        st.subheader("출고 상세 내역")
        if st.button("← 캘린더로 돌아가기", key="btn_cal_back"):
            st.session_state["cal_view"] = "calendar"
            safe_rerun()

        if ship_date is None or not str(bp_s).strip():
            st.warning("상세 조회 대상이 없습니다. 캘린더에서 BP를 클릭해 주세요.")
            st.stop()

        d = pool2.copy()
        if not need_cols(d, ["_ship_date", COL_BP, COL_QTY, COL_ITEM_CODE, COL_ITEM_NAME], "출고 상세"):
            st.stop()

        sub = d[(d["_ship_date"] == ship_date) & (d[COL_BP].astype(str).str.strip() == str(bp_s).strip())].copy()
        if sub.empty:
            st.info("해당 조건의 출고 데이터가 없습니다. (좌측 필터 조건도 함께 확인)")
            st.stop()

        total_qty2 = int(round(float(pd.to_numeric(sub[COL_QTY], errors="coerce").fillna(0).sum()), 0))
        done_max = sub[COL_DONE].max() if COL_DONE in sub.columns else pd.NaT
        done_min = sub[COL_DONE].min() if COL_DONE in sub.columns else pd.NaT

        st.markdown(f"- **출고일자:** {ship_date.isoformat()}")
        st.markdown(f"- **BP명:** {html.escape(str(bp_s))}")
        st.markdown(f"- **요청수량 합:** {total_qty2:,}")
        if COL_DONE in sub.columns:
            st.markdown(f"- **작업완료:** {format_done_range(done_min, done_max)}")
        st.divider()

        g = (
            sub.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)
            .agg(요청수량=(COL_QTY, "sum"), 작업완료=(COL_DONE, "max") if COL_DONE in sub.columns else (COL_QTY, "size"))
            .reset_index()
        )
        g["출고일자"] = ship_date.isoformat()
        g["작업완료"] = g["작업완료"].apply(fmt_date) if COL_DONE in sub.columns else "-"
        g["요청수량"] = pd.to_numeric(g["요청수량"], errors="coerce").fillna(0).round(0).astype("Int64")
        g = g.sort_values("요청수량", ascending=False, na_position="last")

        render_pretty_table(
            g[["출고일자", "작업완료", COL_ITEM_CODE, COL_ITEM_NAME, "요청수량"]],
            height=520,
            wrap_cols=[COL_ITEM_NAME],
            number_cols=["요청수량"],
        )
    else:
        st.subheader("출고 캘린더 (월별)")
        render_month_calendar(cal_pool, ym)

# =========================
# ② SKU별 조회
# =========================
elif nav == "② SKU별 조회":
    st.subheader("SKU별 조회")

    ignore_month = st.checkbox("월 필터 무시(전체기간 기준으로 SKU 조회/코멘트)", value=True, key="sku_ignore_month_filter")
    sku_scope = pool2.copy() if ignore_month else df_view.copy()

    if not need_cols(sku_scope, [COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY, COL_SHIP, COL_BP], "SKU별 조회"):
        st.stop()

    st.markdown("### 품목코드 검색")
    show_all_history = st.checkbox("전체 히스토리 보기", value=True, key="sku_show_all_history")

    base = sku_scope.copy()
    base[COL_ITEM_CODE] = base[COL_ITEM_CODE].astype(str).str.strip()
    base[COL_ITEM_NAME] = base[COL_ITEM_NAME].astype(str).str.strip()

    q = st.text_input("품목코드 검색 (부분검색 가능)", value="", placeholder="예: B0GF057A1", key="sku_query")

    if q.strip():
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
        else:
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

            dsku = base[base[COL_ITEM_CODE] == sel_code].copy()

            item_name = "-"
            nn = dsku[COL_ITEM_NAME].dropna()
            if not nn.empty:
                item_name = str(nn.iloc[0]).strip()

            st.markdown(f"- **품목코드:** {html.escape(sel_code)}")
            st.markdown(f"- **품목명:** {html.escape(item_name)}")

            if not show_all_history:
                today_ts = pd.Timestamp(date.today())
                ship_dt = pd.to_datetime(dsku[COL_SHIP], errors="coerce")
                dsku = dsku[(ship_dt.isna()) | (ship_dt >= today_ts)].copy()

            dsku["출고예정일"] = dsku[COL_SHIP].apply(lambda x: "미정" if pd.isna(x) else fmt_date(x))

            st.markdown("### 특이 / 이슈 포인트 (SKU 자동 코멘트)")

            sku_month = (
                dsku.dropna(subset=["_month_label"])
                .assign(_month_key=lambda x: x["_month_label"].astype(str).apply(parse_month_label_key))
                .groupby(["_month_label", "_month_key"], dropna=False)[COL_QTY]
                .sum(min_count=1)
                .reset_index()
                .rename(columns={COL_QTY: "qty"})
                .sort_values("_month_key")
            )

            mom_items = sku_comment_mom(sku_month)
            trend_items = sku_comment_trend(sku_month)
            bp_spike_items = sku_comment_bp_spike(dsku)

            if mom_items:
                render_numbered_block("월간 증감 (최근 2개월)", mom_items)
            if trend_items:
                render_numbered_block("추이 코멘트 (최근 3개월, 룰 기반)", trend_items)
            if bp_spike_items:
                render_numbered_block("BP별 평소 대비 급증 사례(월 단위)", bp_spike_items)

            st.divider()

            out = (
                dsku.groupby(["출고예정일", COL_BP], dropna=False)[COL_QTY]
                .sum(min_count=1)
                .reset_index()
                .rename(columns={COL_BP: "BP명", COL_QTY: "요청수량"})
            )
            out["요청수량"] = pd.to_numeric(out["요청수량"], errors="coerce").fillna(0).round(0).astype("Int64")

            render_pretty_table(out[["출고예정일", "BP명", "요청수량"]], height=520, wrap_cols=["BP명"], number_cols=["요청수량"])
    else:
        st.info("상단에 품목코드를 입력하면, 해당 SKU의 코멘트 및 히스토리가 표시됩니다.")

    st.divider()
    period_title = "누적 SKU Top10 (요청수량 기준)" if st.session_state["f_month"] == "전체" else f"{st.session_state['f_month']} SKU Top10 (요청수량 기준)"
    st.markdown(f"### {period_title}")

    top10_sku = build_item_topn_with_bp(df_view.copy(), 10)
    render_pretty_table(top10_sku, height=520, wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"], number_cols=["요청수량_합"])

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
    st.divider()

    st.subheader("주차 선택 → Top 10 (BP/품목코드/품목명/요청수량)")
    top10 = (
        wdf.groupby([COL_BP, COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1).reset_index()
        .sort_values(COL_QTY, ascending=False, na_position="last")
        .head(10)
        .copy()
    )
    top10.insert(0, "순위", range(1, len(top10) + 1))
    top10[COL_QTY] = pd.to_numeric(top10[COL_QTY], errors="coerce").fillna(0).round(0).astype("Int64")
    render_pretty_table(top10, height=520, wrap_cols=[COL_BP, COL_ITEM_NAME], number_cols=[COL_QTY])

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
# ④ 월간요약
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

    comment_items = []
    comment_items += period_kpi_delta_comment(cur_df=mdf, prev_df=prev_mdf)
    comment_items += category_top_comment(mdf, top_n=2)
    comment_items += concentration_comment(mdf)
    comment_items += undated_ship_risk_comment(mdf)
    render_numbered_block("월간 특이사항 (자동 코멘트)", comment_items)
    if prev_month:
        st.caption(f"※ 비교 기준: 선택 월({sel_month}) vs 전월({prev_month})")
    st.divider()

    st.subheader("월 선택 → Top 10 (BP/품목코드/품목명/요청수량)")
    top10 = (
        mdf.groupby([COL_BP, COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1).reset_index()
        .sort_values(COL_QTY, ascending=False, na_position="last")
        .head(10)
        .copy()
    )
    top10.insert(0, "순위", range(1, len(top10) + 1))
    top10[COL_QTY] = pd.to_numeric(top10[COL_QTY], errors="coerce").fillna(0).round(0).astype("Int64")
    render_pretty_table(top10, height=520, wrap_cols=[COL_BP, COL_ITEM_NAME], number_cols=[COL_QTY])

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

    tmp = base[[COL_CUST2, COL_ORDER_NO]].copy()
    tmp["_ord"] = tmp[COL_ORDER_NO].astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    rep_cnt = tmp.dropna(subset=["_ord"]).groupby(COL_CUST2)["_ord"].nunique()
    out["출고건수"] = out[COL_CUST2].astype(str).map(rep_cnt).fillna(0).astype(int)

    for c in ["평균_리드타임_작업완료기준", "리드타임_중간값_작업완료기준", "리드타임 느린 상위10% 기준(P90)"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").round(2)

    out["요청수량_합"] = pd.to_numeric(out["요청수량_합"], errors="coerce").fillna(0).round(0).astype("Int64")
    out["집계행수_표본"] = pd.to_numeric(out["집계행수_표본"], errors="coerce").fillna(0).astype("Int64")

    out = out.sort_values("요청수량_합", ascending=False, na_position="last")
    render_pretty_table(out, height=520, wrap_cols=[COL_CUST2], number_cols=["요청수량_합", "출고건수", "집계행수_표본"])
    st.caption("※ P90은 ‘느린 상위 10%’ 경계값(리드타임이 큰 구간)입니다.")

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

    tmp = base[[COL_BP, COL_ORDER_NO]].copy()
    tmp["_ord"] = tmp[COL_ORDER_NO].astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    rep_cnt = tmp.dropna(subset=["_ord"]).groupby(COL_BP)["_ord"].nunique()
    out["출고건수"] = out[COL_BP].astype(str).map(rep_cnt).fillna(0).astype(int)

    out["요청수량_합"] = pd.to_numeric(out["요청수량_합"], errors="coerce").fillna(0).round(0).astype("Int64")
    for c in ["평균_리드타임_작업완료기준", "리드타임_중간값_작업완료기준"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").round(2)

    out["최근_출고일"] = out["최근_출고일"].apply(fmt_date)
    out["최근_작업완료일"] = out["최근_작업완료일"].apply(fmt_date)
    out["집계행수_표본"] = pd.to_numeric(out["집계행수_표본"], errors="coerce").fillna(0).astype("Int64")

    out = out.sort_values("요청수량_합", ascending=False, na_position="last")
    render_pretty_table(out, height=520, wrap_cols=[COL_BP], number_cols=["요청수량_합", "출고건수", "집계행수_표본"])

st.caption("※ 모든 집계는 Google Sheet RAW 기반이며, 제품분류(B0/B1) 고정 + 선택한 필터 범위 내에서 계산됩니다.")

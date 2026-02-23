# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반)
# - 메뉴 순서: ① 출고 캘린더 -> ② SKU별 조회 -> ③ 주차요약 -> ④ 월간요약 -> ⑤ 국가별 조회 -> ⑥ BP명별 조회
# - SKU별 조회 UI: 품목코드 검색(상단) -> 누적 SKU Top10(하단)
# - SKU 자동 코멘트(룰 기반): MoM(2개월), 추이(3개월: 패턴 상세), BP 급증 사례(월단위)
# - 코멘트 UI: 헤더-내용은 붙이고, 블록 간격만 확보(가독성 개선)
# - 주차 라벨: 출고일자 우선(없으면 작업완료일)로 산정하여 유령 주차 방지
# - 전주/전월 +30% 급증 리포트: dtype(object) 에러 방지(증가배수 numeric 강제)
# - ✅ 주차/월간 자동코멘트:
#    1) 신규 BP 출고(과거 전체기간에 없던 BP가 해당 주/월에 처음 등장)
#    2) 직전기간 대비 KPI(현재값 + 증감 표기): 발주건수(주문번호 distinct)/출고건수(대표행)/출고수량/평균 리드타임
#    3) 카테고리 라인 TOP2(출고수량 기준)
#    4) Top BP 집중도: BP명(수량) + 점유율
#    5) Top SKU 집중도: 품목코드/품목명(수량) + 점유율
#    6) 출고일 미정 리스크(가능할 때만 표시)
#
# - ✅ 월간 리포트(버튼 생성, 복사 가능):
#    * 거래처구분1 기준 해외B2B / 국내B2B 섹션 분리
#    * 신규 BP 첫출고(해당 섹션 내 과거 전체기간 대비 신규)
#    * 출고량 증감 요약(전월 대비 수량/증감)
#    * 특정 SKU 대량 출고(Top SKU + BP별 분해)
#    * 전월 대비 주요 SKU 증감(% + 수량 prev→cur)
#    * (해외B2B만) JP/CN 라인 제외 전월 대비 증가 SKU(%로 표기 + BP분해)
#    * 차월 예정(선택월 다음달) 대량 출고 Top3 (BP명/품목코드/품목명/요청수량) — 특이건 없으면 생략
#
# - ✅ NEW: 출고 캘린더(메인)
#    * 월간 캘린더(일자 셀 border)
#    * 일자 셀: "BP명 / 요청수량합"만 노출
#    * BP 클릭(1번 클릭) -> BP/일자 상세 화면으로 전환
#    * 상세 화면: 출고건(해외=인보이스No / 국내=주문번호)별 요약 + 품목라인(전체) 즉시 표시 (추가 클릭 불필요)
# ==========================================

import re
import html
import calendar as pycal
from urllib.parse import quote

import streamlit as st
import pandas as pd
from datetime import date, datetime

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

# ✅ 발주건수 = 주문번호 distinct (중복 제거)
COL_ORDER_NO = "주문번호"

# ✅ 해외B2B 출고건 단위 = 인보이스No. (컬럼명은 RAW마다 다를 수 있어서 후보로 탐색)
INVOICE_COL_CANDIDATES = [
    "인보이스No.", "인보이스No", "인보이스번호", "인보이스넘버", "인보이스 넘버",
    "Invoice No", "InvoiceNo", "INVOICE NO", "INVOICE_NO", "Invoice"
]

# ✅ 카테고리 라인(컬럼명이 확정이 아니라 후보)
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
.wrap {white-space: normal; word-break: break-word; line-height: 1.25rem;}
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

/* ✅ 캘린더 UI */
.cal-wrap{margin-top: 0.6rem;}
.cal-head{
  display:grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 0;
  border: 1px solid #e5e7eb;
  border-bottom: 0;
  border-radius: 14px 14px 0 0;
  overflow: hidden;
  background:#fff;
}
.cal-head div{
  padding: 10px 10px;
  background:#f9fafb;
  border-right:1px solid #e5e7eb;
  font-weight:800;
  color:#111827;
}
.cal-head div:last-child{border-right:0;}

.cal-grid{
  display:grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 0;
  border: 1px solid #e5e7eb;
  border-radius: 0 0 14px 14px;
  overflow: hidden;
  background:#fff;
}
.cal-cell{
  min-height: 150px;
  border-right:1px solid #e5e7eb;
  border-top:1px solid #e5e7eb;
  padding: 10px 10px 12px 10px;
}
.cal-cell:nth-child(7n){border-right:0;}
.cal-day{
  font-weight:900;
  color:#111827;
  margin-bottom: 8px;
}
.cal-day.muted{color:#9ca3af;}

.cal-chip{
  display:block;
  width:100%;
  box-sizing:border-box;
  padding: 7px 10px;
  margin: 6px 0;
  border: 1px solid #d1d5db;
  border-radius: 10px;
  background:#ffffff;
  color:#111827;
  text-decoration:none;
  font-size: 0.92rem;
  line-height:1.15rem;
}
.cal-chip:hover{background:#f7fbff; border-color:#b6d4ff;}
.cal-chip .q{color:#111827; font-weight:900;}
.cal-chip .bp{color:#111827;}
.cal-more{
  display:block;
  margin-top: 6px;
  color:#2563eb;
  font-size:0.9rem;
}
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
# 코멘트 렌더
# -------------------------
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

# -------------------------
# SKU 자동 코멘트 (기존 유지)
# -------------------------
def _fmt_int(x) -> str:
    try:
        return f"{int(round(float(x))):,}"
    except Exception:
        return "0"

def _fmt_date_or_mijung(x) -> str:
    if pd.isna(x) or x is None or str(x).strip() == "":
        return "미정"
    try:
        return pd.to_datetime(x).strftime("%Y-%m-%d")
    except Exception:
        return str(x)

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

    if q1 >= q0 and q1 >= q2 and (q1 > q0 or q1 > q2):
        d1 = q1 - q0
        d2 = q2 - q1
        return [f"최근 3개월({l0} → {l2}) 기준: **상승 후 하락(피크형)** · {l0}→{l1} {_fmt_int(d1)} / {l1}→{l2} {_fmt_int(d2)}"]
    if q1 <= q0 and q1 <= q2 and (q1 < q0 or q1 < q2):
        d1 = q1 - q0
        d2 = q2 - q1
        return [f"최근 3개월({l0} → {l2}) 기준: **하락 후 반등(바닥형)** · {l0}→{l1} {_fmt_int(d1)} / {l1}→{l2} {_fmt_int(d2)}"]

    mid_vs_avg = q1 - (q0 + q2) / 2
    sign = "상회" if mid_vs_avg > 0 else "하회" if mid_vs_avg < 0 else "유사"
    return [f"최근 3개월({l0} → {l2}) 기준: **변동(혼조)** · 중간월({l1})이 양끝 평균 대비 {sign} ({_fmt_int(mid_vs_avg)})"]

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

            sub_ship = df_sku[
                (df_sku[COL_BP].astype(str).str.strip() == str(bp).strip()) &
                (df_sku["_month_label"].astype(str) == str(cur_month))
            ].copy()
            ship_dt = pd.to_datetime(sub_ship[COL_SHIP], errors="coerce") if COL_SHIP in sub_ship.columns else pd.Series([pd.NaT])
            ship_pick = ship_dt.min() if ship_dt.notna().any() else pd.NaT

            spikes.append({
                "bp": str(bp),
                "month": str(cur_month),
                "ship": ship_pick,
                "pct": pct,
                "qty": cur_qty,
                "baseline": baseline
            })

    if not spikes:
        return []

    spikes = sorted(spikes, key=lambda x: x["pct"], reverse=True)[:top_n]
    out = []
    for s in spikes:
        out.append(
            f"{s['bp']} 에서 {_fmt_date_or_mijung(s['ship'])} ({s['month']}) 기존 평균 대비 **{s['pct']:+.0f}%** · {_fmt_int(s['baseline'])} → {_fmt_int(s['qty'])}"
        )
    return out

# -------------------------
# BP list helpers (품목 Top5/Top10용)
# -------------------------
def build_bp_list_map(df_period: pd.DataFrame) -> pd.DataFrame:
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
        return "/ ".join(out)

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
    cmp["이전_요청수량"] = pd.to_numeric(cmp["이전_요청수량"], errors="coerce").fillna(0)
    cmp["현재_요청수량"] = pd.to_numeric(cmp["현재_요청수량"], errors="coerce").fillna(0)

    cmp["증가배수"] = cmp.apply(
        lambda r: (r["현재_요청수량"] / r["이전_요청수량"]) if r["이전_요청수량"] > 0 else pd.NA,
        axis=1
    )

    spike = cmp[(cmp["이전_요청수량"] > 0) & (cmp["현재_요청수량"] >= cmp["이전_요청수량"] * SPIKE_FACTOR)].copy()

    bp_map = build_bp_list_map(cur_df)
    spike = spike.merge(bp_map, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="left")

    spike = spike.sort_values("현재_요청수량", ascending=False, na_position="last")
    spike["현재_요청수량"] = spike["현재_요청수량"].fillna(0).round(0).astype(int)
    spike["이전_요청수량"] = spike["이전_요청수량"].fillna(0).round(0).astype(int)
    spike["증가배수"] = pd.to_numeric(spike["증가배수"], errors="coerce").round(2)
    spike["BP명(요청수량)"] = spike["BP명(요청수량)"].fillna("")
    return spike[cols]

# -------------------------
# ✅ 주차/월간 자동 코멘트 helpers (기존 유지)
# -------------------------
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
    """
    ✅ 출고건수는 발주건수(주문번호)와 분리
    - 대표행(TRUE) 기준 카운트 유지
    """
    if df is None or df.empty:
        return 0
    if "_is_rep" in df.columns:
        return int(df["_is_rep"].sum())
    return int(df.shape[0])

def _get_qty(df: pd.DataFrame) -> int:
    if df is None or df.empty or COL_QTY not in df.columns:
        return 0
    return int(round(float(df[COL_QTY].fillna(0).sum()), 0))

def _get_lt_mean(df: pd.DataFrame) -> float:
    if df is None or df.empty or COL_LT2 not in df.columns:
        return float("nan")
    s = pd.to_numeric(df[COL_LT2], errors="coerce").dropna()
    if s.empty:
        return float("nan")
    return float(s.mean())

def _find_category_col(df: pd.DataFrame) -> str | None:
    for c in CATEGORY_COL_CANDIDATES:
        if c in df.columns:
            return c
    return None

def new_bp_comment(all_df: pd.DataFrame, cur_df: pd.DataFrame, key_col_num: str, cur_key_num: int | None, top_n: int = 5) -> list[str]:
    if cur_df is None or cur_df.empty or COL_BP not in cur_df.columns:
        return []

    hist = all_df.copy()
    if key_col_num in hist.columns and cur_key_num is not None:
        hist_key = pd.to_numeric(hist[key_col_num], errors="coerce")
        hist = hist[hist_key.notna() & (hist_key.astype(int) < int(cur_key_num))]

    hist_bps = set(hist[COL_BP].dropna().astype(str).str.strip().tolist()) if (COL_BP in hist.columns and not hist.empty) else set()
    cur_bps = set(cur_df[COL_BP].dropna().astype(str).str.strip().tolist())

    new_bps = [bp for bp in cur_bps if bp and bp not in hist_bps]
    if not new_bps:
        return ["신규 출고 BP: 없음"]

    sub = cur_df[cur_df[COL_BP].astype(str).str.strip().isin(new_bps)].copy()
    if COL_QTY in sub.columns:
        g = sub.groupby(COL_BP)[COL_QTY].sum().sort_values(ascending=False).head(top_n)
        desc = ", ".join([f"{idx}({_fmt_int(val)})" for idx, val in g.items()])
    else:
        desc = ", ".join(new_bps[:top_n])

    return [f"신규 출고 BP: {desc}"]

def category_top_comment(cur_df: pd.DataFrame, top_n: int = 2) -> list[str]:
    if cur_df is None or cur_df.empty:
        return []
    cat_col = _find_category_col(cur_df)
    if not cat_col:
        return []
    if COL_QTY not in cur_df.columns:
        return []

    tmp = cur_df.copy()
    tmp[cat_col] = tmp[cat_col].astype(str).str.strip()
    g = (
        tmp.groupby(cat_col, dropna=False)[COL_QTY]
        .sum(min_count=1)
        .sort_values(ascending=False)
        .head(top_n)
    )
    if g.empty:
        return []
    desc = ", ".join([f"{idx}({_fmt_int(val)})" for idx, val in g.items()])
    return [f"카테고리 TOP{top_n}: {desc}"]

def concentration_comment(cur_df: pd.DataFrame) -> list[str]:
    if cur_df is None or cur_df.empty or COL_QTY not in cur_df.columns:
        return []

    total = float(cur_df[COL_QTY].fillna(0).sum())
    if total <= 0:
        return []

    out = []

    # Top BP
    if COL_BP in cur_df.columns:
        g = (
            cur_df.groupby(COL_BP, dropna=False)[COL_QTY]
            .sum(min_count=1)
            .sort_values(ascending=False)
        )
        if not g.empty:
            top_bp = str(g.index[0]).strip()
            top_bp_qty = float(g.iloc[0])
            top_bp_share = top_bp_qty / total * 100
            out.append(f"Top BP 집중도: 1위 {top_bp}({_fmt_int(top_bp_qty)}) {top_bp_share:.0f}%")

    # Top SKU
    if all(c in cur_df.columns for c in [COL_ITEM_CODE, COL_ITEM_NAME]):
        g2 = (
            cur_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
            .sum(min_count=1)
            .sort_values(ascending=False)
        )
        if not g2.empty:
            (top_code, top_name) = g2.index[0]
            top_code = str(top_code).strip()
            top_name = str(top_name).strip()
            top_qty = float(g2.iloc[0])
            top_share = top_qty / total * 100
            out.append(f"Top SKU 집중도: 1위 {top_code} / {top_name}({_fmt_int(top_qty)}) {top_share:.0f}%")

    return out[:2]

def undated_ship_risk_comment(cur_df: pd.DataFrame) -> list[str]:
    if cur_df is None or cur_df.empty:
        return []
    if COL_SHIP not in cur_df.columns or COL_QTY not in cur_df.columns:
        return []

    total_qty = float(cur_df[COL_QTY].fillna(0).sum())
    if total_qty <= 0:
        return []

    ship_dt = pd.to_datetime(cur_df[COL_SHIP], errors="coerce")
    miss = cur_df[ship_dt.isna()].copy()
    miss_qty = float(miss[COL_QTY].fillna(0).sum()) if not miss.empty else 0.0

    if miss_qty <= 0:
        return []
    pct = miss_qty / total_qty * 100
    return [f"출고일 미정 수량: {_fmt_int(miss_qty)} ({pct:.0f}%)"]

def period_kpi_delta_comment(cur_df: pd.DataFrame, prev_df: pd.DataFrame) -> list[str]:
    cur_order = _get_order_cnt(cur_df)
    prev_order = _get_order_cnt(prev_df)

    cur_ship = _get_ship_cnt(cur_df)
    prev_ship = _get_ship_cnt(prev_df)

    cur_qty = _get_qty(cur_df)
    prev_qty = _get_qty(prev_df)

    cur_lt = _get_lt_mean(cur_df)
    prev_lt = _get_lt_mean(prev_df)

    order_diff = cur_order - prev_order
    ship_diff = cur_ship - prev_ship
    qty_diff = cur_qty - prev_qty

    order_part = f"발주건수 {cur_order}건 ({_fmt_delta(order_diff)})"
    ship_part = f"출고건수 {cur_ship}건 ({_fmt_delta(ship_diff)})"
    qty_part = f"출고수량 {cur_qty:,}개 ({_fmt_delta(qty_diff)})"

    if (not pd.isna(cur_lt)) and (not pd.isna(prev_lt)):
        lt_diff = cur_lt - prev_lt
        lt_part = f"평균 리드타임 {cur_lt:.1f}일 ({_fmt_delta(lt_diff)})"
    elif (not pd.isna(cur_lt)) and pd.isna(prev_lt):
        lt_part = f"평균 리드타임 {cur_lt:.1f}일 (직전기간 데이터 부족)"
    else:
        lt_part = "평균 리드타임 -"

    return [f"직전기간 대비: {order_part} / {ship_part} / {qty_part} / {lt_part}"]

# -------------------------
# ✅ 월간 리포트 생성 helpers (기존 유지)
# -------------------------
def _month_label_next(label: str) -> str | None:
    y, m = parse_month_label_key(label)
    if y <= 0 or m <= 0:
        return None
    if m == 12:
        return make_month_label(y + 1, 1)
    return make_month_label(y, m + 1)

def _is_jp_cn_line(item_name: str) -> bool:
    s = (item_name or "").upper()
    return (" JP" in s) or (" CN" in s) or ("JP " in s) or ("CN " in s) or ("JP" in s and "JPG" not in s) or ("CN" in s)

def _bp_item_qty_breakdown(df: pd.DataFrame, code: str, name: str, top_n: int = 3) -> str:
    if df is None or df.empty:
        return ""
    sub = df[(df[COL_ITEM_CODE].astype(str).str.strip() == str(code).strip()) &
             (df[COL_ITEM_NAME].astype(str).str.strip() == str(name).strip())].copy()
    if sub.empty:
        return ""
    g = sub.groupby(COL_BP)[COL_QTY].sum().sort_values(ascending=False).head(top_n)
    parts = [f"{bp}({int(round(q)):,})" for bp, q in g.items()]
    return "/ ".join(parts)

def _sku_mom_change_lines(cur_df: pd.DataFrame, prev_df: pd.DataFrame, top_n: int = 6) -> list[str]:
    if cur_df is None or cur_df.empty or COL_QTY not in cur_df.columns:
        return []

    cur = (
        cur_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index(name="cur")
    )

    prev = (
        prev_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index(name="prev")
    ) if (prev_df is not None and not prev_df.empty and COL_QTY in prev_df.columns) else pd.DataFrame(
        columns=[COL_ITEM_CODE, COL_ITEM_NAME, "prev"]
    )

    m = cur.merge(prev, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="left")
    m["prev"] = pd.to_numeric(m["prev"], errors="coerce").fillna(0)
    m["cur"] = pd.to_numeric(m["cur"], errors="coerce").fillna(0)

    m = m[m["prev"] > 0].copy()
    if m.empty:
        return []

    m["pct"] = (m["cur"] / m["prev"] - 1.0) * 100.0
    m = m.sort_values(["cur"], ascending=False).head(top_n)

    out = []
    for _, r in m.iterrows():
        code = str(r[COL_ITEM_CODE]).strip()
        name = str(r[COL_ITEM_NAME]).strip()
        prev_qty = int(round(float(r["prev"]), 0))
        cur_qty = int(round(float(r["cur"]), 0))
        pct = float(r["pct"])
        out.append(f"- {code} {name} : {pct:+.0f}% ({prev_qty:,} → {cur_qty:,})")
    return out

def _new_bp_first_ship_lines(all_df_section: pd.DataFrame, cur_df_section: pd.DataFrame, cur_month_key: int | None, top_items: int = 4) -> list[str]:
    if cur_df_section is None or cur_df_section.empty or COL_BP not in cur_df_section.columns:
        return []

    hist = all_df_section.copy()
    if "_month_key_num" in hist.columns and cur_month_key is not None:
        hist = hist[pd.to_numeric(hist["_month_key_num"], errors="coerce").fillna(0).astype(int) < int(cur_month_key)]

    hist_bps = set(hist[COL_BP].dropna().astype(str).str.strip().tolist()) if not hist.empty else set()
    cur_bps = sorted(set(cur_df_section[COL_BP].dropna().astype(str).str.strip().tolist()))

    new_bps = [bp for bp in cur_bps if bp and bp not in hist_bps]
    if not new_bps:
        return ["- 신규 BP 첫 출고: 없음"]

    out = []
    for bp in new_bps[:5]:
        sub = cur_df_section[cur_df_section[COL_BP].astype(str).str.strip() == bp].copy()
        total_qty = int(round(sub[COL_QTY].fillna(0).sum(), 0)) if COL_QTY in sub.columns else 0
        sku_cnt = int(sub[COL_ITEM_CODE].dropna().astype(str).str.strip().nunique()) if COL_ITEM_CODE in sub.columns else 0

        top = (
            sub.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY]
            .sum().reset_index(name="qty")
            .sort_values("qty", ascending=False)
            .head(top_items)
        )
        top_list = [f"{r[COL_ITEM_CODE]} {r[COL_ITEM_NAME]}({int(round(r['qty'])):,})" for _, r in top.iterrows()] if not top.empty else []
        top_txt = " / ".join(top_list) if top_list else "-"

        out.append(f"- {bp}: 총 {sku_cnt}SKU / {total_qty:,}개 | 주요 품목: {top_txt}")
    return out

def _qty_delta_summary(cur_df: pd.DataFrame, prev_df: pd.DataFrame) -> str:
    cur_qty = _get_qty(cur_df)
    prev_qty = _get_qty(prev_df)
    diff = cur_qty - prev_qty
    sign = "+" if diff >= 0 else ""
    return f"출고수량 전월 대비 {sign}{diff:,}개 · {prev_qty:,} → {cur_qty:,}"

def _top_bp_lines(cur_df: pd.DataFrame, top_n: int = 3) -> list[str]:
    if cur_df is None or cur_df.empty or COL_BP not in cur_df.columns or COL_QTY not in cur_df.columns:
        return []
    g = cur_df.groupby(COL_BP)[COL_QTY].sum().sort_values(ascending=False).head(top_n)
    if g.empty:
        return []
    return [f"- 주요 BP: " + " / ".join([f"{bp}({int(round(q)):,})" for bp, q in g.items()])]

def _big_sku_lines(cur_df: pd.DataFrame, top_n: int = 4) -> list[str]:
    if cur_df is None or cur_df.empty or COL_QTY not in cur_df.columns:
        return []
    g = (
        cur_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY]
        .sum().reset_index(name="qty")
        .sort_values("qty", ascending=False)
        .head(top_n)
    )
    out = []
    for i, r in g.iterrows():
        code = str(r[COL_ITEM_CODE]).strip()
        name = str(r[COL_ITEM_NAME]).strip()
        qty = int(round(float(r["qty"]), 0))
        bp_break = _bp_item_qty_breakdown(cur_df, code, name, top_n=3)
        if bp_break:
            out.append(f"- {i+1:02d}) {code} {name} : {qty:,}개 → {bp_break}")
        else:
            out.append(f"- {i+1:02d}) {code} {name} : {qty:,}개")
    return out

def _jp_cn_excluded_increase_lines(cur_df: pd.DataFrame, prev_df: pd.DataFrame, top_n: int = 3) -> list[str]:
    if cur_df is None or cur_df.empty or COL_QTY not in cur_df.columns:
        return []
    if prev_df is None or prev_df.empty:
        return []

    cur = (
        cur_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY]
        .sum().reset_index(name="cur")
    )
    prev = (
        prev_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY]
        .sum().reset_index(name="prev")
    )

    m = cur.merge(prev, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="left")
    m["prev"] = pd.to_numeric(m["prev"], errors="coerce").fillna(0)
    m["cur"] = pd.to_numeric(m["cur"], errors="coerce").fillna(0)

    m["is_jpcn"] = m[COL_ITEM_NAME].astype(str).apply(_is_jp_cn_line)
    m = m[~m["is_jpcn"]].copy()

    m = m[(m["prev"] > 0) & (m["cur"] > m["prev"])].copy()
    if m.empty:
        return []

    m["pct"] = (m["cur"] / m["prev"] - 1) * 100.0
    m = m.sort_values(["pct", "cur"], ascending=[False, False]).head(top_n)

    out = []
    for _, r in m.iterrows():
        code = str(r[COL_ITEM_CODE]).strip()
        name = str(r[COL_ITEM_NAME]).strip()
        prev_qty = int(round(float(r["prev"]), 0))
        cur_qty = int(round(float(r["cur"]), 0))
        pct = float(r["pct"])
        bp_break = _bp_item_qty_breakdown(cur_df, code, name, top_n=3)
        if bp_break:
            out.append(f"- {code} {name} : {prev_qty:,} → {cur_qty:,} (약 {pct:+.0f}%) → {bp_break}")
        else:
            out.append(f"- {code} {name} : {prev_qty:,} → {cur_qty:,} (약 {pct:+.0f}%)")
    return out

def _next_month_top3_plan_lines(next_df: pd.DataFrame, section_name: str) -> list[str]:
    if next_df is None or next_df.empty or COL_QTY not in next_df.columns:
        return []

    bp_tot = next_df.groupby(COL_BP)[COL_QTY].sum().sort_values(ascending=False)
    if bp_tot.empty:
        return []

    total = float(next_df[COL_QTY].fillna(0).sum())

    def is_significant(qty: float) -> bool:
        return (qty >= 10000) or (total > 0 and (qty / total) >= 0.15)

    candidates = [(bp, float(q)) for bp, q in bp_tot.items() if is_significant(float(q))]
    if not candidates:
        return []

    candidates = candidates[:3]
    out = [f"- {section_name} 차월 대량 출고(Top{len(candidates)})"]
    for bp, _q in candidates:
        sub = next_df[next_df[COL_BP].astype(str).str.strip() == str(bp).strip()].copy()
        sku_top = (
            sub.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY]
            .sum().reset_index(name="qty")
            .sort_values("qty", ascending=False)
            .head(1)
        )
        if sku_top.empty:
            continue
        r = sku_top.iloc[0]
        code = str(r[COL_ITEM_CODE]).strip()
        name = str(r[COL_ITEM_NAME]).strip()
        qty = int(round(float(r["qty"]), 0))
        out.append(f"  • {bp}: {code} {name} {qty:,}개")
    return out

def _build_monthly_report_text(
    base_df: pd.DataFrame,
    sel_month_label: str,
    prev_month_label: str | None,
    next_month_label: str | None
) -> str:
    cur_df = base_df[base_df["_month_label"].astype(str) == str(sel_month_label)].copy()
    prev_df = base_df[base_df["_month_label"].astype(str) == str(prev_month_label)].copy() if prev_month_label else pd.DataFrame()
    next_df = base_df[base_df["_month_label"].astype(str) == str(next_month_label)].copy() if next_month_label else pd.DataFrame()

    def pick_section(df: pd.DataFrame, cust1_val: str) -> pd.DataFrame:
        if df is None or df.empty or COL_CUST1 not in df.columns:
            return pd.DataFrame()
        return df[df[COL_CUST1].astype(str).str.strip() == cust1_val].copy()

    cur_over = pick_section(cur_df, "해외B2B")
    prev_over = pick_section(prev_df, "해외B2B")
    next_over = pick_section(next_df, "해외B2B")

    cur_dom = pick_section(cur_df, "국내B2B")
    prev_dom = pick_section(prev_df, "국내B2B")
    next_dom = pick_section(next_df, "국내B2B")

    cur_key = month_key_num_from_label(sel_month_label)

    lines = []
    lines.append(f"{sel_month_label} B2B 현황 공유 드립니다. (SAP현황에 따라 자료는 오차범위가 있을 수 있습니다🙂)")
    lines.append("")

    lines.append("*해외B2B*")
    all_over = base_df[base_df[COL_CUST1].astype(str).str.strip() == "해외B2B"].copy() if COL_CUST1 in base_df.columns else pd.DataFrame()
    new_bp_over = _new_bp_first_ship_lines(all_over, cur_over, cur_key)
    lines.append(":white_check_mark: 신규 업체 첫 출고")
    lines.extend(new_bp_over)
    lines.append("")

    lines.append(":white_check_mark: 출고량 증감 요약")
    lines.append(f"- {_qty_delta_summary(cur_over, prev_over)}")
    lines.extend(_top_bp_lines(cur_over, top_n=3))
    lines.append("")

    lines.append(":white_check_mark: 특정 SKU 대량 출고 (Top)")
    big_over = _big_sku_lines(cur_over, top_n=4)
    lines.extend(big_over if big_over else ["- (표시할 데이터 없음)"])
    lines.append("")

    lines.append(":white_check_mark: 전월 대비 주요 SKU 증감")
    mom_over = _sku_mom_change_lines(cur_over, prev_over, top_n=6)
    lines.extend(mom_over if mom_over else ["- 전월 데이터 부족 또는 prev=0으로 산정 불가 SKU만 존재"])
    lines.append("")

    lines.append(":white_check_mark: JP, CN 라인 제외 전월 대비 출고량 증가 SKU")
    jpcn_over = _jp_cn_excluded_increase_lines(cur_over, prev_over, top_n=3)
    lines.extend(jpcn_over if jpcn_over else ["- 해당 없음"])
    lines.append("")

    plan_over = _next_month_top3_plan_lines(next_over, "해외B2B")
    if plan_over:
        lines.append(":spiral_calendar_pad: 차월 간략 일정(대량 출고 중심)")
        lines.extend(plan_over)
        lines.append("")

    lines.append("*국내B2B*")
    all_dom = base_df[base_df[COL_CUST1].astype(str).str.strip() == "국내B2B"].copy() if COL_CUST1 in base_df.columns else pd.DataFrame()
    new_bp_dom = _new_bp_first_ship_lines(all_dom, cur_dom, cur_key)
    lines.append(":white_check_mark: 신규 업체 첫 출고")
    lines.extend(new_bp_dom)
    lines.append("")

    lines.append(":white_check_mark: 출고량 증감 요약")
    lines.append(f"- {_qty_delta_summary(cur_dom, prev_dom)}")
    lines.extend(_top_bp_lines(cur_dom, top_n=3))
    lines.append("")

    lines.append(":white_check_mark: 특정 SKU 대량 출고 (Top)")
    big_dom = _big_sku_lines(cur_dom, top_n=4)
    lines.extend(big_dom if big_dom else ["- (표시할 데이터 없음)"])
    lines.append("")

    lines.append(":white_check_mark: 전월 대비 주요 SKU 증감")
    mom_dom = _sku_mom_change_lines(cur_dom, prev_dom, top_n=6)
    lines.extend(mom_dom if mom_dom else ["- 전월 데이터 부족 또는 prev=0으로 산정 불가 SKU만 존재"])
    lines.append("")

    plan_dom = _next_month_top3_plan_lines(next_dom, "국내B2B")
    if plan_dom:
        lines.append(":spiral_calendar_pad: 차월 간략 일정(대량 출고 중심)")
        lines.extend(plan_dom)
        lines.append("")

    return "\n".join(lines).strip()

# -------------------------
# 출고 캘린더 helpers
# -------------------------
def find_invoice_col(df: pd.DataFrame) -> str | None:
    for c in INVOICE_COL_CANDIDATES:
        if c in df.columns:
            return c
    return None

def build_ship_doc_column(df: pd.DataFrame, invoice_col: str | None) -> pd.Series:
    """
    출고건 단위:
      - 해외B2B: 인보이스No
      - 국내B2B: 주문번호
    """
    cust1 = df[COL_CUST1].astype(str).str.strip() if COL_CUST1 in df.columns else pd.Series([""] * len(df))
    inv = df[invoice_col].astype(str).str.strip() if (invoice_col and invoice_col in df.columns) else pd.Series([""] * len(df))
    ordno = df[COL_ORDER_NO].astype(str).str.strip() if COL_ORDER_NO in df.columns else pd.Series([""] * len(df))

    out = []
    for c1, i, o in zip(cust1.tolist(), inv.tolist(), ordno.tolist()):
        if str(c1).strip() == "해외B2B":
            v = (i or "").strip()
            out.append(v if v else "(인보이스 미기재)")
        else:
            v = (o or "").strip()
            out.append(v if v else "(주문번호 미기재)")
    return pd.Series(out, index=df.index)

def render_calendar_html(
    base_df: pd.DataFrame,
    year: int,
    month: int,
    page_key: str = "cal",
    max_items_per_day: int = 7
):
    """
    base_df: 캘린더용 데이터(필터 반영된 DF, raw_all 기반 권장)
    - 셀: BP명/요청수량합 리스트(클릭=상세)
    """
    if base_df is None or base_df.empty:
        st.info("표시할 데이터가 없습니다.")
        return

    if not need_cols(base_df, [COL_BP, COL_QTY, COL_SHIP, COL_CUST1], "출고 캘린더"):
        return

    # 출고일자 기준(날짜 없는 건 캘린더에서는 제외)
    ship_dt = pd.to_datetime(base_df[COL_SHIP], errors="coerce")
    base_df = base_df[ship_dt.notna()].copy()
    base_df["_ship_date"] = pd.to_datetime(base_df[COL_SHIP], errors="coerce").dt.date

    # 월 범위
    try:
        first_day = date(year, month, 1)
    except Exception:
        st.warning("연/월 값이 올바르지 않습니다.")
        return

    _, last_day_num = pycal.monthrange(year, month)
    last_day = date(year, month, last_day_num)

    base_df = base_df[(base_df["_ship_date"] >= first_day) & (base_df["_ship_date"] <= last_day)].copy()
    if base_df.empty:
        st.info("선택한 월에 출고 데이터가 없습니다.")
        return

    # day x bp sum
    g = (
        base_df.groupby(["_ship_date", COL_BP], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .rename(columns={COL_QTY: "qty_sum"})
    )
    g["qty_sum"] = pd.to_numeric(g["qty_sum"], errors="coerce").fillna(0)

    # 날짜별 bp 리스트 dict
    day_map: dict[date, list[tuple[str, int]]] = {}
    for d, sub in g.groupby("_ship_date"):
        sub = sub.sort_values("qty_sum", ascending=False)
        items = []
        for _, r in sub.iterrows():
            bp = str(r.get(COL_BP, "")).strip()
            q = int(round(float(r.get("qty_sum", 0)), 0))
            if not bp:
                continue
            items.append((bp, q))
        day_map[d] = items

    # 달력 grid 계산(월요일 시작)
    cal = pycal.Calendar(firstweekday=0)  # Monday=0
    weeks = cal.monthdatescalendar(year, month)  # list of weeks, each week is 7 date objects

    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    head = '<div class="cal-head">' + "".join([f"<div>{w}</div>" for w in weekdays]) + "</div>"

    cells = []
    for week in weeks:
        for d in week:
            in_month = (d.month == month)
            day_cls = "cal-day" if in_month else "cal-day muted"
            cell = [f'<div class="cal-cell"><div class="{day_cls}">{d.day}</div>']

            items = day_map.get(d, []) if in_month else []
            if items:
                # 과밀 방지: 상위 max_items_per_day만 노출, 나머지는 "+n more"
                show = items[:max_items_per_day]
                more_cnt = max(0, len(items) - len(show))

                for bp, q in show:
                    # 1클릭 이동: query params
                    href = f"?page=bpday&y={year}&m={month}&d={d.day}&bp={quote(bp)}"
                    chip = f'<a class="cal-chip" href="{href}"><span class="bp">{html.escape(bp)}</span> / <span class="q">{q:,}</span></a>'
                    cell.append(chip)

                if more_cnt > 0:
                    cell.append(f'<span class="cal-more">+ {more_cnt} more</span>')

            cell.append("</div>")
            cells.append("".join(cell))

    grid = '<div class="cal-grid">' + "".join(cells) + "</div>"
    st.markdown(f'<div class="cal-wrap">{head}{grid}</div>', unsafe_allow_html=True)

def clear_query_params():
    try:
        st.query_params.clear()
    except Exception:
        # 구

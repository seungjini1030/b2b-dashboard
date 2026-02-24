# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반)
# - 메뉴 순서: ⓪ 출고캘린더 -> ① SKU별 조회 -> ② 주차요약 -> ③ 월간요약 -> ④ 국가별 조회 -> ⑤ BP명별 조회
# - ✅ 출고캘린더(월간):
#    * 월간 캘린더 그리드(월~일) 형태로 표시
#    * 각 일자에 BP명 "전부" 표시(더보기/오늘 버튼 없음)
#    * 해외B2B/국내B2B는 "버튼 배경색"으로만 구분(앞 점/라벨 없음)
#    * BP명 클릭 → 같은 페이지에서 출고 상세로 전환(쿼리파라미터 기반)  ✅ target="_self"로 새창 방지
#    * 상세에서 '캘린더로 돌아가기' 버튼 제공(새창X)
#
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
# ==========================================

import re
import html
import calendar
from datetime import date, datetime

import streamlit as st
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

# ✅ 발주건수 = 주문번호 distinct (중복 제거)
COL_ORDER_NO = "주문번호"

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
.cal-wrap { margin-top: 0.6rem; }
.cal-head{
  display:flex; align-items:center; justify-content:space-between;
  gap: 0.75rem;
  margin: 0.35rem 0 0.6rem 0;
}
.cal-title{
  font-weight: 900; font-size: 1.15rem; color:#111827;
}
.cal-nav a{
  display:inline-flex; align-items:center; justify-content:center;
  width: 34px; height: 34px;
  border:1px solid #e5e7eb;
  border-radius:10px;
  text-decoration:none;
  color:#111827;
  background:#fff;
}
.cal-grid{
  width: 100%;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  overflow: hidden;
  background: #fff;
}
.cal-row{
  display:grid;
  grid-template-columns: repeat(7, 1fr);
}
.cal-dow{
  background:#f9fafb;
  border-bottom:1px solid #e5e7eb;
}
.cal-dow div{
  padding: 10px 10px;
  font-weight: 800;
  color:#111827;
  font-size: 0.95rem;
}
.cal-cell{
  min-height: 118px;
  padding: 10px 10px 12px 10px;
  border-right:1px solid #f3f4f6;
  border-bottom:1px solid #f3f4f6;
}
.cal-row .cal-cell:last-child{ border-right:none; }
.cal-date{
  font-weight: 900;
  color:#111827;
  font-size: 0.95rem;
  margin-bottom: 8px;
}
.cal-date.muted{ color:#9ca3af; }

.cal-pill{
  display:block;
  padding: 7px 10px;
  border-radius: 12px;
  border: 1px solid transparent;
  text-decoration: none;
  font-size: 0.92rem;
  font-weight: 700;
  line-height: 1.1rem;
  margin: 6px 0;
  word-break: break-word;
}
.cal-pill.over{
  background:#ede9fe;
  border-color:#c4b5fd;
  color:#5b21b6;
}
.cal-pill.dom{
  background:#dbeafe;
  border-color:#93c5fd;
  color:#1e40af;
}
.cal-pill:hover{ filter: brightness(0.98); }

.cal-help{
  color:#6b7280;
  font-size: 0.9rem;
  margin-top: -2px;
}
.back-link{
  display:inline-flex;
  align-items:center;
  gap: 0.45rem;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 8px 12px;
  text-decoration:none;
  color:#111827;
  background:#fff;
  font-weight: 800;
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
# SKU 자동 코멘트 (원본 유지)
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
# (이하 주차/월간/리포트/스파이크 등 원본 로직 그대로 유지)
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
# ✅ 주차/월간 자동 코멘트 helpers (원본 유지)
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
# Google Sheet Load
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

    if (COL_YEAR in df.columns) and (COL_MONTH in df.columns):
        y = pd.to_numeric(df[COL_YEAR], errors="coerce")
        m = pd.to_numeric(df[COL_MONTH], errors="coerce")
        df["_month_label"] = [
            make_month_label(yy, mm) if pd.notna(yy) and pd.notna(mm) else None
            for yy, mm in zip(y, m)
        ]
    else:
        df["_month_label"] = None

    # ✅ 캘린더용 기준일(출고일자 우선, 없으면 작업완료)
    ship_dt = pd.to_datetime(df[COL_SHIP], errors="coerce") if COL_SHIP in df.columns else pd.Series([pd.NaT] * len(df))
    done_dt = pd.to_datetime(df[COL_DONE], errors="coerce") if COL_DONE in df.columns else pd.Series([pd.NaT] * len(df))
    base_dt = ship_dt.where(ship_dt.notna(), done_dt)
    df["_base_dt"] = base_dt
    df["_base_date"] = pd.to_datetime(base_dt, errors="coerce").dt.date

    return df

# -------------------------
# Query params helpers (캘린더 전환용)
# -------------------------
def _get_qp() -> dict:
    try:
        return dict(st.query_params)
    except Exception:
        return st.experimental_get_query_params()

def _qp_get(qp: dict, key: str, default=None):
    v = qp.get(key, default)
    if isinstance(v, list):
        return v[0] if v else default
    return v

def _mk_href(base: dict) -> str:
    parts = []
    for k, v in base.items():
        if v is None:
            continue
        parts.append(f"{k}={html.escape(str(v))}")
    return "?" + "&".join(parts) if parts else "?"

def _ym_str(y: int, m: int) -> str:
    return f"{int(y):04d}-{int(m):02d}"

def _ym_add(ym: str, delta_month: int) -> str:
    try:
        y, m = ym.split("-")
        y = int(y); m = int(m)
    except Exception:
        t = date.today()
        y, m = t.year, t.month
    total = y * 12 + (m - 1) + delta_month
    ny = total // 12
    nm = (total % 12) + 1
    return _ym_str(ny, nm)

def _parse_ym(ym: str) -> tuple[int, int]:
    try:
        y, m = ym.split("-")
        return int(y), int(m)
    except Exception:
        t = date.today()
        return t.year, t.month

# -------------------------
# Main
# -------------------------
st.title("📦 B2B 출고 대시보드")
st.caption("Google Sheet RAW 기반 | 제품분류 B0/B1 고정 | 필터(거래처구분1/2/월/BP) 반영")

if st.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    reset_keys = ["nav_menu", "f_cust1", "f_cust2", "f_month", "f_bp"]
    for k in reset_keys:
        if k in st.session_state:
            del st.session_state[k]
    st.session_state["nav_menu"] = "⓪ 출고캘린더"
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
# KPI cards (요약)
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
    ["⓪ 출고캘린더", "① SKU별 조회", "② 주차요약", "③ 월간요약", "④ 국가별 조회", "⑤ BP명별 조회"],
    horizontal=True,
    key="nav_menu"
)

# =========================
# ⓪ 출고캘린더 (target="_self" 적용)
# =========================
if nav == "⓪ 출고캘린더":
    st.subheader("출고캘린더")

    qp = _get_qp()
    page = _qp_get(qp, "page", "cal")  # cal / detail
    ym = _qp_get(qp, "ym", None)

    if not ym:
        if "_base_dt" in pool2.columns and pool2["_base_dt"].notna().any():
            mx = pd.to_datetime(pool2["_base_dt"], errors="coerce").max()
            ym = _ym_str(mx.year, mx.month)
        else:
            t = date.today()
            ym = _ym_str(t.year, t.month)

    y, m = _parse_ym(ym)
    prev_ym = _ym_add(ym, -1)
    next_ym = _ym_add(ym, 1)

    base_cal = pool2.copy()
    if sel_bp != "전체" and COL_BP in base_cal.columns:
        base_cal = base_cal[base_cal[COL_BP].astype(str).str.strip() == sel_bp].copy()

    base_dt = pd.to_datetime(base_cal["_base_dt"], errors="coerce")
    base_cal = base_cal[base_dt.notna()].copy()
    base_cal["_base_dt2"] = pd.to_datetime(base_cal["_base_dt"], errors="coerce")
    base_cal = base_cal[(base_cal["_base_dt2"].dt.year == y) & (base_cal["_base_dt2"].dt.month == m)].copy()
    base_cal["_d"] = base_cal["_base_dt2"].dt.date

    if page == "detail":
        sel_day = _qp_get(qp, "day", None)
        sel_bp_q = _qp_get(qp, "bp", None)

        back_href = _mk_href({"page": "cal", "ym": ym})
        # ✅ target="_self"로 새창 방지
        st.markdown(f"""<a class="back-link" href="{back_href}" target="_self">← 캘린더로 돌아가기</a>""", unsafe_allow_html=True)
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

        if not sel_day or not sel_bp_q:
            st.info("상세를 열기 위한 정보가 부족합니다. 캘린더에서 BP명을 클릭해 주세요.")
        else:
            try:
                day_dt = datetime.strptime(sel_day, "%Y-%m-%d").date()
            except Exception:
                day_dt = None

            ddf = base_cal.copy()
            if day_dt:
                ddf = ddf[ddf["_d"] == day_dt].copy()
            ddf = ddf[ddf[COL_BP].astype(str).str.strip() == str(sel_bp_q).strip()].copy()

            st.markdown(f"### {sel_day} · {html.escape(str(sel_bp_q))}")

            total = int(round(ddf[COL_QTY].fillna(0).sum(), 0)) if (not ddf.empty and COL_QTY in ddf.columns) else 0
            render_mini_kpi("요청수량 합", f"{total:,}")
            st.divider()

            if ddf.empty:
                st.info("해당 조건의 출고 데이터가 없습니다.")
            else:
                detail = (
                    ddf.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
                    .sum(min_count=1)
                    .reset_index()
                    .rename(columns={COL_QTY: "요청수량"})
                    .sort_values("요청수량", ascending=False, na_position="last")
                )
                detail["요청수량"] = detail["요청수량"].fillna(0).round(0).astype(int)

                st.markdown("#### 상세 출고 품목 내역")
                render_pretty_table(
                    detail,
                    height=520,
                    wrap_cols=[COL_ITEM_NAME],
                    col_width_px={COL_ITEM_CODE: 150, COL_ITEM_NAME: 520, "요청수량": 130},
                    number_cols=["요청수량"],
                )
    else:
        if base_cal.empty:
            st.info("해당 월에 표시할 출고 데이터가 없습니다. (거래처구분/국가/BP 필터를 확인해 주세요)")
        else:
            if not need_cols(base_cal, ["_d", COL_BP, COL_CUST1], "출고캘린더"):
                st.stop()

            agg = (
                base_cal.groupby(["_d", COL_BP, COL_CUST1], dropna=False)[COL_QTY]
                .sum(min_count=1)
                .reset_index()
                .rename(columns={COL_QTY: "qty"})
            )

            day_map: dict[date, list[tuple[str, str]]] = {}
            for _, r in agg.iterrows():
                d0 = r["_d"]
                bp0 = str(r[COL_BP]).strip()
                c10 = str(r[COL_CUST1]).strip()
                if not bp0 or pd.isna(d0):
                    continue
                day_map.setdefault(d0, []).append((bp0, c10))

            cal = calendar.Calendar(firstweekday=calendar.MONDAY)
            month_days = cal.monthdatescalendar(y, m)

            left_href = _mk_href({"page": "cal", "ym": prev_ym})
            right_href = _mk_href({"page": "cal", "ym": next_ym})
            # ✅ nav 링크도 target="_self"
            st.markdown(
                f"""
                <div class="cal-head">
                  <div class="cal-nav"><a href="{left_href}" target="_self">◀</a></div>
                  <div>
                    <div class="cal-title">{y}년 {m}월</div>
                    <div class="cal-help">※ 각 날짜의 BP명을 클릭하면 ‘출고 상세’로 이동합니다. (새창 없이 페이지 전환)</div>
                  </div>
                  <div class="cal-nav"><a href="{right_href}" target="_self">▶</a></div>
                </div>
                """,
                unsafe_allow_html=True
            )

            dow = ["월", "화", "수", "목", "금", "토", "일"]
            html_rows = []
            html_rows.append('<div class="cal-row cal-dow">' + "".join([f"<div>{d}</div>" for d in dow]) + "</div>")

            for week in month_days:
                cells = []
                for d0 in week:
                    in_month = (d0.month == m)
                    date_cls = "" if in_month else "muted"
                    date_txt = str(d0.day)

                    pills_html = ""
                    items = sorted(day_map.get(d0, []), key=lambda x: (x[0] or ""))

                    for bp0, c10 in items:
                        pill_cls = "over" if c10 == "해외B2B" else "dom" if c10 == "국내B2B" else "dom"
                        href = _mk_href({
                            "page": "detail",
                            "ym": ym,
                            "day": d0.strftime("%Y-%m-%d"),
                            "bp": bp0
                        })
                        # ✅ BP pill도 target="_self"
                        pills_html += f'<a class="cal-pill {pill_cls}" href="{href}" target="_self">{html.escape(bp0)}</a>'

                    cells.append(
                        f"""
                        <div class="cal-cell">
                          <div class="cal-date {date_cls}">{date_txt}</div>
                          {pills_html}
                        </div>
                        """
                    )
                html_rows.append('<div class="cal-row">' + "".join(cells) + "</div>")

            st.markdown(f'<div class="cal-wrap"><div class="cal-grid">{"".join(html_rows)}</div></div>', unsafe_allow_html=True)

# =========================
# 나머지 메뉴는 기존 코드 그대로 쓰면 됨
# (승진이 요청은 "새창 방지"였고, 캘린더 링크에 target="_self"만 추가로 반영)
# =========================
else:
    st.info("이 코드 블록은 ‘캘린더 새창 방지’ 수정본입니다. 기존 전체 코드에 이 캘린더 섹션을 그대로 덮어써서 사용하세요.")

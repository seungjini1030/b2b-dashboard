# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반)
# - ✅ 메뉴 순서: ① 출고 캘린더 -> ② SKU별 조회 -> ③ 주차요약 -> ④ 월간요약 -> ⑤ 국가별 조회 -> ⑥ BP명별 조회
# - ✅ 캘린더:
#    * ✅ Streamlit native 월 전체 캘린더(일~토 그리드) = st.columns(7) 기반 (그리드 깨짐 방지)
#    * 출고일자 기준으로 일자 박스 내 BP명 표시
#    * 출고건 많으면 +N건 클릭 시 펼침/접기
#    * ✅ BP명 클릭 시 페이지 전환(새창 X) = 링크(쿼리파라미터) 내비게이션으로 상세 화면 이동
#    * ✅ 해외B2B/국내B2B 구분 = 캘린더 BP 버튼 색상으로 구별
#    * 상세 화면: 출고일자/작업완료/요청수량합/품목코드/품목명/요청수량
#    * 상세에서 캘린더로 돌아가기
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
#
# ✅ 성능개선(이번 버전):
# - cache ttl 상향 (기본 30분)
# - read_csv usecols 적용(필요 컬럼만 로드)
# - 문자열 dtype 강제(파싱 비용 감소/안정화)
# - 캘린더 day_map 월 단위 캐시
# - KPI 계산 캐시
# - 로딩 spinner 추가
# ==========================================

import re
import html
import calendar as pycal
from datetime import date, datetime
from urllib.parse import quote

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
COL_ORDER_NO = "주문번호"  # ✅ 발주건수 = 주문번호 distinct

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

# ✅ 성능: 실제 사용하는 컬럼만 로드 (시트 컬럼명과 정확히 일치해야 함)
# - 카테고리 라인 후보는 실제 시트에 있는 컬럼명에 맞춰 필요 시 추가해도 됨
USECOLS = [
    COL_QTY, COL_YEAR, COL_MONTH, COL_WEEK_LABEL,
    COL_DONE, COL_SHIP, COL_LT2,
    COL_BP, COL_MAIN,
    COL_CUST1, COL_CUST2,
    COL_CLASS,
    COL_ITEM_CODE, COL_ITEM_NAME,
    COL_ORDER_DATE, COL_ORDER_NO,
]
# ✅ 성능: 문자열 dtype 강제(파싱 비용/오류 감소)
DTYPE_MAP = {
    COL_YEAR: "string",
    COL_MONTH: "string",
    COL_WEEK_LABEL: "string",
    COL_BP: "string",
    COL_MAIN: "string",
    COL_CUST1: "string",
    COL_CUST2: "string",
    COL_CLASS: "string",
    COL_ITEM_CODE: "string",
    COL_ITEM_NAME: "string",
    COL_ORDER_NO: "string",
}

# =========================
# Streamlit 설정
# =========================
st.set_page_config(page_title="B2B 출고 대시보드 (Google Sheet 기반)", layout="wide")

def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

def get_qp() -> dict:
    if hasattr(st, "query_params"):
        return dict(st.query_params)
    return st.experimental_get_query_params()

def set_qp(**kwargs):
    if hasattr(st, "query_params"):
        st.query_params.clear()
        for k, v in kwargs.items():
            st.query_params[k] = v
    else:
        st.experimental_set_query_params(**kwargs)

def qp_get_one(qp: dict, key: str, default: str = "") -> str:
    v = qp.get(key, default)
    if isinstance(v, list):
        return v[0] if v else default
    return v if v is not None else default

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

.cal-nav-wrap{display:flex; gap:0.5rem; justify-content:space-between; align-items:center;}
a.cal-nav{
  display:inline-block;
  width:100%;
  text-align:center;
  padding:0.55rem 0.6rem;
  border:1px solid #e5e7eb;
  border-radius:12px;
  background:#ffffff;
  color:#111827;
  text-decoration:none;
  font-weight:700;
}
a.cal-nav:hover{background:#f9fafb;}

a.cal-link{
  display:block;
  width:100%;
  padding:0.42rem 0.55rem;
  border:1px solid #e5e7eb;
  border-radius:10px;
  background:#ffffff;
  color:#111827;
  text-decoration:none;
  font-size:0.86rem;
  line-height:1.2rem;
  margin:0.28rem 0;
  box-sizing:border-box;
}
a.cal-link:hover{background:#f3f4f6;}
a.cal-link.overseas{
  background:#eef2ff;
  border-color:#c7d2fe;
}
a.cal-link.domestic{
  background:#ecfeff;
  border-color:#a5f3fc;
}
a.cal-action{
  display:block;
  width:100%;
  padding:0.42rem 0.55rem;
  border:1px dashed #e5e7eb;
  border-radius:10px;
  background:#ffffff;
  color:#374151;
  text-decoration:none;
  font-size:0.86rem;
  margin:0.28rem 0;
  text-align:center;
}
a.cal-action:hover{background:#f9fafb;}
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
# SKU 자동 코멘트
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
# ✅ 주차/월간 자동 코멘트 helpers
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
# ✅ 월간 리포트 helpers
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
    if big_over:
        lines.extend(big_over)
    else:
        lines.append("- (표시할 데이터 없음)")
    lines.append("")

    lines.append(":white_check_mark: 전월 대비 주요 SKU 증감")
    mom_over = _sku_mom_change_lines(cur_over, prev_over, top_n=6)
    if mom_over:
        lines.extend(mom_over)
    else:
        lines.append("- 전월 데이터 부족 또는 prev=0으로 산정 불가 SKU만 존재")
    lines.append("")

    lines.append(":white_check_mark: JP, CN 라인 제외 전월 대비 출고량 증가 SKU")
    jpcn_over = _jp_cn_excluded_increase_lines(cur_over, prev_over, top_n=3)
    if jpcn_over:
        lines.extend(jpcn_over)
    else:
        lines.append("- 해당 없음")
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
    if big_dom:
        lines.extend(big_dom)
    else:
        lines.append("- (표시할 데이터 없음)")
    lines.append("")

    lines.append(":white_check_mark: 전월 대비 주요 SKU 증감")
    mom_dom = _sku_mom_change_lines(cur_dom, prev_dom, top_n=6)
    if mom_dom:
        lines.extend(mom_dom)
    else:
        lines.append("- 전월 데이터 부족 또는 prev=0으로 산정 불가 SKU만 존재")
    lines.append("")

    plan_dom = _next_month_top3_plan_lines(next_dom, "국내B2B")
    if plan_dom:
        lines.append(":spiral_calendar_pad: 차월 간략 일정(대량 출고 중심)")
        lines.extend(plan_dom)
        lines.append("")

    return "\n".join(lines).strip()

# -------------------------
# Load RAW (Google Sheet export, live)
# -------------------------
@st.cache_data(ttl=1800, show_spinner=False)  # ✅ 성능: 30분 캐시
def load_raw_from_gsheet() -> pd.DataFrame:
    csv_url = f"https://docs.google.com/spreadsheets/d/{GSHEET_ID}/export?format=csv&gid={GSHEET_GID}"

    # ✅ 성능: usecols + dtype 적용 (가능한 경우)
    try:
        df = pd.read_csv(
            csv_url,
            header=HEADER_ROW_0BASED,
            usecols=USECOLS,
            dtype=DTYPE_MAP,
        )
    except Exception:
        # usecols/dtype가 시트와 100% 안 맞을 때 fallback
        df = pd.read_csv(csv_url, header=HEADER_ROW_0BASED)

    df.columns = df.columns.astype(str).str.strip()
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")]

    # 날짜/수치 변환
    for c in [COL_SHIP, COL_DONE, COL_ORDER_DATE]:
        safe_dt(df, c)
    for c in [COL_QTY, COL_LT2, "리드타임1"]:
        safe_num(df, c)

    # 리드타임 대체 계산(필요 시)
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

    # 월 라벨
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
# 캘린더 state & routing
# =========================
def init_calendar_state():
    if "cal_view" not in st.session_state:
        st.session_state["cal_view"] = "calendar"
    if "cal_ym" not in st.session_state:
        st.session_state["cal_ym"] = ""
    if "cal_selected_date" not in st.session_state:
        st.session_state["cal_selected_date"] = None
    if "cal_selected_bp" not in st.session_state:
        st.session_state["cal_selected_bp"] = ""
    if "cal_expanded" not in st.session_state:
        st.session_state["cal_expanded"] = set()

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

def sync_calendar_from_qp():
    qp = get_qp()
    action = qp_get_one(qp, "cal", "").strip().lower()
    if not action:
        return

    ym = qp_get_one(qp, "ym", "").strip()
    d_str = qp_get_one(qp, "d", "").strip()
    bp = qp_get_one(qp, "bp", "")

    try:
        if action == "setym":
            if ym:
                st.session_state["cal_ym"] = ym
            st.session_state["cal_view"] = "calendar"

        elif action == "detail":
            if ym:
                st.session_state["cal_ym"] = ym
            if d_str:
                st.session_state["cal_selected_date"] = date.fromisoformat(d_str)
            st.session_state["cal_selected_bp"] = bp
            st.session_state["cal_view"] = "detail"

        elif action == "toggle":
            if d_str:
                dd = date.fromisoformat(d_str)
                expanded: set[date] = st.session_state.get("cal_expanded", set())
                if dd in expanded:
                    expanded.discard(dd)
                else:
                    expanded.add(dd)
                st.session_state["cal_expanded"] = expanded
            st.session_state["cal_view"] = "calendar"
            if ym:
                st.session_state["cal_ym"] = ym

        elif action == "back":
            st.session_state["cal_view"] = "calendar"
            if ym:
                st.session_state["cal_ym"] = ym

    finally:
        set_qp()

def cal_href(action: str, **params) -> str:
    qs = [f"cal={quote(str(action))}"]
    for k, v in params.items():
        if v is None:
            continue
        qs.append(f"{quote(str(k))}={quote(str(v))}")
    return "?" + "&".join(qs)

# =========================
# KPI 계산 캐시(성능)
# =========================
@st.cache_data(ttl=1800, show_spinner=False)
def compute_kpis(df_view: pd.DataFrame, df_rep: pd.DataFrame):
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

    return {
        "total_qty": total_qty,
        "total_cnt": total_cnt,
        "latest_done": latest_done,
        "avg_lt2_overseas": avg_lt2_overseas,
        "top_bp_qty_name": top_bp_qty_name,
        "top_bp_qty_val": top_bp_qty_val,
        "top_bp_cnt_name": top_bp_cnt_name,
        "top_bp_cnt_val": top_bp_cnt_val,
    }

# =========================
# 캘린더 데이터 준비
# =========================
def build_calendar_base_df(pool2: pd.DataFrame, sel_bp: str) -> pd.DataFrame:
    base = pool2.copy()
    if sel_bp != "전체" and COL_BP in base.columns:
        base = base[base[COL_BP].astype(str).str.strip() == sel_bp].copy()
    safe_dt(base, COL_SHIP)
    safe_dt(base, COL_DONE)
    safe_num(base, COL_QTY)
    return base

@st.cache_data(ttl=1800, show_spinner=False)
def build_day_map_cached(cal_base_min: pd.DataFrame, ym: str) -> dict[date, list[dict]]:
    """
    ✅ 성능: 캘린더 day_map 월단위 캐시
    cal_base_min: 필요한 최소 컬럼만 들어온 df
    """
    if cal_base_min is None or cal_base_min.empty:
        return {}

    tmp = cal_base_min.dropna(subset=[COL_SHIP]).copy()
    tmp["_ship_dt"] = pd.to_datetime(tmp[COL_SHIP], errors="coerce")
    tmp = tmp[tmp["_ship_dt"].notna()].copy()
    tmp["_ym"] = tmp["_ship_dt"].dt.strftime("%Y-%m")
    tmp = tmp[tmp["_ym"] == ym].copy()
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

    # ✅ 성능: day_map 계산 최소 컬럼만 전달 + 캐시 사용
    cal_base_min = cal_base[[c for c in [COL_SHIP, COL_BP, COL_QTY, COL_CUST1] if c in cal_base.columns]].copy()
    day_map = build_day_map_cached(cal_base_min, ym)

    prev_ym = add_months(ym, -1)
    next_ym = add_months(ym, +1)

    t1, t2, t3 = st.columns([1.2, 2.2, 1.2], vertical_alignment="center")
    with t1:
        st.markdown(
            f'<div class="cal-nav-wrap"><a class="cal-nav" href="{cal_href("setym", ym=prev_ym)}">◀ 이전달</a></div>',
            unsafe_allow_html=True
        )
    with t2:
        st.markdown(f"### {y}년 {m}월 출고 캘린더")
        st.caption("※ 일자 박스의 BP명을 클릭하면 출고 상세 화면으로 이동합니다. (페이지 전환)")
    with t3:
        st.markdown(
            f'<div class="cal-nav-wrap"><a class="cal-nav" href="{cal_href("setym", ym=next_ym)}">다음달 ▶</a></div>',
            unsafe_allow_html=True
        )

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

                        cls = ""
                        if cust1 == "해외B2B":
                            cls = "overseas"
                        elif cust1 == "국내B2B":
                            cls = "domestic"

                        label = f"{html.escape(str(bp))} ({qsum:,})"
                        href = cal_href("detail", ym=ym, d=d.isoformat(), bp=bp)
                        st.markdown(
                            f'<a class="cal-link {cls}" href="{href}">{label}</a>',
                            unsafe_allow_html=True
                        )

                    if hidden > 0 and (not is_expanded):
                        href_more = cal_href("toggle", ym=ym, d=d.isoformat())
                        st.markdown(
                            f'<a class="cal-action" href="{href_more}">+{hidden}건 더 보기</a>',
                            unsafe_allow_html=True
                        )

                    if is_expanded and len(events) > 3:
                        href_less = cal_href("toggle", ym=ym, d=d.isoformat())
                        st.markdown(
                            f'<a class="cal-action" href="{href_less}">접기</a>',
                            unsafe_allow_html=True
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
    set_qp()
    st.session_state["nav_menu"] = "① 출고 캘린더"
    safe_rerun()

with st.spinner("Google Sheet RAW 로딩 중..."):
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
# KPI cards (cached)
# =========================
k = compute_kpis(df_view, df_rep)

st.markdown(
    f"""
    <div class="kpi-wrap">
      <div class="kpi-card">
        <div class="kpi-title">총 출고수량(합)</div>
        <div class="kpi-value">{(f"{k['total_qty']:,.0f}" if k['total_qty'] is not None else "-")}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">총 출고건수(합)</div>
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
        <div class="kpi-title">출고건수 TOP BP</div>
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

# =========================
# ① 출고 캘린더 / 상세 라우팅
# =========================
if nav == "① 출고 캘린더":
    init_calendar_state()
    sync_calendar_from_qp()

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
        st.markdown(
            f'<a class="cal-nav" href="{cal_href("back", ym=ym)}" style="display:inline-block;width:auto;padding:0.45rem 0.7rem;">← 캘린더로 돌아가기</a>',
            unsafe_allow_html=True
        )

        if ship_date is None or str(bp_s).strip() == "":
            st.warning("상세 조회 대상이 없습니다. 캘린더에서 BP를 클릭해 주세요.")
            st.stop()

        d = cal_base.copy()
        if not need_cols(d, [COL_SHIP, COL_BP, COL_QTY, COL_ITEM_CODE, COL_ITEM_NAME], "출고 상세"):
            st.stop()

        d["_ship_date"] = pd.to_datetime(d[COL_SHIP], errors="coerce").dt.date
        sub = d[(d["_ship_date"] == ship_date) & (d[COL_BP].astype(str).str.strip() == str(bp_s).strip())].copy()

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

# =========================
# ②~⑥ 나머지 탭: 기존 로직 유지
# (성능개선 포인트는 load/kpi/calendar 쪽에 집중)
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

    q = st.text_input(
        "품목코드 검색 (부분검색 가능)",
        value="",
        placeholder="예: B0GF057A1",
        key="sku_query"
    )

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

            dsku[COL_SHIP] = dsku[COL_SHIP].replace("", pd.NA)

            if not show_all_history:
                today_ts = pd.Timestamp(date.today())
                ship_dt = pd.to_datetime(dsku[COL_SHIP], errors="coerce")
                dsku = dsku[(ship_dt.isna()) | (ship_dt >= today_ts)].copy()

            def ship_to_label(x):
                if pd.isna(x):
                    return "미정"
                return fmt_date(x)

            dsku["출고예정일"] = dsku[COL_SHIP].apply(ship_to_label)

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

            if (not mom_items) and (not trend_items) and (not bp_spike_items):
                st.caption("코멘트 산출에 필요한 월별 데이터가 부족합니다. (월 데이터 2개월 이상 필요)")

            st.divider()

            out = (
                dsku.groupby(["출고예정일", COL_BP], dropna=False)[COL_QTY]
                .sum(min_count=1)
                .reset_index()
                .rename(columns={COL_BP: "BP명", COL_QTY: "요청수량"})
            )
            out["요청수량"] = out["요청수량"].fillna(0).round(0).astype(int)
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
                number_cols=["요청수량"],
            )
    else:
        st.info("상단에 품목코드를 입력하면, 해당 SKU의 코멘트 및 히스토리가 표시됩니다.")

    st.divider()

    period_title = "누적 SKU Top10 (요청수량 기준)" if sel_month_label == "전체" else f"{sel_month_label} SKU Top10 (요청수량 기준)"
    st.markdown(f"### {period_title}")

    top10_sku = build_item_top10_with_bp(df_view.copy())
    render_pretty_table(
        top10_sku,
        height=520,
        wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"],
        col_width_px={"순위": 60, COL_ITEM_CODE: 130, COL_ITEM_NAME: 420, "요청수량_합": 120, "BP명(요청수량)": 520},
        number_cols=["요청수량_합"],
    )
    st.caption("※ BP명(요청수량)은 해당 SKU의 출고처별 수량 합계입니다. (왼쪽 필터 범위 기준)")

elif nav == "③ 주차요약":
    st.subheader("주차요약")
    d = df_view.copy()
    if not need_cols(d, [COL_QTY, COL_BP, COL_ITEM_CODE, COL_ITEM_NAME], "주차요약"):
        st.stop()

    week_list = [x for x in d["_week_label"].dropna().astype(str).unique().tolist() if x.strip() != ""]
    week_list = sorted(week_list, key=parse_week_label_key)

    if not week_list:
        st.info("주차 목록이 없습니다.")
        st.stop()

    sel_week = st.selectbox("주차 선택", week_list, index=len(week_list) - 1, key="wk_sel_week")
    wdf = d[d["_week_label"].astype(str) == str(sel_week)].copy()

    cur_key_num = week_key_num_from_label(sel_week)
    cur_idx = week_list.index(sel_week) if sel_week in week_list else None

    if cur_idx is None or cur_idx == 0:
        prev_wdf = pd.DataFrame()
        prev_week = None
    else:
        prev_week = week_list[cur_idx - 1]
        prev_wdf = d[d["_week_label"].astype(str) == str(prev_week)].copy()

    comment_items = []
    comment_items += new_bp_comment(all_df=d, cur_df=wdf, key_col_num="_week_key_num", cur_key_num=cur_key_num)
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
        col_width_px={"순위": 60, COL_BP: 240, COL_ITEM_CODE: 120, COL_ITEM_NAME: 420, COL_QTY: 120},
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
        col_width_px={"순위": 60, COL_ITEM_CODE: 130, COL_ITEM_NAME: 420, "요청수량_합": 120, "BP명(요청수량)": 520},
        number_cols=["요청수량_합"],
    )
    st.caption("※ 품목 Top5는 선택 주차 내 ‘품목 기준 요청수량 합’ TOP5이며, BP명은 해당 품목에 포함된 BP를 (BP별 수량)과 함께 나열합니다.")
    st.divider()

    st.subheader("전주 대비 급증 SKU 리포트 (+30% 이상 증가)")
    if cur_idx is None or cur_idx == 0:
        st.info("전주 비교를 위해서는 선택 주차 이전의 주차 데이터가 필요합니다.")
    else:
        prev_week2 = week_list[cur_idx - 1]
        prev_wdf2 = d[d["_week_label"].astype(str) == str(prev_week2)].copy()
        spike_df = build_spike_report_only(wdf, prev_wdf2)

        st.caption(
            f"※ 비교 기준: 선택 주차({sel_week}) vs 전주({prev_week2}) | "
            f"급증 정의: 현재 요청수량 ≥ 전주 요청수량 × {SPIKE_FACTOR} (전주 대비 +30% 이상 증가)"
        )

        render_pretty_table(
            spike_df,
            height=520,
            wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"],
            col_width_px={
                COL_ITEM_CODE: 130, COL_ITEM_NAME: 420,
                "이전_요청수량": 120, "현재_요청수량": 120,
                "증가배수": 90, "BP명(요청수량)": 520
            },
            number_cols=["이전_요청수량", "현재_요청수량", "증가배수"],
        )

elif nav == "④ 월간요약":
    st.subheader("월간요약")

    d = df_view.copy()
    if not need_cols(d, [COL_QTY, COL_BP, COL_ITEM_CODE, COL_ITEM_NAME], "월간요약"):
        st.stop()

    month_list = [x for x in d["_month_label"].dropna().astype(str).unique().tolist() if x.strip() != ""]
    month_list = list(dict.fromkeys(month_list))
    month_list = sorted(month_list, key=parse_month_label_key)

    if not month_list:
        st.info("월 목록이 없습니다. RAW의 '년', '월1' 컬럼을 확인해 주세요.")
        st.stop()

    sel_month_label2 = st.selectbox("월 선택", month_list, index=len(month_list) - 1, key="m_sel_month")
    mdf = d[d["_month_label"].astype(str) == str(sel_month_label2)].copy()

    cur_key_num = month_key_num_from_label(sel_month_label2)
    cur_idx = month_list.index(sel_month_label2) if sel_month_label2 in month_list else None

    if cur_idx is None or cur_idx == 0:
        prev_mdf = pd.DataFrame()
        prev_month = None
    else:
        prev_month = month_list[cur_idx - 1]
        prev_mdf = d[d["_month_label"].astype(str) == str(prev_month)].copy()

    comment_items = []
    comment_items += new_bp_comment(all_df=d, cur_df=mdf, key_col_num="_month_key_num", cur_key_num=cur_key_num)
    comment_items += period_kpi_delta_comment(cur_df=mdf, prev_df=prev_mdf)
    comment_items += category_top_comment(mdf, top_n=2)
    comment_items += concentration_comment(mdf)
    comment_items += undated_ship_risk_comment(mdf)

    render_numbered_block("월간 특이사항 (자동 코멘트)", comment_items)
    if prev_month:
        st.caption(f"※ 비교 기준: 선택 월({sel_month_label2}) vs 전월({prev_month})")
    st.divider()

    st.markdown("### 📌 월간 리포트 생성(복사해서 슬랙에 바로 붙여넣기)")
    next_month = _month_label_next(sel_month_label2)
    if st.button("📝 월간 리포트 생성", key="btn_month_report"):
        report_text = _build_monthly_report_text(
            base_df=d,
            sel_month_label=sel_month_label2,
            prev_month_label=prev_month,
            next_month_label=next_month
        )
        st.session_state["monthly_report_text"] = report_text

    if "monthly_report_text" in st.session_state:
        st.text_area(
            "월간 리포트 (Ctrl+C로 복사)",
            value=st.session_state["monthly_report_text"],
            height=420
        )
        st.caption("※ 리포트는 현재 좌측 필터 범위(거래처구분1/2/BP 등) 기준으로 생성됩니다. (월 필터는 리포트 내부에서 선택월 기준 적용)")

    st.divider()

    st.subheader("월 선택 → Top 10 (BP/품목코드/품목명/요청수량)")
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
        col_width_px={"순위": 60, COL_BP: 240, COL_ITEM_CODE: 120, COL_ITEM_NAME: 420, COL_QTY: 120},
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
        col_width_px={"순위": 60, COL_ITEM_CODE: 130, COL_ITEM_NAME: 420, "요청수량_합": 120, "BP명(요청수량)": 520},
        number_cols=["요청수량_합"],
    )
    st.caption("※ 품목 Top5는 선택 월 내 ‘품목 기준 요청수량 합’ TOP5이며, BP명은 해당 품목에 포함된 BP를 (BP별 수량)과 함께 나열합니다.")
    st.divider()

    st.subheader("전월 대비 급증 SKU 리포트 (+30% 이상 증가)")
    if cur_idx is None or cur_idx == 0:
        st.info("전월 비교를 위해서는 선택 월 이전의 월 데이터가 필요합니다.")
    else:
        prev_month_label = month_list[cur_idx - 1]
        prev_mdf2 = d[d["_month_label"].astype(str) == str(prev_month_label)].copy()
        spike_df = build_spike_report_only(mdf, prev_mdf2)

        st.caption(
            f"※ 비교 기준: 선택 월({sel_month_label2}) vs 전월({prev_month_label}) | "
            f"급증 정의: 현재 요청수량 ≥ 전월 요청수량 × {SPIKE_FACTOR} (전월 대비 +30% 이상 증가)"
        )

        render_pretty_table(
            spike_df,
            height=520,
            wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"],
            col_width_px={
                COL_ITEM_CODE: 130, COL_ITEM_NAME: 420,
                "이전_요청수량": 120, "현재_요청수량": 120,
                "증가배수": 90, "BP명(요청수량)": 520
            },
            number_cols=["이전_요청수량", "현재_요청수량", "증가배수"],
        )

elif nav == "⑤ 국가별 조회":
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

    for c in ["평균_리드타임_작업완료기준", "리드타임_중간값_작업완료기준", "리드타임 느린 상위10% 기준(P90)"]:
        out[c] = out[c].round(2)

    out = out.sort_values("요청수량_합", ascending=False, na_position="last")

    render_pretty_table(
        out[[COL_CUST2, "요청수량_합", "평균_리드타임_작업완료기준", "리드타임_중간값_작업완료기준",
             "리드타임 느린 상위10% 기준(P90)", "출고건수", "집계행수_표본"]],
        height=520,
        wrap_cols=[COL_CUST2],
        col_width_px={COL_CUST2: 200, "요청수량_합": 120, "출고건수": 90, "집계행수_표본": 110},
        number_cols=["요청수량_합", "출고건수", "집계행수_표본"],
    )
    st.caption("※ P90은 ‘느린 상위 10%’ 경계값(리드타임이 큰 구간)입니다.")

elif nav == "⑥ BP명별 조회":
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

    out = out[[COL_BP, "요청수량_합", "평균_리드타임_작업완료기준", "리드타임_중간값_작업완료기준",
               "최근_출고일", "최근_작업완료일", "출고건수", "집계행수_표본"]].sort_values("요청수량_합", ascending=False, na_position="last")

    render_pretty_table(
        out,
        height=520,
        wrap_cols=[COL_BP],
        col_width_px={COL_BP: 280, "요청수량_합": 120, "출고건수": 90, "집계행수_표본": 110},
        number_cols=["요청수량_합", "출고건수", "집계행수_표본"],
    )

st.caption("※ 모든 집계는 Google Sheet RAW 기반이며, 제품분류(B0/B1) 고정 + 선택한 필터 범위 내에서 계산됩니다.")

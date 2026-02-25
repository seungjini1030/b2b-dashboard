# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반)
# - 메뉴 순서: ① 출고캘린더 -> ② SKU별 조회 -> ③ 주차요약 -> ④ 월간요약 -> ⑤ 국가별 조회 -> ⑥ BP명별 조회
# - ✅ 출고캘린더:
#    * 월 이동(이전/다음)
#    * 해외B2B/국내B2B 토글(상단 구별/범례 제거, 색상은 캘린더 내 BP 버튼에만 적용)
#    * 캘린더 셀(일자 박스) 내부에 BP 버튼(링크형) 표시
#    * BP 클릭 -> 상세 페이지 전환(새창 X) / 뒤로가기 버튼 제공
#    * "+N건" 클릭 -> 해당 날짜 전체 펼치기(토글)
#    * 출고일자 우선, 없으면 작업완료일 기준으로 캘린더 배치
#
# - SKU별 조회 UI: 품목코드 검색(상단) -> 누적 SKU Top10(하단)
# - SKU 자동 코멘트(룰 기반): MoM(2개월), 추이(3개월: 패턴 상세), BP 급증 사례(월단위)
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
import streamlit as st
import pandas as pd
import html
from datetime import date, datetime
import calendar as _cal

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

/* ✅ 캘린더 */
.cal-wrap{margin-top:0.25rem;}
.cal-header{
  display:flex; align-items:center; justify-content:space-between;
  gap:0.75rem; margin: 0.4rem 0 0.6rem 0;
}
.cal-title{
  font-size:1.15rem; font-weight:900; color:#111827;
}
.cal-btns{
  display:flex; align-items:center; gap:0.5rem;
}
.cal-filter{
  display:flex; align-items:center; gap:0.45rem;
}
.cal-filter a{
  text-decoration:none;
  border:1px solid #e5e7eb;
  background:#fff;
  color:#111827;
  padding:6px 10px;
  border-radius:10px;
  font-size:0.92rem;
  font-weight:800;
}
.cal-filter a.on{
  border-color:#d1d5db;
  box-shadow: 0 1px 0 rgba(0,0,0,0.03);
}

/* 요일 헤더 */
.cal-dow{
  display:grid; grid-template-columns:repeat(7, 1fr);
  gap:10px; margin: 0.25rem 0 0.35rem 0;
}
.cal-dow div{
  color:#6b7280;
  font-size:0.88rem;
  font-weight:800;
  padding: 0 2px;
}

/* 날짜 그리드 */
.cal-grid{
  display:grid;
  grid-template-columns:repeat(7, 1fr);
  gap:10px;
}
.cal-cell{
  border:1px solid #edf2f7;
  border-radius: 12px;
  background:#fff;
  padding:8px 8px 8px 8px;        /* ✅ 최대한 좁게 */
  min-height: 96px;               /* ✅ 박스 높이 낮게 */
  overflow:hidden;
}
.cal-cell.empty{
  background:#fcfcfd;
  border:1px dashed #f1f5f9;
}
.cal-day{
  display:flex;
  align-items:center;
  justify-content:space-between;
  margin-bottom:6px;
}
.cal-day .n{
  font-size:0.92rem;
  font-weight:900;
  color:#111827;
}
.cal-items{
  display:flex;
  flex-direction:column;
  gap:6px;
}
a.bp-chip{
  display:inline-flex;
  align-items:center;
  gap:6px;
  text-decoration:none;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  padding: 6px 8px;
  font-size: 0.82rem;            /* ✅ BP명 글자크기 줄임 */
  font-weight: 800;
  line-height: 1.05rem;
  color:#111827;
  background:#fff;
  max-width:100%;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}
a.bp-chip.over{
  background:#EDE9FE;            /* ✅ 연보라 */
  border-color:#C4B5FD;
  color:#4C1D95;
}
a.bp-chip.dom{
  background:#E0F2FE;            /* ✅ 연하늘 */
  border-color:#7DD3FC;
  color:#0C4A6E;
}
a.more-chip{
  display:inline-flex;
  text-decoration:none;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  padding: 6px 8px;
  font-size: 0.82rem;
  font-weight: 900;
  color:#111827;
  background:#fff;
  width: fit-content;
}
.cal-note{
  color:#6b7280;
  font-size:0.9rem;
  margin: 0.15rem 0 0.35rem 0;
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
# ✅ 월간 리포트 생성 helpers
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

# -------------------------
# Query params helpers (HTML 링크 클릭용)
# -------------------------
def _get_qp() -> dict:
    try:
        return st.experimental_get_query_params()
    except Exception:
        return {}

def _set_qp(**kwargs):
    try:
        st.experimental_set_query_params(**kwargs)
    except Exception:
        pass

def _clear_qp():
    _set_qp()

def _qp_first(qp: dict, key: str) -> str | None:
    v = qp.get(key)
    if not v:
        return None
    if isinstance(v, list):
        return v[0] if v else None
    return str(v)

# -------------------------
# ✅ 캘린더 helpers
# -------------------------
def _cal_pick_date(row: pd.Series) -> pd.Timestamp | pd.NaT:
    ship_dt = row.get(COL_SHIP, pd.NaT)
    done_dt = row.get(COL_DONE, pd.NaT)
    base = ship_dt if pd.notna(ship_dt) else done_dt
    return pd.to_datetime(base, errors="coerce") if pd.notna(base) else pd.NaT

def _build_calendar_events(df: pd.DataFrame) -> pd.DataFrame:
    """
    캘린더용 대표 이벤트(날짜+BP+거래처구분1)로 압축
    - 날짜: 출고일자 우선, 없으면 작업완료
    - BP, 거래처구분1 기준으로 그룹
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["_cal_date", COL_BP, COL_CUST1, "qty"])
    tmp = df.copy()
    tmp["_cal_date"] = tmp.apply(_cal_pick_date, axis=1)
    tmp = tmp[tmp["_cal_date"].notna()].copy()
    if tmp.empty:
        return pd.DataFrame(columns=["_cal_date", COL_BP, COL_CUST1, "qty"])
    if COL_QTY not in tmp.columns:
        tmp["qty"] = 0
    g = (
        tmp.groupby(["_cal_date", COL_BP, COL_CUST1], dropna=False)[COL_QTY]
        .sum(min_count=1)
        .reset_index()
        .rename(columns={COL_QTY: "qty"})
    )
    g["_cal_date"] = pd.to_datetime(g["_cal_date"]).dt.date
    g[COL_BP] = g[COL_BP].astype(str).str.strip()
    g[COL_CUST1] = g[COL_CUST1].astype(str).str.strip()
    g["qty"] = pd.to_numeric(g["qty"], errors="coerce").fillna(0)
    return g

def _month_shift(y: int, m: int, delta: int) -> tuple[int, int]:
    mm = m + delta
    yy = y
    while mm <= 0:
        yy -= 1
        mm += 12
    while mm >= 13:
        yy += 1
        mm -= 12
    return yy, mm

def _ym_label(y: int, m: int) -> str:
    return f"{y}년 {m}월"

def _safe_parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _toggle_day_expand(d: date):
    if "cal_expand_days" not in st.session_state:
        st.session_state["cal_expand_days"] = set()
    s = st.session_state["cal_expand_days"]
    if d in s:
        s.remove(d)
    else:
        s.add(d)
    st.session_state["cal_expand_days"] = s

def _is_overseas(cust1: str) -> bool:
    return str(cust1).strip() == "해외B2B"

def _chip_class(cust1: str) -> str:
    return "over" if _is_overseas(cust1) else "dom"

# -------------------------
# Main
# -------------------------
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
        # 캘린더 상태
        "cal_year", "cal_month", "cal_show_over", "cal_show_dom", "cal_page", "cal_detail_bp", "cal_detail_date", "cal_expand_days"
    ]
    for k in reset_keys:
        if k in st.session_state:
            del st.session_state[k]
    _clear_qp()
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
# Navigation (✅ 캘린더를 1번으로)
# =========================
nav = st.radio(
    "메뉴",
    ["① 출고캘린더", "② SKU별 조회", "③ 주차요약", "④ 월간요약", "⑤ 국가별 조회", "⑥ BP명별 조회"],
    horizontal=True,
    key="nav_menu"
)

# nav가 캘린더가 아니면 query param을 정리(캘린더 HTML 링크 잔여 방지)
if nav != "① 출고캘린더":
    qp = _get_qp()
    if qp:
        _clear_qp()

# =========================
# ① 출고캘린더
# =========================
if nav == "① 출고캘린더":
    st.subheader("출고캘린더")

    # 캘린더는 좌측 필터 중 거래처구분1/2만 반영 (월/BP 필터는 미반영)
    # -> pool2: 거래처구분1/2 까지만 반영된 데이터
    cal_base = pool2.copy()

    # 상태 초기화
    if "cal_year" not in st.session_state or "cal_month" not in st.session_state:
        today = date.today()
        st.session_state["cal_year"] = int(today.year)
        st.session_state["cal_month"] = int(today.month)

    if "cal_show_over" not in st.session_state:
        st.session_state["cal_show_over"] = True
    if "cal_show_dom" not in st.session_state:
        st.session_state["cal_show_dom"] = True

    if "cal_page" not in st.session_state:
        st.session_state["cal_page"] = "calendar"  # calendar | detail
    if "cal_expand_days" not in st.session_state:
        st.session_state["cal_expand_days"] = set()

    # query params 처리 (HTML 링크 클릭 이벤트)
    qp = _get_qp()
    qp_view = _qp_first(qp, "view")
    qp_bp = _qp_first(qp, "bp")
    qp_d = _safe_parse_date(_qp_first(qp, "d"))
    qp_prev = _qp_first(qp, "prev")
    qp_next = _qp_first(qp, "next")
    qp_t_over = _qp_first(qp, "t_over")
    qp_t_dom = _qp_first(qp, "t_dom")
    qp_expand = _safe_parse_date(_qp_first(qp, "expand"))

    # 월 이동
    if qp_prev == "1":
        y, m = _month_shift(int(st.session_state["cal_year"]), int(st.session_state["cal_month"]), -1)
        st.session_state["cal_year"], st.session_state["cal_month"] = y, m
        _clear_qp()
        st.rerun()
    if qp_next == "1":
        y, m = _month_shift(int(st.session_state["cal_year"]), int(st.session_state["cal_month"]), +1)
        st.session_state["cal_year"], st.session_state["cal_month"] = y, m
        _clear_qp()
        st.rerun()

    # 토글(해외/국내)
    if qp_t_over == "1":
        st.session_state["cal_show_over"] = not bool(st.session_state["cal_show_over"])
        _clear_qp()
        st.rerun()
    if qp_t_dom == "1":
        st.session_state["cal_show_dom"] = not bool(st.session_state["cal_show_dom"])
        _clear_qp()
        st.rerun()

    # +N건 펼치기 토글
    if qp_expand:
        _toggle_day_expand(qp_expand)
        _clear_qp()
        st.rerun()

    # 상세 전환
    if qp_view == "detail" and qp_bp and qp_d:
        st.session_state["cal_page"] = "detail"
        st.session_state["cal_detail_bp"] = qp_bp
        st.session_state["cal_detail_date"] = qp_d
        _clear_qp()
        st.rerun()

    # 뒤로가기
    if qp_view == "calendar":
        st.session_state["cal_page"] = "calendar"
        _clear_qp()
        st.rerun()

    # 이벤트 테이블
    events = _build_calendar_events(cal_base)

    # 상세 페이지
    if st.session_state.get("cal_page") == "detail":
        bp = st.session_state.get("cal_detail_bp")
        d0 = st.session_state.get("cal_detail_date")
        st.markdown(f"### 📌 {html.escape(str(bp))} / {d0.strftime('%Y-%m-%d')} 출고 상세")

        # back (페이지 전환)
        st.markdown(
            f"""
            <div style="margin:0.2rem 0 0.6rem 0;">
              <a class="more-chip" href="?view=calendar">← 출고캘린더로 돌아가기</a>
            </div>
            """,
            unsafe_allow_html=True
        )

        # 상세 데이터(해당 날짜 + BP)
        tmp = cal_base.copy()
        tmp["_cal_date"] = tmp.apply(_cal_pick_date, axis=1)
        tmp = tmp[tmp["_cal_date"].notna()].copy()
        if not tmp.empty:
            tmp["_cal_date"] = pd.to_datetime(tmp["_cal_date"]).dt.date
            tmp = tmp[(tmp[COL_BP].astype(str).str.strip() == str(bp).strip()) & (tmp["_cal_date"] == d0)].copy()

        if tmp.empty:
            st.info("해당 조건의 상세 데이터가 없습니다.")
        else:
            ship_dt = tmp[COL_SHIP].dropna() if COL_SHIP in tmp.columns else pd.Series([], dtype="datetime64[ns]")
            done_dt = tmp[COL_DONE].dropna() if COL_DONE in tmp.columns else pd.Series([], dtype="datetime64[ns]")

            ship_show = fmt_date(ship_dt.min()) if not ship_dt.empty else "-"
            done_show = fmt_date(done_dt.max()) if not done_dt.empty else "-"

            req_sum = int(round(float(tmp[COL_QTY].fillna(0).sum()), 0)) if COL_QTY in tmp.columns else 0
            render_mini_kpi("요청수량합", f"{req_sum:,}")

            st.markdown(
                f"""
                - **출고일자:** {ship_show}
                - **작업완료:** {done_show}
                """.strip()
            )
            st.divider()

            # 품목 상세
            if need_cols(tmp, [COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY], "출고 상세"):
                detail = (
                    tmp.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
                    .sum(min_count=1)
                    .reset_index()
                    .rename(columns={COL_QTY: "요청수량"})
                    .sort_values("요청수량", ascending=False, na_position="last")
                )
                detail["요청수량"] = pd.to_numeric(detail["요청수량"], errors="coerce").fillna(0).round(0).astype(int)
                render_pretty_table(
                    detail[[COL_ITEM_CODE, COL_ITEM_NAME, "요청수량"]],
                    height=520,
                    wrap_cols=[COL_ITEM_NAME],
                    col_width_px={COL_ITEM_CODE: 150, COL_ITEM_NAME: 520, "요청수량": 120},
                    number_cols=["요청수량"],
                )

    # 캘린더 페이지
    else:
        y = int(st.session_state["cal_year"])
        m = int(st.session_state["cal_month"])

        show_over = bool(st.session_state["cal_show_over"])
        show_dom = bool(st.session_state["cal_show_dom"])

        # 상단 헤더 (범례/구별 제거, 토글만 유지)
        # 토글 색상 표시는 "캘린더 내 BP 칩"에만 적용(요청 반영)
        over_cls = "on" if show_over else ""
        dom_cls = "on" if show_dom else ""
        st.markdown(
            f"""
            <div class="cal-header">
              <div class="cal-btns">
                <a class="more-chip" href="?prev=1">◀</a>
                <div class="cal-title">{_ym_label(y, m)}</div>
                <a class="more-chip" href="?next=1">▶</a>
              </div>
              <div class="cal-filter">
                <a class="{over_cls}" href="?t_over=1">해외B2B</a>
                <a class="{dom_cls}" href="?t_dom=1">국내B2B</a>
              </div>
            </div>
            <div class="cal-note">※ 캘린더는 좌측 필터 중 ‘거래처구분1/2’만 반영합니다. (월/BP 필터는 캘린더 내부 이동을 위해 미적용)</div>
            """,
            unsafe_allow_html=True
        )

        # 월 내 이벤트만
        if not events.empty:
            ev = events.copy()
            ev["_y"] = pd.to_datetime(ev["_cal_date"]).dt.year
            ev["_m"] = pd.to_datetime(ev["_cal_date"]).dt.month
            ev = ev[(ev["_y"] == y) & (ev["_m"] == m)].copy()
        else:
            ev = pd.DataFrame(columns=["_cal_date", COL_BP, COL_CUST1, "qty"])

        # 토글 반영
        if not ev.empty:
            if not show_over:
                ev = ev[ev[COL_CUST1].astype(str).str.strip() != "해외B2B"].copy()
            if not show_dom:
                ev = ev[ev[COL_CUST1].astype(str).str.strip() != "국내B2B"].copy()

        # 날짜 -> 이벤트 리스트(표시용)
        by_day: dict[date, list[dict]] = {}
        if not ev.empty:
            for d1, sub in ev.groupby("_cal_date"):
                items = []
                sub = sub.sort_values("qty", ascending=False, na_position="last")
                for _, r in sub.iterrows():
                    items.append({
                        "bp": str(r[COL_BP]).strip(),
                        "cust1": str(r[COL_CUST1]).strip(),
                        "qty": float(r.get("qty", 0) or 0),
                    })
                by_day[d1] = items

        # 캘린더 레이아웃(월요일 시작)
        cal = _cal.Calendar(firstweekday=0)  # 0=Monday
        month_days = cal.monthdatescalendar(y, m)  # weeks (list of 7 dates)

        # 요일
        st.markdown(
            """
            <div class="cal-dow">
              <div>월</div><div>화</div><div>수</div><div>목</div><div>금</div><div>토</div><div>일</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        # 그리드
        st.markdown('<div class="cal-wrap"><div class="cal-grid">', unsafe_allow_html=True)

        MAX_SHOW = 4  # 기본 표시 개수(나머지는 +N건)

        for week in month_days:
            for d1 in week:
                # d1은 date
                in_month = (d1.month == m)
                items = by_day.get(d1, [])

                if not in_month:
                    st.markdown('<div class="cal-cell empty"></div>', unsafe_allow_html=True)
                    continue

                # 확장 여부
                expanded = d1 in st.session_state.get("cal_expand_days", set())
                show_items = items if expanded else items[:MAX_SHOW]
                hidden_n = max(0, len(items) - len(show_items))

                # 셀 HTML 구성 (✅ 버튼을 셀 박스 안에 넣기 위해 전부 HTML 링크로 구성)
                cell_html = []
                cell_html.append('<div class="cal-cell">')
                cell_html.append(
                    f"""
                    <div class="cal-day">
                      <div class="n">{d1.day}</div>
                    </div>
                    """
                )
                cell_html.append('<div class="cal-items">')

                if not items:
                    cell_html.append('<div style="color:#94a3b8; font-size:0.85rem; font-weight:800;">-</div>')
                else:
                    for it in show_items:
                        bp = html.escape(it["bp"])
                        cls = _chip_class(it["cust1"])
                        # BP 클릭 -> detail 페이지 전환
                        cell_html.append(f'<a class="bp-chip {cls}" href="?view=detail&bp={html.escape(it["bp"])}&d={d1.strftime("%Y-%m-%d")}">{bp}</a>')

                    # +N건 (토글)
                    if hidden_n > 0:
                        cell_html.append(f'<a class="more-chip" href="?expand={d1.strftime("%Y-%m-%d")}">+{hidden_n}건</a>')
                    elif expanded and len(items) > MAX_SHOW:
                        # 이미 확장된 상태에서 다시 접기 토글을 제공하고 싶으면 여기서 제공 가능
                        cell_html.append(f'<a class="more-chip" href="?expand={d1.strftime("%Y-%m-%d")}">접기</a>')

                cell_html.append('</div></div>')

                st.markdown("".join(cell_html), unsafe_allow_html=True)

        st.markdown('</div></div>', unsafe_allow_html=True)

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

# =========================
# ③ 주차요약
# =========================
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

# =========================
# ④ 월간요약
# =========================
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

# =========================
# ⑤ 국가별 조회
# =========================
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

# =========================
# ⑥ BP명별 조회
# =========================
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

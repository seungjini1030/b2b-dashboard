# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반)
# - 메뉴 순서: ① SKU별 조회 -> ② 주차요약 -> ③ 월간요약 -> ④ 국가별 조회 -> ⑤ BP명별 조회
# - SKU별 조회 UI: 품목코드 검색(상단) -> 누적 SKU Top10(하단)
# - SKU 자동 코멘트(룰 기반): MoM(2개월), 추이(3개월: 패턴 상세), BP 급증 사례(월단위)
# - 코멘트 UI: 헤더-내용은 붙이고, 블록 간격만 확보(가독성 개선)
# - 주차 라벨: 출고일자 우선(없으면 작업완료일)로 산정하여 유령 주차 방지
# - 전주/전월 +30% 급증 리포트: dtype(object) 에러 방지(증가배수 numeric 강제)
# - ✅ 주차/월간 자동코멘트(기존 유지):
#    1) 신규 BP 출고(과거 전체기간에 없던 BP가 해당 주/월에 처음 등장)
#    2) 직전기간 대비 KPI(현재값 + 증감 표기): 발주건수(주문번호 distinct)/출고건수(대표행)/출고수량/평균 리드타임
#    3) 카테고리 라인 TOP2(출고수량 기준)
#    4) Top BP 집중도: BP명(수량) + 점유율
#    5) Top SKU 집중도: 품목코드/품목명(수량) + 점유율
#    6) 출고일 미정 리스크(가능할 때만 표시)
# - ✅ 월간 리포트(버튼 클릭 시 생성 + 복사 가능):
#    - 해외B2B/국내B2B 섹션 분리
#    - BP명 기반 "사람이 쓰는 문장" 형태 자동 생성(쿠팡/올영/국군복지단 등)
#    - 해외B2B만 JP/CN 라인 제외 전월 대비 증가 SKU(%로 표현)
#    - 차월(다음달) 대량 출고 예정 Top3: 출고일자 기준, BP/품목/수량 + (특이 없으면 생략)
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
COL_SHIP = "출고일자"
COL_LT2 = "리드타임2"
COL_BP = "BP명"
COL_MAIN = "대표행"
COL_CUST1 = "거래처구분1"
COL_CUST2 = "거래처구분2"
COL_CLASS = "제품분류"
COL_ITEM_CODE = "품목코드"
COL_ITEM_NAME = "품목명"
COL_ORDER_DATE = "발주일자"
COL_ORDER_NO = "주문번호"  # ✅ 발주건수 = 주문번호 distinct (중복 제거)

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
    """
    - 4) Top BP 집중도: 1위 BP명(수량) 점유율
    - 5) Top SKU 집중도: 1위 품목코드 / 품목명(수량) 점유율
    """
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
    """
    예) 발주건수 35건 (-17 ▼) / 출고건수 18건 (+3 ▲) / 출고수량 10,000개 (-500 ▼) / 평균 리드타임 6.2일 (-2 ▼)
    """
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

# =========================
# ✅ 월간 리포트(문장형) helpers
# =========================
def _pct(curr: float, prev: float) -> float | None:
    if prev is None or prev <= 0:
        return None
    return (curr / prev - 1.0) * 100.0

def _sum_qty(df: pd.DataFrame) -> int:
    if df is None or df.empty or COL_QTY not in df.columns:
        return 0
    return int(round(float(df[COL_QTY].fillna(0).sum()), 0))

def _nunique(df: pd.DataFrame, col: str) -> int:
    if df is None or df.empty or col not in df.columns:
        return 0
    s = df[col].astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    return int(s.dropna().nunique())

def _month_key(label: str) -> tuple[int, int]:
    return parse_month_label_key(label)

def _month_label_from_dt(dtval: pd.Timestamp) -> str | None:
    if pd.isna(dtval):
        return None
    return make_month_label(int(dtval.year), int(dtval.month))

def _top_bp_list(df: pd.DataFrame, top_n: int = 3) -> list[str]:
    if df is None or df.empty or COL_BP not in df.columns or COL_QTY not in df.columns:
        return []
    g = df.groupby(COL_BP)[COL_QTY].sum().sort_values(ascending=False).head(top_n)
    return [str(x) for x in g.index.tolist()]

def _format_bp_qty_breakdown(df: pd.DataFrame, sku_code: str, top_n: int = 3) -> str:
    if df is None or df.empty:
        return ""
    sub = df[df[COL_ITEM_CODE].astype(str).str.strip() == str(sku_code).strip()].copy()
    if sub.empty or COL_BP not in sub.columns or COL_QTY not in sub.columns:
        return ""
    g = sub.groupby(COL_BP)[COL_QTY].sum().sort_values(ascending=False).head(top_n)
    parts = [f"{bp}({_fmt_int(q)})" for bp, q in g.items()]
    return " / ".join(parts)

def _top_sku_mass_shipments(df: pd.DataFrame, top_n: int = 4, bp_break_top: int = 3) -> list[str]:
    if df is None or df.empty or not all(c in df.columns for c in [COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY]):
        return []
    g = (
        df.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY]
        .sum().sort_values(ascending=False).head(top_n)
    )
    out = []
    rank = 1
    for (code, name), qty in g.items():
        bd = _format_bp_qty_breakdown(df, code, top_n=bp_break_top)
        out.append(f"{rank}️⃣ {code} {name} : {_fmt_int(qty)}개")
        if bd:
            out.append(f"→ {bd}")
        rank += 1
    return out

def _sku_mom_change_lines(cur_df: pd.DataFrame, prev_df: pd.DataFrame, top_n: int = 6) -> list[str]:
    if cur_df is None or cur_df.empty or COL_QTY not in cur_df.columns:
        return []
    cur = (
        cur_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY]
        .sum().reset_index(name="cur")
    )
    prev = (
        prev_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY]
        .sum().reset_index(name="prev")
    ) if (prev_df is not None and not prev_df.empty and COL_QTY in prev_df.columns) else pd.DataFrame(columns=[COL_ITEM_CODE, COL_ITEM_NAME, "prev"])

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
        pct = float(r["pct"])
        out.append(f"- {code} {name} : {pct:+.0f}%")
    return out

def _jp_cn_excluded_increase(cur_df: pd.DataFrame, prev_df: pd.DataFrame, jp_cn_tokens: list[str], top_n: int = 5) -> list[str]:
    if cur_df is None or cur_df.empty or COL_CUST2 not in cur_df.columns:
        return []

    def _is_jp_cn(x) -> bool:
        s = str(x).upper()
        return any(tok in s for tok in jp_cn_tokens)

    cur2 = cur_df[~cur_df[COL_CUST2].astype(str).apply(_is_jp_cn)].copy()
    prev2 = prev_df.copy()
    if prev2 is not None and not prev2.empty and COL_CUST2 in prev2.columns:
        prev2 = prev2[~prev2[COL_CUST2].astype(str).apply(_is_jp_cn)].copy()

    cur = cur2.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY].sum().reset_index(name="cur")
    prev = prev2.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY].sum().reset_index(name="prev") if (prev2 is not None and not prev2.empty) else pd.DataFrame(columns=[COL_ITEM_CODE, COL_ITEM_NAME, "prev"])

    m = cur.merge(prev, on=[COL_ITEM_CODE, COL_ITEM_NAME], how="left")
    m["prev"] = pd.to_numeric(m["prev"], errors="coerce").fillna(0)
    m["cur"] = pd.to_numeric(m["cur"], errors="coerce").fillna(0)

    m = m[(m["prev"] > 0) & (m["cur"] > m["prev"])].copy()
    if m.empty:
        return []

    m["pct"] = (m["cur"] / m["prev"] - 1.0) * 100.0
    m = m.sort_values(["pct", "cur"], ascending=False).head(top_n)

    out = []
    for _, r in m.iterrows():
        code = str(r[COL_ITEM_CODE]).strip()
        name = str(r[COL_ITEM_NAME]).strip()
        prevv = int(round(float(r["prev"]), 0))
        curr = int(round(float(r["cur"]), 0))
        pct = float(r["pct"])
        bd = _format_bp_qty_breakdown(cur2, code, top_n=3)
        out.append(f"- {code} {name}")
        out.append(f"  전월: {prevv:,} → 이번달: {curr:,} ({pct:+.0f}%)")
        if bd:
            out.append(f"  → {bd}")
    return out

def _new_bp_first_ship_section(all_df: pd.DataFrame, cur_df: pd.DataFrame, cur_month_key_num: int | None, top_new: int = 3) -> list[str]:
    if cur_df is None or cur_df.empty or COL_BP not in cur_df.columns:
        return []

    hist = all_df.copy()
    if "_month_key_num" in hist.columns and cur_month_key_num is not None:
        hist = hist[pd.to_numeric(hist["_month_key_num"], errors="coerce").fillna(0).astype(int) < int(cur_month_key_num)]

    hist_bps = set(hist[COL_BP].dropna().astype(str).str.strip().tolist()) if (hist is not None and not hist.empty and COL_BP in hist.columns) else set()
    cur_bps = sorted(set(cur_df[COL_BP].dropna().astype(str).str.strip().tolist()))
    new_bps = [bp for bp in cur_bps if bp and bp not in hist_bps]
    if not new_bps:
        return []

    sub = cur_df[cur_df[COL_BP].astype(str).str.strip().isin(new_bps)].copy()
    g = sub.groupby(COL_BP)[COL_QTY].sum().sort_values(ascending=False).head(top_new)

    out = ["✅ 신규 업체 첫 출고"]
    for bp, qty in g.items():
        bpdf = sub[sub[COL_BP].astype(str).str.strip() == str(bp).strip()].copy()
        sku_cnt = _nunique(bpdf, COL_ITEM_CODE)
        out.append(f"- 업체명 : {bp}")
        out.append(f"  총 {sku_cnt}SKU/ {_fmt_int(qty)}개 수량 출고")

        top_items = (
            bpdf.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY]
            .sum().sort_values(ascending=False).head(4)
        )
        if not top_items.empty:
            out.append("  주요 출고 품목")
            for (code, name), _q in top_items.items():
                out.append(f"  · {code}\t{name}")
    return out

def _next_month_heavy_plan(df_all_view: pd.DataFrame, cur_month_label: str, cust1_value: str, top_n: int = 3, min_qty: int = 10000) -> list[str]:
    if df_all_view is None or df_all_view.empty:
        return []
    if not all(c in df_all_view.columns for c in [COL_SHIP, COL_CUST1, COL_BP, COL_ITEM_CODE, COL_ITEM_NAME, COL_QTY]):
        return []

    y, m = _month_key(cur_month_label)
    if y <= 0 or m <= 0:
        return []
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    next_month_label = make_month_label(ny, nm)

    ship_dt = pd.to_datetime(df_all_view[COL_SHIP], errors="coerce")
    sub = df_all_view[ship_dt.notna()].copy()
    sub = sub[sub[COL_CUST1].astype(str).str.strip() == cust1_value].copy()
    if sub.empty:
        return []

    sub["_ship_month"] = ship_dt.loc[sub.index].apply(_month_label_from_dt)
    sub = sub[sub["_ship_month"].astype(str) == str(next_month_label)].copy()
    if sub.empty:
        return []

    agg = sub.groupby([COL_BP, COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY].sum().reset_index(name="qty")

    idx = agg.groupby(COL_BP)["qty"].idxmax()
    pick = agg.loc[idx].sort_values("qty", ascending=False).head(top_n)

    if pick.empty:
        return []
    if float(pick["qty"].max()) < float(min_qty):
        return []  # 특이 없으면 생략

    out = [f"🗓️ 차월({next_month_label}) 대량 출고 예정 Top {min(top_n, len(pick))}"]
    for _, r in pick.iterrows():
        bp = str(r[COL_BP]).strip()
        code = str(r[COL_ITEM_CODE]).strip()
        name = str(r[COL_ITEM_NAME]).strip()
        qty = int(round(float(r["qty"]), 0))
        out.append(f"- {bp} / {code} {name} {qty:,}")
    return out

# ---- BP명 기반 문장 템플릿(국내B2B) ----
DOM_BP_PATTERNS = [
    ("쿠팡", ["쿠팡", "COUPANG"]),
    ("올영", ["올영", "OLIVE", "올리브영", "OY"]),
    ("국군복지단", ["국군복지단", "PX", "군", "복지단"]),
]

def _match_dom_bp_name(bp: str) -> str | None:
    s = str(bp).upper()
    for canon, toks in DOM_BP_PATTERNS:
        for t in toks:
            if str(t).upper() in s:
                return canon
    return None

def _bp_share_by_qty(df: pd.DataFrame, bp_name: str) -> float:
    if df is None or df.empty or COL_QTY not in df.columns or COL_BP not in df.columns:
        return 0.0
    tot = float(df[COL_QTY].fillna(0).sum())
    if tot <= 0:
        return 0.0
    sub = df[df[COL_BP].astype(str) == str(bp_name)].copy()
    return float(sub[COL_QTY].fillna(0).sum()) / tot

def _bp_share_by_orders(df: pd.DataFrame, bp_name: str) -> float:
    if df is None or df.empty or COL_ORDER_NO not in df.columns or COL_BP not in df.columns:
        return 0.0
    tot = _get_order_cnt(df)
    if tot <= 0:
        return 0.0
    sub = df[df[COL_BP].astype(str) == str(bp_name)].copy()
    return _get_order_cnt(sub) / tot

def _top_sku_for_bp(df: pd.DataFrame, bp_name: str) -> tuple[str, str, int] | None:
    if df is None or df.empty:
        return None
    sub = df[df[COL_BP].astype(str) == str(bp_name)].copy()
    if sub.empty:
        return None
    g = sub.groupby([COL_ITEM_CODE, COL_ITEM_NAME])[COL_QTY].sum().sort_values(ascending=False).head(1)
    if g.empty:
        return None
    (code, name), qty = g.index[0], float(g.iloc[0])
    return (str(code).strip(), str(name).strip(), int(round(qty, 0)))

def _mom_for_bp_sku(cur_df: pd.DataFrame, prev_df: pd.DataFrame, bp_name: str, sku_code: str) -> float | None:
    if prev_df is None or prev_df.empty:
        return None
    cur_sub = cur_df[(cur_df[COL_BP].astype(str) == str(bp_name)) & (cur_df[COL_ITEM_CODE].astype(str) == str(sku_code))]
    prev_sub = prev_df[(prev_df[COL_BP].astype(str) == str(bp_name)) & (prev_df[COL_ITEM_CODE].astype(str) == str(sku_code))]
    cur_qty = float(cur_sub[COL_QTY].fillna(0).sum()) if not cur_sub.empty else 0.0
    prev_qty = float(prev_sub[COL_QTY].fillna(0).sum()) if not prev_sub.empty else 0.0
    if prev_qty <= 0:
        return None
    return (cur_qty / prev_qty - 1.0) * 100.0

def _domestic_focus_section_human(cur_dom: pd.DataFrame, prev_dom: pd.DataFrame) -> list[str]:
    """
    ✅ 국내B2B '사람이 쓰는 문장' 형태
    - 전월 대비 출고건수(주문번호 distinct) 증감
    - 출고건수 Top BP / 출고수량 Top BP 각각 비중(%) 포함
    - 쿠팡/올영/국군복지단 등 매칭되는 BP는 문장 템플릿으로 1~2줄 자동 생성
    """
    if cur_dom is None or cur_dom.empty:
        return ["(국내B2B) 이번달 데이터 없음"]

    out = []

    cur_orders = _get_order_cnt(cur_dom)
    prev_orders = _get_order_cnt(prev_dom)
    diff_orders = cur_orders - prev_orders
    out.append("✅ 전월 대비 출고건수 증가, 거래처는 소수 집중" if diff_orders > 0 else "✅ 전월 대비 출고건수 변동/감소")
    out.append(f"- 발주/출고건수(주문번호 distinct): {cur_orders}건 ({_fmt_delta(diff_orders)})")

    # Top BP by orders
    if COL_ORDER_NO in cur_dom.columns:
        tmp = cur_dom.copy()
        tmp["_ord"] = tmp[COL_ORDER_NO].astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
        ord_bp = tmp.dropna(subset=["_ord"]).groupby(COL_BP)["_ord"].nunique().sort_values(ascending=False)
        if not ord_bp.empty:
            top_bp_cnt = str(ord_bp.index[0])
            top_bp_cnt_val = int(ord_bp.iloc[0])
            top_bp_cnt_share = _bp_share_by_orders(cur_dom, top_bp_cnt) * 100
        else:
            top_bp_cnt = "-"
            top_bp_cnt_val = 0
            top_bp_cnt_share = 0.0
    else:
        top_bp_cnt = "-"
        top_bp_cnt_val = 0
        top_bp_cnt_share = 0.0

    # Top BP by qty
    if COL_QTY in cur_dom.columns:
        qty_bp = cur_dom.groupby(COL_BP)[COL_QTY].sum().sort_values(ascending=False)
        if not qty_bp.empty:
            top_bp_qty = str(qty_bp.index[0])
            top_bp_qty_val = int(round(float(qty_bp.iloc[0]), 0))
            top_bp_qty_share = _bp_share_by_qty(cur_dom, top_bp_qty) * 100
        else:
            top_bp_qty = "-"
            top_bp_qty_val = 0
            top_bp_qty_share = 0.0
    else:
        top_bp_qty = "-"
        top_bp_qty_val = 0
        top_bp_qty_share = 0.0

    out.append("✅ 출고건수 비중은 {}/ 출고수량 비중은 {} ↑".format(top_bp_cnt if top_bp_cnt != "-" else "상위BP", top_bp_qty if top_bp_qty != "-" else "상위BP"))
    out.append(f"- 출고건수 Top BP: {top_bp_cnt} ({top_bp_cnt_val}건, 약 {top_bp_cnt_share:.0f}%)")
    out.append(f"- 출고수량 Top BP: {top_bp_qty} ({top_bp_qty_val:,}개, 약 {top_bp_qty_share:.0f}%)")

    # BP별 문장 생성(쿠팡/올영/국군복지단)
    # 1) 우선 이번달 등장 BP 중 매칭되는 BP를 찾는다
    bps = cur_dom[COL_BP].dropna().astype(str).tolist() if COL_BP in cur_dom.columns else []
    # 같은 canonical이 여러 개면(예: 올영 OY/올영) 수량 큰 BP 하나만
    canon_best = {}
    for bp in set([str(x).strip() for x in bps]):
        canon = _match_dom_bp_name(bp)
        if not canon:
            continue
        q = float(cur_dom[cur_dom[COL_BP].astype(str) == bp][COL_QTY].fillna(0).sum())
        if canon not in canon_best or q > canon_best[canon]["qty"]:
            canon_best[canon] = {"bp": bp, "qty": q}

    # 2) canonical 우선순위대로 문장 생성
    for canon in ["쿠팡", "올영", "국군복지단"]:
        if canon not in canon_best:
            continue
        bp_name = canon_best[canon]["bp"]
        top_sku = _top_sku_for_bp(cur_dom, bp_name)
        if not top_sku:
            continue
        code, name, qty = top_sku
        mom = _mom_for_bp_sku(cur_dom, prev_dom, bp_name, code)

        if canon == "쿠팡":
            share = _bp_share_by_qty(cur_dom, bp_name) * 100
            if mom is None:
                out.append(f"- {bp_name} : {code} {name} ↑ : {bp_name} 출고량 약 {share:.0f}% 차지")
            else:
                out.append(f"- {bp_name} : {code} {name} ↑ ({mom:+.0f}%) : {bp_name} 출고량 약 {share:.0f}% 차지")

        elif canon == "올영":
            # 망곰 키워드 감지
            has_mg = ("망곰" in name) or (cur_dom[(cur_dom[COL_BP].astype(str) == bp_name) & (cur_dom[COL_ITEM_NAME].astype(str).str.contains("망곰", na=False))].shape[0] > 0)
            if has_mg:
                out.append(f"- {bp_name} : 망곰 세트 출고 진행 (대표 SKU: {code} {name} / {qty:,}개)")
            else:
                out.append(f"- {bp_name} : {code} {name} ↑ ({qty:,}개)")

        elif canon == "국군복지단":
            out.append(f"- {bp_name} : {code} {name} {qty:,}개 추가 출고")

    return out

def make_monthly_report_text_rich(
    month_label: str,
    all_view_df: pd.DataFrame,
    cur_month_df: pd.DataFrame,
    prev_month_df: pd.DataFrame,
    cur_month_key_num: int | None,
    jp_cn_tokens: list[str] = None,
) -> str:
    jp_cn_tokens = jp_cn_tokens or ["JP", "JAPAN", "CN", "CHINA", "중국", "일본"]

    lines = []
    lines.append(f"{month_label} B2B 현황 공유 드립니다. (SAP현황에 따라 자료는 오차범위가 있을 수 있습니다🙂)")
    lines.append(":link:B2B 월간리포트")
    lines.append("")

    # --- 해외/국내 분리 ---
    cur_over = cur_month_df[cur_month_df[COL_CUST1].astype(str).str.strip() == "해외B2B"].copy() if (cur_month_df is not None and not cur_month_df.empty and COL_CUST1 in cur_month_df.columns) else pd.DataFrame()
    prev_over = prev_month_df[prev_month_df[COL_CUST1].astype(str).str.strip() == "해외B2B"].copy() if (prev_month_df is not None and not prev_month_df.empty and COL_CUST1 in prev_month_df.columns) else pd.DataFrame()

    cur_dom = cur_month_df[cur_month_df[COL_CUST1].astype(str).str.strip().isin(["국내B2B", "국내 B2B"])].copy() if (cur_month_df is not None and not cur_month_df.empty and COL_CUST1 in cur_month_df.columns) else pd.DataFrame()
    prev_dom = prev_month_df[prev_month_df[COL_CUST1].astype(str).str.strip().isin(["국내B2B", "국내 B2B"])].copy() if (prev_month_df is not None and not prev_month_df.empty and COL_CUST1 in prev_month_df.columns) else pd.DataFrame()

    # =====================
    # 해외B2B 리포트
    # =====================
    lines.append("해외B2B")

    # 1) 신규 업체 첫 출고
    new_bp_block = _new_bp_first_ship_section(all_df=all_view_df, cur_df=cur_over, cur_month_key_num=cur_month_key_num, top_new=3)
    if new_bp_block:
        lines += new_bp_block
        lines.append("")

    # 2) 출고량 증감 요약 + 주요 업체
    over_cur_qty = _sum_qty(cur_over)
    over_prev_qty = _sum_qty(prev_over)
    over_diff = over_cur_qty - over_prev_qty
    over_pct = _pct(over_cur_qty, over_prev_qty)
    if over_prev_qty > 0 and over_pct is not None:
        lines.append("✅ 출고량 증감 요약")
        lines.append(f"- 출고량 전월 대비 {'대폭 증가' if over_diff > 0 else '감소/변동'} ({over_diff:+,})")
        top_bps = _top_bp_list(cur_over, top_n=3)
        if top_bps:
            lines.append("- 주요 업체")
            for bp in top_bps:
                lines.append(f"  {bp}")
        lines.append("")

    # 3) 특정 SKU 대량 출고
    mass_lines = _top_sku_mass_shipments(cur_over, top_n=4, bp_break_top=3)
    if mass_lines:
        lines.append("✅ 특정 SKU 대량 출고 (Top4)")
        lines += mass_lines
        lines.append("")

    # 4) 전월 대비 주요 SKU 증감 (지속출고 대신 '전월 대비 증감'으로 표기)
    mom_sku_lines = _sku_mom_change_lines(cur_over, prev_over, top_n=6)
    if mom_sku_lines:
        lines.append("✅ 전월 대비 주요 SKU 증감")
        lines += mom_sku_lines
        lines.append("")

    # 5) JP/CN 제외 증가 SKU (해외만)
    jp_cn_lines = _jp_cn_excluded_increase(cur_over, prev_over, jp_cn_tokens=jp_cn_tokens, top_n=3)
    if jp_cn_lines:
        lines.append("✅ JP, CN 라인 제외 전월 대비 출고량 증가 SKU")
        lines += jp_cn_lines
        lines.append("")

    # 6) 차월(다음달) 대량 출고 예정 Top3 (특이 없으면 생략)
    next_plan = _next_month_heavy_plan(
        df_all_view=all_view_df,
        cur_month_label=month_label,
        cust1_value="해외B2B",
        top_n=3,
        min_qty=10000,
    )
    if next_plan:
        lines.append("")
        lines += next_plan

    lines.append("")
    lines.append("")

    # =====================
    # 국내B2B 리포트 (사람 문장형)
    # =====================
    lines.append("국내B2B")
    lines += _domestic_focus_section_human(cur_dom, prev_dom)

    return "\n".join(lines)

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
# Main
# -------------------------
st.title("📦 B2B 출고 대시보드")
st.caption("Google Sheet RAW 기반 | 제품분류 B0/B1 고정 | 필터(거래처구분1/2/월/BP) 반영")

if st.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    reset_keys = [
        "nav_menu", "wk_sel_week", "m_sel_month",
        "sku_query", "sku_candidate_pick", "sku_show_all_history",
        "f_cust1", "f_cust2", "f_month", "f_bp",
        "sku_ignore_month_filter",
        "monthly_report_text"
    ]
    for k in reset_keys:
        if k in st.session_state:
            del st.session_state[k]
    st.session_state["nav_menu"] = "① SKU별 조회"
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
# Navigation
# =========================
nav = st.radio(
    "메뉴",
    ["① SKU별 조회", "② 주차요약", "③ 월간요약", "④ 국가별 조회", "⑤ BP명별 조회"],
    horizontal=True,
    key="nav_menu"
)

# =========================
# ① SKU별 조회
# =========================
if nav == "① SKU별 조회":
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
# ② 주차요약
# =========================
elif nav == "② 주차요약":
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
# ③ 월간요약
# =========================
elif nav == "③ 월간요약":
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

    # ✅ 기존 월간 자동코멘트 유지
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

    # ✅ 월간 리포트 생성(버튼 클릭 + 복사 가능)
    st.subheader("📌 월간 리포트 (복사/공유용)")
    st.caption("버튼 클릭 시, 해외B2B/국내B2B 섹션을 나눠 ‘사람이 쓰는 문장’ 형태로 리포트가 생성됩니다.")

    if st.button("📝 월간 리포트 생성"):
        st.session_state["monthly_report_text"] = make_monthly_report_text_rich(
            month_label=sel_month_label2,
            all_view_df=df_view,   # ✅ 다음달 예정 산출 때문에 '현재 필터 범위 전체' 필요
            cur_month_df=mdf,
            prev_month_df=prev_mdf,
            cur_month_key_num=cur_key_num,
            jp_cn_tokens=["JP", "JAPAN", "CN", "CHINA", "중국", "일본"],
        )

    report_text = st.session_state.get("monthly_report_text", "")
    st.text_area("생성된 리포트(전체 복사해서 슬랙/메일에 붙여넣기)", value=report_text, height=380)

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
# ④ 국가별 조회
# =========================
elif nav == "④ 국가별 조회":
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
# ⑤ BP명별 조회
# =========================
elif nav == "⑤ BP명별 조회":
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

# ==========================================
# B2B 출고 대시보드 (Google Sheet 기반)
# - ✅ ①/② 메뉴명: 주차요약/월간요약
# - ✅ 주차/월간 자동 코멘트 (룰 기반)
# - ✅ 주차 라벨 오류 방지: 출고일자/작업완료일 기반 보정(12월 5주차 같은 이상 라벨 제거)
# - ✅ 신규 BP 기준 변경: "전체 RAW 기준 최초 등장"인 BP만 노출(주차/월 단위 첫 등장)
# - ✅ 코멘트에 품목코드+품명 같이 표기
# - ✅ UX: 섹션 타이틀 + 번호형 리스트로 표시
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
COL_ORDERNO = "주문번호"

INVOICE_CANDIDATES = [
    "인보이스No.", "인보이스No", "인보이스번호", "Invoice No.", "InvoiceNo", "INVOICE NO", "INVOICE",
    "송장번호", "문서번호"
]

KEEP_CLASSES = ["B0", "B1"]
LT_ONLY_CUST1 = "해외B2B"
SPIKE_FACTOR = 1.3  # +30%

SPECIAL_BPS = {"박스미", "CGETC", "러메어홀딩스"}

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

def find_invoice_col(df: pd.DataFrame) -> str | None:
    for c in INVOICE_CANDIDATES:
        if c in df.columns:
            return c
    return None

# -------------------------
# Label helpers
# -------------------------
def make_month_label(year: int, month: int) -> str:
    return f"{int(year)}년 {int(month)}월"

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

def week_label_from_date(dt: pd.Timestamp) -> str | None:
    if pd.isna(dt):
        return None
    y = int(dt.year)
    m = int(dt.month)
    d = int(dt.day)
    wk = (d - 1) // 7 + 1
    return f"{y}년 {m}월 {wk}주차"

def build_week_label_from_raw_safe(row: pd.Series) -> str | None:
    """
    ✅ 핵심 수정 포인트:
    - 출고일자(우선) or 작업완료일이 있으면 그 날짜로 주차 라벨 생성 (RAW 주차/월 값 신뢰 X)
    - 날짜가 없을 때만 RAW '주차'를 파싱해서 쓰되, 값이 이상하면 None 처리
    - RAW 파싱 결과가 날짜 월과 다르면 날짜 기반 라벨로 교정
    """
    ship_dt = row.get(COL_SHIP, pd.NaT)
    done_dt = row.get(COL_DONE, pd.NaT)

    # 1) 날짜가 있으면 날짜 기반으로 강제 생성 (가장 안전)
    base_dt = ship_dt if pd.notna(ship_dt) else done_dt
    if pd.notna(base_dt):
        return week_label_from_date(pd.to_datetime(base_dt, errors="coerce"))

    # 2) 날짜가 없을 때만 RAW 주차 파싱
    wk_raw = str(row.get(COL_WEEK_LABEL, "")).strip()
    if wk_raw == "" or wk_raw.lower() == "nan":
        return None

    # "2026년 2월 2주차" 같은 완성형이면 그대로(단 값 검증)
    y = m = w = None
    my = re.search(r"(\d{4})\s*년", wk_raw)
    mm = re.search(r"(\d+)\s*월", wk_raw)
    mw = re.search(r"(\d+)\s*주차", wk_raw)
    if my and mm and mw:
        y = int(my.group(1)); m = int(mm.group(1)); w = int(mw.group(1))
    else:
        # "2주차"처럼 월/년 없는 경우: 년/월1 보조
        if mw:
            w = int(mw.group(1))
        else:
            return None

        yy = row.get(COL_YEAR, None)
        mo = row.get(COL_MONTH, None)
        try:
            y = int(pd.to_numeric(yy, errors="coerce"))
            m = int(pd.to_numeric(mo, errors="coerce"))
        except Exception:
            return None

    # 값 검증 (여기서 12월 5주차 같은 "실제 존재 여부"는 모르지만 최소 범위 막기)
    if not (y and 2000 <= y <= 2100):
        return None
    if not (m and 1 <= m <= 12):
        return None
    if not (w and 1 <= w <= 6):
        return None

    return f"{y}년 {m}월 {w}주차"

# -------------------------
# BP list helpers
# -------------------------
def build_item_name_map(df: pd.DataFrame) -> dict[str, str]:
    """
    품목코드 -> 대표 품목명(가장 많이 등장한 값) 매핑
    """
    if df.empty or COL_ITEM_CODE not in df.columns:
        return {}
    tmp = df[[COL_ITEM_CODE, COL_ITEM_NAME]].dropna(subset=[COL_ITEM_CODE]).copy()
    tmp[COL_ITEM_CODE] = tmp[COL_ITEM_CODE].astype(str).str.strip()
    if COL_ITEM_NAME in tmp.columns:
        tmp[COL_ITEM_NAME] = tmp[COL_ITEM_NAME].astype(str).str.strip()
    else:
        tmp[COL_ITEM_NAME] = ""
    out = {}
    for code, sub in tmp.groupby(COL_ITEM_CODE):
        name = sub[COL_ITEM_NAME].value_counts().index[0] if not sub[COL_ITEM_NAME].value_counts().empty else ""
        out[str(code)] = str(name)
    return out

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
        .sum(min_count=1).reset_index(name="현재_요청수량")
    )
    prev_sku = (
        prev_df.groupby([COL_ITEM_CODE, COL_ITEM_NAME], dropna=False)[COL_QTY]
        .sum(min_count=1).reset_index(name="이전_요청수량")
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

# =========================
# 자동 코멘트 (UX: 섹션 + 번호)
# =========================
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

def _sku_label(code: str, name_map: dict[str, str]) -> str:
    n = name_map.get(str(code), "")
    if n:
        return f"{code} {n}"
    return str(code)

def comment_top_sku_changed(df_cur: pd.DataFrame, df_prev: pd.DataFrame, name_map: dict[str, str]) -> list[str]:
    if df_cur.empty or df_prev.empty:
        return []
    cur = df_cur.groupby(COL_ITEM_CODE, dropna=False)[COL_QTY].sum().sort_values(ascending=False)
    prev = df_prev.groupby(COL_ITEM_CODE, dropna=False)[COL_QTY].sum().sort_values(ascending=False)
    if cur.empty or prev.empty:
        return []
    a = str(prev.index[0]); b = str(cur.index[0])
    if a == b:
        return []
    return [f"전기 Top1 → 금기 Top1 변경: `{_sku_label(a, name_map)}` → `{_sku_label(b, name_map)}`"]

def comment_growth_30_sku(df_cur: pd.DataFrame, df_prev: pd.DataFrame, name_map: dict[str, str], top_n=5) -> list[str]:
    if df_cur.empty or df_prev.empty:
        return []
    cur = df_cur.groupby(COL_ITEM_CODE, dropna=False)[COL_QTY].sum().reset_index(name="cur_qty")
    prev = df_prev.groupby(COL_ITEM_CODE, dropna=False)[COL_QTY].sum().reset_index(name="prev_qty")
    m = cur.merge(prev, on=COL_ITEM_CODE, how="left").fillna({"prev_qty": 0})
    hit = m[(m["prev_qty"] > 0) & (m["cur_qty"] >= m["prev_qty"] * SPIKE_FACTOR)].copy()
    if hit.empty:
        return []
    hit["growth_pct"] = (hit["cur_qty"] / hit["prev_qty"] - 1) * 100
    hit = hit.sort_values("growth_pct", ascending=False).head(top_n)
    out = []
    for _, r in hit.iterrows():
        code = str(r[COL_ITEM_CODE])
        out.append(
            f"`{_sku_label(code, name_map)}` 전기 {_fmt_int(r['prev_qty'])} → 금기 {_fmt_int(r['cur_qty'])} (**+{r['growth_pct']:.0f}%**)"
        )
    return out

def comment_sku_concentration(df_cur: pd.DataFrame, name_map: dict[str, str],
                              conc_threshold=0.5, other_bp_min_share=0.15, top_n=10) -> list[str]:
    if df_cur.empty:
        return []

    lines = []
    bp_tot = df_cur.groupby(COL_BP, dropna=False)[COL_QTY].sum()
    bp_sku = df_cur.groupby([COL_BP, COL_ITEM_CODE], dropna=False)[COL_QTY].sum().reset_index()

    for bp, tot in bp_tot.items():
        if tot is None or float(tot) <= 0:
            continue
        sub = bp_sku[bp_sku[COL_BP] == bp].sort_values(COL_QTY, ascending=False)
        if sub.empty:
            continue
        top_row = sub.iloc[0]
        sku = str(top_row[COL_ITEM_CODE])
        share_in_bp = float(top_row[COL_QTY]) / float(tot)

        if share_in_bp < conc_threshold:
            continue

        if str(bp) in SPECIAL_BPS:
            sku_by_bp = (
                df_cur[df_cur[COL_ITEM_CODE] == sku]
                .groupby(COL_BP, dropna=False)[COL_QTY].sum()
                .sort_values(ascending=False)
            )
            sku_total = float(sku_by_bp.sum()) if not sku_by_bp.empty else 0.0
            if sku_total <= 0:
                lines.append(f"{bp} : `{_sku_label(sku, name_map)}` 비중 **{share_in_bp*100:.0f}%**")
                continue

            top_bp = str(sku_by_bp.index[0])
            others = sku_by_bp[sku_by_bp.index.astype(str) != top_bp]
            meaningful = others[(others / sku_total) >= other_bp_min_share]

            if meaningful.empty:
                lines.append(f"{bp} : `{_sku_label(sku, name_map)}` 비중 **{share_in_bp*100:.0f}%**")
            else:
                other_parts = ", ".join([f"{idx}({_fmt_int(val)})" for idx, val in meaningful.items()])
                lines.append(f"{bp} : `{_sku_label(sku, name_map)}` 비중 **{share_in_bp*100:.0f}%** (타 BP 후순위: {other_parts})")
        else:
            lines.append(f"{bp} : `{_sku_label(sku, name_map)}` 비중 **{share_in_bp*100:.0f}%**")

    return lines[:top_n]

def build_bp_first_seen_maps(full_df: pd.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    """
    ✅ 신규 BP 기준을 "전체 누적"으로 변경:
    - BP가 전체 raw에서 처음 등장한 주차/월을 계산
    - 주차 코멘트: bp_first_week[bp] == 현재주차 일 때만 신규
    - 월간 코멘트: bp_first_month[bp] == 현재월 일 때만 신규
    """
    if full_df.empty or COL_BP not in full_df.columns:
        return {}, {}

    d = full_df.copy()
    d[COL_BP] = d[COL_BP].astype(str).str.strip()

    # 주차/월 라벨이 없으면 생성 실패하므로 안전 처리
    if "_week_label" not in d.columns:
        d["_week_label"] = None
    if "_month_label" not in d.columns:
        d["_month_label"] = None

    # 첫 등장: "라벨 기준" 최소값
    # 라벨 정렬키를 만들어서 min 선택
    def wk_key(x: str):
        return parse_week_label_key(str(x)) if pd.notna(x) else (9999, 99, 99)

    def mo_key(x: str):
        return parse_month_label_key(str(x)) if pd.notna(x) else (9999, 99)

    bp_first_week = {}
    bp_first_month = {}

    for bp, sub in d.groupby(COL_BP, dropna=False):
        wk_vals = [x for x in sub["_week_label"].dropna().astype(str).tolist() if x.strip() != ""]
        mo_vals = [x for x in sub["_month_label"].dropna().astype(str).tolist() if x.strip() != ""]
        if wk_vals:
            bp_first_week[str(bp)] = sorted(wk_vals, key=wk_key)[0]
        if mo_vals:
            bp_first_month[str(bp)] = sorted(mo_vals, key=mo_key)[0]

    return bp_first_week, bp_first_month

def comment_new_bp_by_first_seen(df_cur: pd.DataFrame, full_df: pd.DataFrame, current_label: str,
                                bp_first_map: dict[str, str], label_col: str, top_n=10) -> list[str]:
    """
    label_col: "_week_label" or "_month_label"
    """
    if df_cur.empty or COL_BP not in df_cur.columns:
        return []

    cur_bps = sorted(df_cur[COL_BP].dropna().astype(str).str.strip().unique().tolist())
    new_bps = [bp for bp in cur_bps if bp_first_map.get(bp) == current_label]
    if not new_bps:
        return []

    sub = df_cur[df_cur[COL_BP].astype(str).str.strip().isin(new_bps)].copy()
    g = sub.groupby(COL_BP, dropna=False).agg(
        qty=(COL_QTY, "sum"),
        first_ship=(COL_SHIP, "min"),
    ).reset_index().sort_values("qty", ascending=False).head(top_n)

    lines = []
    for _, r in g.iterrows():
        lines.append(f"{r[COL_BP]} / 요청수량 {_fmt_int(r['qty'])} / 출고일자 {_fmt_date_or_mijung(r['first_ship'])}")
    return lines

def comment_leadtime_outlier(df_cur: pd.DataFrame, invoice_col: str | None,
                             name_map: dict[str, str], z=2.0, min_delta_if_no_std=2.0, top_n=10) -> list[str]:
    if df_cur.empty or (COL_LT2 not in df_cur.columns) or (COL_CUST2 not in df_cur.columns):
        return []
    d = df_cur.dropna(subset=[COL_LT2]).copy()
    if d.empty:
        return []

    stats = d.groupby(COL_CUST2, dropna=False)[COL_LT2].agg(["mean", "std"]).reset_index()
    d = d.merge(stats, on=COL_CUST2, how="left")

    d["is_outlier"] = False
    has_std = d["std"].fillna(0) > 0
    d.loc[has_std, "is_outlier"] = d.loc[has_std, COL_LT2] > (d.loc[has_std, "mean"] + z * d.loc[has_std, "std"])
    d.loc[~has_std, "is_outlier"] = d.loc[~has_std, COL_LT2] > (d.loc[~has_std, "mean"] + min_delta_if_no_std)

    out = d[d["is_outlier"]].copy()
    if out.empty:
        return []

    out["delta"] = out[COL_LT2] - out["mean"]
    out = out.sort_values("delta", ascending=False).head(top_n)

    lines = []
    for _, r in out.iterrows():
        inv = "-"
        if invoice_col and invoice_col in out.columns:
            v = r.get(invoice_col, None)
            inv = "-" if pd.isna(v) else str(v).strip()

        bp = str(r.get(COL_BP, "-")).strip()
        sku = str(r.get(COL_ITEM_CODE, "-")).strip()
        grp = str(r.get(COL_CUST2, "-")).strip()

        lines.append(
            f"[{grp}] 인보이스 `{inv}` / {bp} / `{_sku_label(sku, name_map)}` "
            f"리드타임 {float(r[COL_LT2]):.1f} (평균 {float(r['mean']):.1f}, +{float(r['delta']):.1f})"
        )
    return lines

def comment_shipcount_spike_sku(df_cur: pd.DataFrame, df_prev: pd.DataFrame,
                                name_map: dict[str, str], spike_ratio=1.3, min_increase=3, top_n=10) -> list[str]:
    if df_cur.empty or df_prev.empty:
        return []
    if COL_ORDERNO not in df_cur.columns or COL_ORDERNO not in df_prev.columns:
        return []

    cur = df_cur.groupby(COL_ITEM_CODE, dropna=False)[COL_ORDERNO].nunique().reset_index(name="cur_cnt")
    prev = df_prev.groupby(COL_ITEM_CODE, dropna=False)[COL_ORDERNO].nunique().reset_index(name="prev_cnt")
    m = cur.merge(prev, on=COL_ITEM_CODE, how="left").fillna({"prev_cnt": 0})
    m["inc"] = m["cur_cnt"] - m["prev_cnt"]

    hit = m[(m["prev_cnt"] > 0) & (m["cur_cnt"] >= m["prev_cnt"] * spike_ratio) & (m["inc"] >= min_increase)].copy()
    if hit.empty:
        return []
    hit["growth_pct"] = (hit["cur_cnt"] / hit["prev_cnt"] - 1) * 100
    hit = hit.sort_values("growth_pct", ascending=False).head(top_n)

    lines = []
    for _, r in hit.iterrows():
        code = str(r[COL_ITEM_CODE])
        lines.append(
            f"`{_sku_label(code, name_map)}` {int(r['prev_cnt'])}건 → {int(r['cur_cnt'])}건 (**+{r['growth_pct']:.0f}%**)"
        )
    return lines

def comment_bp_qty_spike(df_cur: pd.DataFrame, df_prev: pd.DataFrame, spike_ratio=1.3, top_n=10) -> list[str]:
    if df_cur.empty or df_prev.empty:
        return []
    cur = df_cur.groupby(COL_BP, dropna=False)[COL_QTY].sum().reset_index(name="cur_qty")
    prev = df_prev.groupby(COL_BP, dropna=False)[COL_QTY].sum().reset_index(name="prev_qty")
    m = cur.merge(prev, on=COL_BP, how="left").fillna({"prev_qty": 0})

    hit = m[(m["prev_qty"] > 0) & (m["cur_qty"] >= m["prev_qty"] * spike_ratio)].copy()
    if hit.empty:
        return []
    hit["growth_pct"] = (hit["cur_qty"] / hit["prev_qty"] - 1) * 100
    hit = hit.sort_values("growth_pct", ascending=False).head(top_n)

    lines = []
    for _, r in hit.iterrows():
        lines.append(f"{r[COL_BP]} {_fmt_int(r['prev_qty'])} → {_fmt_int(r['cur_qty'])} (**+{r['growth_pct']:.0f}%**)")
    return lines

def render_comment_sections(sections: dict[str, list[str]]):
    """
    ✅ UX: 섹션 타이틀 + 번호 리스트
    """
    shown = False
    for title, items in sections.items():
        if not items:
            continue
        shown = True
        st.markdown(f"**{title}**")
        for i, line in enumerate(items, start=1):
            st.markdown(f"{i}) {line}")
        st.markdown("---")
    if not shown:
        st.caption("특이사항 없음")

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
        [COL_BP, COL_ITEM_CODE, COL_ITEM_NAME, COL_CUST1, COL_CUST2, COL_WEEK_LABEL, COL_CLASS, COL_MAIN, COL_ORDERNO]
    )

    if COL_MAIN in df.columns:
        df["_is_rep"] = to_bool_true(df[COL_MAIN])
    else:
        df["_is_rep"] = False

    # ✅ 주차 라벨: 안전 로직 적용 (오류 라벨 생성 방지)
    df["_week_label"] = df.apply(build_week_label_from_raw_safe, axis=1)

    # 월 라벨 (년+월1 기반)
    if (COL_YEAR in df.columns) and (COL_MONTH in df.columns):
        y = pd.to_numeric(df[COL_YEAR], errors="coerce")
        m = pd.to_numeric(df[COL_MONTH], errors="coerce")
        df["_month_label"] = [
            make_month_label(yy, mm) if pd.notna(yy) and pd.notna(mm) else None
            for yy, mm in zip(y, m)
        ]
    else:
        # fallback: 출고일자 기반 월 라벨
        if COL_SHIP in df.columns:
            ship = pd.to_datetime(df[COL_SHIP], errors="coerce")
            df["_month_label"] = ship.apply(lambda x: make_month_label(x.year, x.month) if pd.notna(x) else None)
        else:
            df["_month_label"] = None

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
        "f_cust1", "f_cust2", "f_month", "f_bp"
    ]
    for k in reset_keys:
        if k in st.session_state:
            del st.session_state[k]
    st.session_state["nav_menu"] = "① 주차요약"
    st.rerun()

try:
    raw = load_raw_from_gsheet().copy()
except Exception as e:
    st.error("Google Sheet에서 RAW 데이터를 불러오지 못했습니다.")
    st.code(str(e))
    st.stop()

# 제품분류 고정
if COL_CLASS in raw.columns:
    raw = raw[raw[COL_CLASS].astype(str).str.strip().isin(KEEP_CLASSES)].copy()
else:
    st.warning(f"'{COL_CLASS}' 컬럼이 없어 제품분류(B0/B1) 고정 필터를 적용할 수 없습니다.")

invoice_col = find_invoice_col(raw)

# ✅ 전체 누적 기준 신규 BP 계산용: first seen 맵 생성
bp_first_week_map, bp_first_month_map = build_bp_first_seen_maps(raw)

# ✅ 품목코드 → 품명 맵 (코멘트용)
name_map_global = build_item_name_map(raw)

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

if COL_ORDERNO in df_view.columns and not df_view.empty:
    total_cnt = int(df_view[COL_ORDERNO].dropna().astype(str).nunique())
else:
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
if COL_BP in df_view.columns and not df_view.empty:
    if COL_ORDERNO in df_view.columns:
        g2 = df_view.groupby(COL_BP, dropna=False)[COL_ORDERNO].nunique().sort_values(ascending=False)
    else:
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
    ["① 주차요약", "② 월간요약", "③ 국가별 조회", "④ BP명별 조회", "⑤ SKU별 조회"],
    horizontal=True,
    key="nav_menu"
)

# =========================
# ① 주차요약
# =========================
if nav == "① 주차요약":
    st.subheader("주차 선택 → Top 10 (BP/품목코드/품목명/요청수량)")

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

    cur_idx = week_list.index(sel_week) if sel_week in week_list else None
    prev_week = None
    prev_wdf = pd.DataFrame()
    if cur_idx is not None and cur_idx > 0:
        prev_week = week_list[cur_idx - 1]
        prev_wdf = d[d["_week_label"].astype(str) == str(prev_week)].copy()

    # ✅ 자동 코멘트(UX 개선)
    with st.expander("주차요약 자동 코멘트 (특이/이슈 포인트)", expanded=True):
        if prev_week is None:
            st.caption("전주 비교를 위해서는 선택 주차 이전의 주차 데이터가 필요합니다.")
        else:
            # 주차 단위에서는 "이번 주차에 처음 등장한 BP(전체 누적 기준)"만 신규로 표기
            sections = {}

            inc_sku = comment_growth_30_sku(wdf, prev_wdf, name_map_global)
            if inc_sku:
                sections["전주 대비 +30% 이상 증가 SKU"] = inc_sku

            top_changed = comment_top_sku_changed(wdf, prev_wdf, name_map_global)
            if top_changed:
                sections["Top SKU 변경"] = top_changed

            conc = comment_sku_concentration(wdf, name_map_global)
            if conc:
                sections["SKU 집중도 (BP 내 Top SKU 비중 ≥ 50%)"] = conc

            new_bp = comment_new_bp_by_first_seen(
                df_cur=wdf,
                full_df=raw,
                current_label=sel_week,
                bp_first_map=bp_first_week_map,
                label_col="_week_label",
            )
            if new_bp:
                sections["신규 BP (전체 누적 기준 최초 등장)"] = new_bp

            out_lt = comment_leadtime_outlier(wdf, invoice_col, name_map_global)
            if out_lt:
                sections["리드타임 이상치 (거래처구분2 평균 대비)"] = out_lt

            if prev_week is not None:
                cnt_spike = comment_shipcount_spike_sku(wdf, prev_wdf, name_map_global)
                if cnt_spike:
                    sections["전주 대비 출고건수 급증 SKU"] = cnt_spike

            render_comment_sections(sections)

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

    st.divider()
    st.subheader("전주 대비 급증 SKU 리포트 (+30% 이상 증가)")
    if prev_week is None:
        st.info("전주 비교를 위해서는 선택 주차 이전의 주차 데이터가 필요합니다.")
    else:
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
                COL_ITEM_CODE: 130, COL_ITEM_NAME: 420,
                "이전_요청수량": 120, "현재_요청수량": 120,
                "증가배수": 90, "BP명(요청수량)": 520
            },
            number_cols=["이전_요청수량", "현재_요청수량", "증가배수"],
        )

# =========================
# ② 월간요약
# =========================
elif nav == "② 월간요약":
    st.subheader("월 선택 → Top 10 (BP/품목코드/품목명/요청수량)")

    d = df_view.copy()
    if not need_cols(d, [COL_QTY, COL_BP, COL_ITEM_CODE, COL_ITEM_NAME], "월간요약"):
        st.stop()

    month_list = [x for x in d["_month_label"].dropna().astype(str).unique().tolist() if x.strip() != ""]
    month_list = list(dict.fromkeys(month_list))
    month_list = sorted(month_list, key=parse_month_label_key)

    if not month_list:
        st.info("월 목록이 없습니다.")
        st.stop()

    sel_month_label2 = st.selectbox("월 선택", month_list, index=len(month_list) - 1, key="m_sel_month")
    mdf = d[d["_month_label"].astype(str) == str(sel_month_label2)].copy()

    cur_idx = month_list.index(sel_month_label2) if sel_month_label2 in month_list else None
    prev_month_label = None
    prev_mdf = pd.DataFrame()
    if cur_idx is not None and cur_idx > 0:
        prev_month_label = month_list[cur_idx - 1]
        prev_mdf = d[d["_month_label"].astype(str) == str(prev_month_label)].copy()

    with st.expander("월간요약 자동 코멘트 (특이/이슈 포인트)", expanded=True):
        if prev_month_label is None:
            st.caption("전월 비교를 위해서는 선택 월 이전의 월 데이터가 필요합니다.")
        else:
            sections = {}

            inc_sku = comment_growth_30_sku(mdf, prev_mdf, name_map_global)
            if inc_sku:
                sections["전월 대비 +30% 이상 증가 SKU"] = inc_sku

            top_changed = comment_top_sku_changed(mdf, prev_mdf, name_map_global)
            if top_changed:
                sections["Top SKU 변경"] = top_changed

            conc = comment_sku_concentration(mdf, name_map_global)
            if conc:
                sections["SKU 집중도 (BP 내 Top SKU 비중 ≥ 50%)"] = conc

            new_bp = comment_new_bp_by_first_seen(
                df_cur=mdf,
                full_df=raw,
                current_label=sel_month_label2,
                bp_first_map=bp_first_month_map,
                label_col="_month_label",
            )
            if new_bp:
                sections["신규 BP (전체 누적 기준 최초 등장)"] = new_bp

            out_lt = comment_leadtime_outlier(mdf, invoice_col, name_map_global)
            if out_lt:
                sections["리드타임 이상치 (거래처구분2 평균 대비)"] = out_lt

            if prev_month_label is not None:
                bp_spike = comment_bp_qty_spike(mdf, prev_mdf)
                if bp_spike:
                    sections["전월 대비 출고수량 급증 BP"] = bp_spike

            render_comment_sections(sections)

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

    st.divider()
    st.subheader("전월 대비 급증 SKU 리포트 (+30% 이상 증가)")
    if prev_month_label is None:
        st.info("전월 비교를 위해서는 선택 월 이전의 월 데이터가 필요합니다.")
    else:
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
                COL_ITEM_CODE: 130, COL_ITEM_NAME: 420,
                "이전_요청수량": 120, "현재_요청수량": 120,
                "증가배수": 90, "BP명(요청수량)": 520
            },
            number_cols=["이전_요청수량", "현재_요청수량", "증가배수"],
        )

# =========================
# ③ 국가별 조회
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

    if COL_ORDERNO in base.columns:
        rep_cnt = base.groupby(COL_CUST2, dropna=False)[COL_ORDERNO].nunique()
    else:
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

# =========================
# ④ BP명별 조회
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

    if COL_ORDERNO in base.columns:
        rep_cnt = base.groupby(COL_BP, dropna=False)[COL_ORDERNO].nunique()
    else:
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

    period_title = "누적 SKU Top10 (요청수량 기준)" if sel_month_label == "전체" else f"{sel_month_label} SKU Top10 (요청수량 기준)"
    st.subheader(period_title)

    top10_sku = build_item_top10_with_bp(df_view.copy())
    render_pretty_table(
        top10_sku,
        height=420,
        wrap_cols=[COL_ITEM_NAME, "BP명(요청수량)"],
        col_width_px={"순위": 60, COL_ITEM_CODE: 130, COL_ITEM_NAME: 420, "요청수량_합": 120, "BP명(요청수량)": 520},
        number_cols=["요청수량_합"],
    )
    st.caption("※ BP명(요청수량)은 해당 SKU의 출고처별 수량 합계입니다. (왼쪽 필터 범위 기준)")

    st.divider()

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

st.caption("※ 모든 집계는 Google Sheet RAW 기반이며, 제품분류(B0/B1) 고정 + 선택한 필터 범위 내에서 계산됩니다.")

# ==========================================
# B2B 출고 대시보드 (안정화 최종본)
# - 캘린더 → BP 클릭 시 상세 즉시 전환
# - 출고건 클릭 시 품목라인 즉시 노출
# - HTML 링크 제거 (Streamlit 버튼 방식)
# ==========================================

import streamlit as st
import pandas as pd
import calendar
from datetime import datetime

st.set_page_config(layout="wide")

# =========================
# 세션 상태 초기화
# =========================
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "calendar"

if "selected_date" not in st.session_state:
    st.session_state.selected_date = None

if "selected_bp" not in st.session_state:
    st.session_state.selected_bp = None

if "selected_doc" not in st.session_state:
    st.session_state.selected_doc = None

# =========================
# 데이터 로드
# =========================
@st.cache_data
def load_data():
    df = pd.read_csv("data.csv")
    df["출고일자"] = pd.to_datetime(df["출고일자"])
    return df

df = load_data()

# =========================
# 메인 타이틀
# =========================
st.title("📦 출고 캘린더")

# =========================
# 1️⃣ 캘린더 화면
# =========================
if st.session_state.view_mode == "calendar":

    year = st.number_input("연도", 2020, 2030, 2026)
    month = st.number_input("월", 1, 12, 1)

    cal = calendar.monthcalendar(year, month)

    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day != 0:
                with cols[i]:
                    date_obj = datetime(year, month, day)
                    day_df = df[df["출고일자"].dt.date == date_obj.date()]

                    st.markdown(f"### {day}")

                    if not day_df.empty:
                        bp_summary = (
                            day_df.groupby("BP명")["요청수량"]
                            .sum()
                            .reset_index()
                        )

                        for _, row in bp_summary.iterrows():
                            if st.button(
                                f"{row['BP명']} / {int(row['요청수량']):,}",
                                key=f"{date_obj}_{row['BP명']}",
                            ):
                                st.session_state.selected_date = date_obj.date()
                                st.session_state.selected_bp = row["BP명"]
                                st.session_state.view_mode = "bp_detail"
                                st.rerun()

# =========================
# 2️⃣ BP 상세 화면
# =========================
elif st.session_state.view_mode == "bp_detail":

    st.button("← 캘린더로 돌아가기", on_click=lambda: st.session_state.update({
        "view_mode": "calendar",
        "selected_doc": None
    }))

    date = st.session_state.selected_date
    bp = st.session_state.selected_bp

    st.subheader("📦 BP 출고 상세 (출고건ID 목록)")
    st.write(f"일자: {date}")
    st.write(f"BP명: {bp}")

    filtered = df[
        (df["출고일자"].dt.date == date)
        & (df["BP명"] == bp)
    ]

    doc_summary = (
        filtered.groupby(["출고건ID", "작업완료일"])
        .agg({"요청수량": "sum"})
        .reset_index()
    )

    st.markdown("---")

    for _, row in doc_summary.iterrows():
        if st.button(
            f"[출고건ID {row['출고건ID']}] "
            f"수량 {int(row['요청수량']):,} | "
            f"작업완료 {row['작업완료일']}",
            key=f"doc_{row['출고건ID']}",
        ):
            st.session_state.selected_doc = row["출고건ID"]
            st.session_state.view_mode = "doc_detail"
            st.rerun()

# =========================
# 3️⃣ 출고건 상세 화면
# =========================
elif st.session_state.view_mode == "doc_detail":

    st.button("← BP 상세로 돌아가기", on_click=lambda: st.session_state.update({
        "view_mode": "bp_detail"
    }))

    doc_id = st.session_state.selected_doc

    st.subheader("📦 출고건 품목 상세")

    doc_df = df[df["출고건ID"] == doc_id]

    st.dataframe(doc_df[["품목코드", "품목명", "요청수량"]])

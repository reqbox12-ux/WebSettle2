"""
domains/payroll/insurance/ui.py — 4대보험 고지내역 업로드 UI
"""
from datetime import datetime
import pandas as pd
import streamlit as st

from shared.utils import sec, fn
from domains.payroll.db import (
    save_insurance_actuals, get_all_insurance_actuals, delete_insurance_actuals,
)
from domains.payroll.insurance.service import (
    parse_pension, parse_health, parse_employment, merge_insurance_records,
)

_now = datetime.now()


def render():
    tab_upload, tab_view = st.tabs(["📤 고지내역 업로드", "📋 등록 현황 확인"])

    with tab_upload:
        _render_upload()

    with tab_view:
        _render_view()


def _render_upload():
    sec("공단 고지내역 업로드 (월별)")
    st.markdown("""
    매월 공단에서 받은 **3개 고지내역 파일**을 업로드하세요.
    이름 기준으로 직원과 자동 매칭되어 급여 계산 시 실납부액으로 대체됩니다.
    - **국민연금**: 엑셀 (2차결정내역통보서)
    - **건강보험**: CSV (cp949)
    - **고용보험**: 엑셀 (고용/산재보험 고지내역)
    """)

    col1, col2 = st.columns(2)
    year  = col1.selectbox("적용 연도", list(range(_now.year, _now.year - 3, -1)), key="ins_up_yr")
    month = col2.selectbox("적용 월",   list(range(1, 13)), index=_now.month - 1, key="ins_up_mn",
                           format_func=lambda m: f"{m}월")

    st.divider()

    c1, c2, c3 = st.columns(3)
    f_pension = c1.file_uploader("국민연금 고지내역 (.xlsx)", type=["xlsx"], key="ins_pension")
    f_health  = c2.file_uploader("건강보험 고지내역 (.csv)",  type=["csv"],  key="ins_health")
    f_employ  = c3.file_uploader("고용보험 고지내역 (.xlsx)", type=["xlsx"], key="ins_employ")

    if st.button("📥 고지내역 저장", type="primary", key="ins_save_btn",
                 disabled=(not f_pension and not f_health and not f_employ)):
        all_errors = []
        pension_recs = health_recs = employ_recs = []

        if f_pension:
            with st.spinner("국민연금 파싱 중..."):
                pension_recs, errs = parse_pension(f_pension)
                all_errors.extend(errs)
                st.caption(f"국민연금: {len(pension_recs)}명 파싱")

        if f_health:
            with st.spinner("건강보험 파싱 중..."):
                health_recs, errs = parse_health(f_health)
                all_errors.extend(errs)
                st.caption(f"건강보험: {len(health_recs)}명 파싱")

        if f_employ:
            with st.spinner("고용보험 파싱 중..."):
                employ_recs, errs = parse_employment(f_employ)
                all_errors.extend(errs)
                st.caption(f"고용보험: {len(employ_recs)}명 파싱")

        merged = merge_insurance_records(pension_recs, health_recs, employ_recs)
        if merged:
            saved, unmatched = save_insurance_actuals(year, month, merged)
            st.success(
                f"✅ {year}년 {month}월 고지내역 저장 완료 — "
                f"총 {saved}명 / 직원 매칭 {saved - unmatched}명 / 미매칭 {unmatched}명"
            )
            if unmatched > 0:
                st.info(
                    "미매칭 직원은 직원 마스터에 등록된 이름과 고지내역 이름이 다를 경우 발생합니다. "
                    "등록 현황에서 확인 후 직원 마스터 이름을 맞춰주세요."
                )
        else:
            st.warning("저장할 데이터가 없습니다.")

        for e in all_errors:
            st.warning(e)

    # 초기화 버튼
    st.divider()
    st.caption("⚠️ 해당 월 고지내역 전체 삭제 (재업로드 전 사용)")
    col_d1, col_d2 = st.columns([1, 3])
    d_year  = col_d1.selectbox("연도", list(range(_now.year, _now.year - 3, -1)), key="ins_del_yr")
    d_month = col_d1.selectbox("월",   list(range(1, 13)), key="ins_del_mn",
                                format_func=lambda m: f"{m}월")
    if col_d2.button("해당 월 고지내역 삭제", key="ins_del_btn"):
        if delete_insurance_actuals(d_year, d_month):
            st.success(f"{d_year}년 {d_month}월 고지내역 삭제 완료")
        else:
            st.error("삭제 실패")


def _render_view():
    sec("등록된 고지내역 확인")

    col1, col2, col3 = st.columns([2, 2, 1])
    year  = col1.selectbox("연도", list(range(_now.year, _now.year - 3, -1)), key="ins_view_yr")
    month = col2.selectbox("월",   list(range(1, 13)), index=_now.month - 1, key="ins_view_mn",
                           format_func=lambda m: f"{m}월")
    col3.markdown("<br>", unsafe_allow_html=True)
    if col3.button("🔄 새로고침", key="ins_refresh_btn", use_container_width=True):
        st.rerun()

    actuals = get_all_insurance_actuals(year, month)
    if not actuals:
        st.info(f"{year}년 {month}월 고지내역이 등록되어 있지 않습니다.")
        return

    df = pd.DataFrame(actuals)
    show_cols = {
        "employee_name": "이름",
        "employee_id":   "직원ID",
        "pension_base":  "연금기준",
        "pension_emp":   "연금(직원)",
        "pension_co":    "연금(회사)",
        "health_base":   "건강기준",
        "health_emp":    "건강+요양(직원)",
        "health_co":     "건강+요양(회사)",
        "employ_base":   "고용기준",
        "employ_emp":    "고용(직원)",
        "employ_co":     "고용(회사)",
    }
    show_df = df[[c for c in show_cols if c in df.columns]].copy()
    show_df = show_df.rename(columns=show_cols)

    # 미매칭 강조
    show_df["직원ID"] = show_df["직원ID"].apply(lambda v: "✅" if pd.notna(v) and v else "⚠️미매칭")

    amt_cols = ["연금기준", "연금(직원)", "연금(회사)", "건강기준", "건강+요양(직원)", "건강+요양(회사)",
                "고용기준", "고용(직원)", "고용(회사)"]
    for col in amt_cols:
        if col in show_df.columns:
            show_df[col] = show_df[col].apply(lambda v: f"{int(v):,}" if pd.notna(v) and v else "0")

    st.dataframe(show_df, use_container_width=True, hide_index=True, height=500)
    st.caption(f"총 {len(actuals)}명 · 매칭 {sum(1 for a in actuals if a.get('employee_id'))}명")

    # 합계
    total_emp = sum(
        (a.get("pension_emp", 0) + a.get("health_emp", 0) + a.get("employ_emp", 0))
        for a in actuals
    )
    total_co  = sum(
        (a.get("pension_co", 0) + a.get("health_co", 0) + a.get("employ_co", 0))
        for a in actuals
    )
    c1, c2 = st.columns(2)
    c1.metric("직원 부담 합계", f"{total_emp:,}원")
    c2.metric("회사 부담 합계", f"{total_co:,}원")

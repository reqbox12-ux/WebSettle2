"""
domains/payroll/ui.py — 급여계산 탭 메인 UI (서브탭 라우팅)
4대보험 고지내역 업로드는 '데이터 업로드' 페이지로 통합됨.
"""
import streamlit as st
from domains.payroll.employee.ui import render as render_employee
from domains.payroll.calculation.ui import render as render_calculation
from domains.payroll.payslip.ui import render as render_payslip
from domains.payroll.email.service import render_email_settings


def render_page():
    st.markdown(
        '<div class="ph"><div class="ph-title">급여 계산</div>'
        '<div class="ph-sub">직원 마스터 → 급여 계산 → 급여명세서 발행 '
        '· 4대보험 고지내역 업로드는 데이터 업로드 탭에서</div></div>',
        unsafe_allow_html=True,
    )

    tab_emp, tab_calc, tab_slip, tab_email = st.tabs([
        "👥 직원 마스터",
        "🧮 급여 계산",
        "📄 급여명세서",
        "📧 이메일 설정",
    ])

    with tab_emp:
        render_employee()

    with tab_calc:
        render_calculation()

    with tab_slip:
        render_payslip()

    with tab_email:
        render_email_settings()

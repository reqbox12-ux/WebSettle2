"""
domains/payroll/payslip/ui.py — 급여명세서 발행 및 미리보기 UI
"""
import base64
from datetime import datetime
import streamlit as st

from shared.config import BRANCH_LIST
from shared.utils import sec, fn
from domains.payroll.db import get_payroll_entries
from domains.payroll.payslip.service import gen_payslip_html, gen_withholding_html

_now = datetime.now()


def render():
    col1, col2, col3 = st.columns([1, 1, 2])
    year  = col1.selectbox("연도", list(range(_now.year, _now.year - 3, -1)), key="ps_yr")
    month = col2.selectbox("월", list(range(1, 13)), index=_now.month - 1, key="ps_mn",
                            format_func=lambda m: f"{m}월")
    br_sel = col3.selectbox("지점", ["전체"] + BRANCH_LIST, key="ps_br")

    entries = get_payroll_entries(year, month, None if br_sel == "전체" else br_sel)
    if not entries:
        st.info("계산된 급여 데이터가 없습니다. 급여계산 탭에서 계산 먼저 실행하세요.")
        return

    insured_entries   = [e for e in entries if e["emp_type"] == "insured"]
    freelance_entries = [e for e in entries if e["emp_type"] == "freelance"]
    business_entries  = [e for e in entries if e["emp_type"] in ("business", "tax_exempt")]

    tab_ins, tab_frl, tab_biz = st.tabs([
        f"급여명세서 (4대보험) — {len(insured_entries)}명",
        f"원천징수영수증 (사업소득자) — {len(freelance_entries)}명",
        f"계산서 내역 (사업자) — {len(business_entries)}개",
    ])

    with tab_ins:
        if not insured_entries:
            st.info("4대보험 가입자 데이터가 없습니다.")
        else:
            _render_payslip_list(insured_entries, year, month, "insured")

    with tab_frl:
        if not freelance_entries:
            st.info("사업소득자 데이터가 없습니다.")
        else:
            _render_payslip_list(freelance_entries, year, month, "freelance")

    with tab_biz:
        if not business_entries:
            st.info("사업자 데이터가 없습니다.")
        else:
            _render_business_list(business_entries, year, month)


def _render_payslip_list(entries: list, year: int, month: int, emp_type: str):
    sec(f"{'급여명세서' if emp_type == 'insured' else '원천징수영수증'} — {year}년 {month}월")

    for entry in entries:
        name   = entry.get("name", "")
        branch = entry.get("branch", "")
        email  = entry.get("email", "")

        if emp_type == "insured":
            html_content = gen_payslip_html(entry)
        else:
            html_content = gen_withholding_html(entry)

        html_b64  = base64.b64encode(html_content.encode("utf-8")).decode()
        file_name = f"{'급여명세서' if emp_type == 'insured' else '원천징수영수증'}_{year}{month:02d}_{name}.html"

        with st.expander(f"📄 {name} · {branch} {'· ' + email if email else ''}"):
            col_dl, col_email = st.columns([2, 1])
            col_dl.markdown(
                f'<a href="data:text/html;base64,{html_b64}" download="{file_name}" '
                f'style="background:#E60028;color:#fff;border-radius:8px;font-weight:600;'
                f'font-size:13px;padding:8px 18px;text-decoration:none;display:inline-block">'
                f'📥 다운로드</a>',
                unsafe_allow_html=True,
            )
            if email:
                if col_email.button("📧 이메일 발송", key=f"send_{entry['employee_id']}_{year}{month}"):
                    st.session_state[f"send_target_{entry['employee_id']}"] = {
                        "entry": entry, "html": html_content, "file_name": file_name,
                    }

            send_key = f"send_target_{entry['employee_id']}"
            if st.session_state.get(send_key):
                target = st.session_state[send_key]
                st.warning(f"**{email}** 으로 발송하시겠습니까?")
                c1, c2 = st.columns(2)
                if c1.button("✅ 확인 발송", key=f"confirm_send_{entry['employee_id']}"):
                    from domains.payroll.email.service import send_payslip_email
                    ok, err = send_payslip_email(
                        to_email=email,
                        subject=f"[{year}년 {month}월] {'급여명세서' if emp_type == 'insured' else '원천징수영수증'} — {name}",
                        html_content=target["html"],
                        attachment_name=target["file_name"],
                    )
                    if ok:
                        st.success("✅ 발송 완료!")
                    else:
                        st.error(f"발송 실패: {err}")
                    del st.session_state[send_key]
                if c2.button("취소", key=f"cancel_send_{entry['employee_id']}"):
                    del st.session_state[send_key]


def _render_business_list(entries: list, year: int, month: int):
    sec(f"계산서 지급 내역 — {year}년 {month}월")
    st.caption("별도 세금 공제 없이 지급 처리된 일반/면세사업자 내역입니다.")

    TYPE_KR = {"business": "일반사업자", "tax_exempt": "면세사업자"}

    # 목록 테이블
    rows_html = ""
    total = 0
    for e in entries:
        type_kr = TYPE_KR.get(e["emp_type"], e["emp_type"])
        amt = int(e.get("gross_pay", 0))
        total += amt
        rows_html += (
            f'<tr>'
            f'<td style="text-align:left;font-weight:600">{e.get("name","")}</td>'
            f'<td>{e.get("branch","")}</td>'
            f'<td>{type_kr}</td>'
            f'<td style="text-align:right;font-feature-settings:\'tnum\' 1">{amt:,}원</td>'
            f'<td style="text-align:right;font-feature-settings:\'tnum\' 1;color:var(--pos)">{amt:,}원</td>'
            f'</tr>'
        )

    html = f"""
    <div class="bt"><table>
    <thead><tr>
      <th style="text-align:left">상호명</th>
      <th>지점</th><th>구분</th><th>계산서 금액</th><th>지급액</th>
    </tr></thead>
    <tbody>
      {rows_html}
      <tr style="font-weight:700;background:var(--sf2)">
        <td colspan="3" style="text-align:right;color:var(--ink3)">합계</td>
        <td style="text-align:right;font-feature-settings:'tnum' 1">{total:,}원</td>
        <td style="text-align:right;font-feature-settings:'tnum' 1;color:var(--pos)">{total:,}원</td>
      </tr>
    </tbody></table></div>
    """
    st.markdown(html, unsafe_allow_html=True)

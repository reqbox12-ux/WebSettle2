"""
domains/payroll/employee/ui.py — 직원 마스터 관리 UI
"""
import streamlit as st
import pandas as pd

from shared.utils import sec
from domains.branch.db import get_active_branch_names
from domains.payroll.db import (
    get_all_employees, get_employees_by_branch,
    upsert_employee, delete_employee, deduplicate_employees,
    create_employee_account, get_employee_account, get_all_employee_accounts,
    reset_employee_password,
)
from domains.payroll.employee.service import import_employees_from_excel

EMP_TYPE_LABELS = {
    "insured":    "4대보험 가입자",
    "freelance":  "사업소득자 (3.3%)",
    "business":   "일반사업자",
    "tax_exempt": "면세사업자",
}
EMP_TYPE_SHORT = {
    "insured":    "4대보험",
    "freelance":  "사업소득자",
    "business":   "일반사업자",
    "tax_exempt": "면세사업자",
}


def render():
    BRANCH_LIST = get_active_branch_names()
    sec("직원 마스터")

    tab_list, tab_add, tab_import, tab_account = st.tabs(
        ["직원 목록", "직원 추가/수정", "엑셀 일괄 등록", "🔑 직원 계정"]
    )

    # ── 직원 목록 ────────────────────────────────────────────
    with tab_list:
        # 중복 직원 정리 --------------------------------------
        with st.expander("🧹 중복 직원 정리 (이름 + 지점 + 유형 기준)", expanded=False):
            st.caption(
                "**이름 · 소속지점 · 고용유형** 3가지가 모두 동일한 경우에만 중복으로 처리합니다. "
                "같은 이름이라도 유형이 다르면(예: 4대보험 기본급 + 사업소득 인센티브) 중복이 아닙니다. "
                "가장 먼저 등록된 행(최소 ID)을 대표로 남기고, 연결된 급여 내역은 자동 재연결됩니다."
            )
            if st.button("🧹 지금 중복 정리 실행", key="dedup_btn", type="primary"):
                result = deduplicate_employees()
                if result["groups"] == 0:
                    st.success("✅ 중복 직원이 없습니다. 데이터가 깔끔합니다!")
                else:
                    st.success(
                        f"✅ 정리 완료 — {result['groups']}개 그룹에서 "
                        f"중복 {result['deleted']}명 삭제"
                    )
                    EMP_TYPE_SHORT_LOCAL = {
                        "insured": "4대보험", "freelance": "사업소득자",
                        "business": "일반사업자", "tax_exempt": "면세사업자",
                    }
                    rows = [
                        {
                            "이름": d["name"], "지점": d["branch"],
                            "유형": EMP_TYPE_SHORT_LOCAL.get(d.get("emp_type", ""), d.get("emp_type", "")),
                            "유지 ID": d["kept_id"], "삭제 수": d["removed"],
                        }
                        for d in result["detail"]
                    ]
                    st.dataframe(rows, use_container_width=True, hide_index=True)
                st.rerun()

        col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
        sel_br   = col_f1.selectbox("지점 필터", ["전체"] + BRANCH_LIST, key="emp_br_filter")
        type_filter = col_f2.selectbox("유형 필터", ["전체", "4대보험", "사업소득자", "사업자"],
                                       key="emp_type_filter")
        show_all = col_f3.checkbox("퇴직자 포함", value=False, key="emp_show_all")

        if sel_br == "전체":
            emps = get_all_employees(active_only=not show_all)
        else:
            emps = get_employees_by_branch(sel_br, active_only=not show_all)

        if type_filter == "4대보험":
            emps = [e for e in emps if e["emp_type"] == "insured"]
        elif type_filter == "사업소득자":
            emps = [e for e in emps if e["emp_type"] == "freelance"]
        elif type_filter == "사업자":
            emps = [e for e in emps if e["emp_type"] in ("business", "tax_exempt")]

        if not emps:
            st.info("등록된 직원/사업자가 없습니다.")
        else:
            df = pd.DataFrame(emps)
            display_cols = {
                "id": "ID", "name": "이름", "branch": "지점",
                "emp_type": "유형", "dependents": "부양가족",
                "base_salary": "기본급", "meal_allowance": "식대",
                "transport": "교통비", "email": "이메일",
                "phone": "전화번호", "work_start": "출근시간", "work_end": "퇴근시간",
                "break_minutes": "휴게(분)", "hourly_rate": "시급",
                "join_date": "입사/등록일", "is_active": "재직",
            }
            edit_df = df[[c for c in display_cols if c in df.columns]].copy()
            edit_df = edit_df.rename(columns=display_cols)
            edit_df["유형"] = edit_df["유형"].map(EMP_TYPE_SHORT).fillna(edit_df["유형"])
            edit_df["재직"] = edit_df["재직"].apply(lambda v: bool(v))
            for col in ["부양가족", "기본급", "식대", "교통비", "휴게(분)", "시급"]:
                if col in edit_df.columns:
                    edit_df[col] = pd.to_numeric(edit_df[col], errors="coerce").fillna(0).astype(int)

            edited = st.data_editor(
                edit_df,
                use_container_width=True,
                hide_index=True,
                height=450,
                num_rows="fixed",
                key="emp_editor_table",
                column_config={
                    "ID":         st.column_config.NumberColumn("ID", disabled=True, width="small"),
                    "이름":       st.column_config.TextColumn("이름", width="medium"),
                    "지점":       st.column_config.SelectboxColumn("지점", options=BRANCH_LIST),
                    "유형":       st.column_config.SelectboxColumn("유형", options=list(EMP_TYPE_SHORT.values())),
                    "부양가족":   st.column_config.NumberColumn("부양가족", min_value=0, max_value=10, step=1),
                    "기본급":     st.column_config.NumberColumn("기본급", format="%d", min_value=0),
                    "식대":       st.column_config.NumberColumn("식대", format="%d", min_value=0),
                    "교통비":     st.column_config.NumberColumn("교통비", format="%d", min_value=0),
                    "이메일":     st.column_config.TextColumn("이메일"),
                    "전화번호":   st.column_config.TextColumn("전화번호"),
                    "출근시간":   st.column_config.TextColumn("출근시간", help="HH:MM 형식 (예: 09:00)"),
                    "퇴근시간":   st.column_config.TextColumn("퇴근시간", help="HH:MM 형식 (예: 18:00)"),
                    "휴게(분)":   st.column_config.NumberColumn("휴게(분)", format="%d", min_value=0,
                                                                help="정규 휴게시간(분). 예: 1시간=60"),
                    "시급":       st.column_config.NumberColumn("시급", format="%d", min_value=0),
                    "입사/등록일": st.column_config.TextColumn("입사/등록일"),
                    "재직":       st.column_config.CheckboxColumn("재직"),
                },
            )
            st.caption(f"총 {len(emps)}명 · 셀을 클릭해 직접 수정 후 아래 저장 버튼을 누르세요.")

            if st.button("💾 변경사항 저장", key="emp_inline_save", type="primary"):
                changes = st.session_state.get("emp_editor_table", {}).get("edited_rows", {})
                if not changes:
                    st.info("변경된 내용이 없습니다.")
                else:
                    type_reverse = {v: k for k, v in EMP_TYPE_SHORT.items()}
                    col_reverse  = {v: k for k, v in display_cols.items()}
                    saved_count  = 0
                    for row_idx_str, row_changes in changes.items():
                        emp = dict(emps[int(row_idx_str)])
                        for col_label, val in row_changes.items():
                            db_col = col_reverse.get(col_label)
                            if not db_col:
                                continue
                            if db_col == "emp_type":
                                emp[db_col] = type_reverse.get(val, val)
                            elif db_col == "is_active":
                                emp[db_col] = 1 if val else 0
                            elif db_col in ("base_salary", "meal_allowance", "transport",
                                            "dependents", "hourly_rate", "break_minutes"):
                                emp[db_col] = int(val or 0)
                            else:
                                emp[db_col] = str(val or "").strip()
                        upsert_employee(emp)
                        saved_count += 1
                    st.success(f"✅ {saved_count}명 수정 완료")
                    st.rerun()

            st.divider()
            del_id = st.number_input("삭제할 직원 ID", min_value=1, step=1, key="del_emp_id")
            if st.button("직원 비활성화 (퇴직처리)", key="del_emp_btn"):
                if delete_employee(int(del_id)):
                    st.success("처리 완료")
                    st.rerun()
                else:
                    st.error("처리 실패")

    # ── 직원 추가/수정 ────────────────────────────────────────
    with tab_add:
        st.markdown("##### 직원 정보 입력")
        col1, col2, col3 = st.columns(3)
        emp_id   = col1.number_input("ID (수정 시 입력, 신규는 0)", min_value=0, step=1, key="emp_edit_id")
        emp_name = col2.text_input("이름 / 상호 *", key="emp_name")
        emp_br   = col3.selectbox("소속지점 *", BRANCH_LIST, key="emp_branch")

        col4, col5 = st.columns(2)
        emp_type = col4.selectbox(
            "유형 *",
            ["insured", "freelance", "business", "tax_exempt"],
            format_func=lambda x: EMP_TYPE_LABELS[x],
            key="emp_type",
        )
        emp_join = col5.text_input("입사/등록일 (YYYY-MM-DD)", key="emp_join")

        is_insured  = emp_type == "insured"
        is_business = emp_type in ("business", "tax_exempt")

        if is_insured:
            col6, col7, col8, col9 = st.columns(4)
            emp_dep   = col6.number_input("부양가족수 (본인 포함)", min_value=0, max_value=10, value=1, key="emp_dep")
            emp_base  = col7.number_input("세전기본급", min_value=0, step=10000, key="emp_base")
            emp_meal  = col8.number_input("식대", min_value=0, step=10000, value=100000, key="emp_meal")
            emp_trans = col9.number_input("교통비", min_value=0, step=10000, key="emp_trans")
        else:
            emp_dep   = 0
            emp_base  = 0
            emp_meal  = 0
            emp_trans = 0

        col10, col11 = st.columns(2)
        emp_email = col10.text_input("이메일 (랜딩페이지 로그인 ID)", key="emp_email")
        emp_phone = col11.text_input("전화번호 (기본 비밀번호 뒷4자리)", key="emp_phone",
                                     placeholder="010-1234-5678")

        col12, col13, col14, col15 = st.columns(4)
        emp_wstart = col12.text_input("출근시간", value="09:00", key="emp_wstart",
                                      help="HH:MM 형식 (지각 판정 기준)")
        emp_wend   = col13.text_input("퇴근시간", value="18:00", key="emp_wend",
                                      help="HH:MM 형식")
        emp_break  = col14.number_input("정규 휴게(분)", min_value=0, step=30, value=60,
                                        key="emp_break",
                                        help="정규 휴게시간(분). 예: 1시간=60. 버튼 미사용시에도 자동 차감")
        emp_hwage  = col15.number_input("시급 (시간제 해당자)", min_value=0, step=100,
                                        key="emp_hwage", help="월급제는 0 입력")

        if is_business:
            emp_idnum = st.text_input("사업자등록번호", key="emp_idnum",
                                      help="계산서 발행 확인용")
        elif emp_type == "freelance":
            emp_idnum = st.text_input("주민등록번호", type="password", key="emp_idnum",
                                      help="원천징수영수증 발급용")
        else:
            emp_idnum = ""

        emp_note = st.text_input("비고", key="emp_note")

        # 사업자 유형 안내
        if is_business:
            st.info(
                f"{'📄 일반사업자' if emp_type == 'business' else '📄 면세사업자'}: "
                "계산서 발행 기준으로 지급 처리됩니다. 별도 세금 공제 없음."
            )

        if st.button("저장", type="primary", key="emp_save_btn"):
            if not emp_name or not emp_br:
                st.error("이름과 지점은 필수입니다.")
            else:
                data = {
                    "id":             int(emp_id) if emp_id else None,
                    "name":           emp_name.strip(),
                    "branch":         emp_br,
                    "emp_type":       emp_type,
                    "dependents":     int(emp_dep),
                    "base_salary":    int(emp_base),
                    "meal_allowance": int(emp_meal),
                    "transport":      int(emp_trans),
                    "email":          emp_email.strip(),
                    "phone":          emp_phone.strip(),
                    "work_start":     emp_wstart.strip() or "09:00",
                    "work_end":       emp_wend.strip() or "18:00",
                    "break_minutes":  int(emp_break),
                    "hourly_rate":    int(emp_hwage),
                    "id_number":      emp_idnum.strip() if emp_idnum else "",
                    "join_date":      emp_join.strip(),
                    "is_active":      1,
                    "note":           emp_note.strip(),
                }
                eid = upsert_employee(data)
                # 전화번호가 있으면 포털 계정 자동 생성 (아이디=전화번호, 초기PW=뒷4자리)
                _phone_n = emp_phone.strip().replace("-", "").replace(" ", "")
                if len(_phone_n) >= 8 and not get_employee_account(eid):
                    ok_acc, _ = create_employee_account(eid, _phone_n, _phone_n[-4:])
                    if ok_acc:
                        st.info(f"🔑 포털 계정 자동 생성 — 아이디: {_phone_n} / 초기PW: {_phone_n[-4:]} (첫 로그인 시 변경 필수)")
                st.success(f"✅ 저장 완료 (ID: {eid})")
                st.rerun()

    # ── 직원 계정 관리 ────────────────────────────────────────
    with tab_account:
        sec("직원 계정 관리")
        st.caption("직원들이 **지점 포털**에 로그인할 계정을 관리합니다. "
                   "**아이디=전화번호**, 초기 비밀번호=전화번호 뒷 4자리 "
                   "(첫 로그인 시 비밀번호 변경 강제: 8자 이상, 대문자+소문자+숫자)")

        all_emps_acc  = get_all_employees()
        staff_emps    = [e for e in all_emps_acc if e["emp_type"] in ("insured", "freelance")]
        existing_accs = {a["employee_id"]: a for a in get_all_employee_accounts()}

        def _phone_clean(e):
            return e.get("phone", "").replace("-", "").replace(" ", "")

        # 일괄 생성 — 전화번호만 있으면 가능
        eligible = [e for e in staff_emps if len(_phone_clean(e)) >= 8]
        no_info  = [e for e in staff_emps if len(_phone_clean(e)) < 8]

        col_aa, col_ab = st.columns([3, 1])
        with col_aa:
            if no_info:
                st.warning(f"⚠️ 전화번호 미등록: **{len(no_info)}명** "
                           f"— 직원 추가/수정 탭에서 먼저 입력하세요.")
        with col_ab:
            if st.button(f"✨ 계정 일괄 생성 ({len(eligible)}명)", type="primary", key="bulk_create_acc"):
                created = skipped = 0
                for emp in eligible:
                    phone = _phone_clean(emp)
                    ok, _ = create_employee_account(emp["id"], phone, phone[-4:])
                    if ok:
                        created += 1
                    else:
                        skipped += 1
                st.success(f"✅ 생성: {created}명 | 이미 있음(유지): {skipped}명")
                st.rerun()

        st.divider()

        # 계정 현황 테이블
        st.markdown("##### 계정 현황")
        rows = []
        for emp in staff_emps:
            acc = existing_accs.get(emp["id"])
            rows.append({
                "ID": emp["id"],
                "이름": emp["name"],
                "지점": emp["branch"],
                "유형": EMP_TYPE_SHORT.get(emp["emp_type"], emp["emp_type"]),
                "아이디(전화번호)": emp.get("phone", "").replace("-", "").replace(" ", "") or "—",
                "이메일": emp.get("email", "") or "—",
                "계정": "✅" if acc else "❌",
                "마지막로그인": (acc["last_login"][:16] if acc and acc.get("last_login") else "—"),
                "PW변경필요": ("⚠️ 미변경" if acc and acc.get("must_change_pw") else ("✅" if acc else "—")),
                "상태": ("활성" if acc and acc.get("is_active") else ("비활성" if acc else "—")),
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=380)
        else:
            st.info("4대보험/사업소득자 직원이 없습니다.")

        st.divider()
        st.markdown("##### 개별 계정 생성 / 비밀번호 초기화")
        col_c1, col_c2, col_c3 = st.columns([2, 2, 2])
        target_id = int(col_c1.number_input("직원 ID", min_value=1, step=1, key="acc_emp_id"))
        custom_pw = col_c2.text_input("비밀번호 (비워두면 전화뒷4자리)", key="acc_custom_pw")

        col_btn1, col_btn2 = col_c3.columns(2)
        if col_btn1.button("생성/갱신", type="primary", key="single_create_acc"):
            emp_found = next((e for e in all_emps_acc if e["id"] == target_id), None)
            if not emp_found:
                st.error("해당 ID의 직원이 없습니다.")
            else:
                phone_raw = emp_found.get("phone", "").replace("-", "").replace(" ", "")
                if len(phone_raw) < 8:
                    st.error("전화번호를 먼저 등록하세요.")
                else:
                    pw = custom_pw.strip() if custom_pw.strip() else phone_raw[-4:]
                    ok, msg = create_employee_account(emp_found["id"], phone_raw, pw)
                    if ok:
                        st.success(f"✅ {emp_found['name']} 계정 생성 완료 — 아이디: {phone_raw} / 초기PW: {pw}")
                    else:
                        st.error(f"실패: {msg}")
                    st.rerun()

        if col_btn2.button("PW초기화", key="reset_pw_btn"):
            emp_found = next((e for e in all_emps_acc if e["id"] == target_id), None)
            if not emp_found:
                st.error("해당 ID의 직원이 없습니다.")
            else:
                phone_raw = emp_found.get("phone", "").replace("-", "").replace(" ", "")
                pw = custom_pw.strip() if custom_pw.strip() else (phone_raw[-4:] if len(phone_raw) >= 4 else "0000")
                if reset_employee_password(emp_found["id"], pw):
                    st.success(f"✅ {emp_found['name']} 비밀번호 초기화 완료 (새 PW: {pw}) — 다음 로그인 시 변경 안내")
                else:
                    st.error("초기화 실패")
                st.rerun()

    # ── 엑셀 일괄 등록 ───────────────────────────────────────
    with tab_import:
        st.markdown("""
        **엑셀 양식 구조**
        - **시트1 (4대보험가입자)**: 직원명, 소속지점, 입사일, 부양가족수, 세전기본급, 식대, 교통비, 이메일, 비고
        - **시트2 (사업소득자)**: 직원명, 소속지점, 등록일, 주민등록번호, 이메일, 비고
        - **시트3 (사업자)**: 상호명, 소속지점, 사업자구분(일반/면세), 사업자등록번호, 이메일, 비고
        """)

        st.info(
            "💡 **중복 자동 방지**: 이름 + 소속지점이 동일한 직원이 이미 존재하면 "
            "덮어쓰기(업데이트)로 처리되므로 재업로드해도 중복이 생기지 않습니다."
        )
        uploaded = st.file_uploader("직원마스터_초기데이터.xlsx", type=["xlsx"], key="emp_bulk_upload")
        if uploaded and st.button("일괄 등록", type="primary", key="emp_bulk_btn"):
            with st.spinner("처리 중..."):
                saved, errors = import_employees_from_excel(uploaded)
            st.success(f"✅ {saved}명/개 처리 완료 (신규 등록 또는 정보 업데이트)")
            if errors:
                for e in errors:
                    st.warning(e)
            st.rerun()

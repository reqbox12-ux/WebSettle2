"""
domains/payroll/calculation/ui.py — 급여 입력 UI (개편)

워크플로우:
  ① 엑셀 1개 업로드 (시트: 4대보험 / 사업소득 / 사업자)
     → 이름+지점 자동 매칭 후 금액 입력란 자동 채움
  ② 직접 수정 가능
  ③ [급여 확정] 버튼 → 기존 데이터 삭제 후 전체 저장
"""
from datetime import datetime
import pandas as pd
import streamlit as st

from shared.config import BRANCH_LIST
from shared.utils import fn, sec
from domains.payroll.db import (
    get_all_employees, get_employees_by_branch,
    get_payroll_entries, save_payroll_entry,
    get_insurance_rates, save_insurance_rates,
    get_tax_brackets, upsert_tax_brackets,
    is_payroll_locked, lock_payroll, unlock_payroll,
    get_insurance_actual, delete_payroll_entries,
    get_public_holidays, upsert_public_holiday, delete_public_holiday,
)
from domains.payroll.calculation.service import calc_insured, calc_freelance, calc_business
from domains.payroll.insurance.service import apply_insurance_actuals, parse_tax_brackets

_now = datetime.now()
EMP_TYPE_LABELS = {
    "insured":    "4대보험",
    "freelance":  "사업소득자",
    "business":   "일반사업자",
    "tax_exempt": "면세사업자",
}

# ── 스테이징 헬퍼 ─────────────────────────────────────────────
def _stage_key(year: int, month: int) -> str:
    return f"pay_stage_{year}_{month}"


def _get_stage(year: int, month: int) -> dict:
    k = _stage_key(year, month)
    if k not in st.session_state:
        st.session_state[k] = {"insured": {}, "freelance": {}, "business": {}}
    return st.session_state[k]


def _ver_key(year: int, month: int) -> str:
    """위젯 버전 키 — 엑셀 적용마다 증가 → 완전히 새 위젯 생성 강제"""
    return f"pay_ver_{year}_{month}"


def _get_ver(year: int, month: int) -> int:
    return st.session_state.get(_ver_key(year, month), 0)


def _bump_ver(year: int, month: int):
    """버전을 올려서 다음 렌더에서 완전히 새 위젯이 만들어지게 함"""
    st.session_state[_ver_key(year, month)] = _get_ver(year, month) + 1


def _wkey(prefix: str, emp_id: int, year: int, month: int) -> str:
    """버전 포함 위젯 키 — 버전이 바뀌면 Streamlit이 새 위젯으로 인식"""
    ver = _get_ver(year, month)
    return f"{prefix}_{emp_id}_{year}_{month}_v{ver}"


def _clear_widget_keys(emps: list, prefix: str, year: int, month: int):
    """해당 직원 목록의 위젯 세션 상태 키를 모두 제거"""
    for emp in emps:
        key = _wkey(prefix, emp["id"], year, month)
        if key in st.session_state:
            del st.session_state[key]


# ── 엑셀 파싱 ─────────────────────────────────────────────────
def _find_col(columns: list, keywords: list):
    for kw in keywords:
        for c in columns:
            if kw in str(c).strip():
                return c
    return None


def _to_int(val) -> int:
    try:
        return int(float(str(val).replace(",", "").strip()))
    except Exception:
        return 0


def _match_amounts(emps: list, df: pd.DataFrame) -> dict:
    """직원 마스터와 엑셀 데이터를 이름+지점으로 매칭. {emp_id: amount} 반환"""
    cols = [str(c).strip() for c in df.columns]
    name_col   = _find_col(cols, ["이름", "성명", "직원", "상호"])
    branch_col = _find_col(cols, ["지점", "소속", "부서"])
    amount_col = _find_col(cols, ["금액", "세전", "기본급", "지급", "급여"])

    if not (name_col and branch_col and amount_col):
        return {}

    emp_map = {(e["name"], e["branch"]): e for e in emps}
    result: dict = {}
    for _, row in df.iterrows():
        name   = str(row[name_col]).strip()
        branch = str(row[branch_col]).strip()
        if not name or name in ("nan", "이름", "성명"):
            continue
        amount = _to_int(row[amount_col])
        emp    = emp_map.get((name, branch))
        if emp and amount > 0:
            result[emp["id"]] = amount
    return result


def _parse_payroll_excel(file, insured_emps, freelance_emps, business_emps) -> tuple:
    """
    급여 엑셀 파싱. st.* 호출 없이 결과와 로그를 반환.
    반환: (amounts_dict, log_dict)
      amounts_dict = {"insured":{id:amt}, "freelance":{id:amt}, "business":{id:amt}}
      log_dict     = {"sheets":[], "rows":[], "errors":[], "success":bool}
    """
    log = {"sheets": [], "rows": [], "errors": [], "success": False}

    try:
        xl = pd.ExcelFile(file)
    except Exception as e:
        log["errors"].append(f"❌ 엑셀 파일 읽기 실패: {e}")
        return {"insured": {}, "freelance": {}, "business": {}}, log

    log["sheets"] = xl.sheet_names

    def _pick_sheet(keywords):
        for kw in keywords:
            for sn in xl.sheet_names:
                if kw in str(sn):
                    return sn
        return None

    def _parse_sheet(sheet_name, emps, label):
        if not sheet_name:
            return {}
        try:
            df = xl.parse(sheet_name, dtype=str).fillna("")
            df.columns = [str(c).strip() for c in df.columns]
            cols = list(df.columns)

            # 컬럼 감지
            name_col   = _find_col(cols, ["이름", "성명", "직원", "상호"])
            branch_col = _find_col(cols, ["지점", "소속", "부서"])
            amount_col = _find_col(cols, ["금액", "세전", "기본급", "지급", "급여"])

            if not name_col:
                log["errors"].append(f"❌ [{label}] 이름 컬럼 없음 — 현재 컬럼: {cols}")
                return {}
            if not branch_col:
                log["errors"].append(f"❌ [{label}] 지점 컬럼 없음 — 현재 컬럼: {cols}")
                return {}
            if not amount_col:
                log["errors"].append(f"❌ [{label}] 금액 컬럼 없음 — 현재 컬럼: {cols}")
                return {}

            log["rows"].append(f"[{label}] 시트='{sheet_name}' | 컬럼 인식: 이름={name_col}, 지점={branch_col}, 금액={amount_col}")

            result = _match_amounts(emps, df)

            # 매칭 결과 로그
            log["rows"].append(f"  └ 매칭 성공: {len(result)}명")
            if emps:
                matched_ids = set(result.keys())
                unmatched = [
                    f"{e['name']}({e['branch']})"
                    for e in emps
                    if e["id"] not in matched_ids and int(e.get("base_salary", 0)) > 0
                ]
                if unmatched:
                    log["rows"].append(f"  └ 미매칭(엑셀에 없는 직원): {', '.join(unmatched[:15])}")
                # 엑셀에는 있으나 마스터에 없는 행
                emp_map = {(e["name"], e["branch"]) for e in emps}
                xl_only = []
                for _, row in df.iterrows():
                    n = str(row[name_col]).strip()
                    b = str(row[branch_col]).strip()
                    if n and n not in ("nan", "이름", "성명") and (n, b) not in emp_map:
                        xl_only.append(f"{n}({b})")
                if xl_only:
                    log["rows"].append(f"  └ 엑셀에만 있음(직원마스터 미등록): {', '.join(xl_only[:10])}")

            return result
        except Exception as ex:
            log["errors"].append(f"❌ [{label}] 파싱 오류: {ex}")
            return {}

    ins_sheet = _pick_sheet(["4대보험", "insured", "보험"])
    frl_sheet = _pick_sheet(["사업소득", "freelance", "프리랜서"])
    biz_sheet = _pick_sheet(["사업자",  "business", "계산서"])

    # 시트가 1개뿐이고 키워드 미매칭 → 첫 번째 시트를 4대보험으로
    if not ins_sheet and not frl_sheet and not biz_sheet:
        ins_sheet = xl.sheet_names[0]
        log["rows"].append(f"⚠️ 시트명 키워드 미감지 → '{ins_sheet}'을 4대보험 시트로 자동 처리")

    amounts = {
        "insured":   _parse_sheet(ins_sheet,  insured_emps,   "4대보험"),
        "freelance": _parse_sheet(frl_sheet,  freelance_emps, "사업소득"),
        "business":  _parse_sheet(biz_sheet,  business_emps,  "사업자"),
    }
    total = sum(len(v) for v in amounts.values())
    log["success"] = total > 0
    return amounts, log


# ── 메인 render ───────────────────────────────────────────────
def render():
    tab_input, tab_result, tab_settings = st.tabs(
        ["💰 급여 입력", "📊 계산 결과", "⚙️ 요율/세액 설정"]
    )
    with tab_input:
        _render_input()
    with tab_result:
        _render_result()
    with tab_settings:
        _render_settings()


# ── 급여 입력 탭 ──────────────────────────────────────────────
def _render_input():
    # ── 연월 / 지점 선택 ──────────────────────────────────────
    c1, c2, c3 = st.columns([1, 1, 2])
    year   = c1.selectbox("연도", list(range(_now.year, _now.year - 3, -1)), key="pc_yr")
    month  = c2.selectbox("월",   list(range(1, 13)), index=_now.month - 1, key="pc_mn",
                           format_func=lambda m: f"{m}월")
    br_sel = c3.selectbox("지점", ["전체"] + BRANCH_LIST, key="pc_br")

    # ── 잠금 확인 ─────────────────────────────────────────────
    if is_payroll_locked(year, month):
        st.warning(f"⚠️ {year}년 {month}월 급여는 확정(잠금) 상태입니다.")
        if st.session_state.get("auth_user", {}).get("role") == "admin":
            if st.button("🔓 잠금 해제", key="unlock_input"):
                unlock_payroll(year, month)
                st.rerun()
        return

    # ── 직원 목록 ─────────────────────────────────────────────
    emps = get_all_employees() if br_sel == "전체" else get_employees_by_branch(br_sel)
    insured_emps   = [e for e in emps if e["emp_type"] == "insured"]
    freelance_emps = [e for e in emps if e["emp_type"] == "freelance"]
    business_emps  = [e for e in emps if e["emp_type"] in ("business", "tax_exempt")]

    if not emps:
        st.info("등록된 직원이 없습니다. 직원 마스터를 먼저 등록하세요.")
        return

    stage = _get_stage(year, month)

    # ── 데이터 초기화 ─────────────────────────────────────────
    with st.expander("🗑️ 급여 데이터 초기화 (전체 삭제)", expanded=False):
        st.warning(f"⚠️ {year}년 {month}월에 저장된 모든 급여 데이터를 삭제합니다.")
        col_del1, col_del2 = st.columns([3, 1])
        branch_del = col_del1.selectbox("삭제 범위", ["전체"] + BRANCH_LIST, key="del_br")
        col_del2.markdown("<br>", unsafe_allow_html=True)
        if col_del2.button("삭제 실행", type="primary", key="del_all_btn", use_container_width=True):
            br_arg = None if branch_del == "전체" else branch_del
            cnt = delete_payroll_entries(year, month, br_arg)
            # 스테이징 초기화
            st.session_state[_stage_key(year, month)] = {"insured": {}, "freelance": {}, "business": {}}
            _clear_widget_keys(insured_emps,   "ins", year, month)
            _clear_widget_keys(freelance_emps, "frl", year, month)
            _clear_widget_keys(business_emps,  "biz", year, month)
            st.cache_data.clear()
            st.success(f"✅ {cnt}건 삭제 완료")
            st.rerun()

    # ── 엑셀 일괄 업로드 ─────────────────────────────────────
    st.markdown("#### 📤 엑셀 일괄 업로드")
    st.markdown("""
    <div style="background:var(--infos,#e8f0fb);border:1px solid rgba(57,99,168,.2);
    border-radius:8px;padding:12px 16px;font-size:12.5px;margin-bottom:12px">
    <b>엑셀 시트 구성:</b>&nbsp;
    <code>4대보험</code> | <code>사업소득</code> | <code>사업자</code><br>
    <b>필수 컬럼:</b>&nbsp; 이름 &nbsp;·&nbsp; 지점 &nbsp;·&nbsp; 금액(세전/기본급/지급액 등)
    </div>
    """, unsafe_allow_html=True)

    xl_col1, xl_col2 = st.columns([4, 1])
    xl_file  = xl_col1.file_uploader(
        f"급여_{year}년_{month}월.xlsx", type=["xlsx", "xls"],
        key=f"xl_pay_{year}_{month}",
    )
    xl_col2.markdown("<br>", unsafe_allow_html=True)
    apply_xl = xl_col2.button("📥 적용", key="apply_xl_btn",
                               use_container_width=True, disabled=xl_file is None)

    if xl_file and apply_xl:
        parsed, log = _parse_payroll_excel(xl_file, insured_emps, freelance_emps, business_emps)
        st.session_state["xl_log"] = log
        total = sum(len(v) for v in parsed.values())
        if total > 0:
            # 엑셀에 없는 직원은 명시적으로 0 설정 (기본급 그대로 남지 않도록)
            stage["insured"]   = {e["id"]: 0 for e in insured_emps}
            stage["freelance"] = {e["id"]: 0 for e in freelance_emps}
            stage["business"]  = {e["id"]: 0 for e in business_emps}
            # 엑셀 매칭 직원만 해당 금액으로 덮어씀
            stage["insured"].update(parsed["insured"])
            stage["freelance"].update(parsed["freelance"])
            stage["business"].update(parsed["business"])
            st.session_state[_stage_key(year, month)] = stage
            # 버전 올림 → 완전히 새로운 위젯 키 생성 → value= 파라미터 반드시 반영
            _bump_ver(year, month)
            parts = []
            if parsed["insured"]:   parts.append(f"4대보험 {len(parsed['insured'])}명")
            if parsed["freelance"]: parts.append(f"사업소득 {len(parsed['freelance'])}명")
            if parsed["business"]:  parts.append(f"사업자 {len(parsed['business'])}명")
            st.session_state["xl_log"]["success_msg"] = f"✅ 엑셀 적용 완료 — {' / '.join(parts)}"
            st.rerun()

    # ── 엑셀 적용 결과 (session_state에서 영구 표시) ──────────
    xl_log = st.session_state.get("xl_log")
    if xl_log is not None:
        with st.expander("📊 엑셀 적용 결과 (클릭하여 닫기)", expanded=True):
            if xl_log.get("sheets"):
                st.info(f"📋 파일 내 시트: **{' | '.join(xl_log['sheets'])}**")
            if xl_log.get("success_msg"):
                st.success(xl_log["success_msg"])
            for row in xl_log.get("rows", []):
                if row.startswith("⚠️"):
                    st.warning(row)
                elif row.startswith("  └"):
                    st.caption(row)
                else:
                    st.markdown(f"`{row}`")
            for err in xl_log.get("errors", []):
                st.error(err)
            if not xl_log.get("success") and not xl_log.get("errors"):
                st.error("❌ 매칭된 직원이 없습니다. 시트명(4대보험/사업소득/사업자)과 컬럼명(이름/지점/금액)을 확인하세요.")
            if st.button("✖ 결과 닫기", key="close_xl_log"):
                del st.session_state["xl_log"]
                st.rerun()

    st.divider()

    # ── 4대보험 입력 ──────────────────────────────────────────
    if insured_emps:
        sec(f"4대보험 가입자 ({len(insured_emps)}명)")
        st.caption("이번 달 기본급을 입력하세요. (식대·교통비는 직원 마스터 기준 자동 적용)")

        h1, h2, h3, h4, h5 = st.columns([2, 2, 2, 2, 1])
        for col, hdr in zip([h1,h2,h3,h4,h5],
                            ["이름","지점","기본급(마스터)","이번달 기본급","부양"]):
            col.markdown(f"**{hdr}**")

        for emp in insured_emps:
            default = stage["insured"].get(emp["id"], int(emp.get("base_salary", 0)))
            c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 1])
            c1.markdown(emp["name"])
            c2.markdown(emp["branch"])
            c3.markdown(f"{int(emp.get('base_salary', 0)):,}")
            c4.number_input("", min_value=0, value=default, step=10000,
                            key=_wkey("ins", emp["id"], year, month),
                            label_visibility="collapsed")
            c5.markdown(str(emp.get("dependents", 1)))

    # ── 사업소득자 입력 ───────────────────────────────────────
    if freelance_emps:
        sec(f"사업소득자 ({len(freelance_emps)}명)")
        st.caption("이번 달 지급액(세전)을 입력하세요. 3.3% 원천징수 자동 계산됩니다.")

        h1, h2, h3 = st.columns([2, 2, 4])
        for col, hdr in zip([h1,h2,h3], ["이름","지점","이번달 지급액 (세전)"]):
            col.markdown(f"**{hdr}**")

        for emp in freelance_emps:
            default = stage["freelance"].get(emp["id"], 0)
            c1, c2, c3 = st.columns([2, 2, 4])
            c1.markdown(emp["name"])
            c2.markdown(emp["branch"])
            c3.number_input("", min_value=0, value=default, step=10000,
                            key=_wkey("frl", emp["id"], year, month),
                            label_visibility="collapsed")

    # ── 일반/면세사업자 입력 ──────────────────────────────────
    if business_emps:
        sec(f"일반/면세사업자 ({len(business_emps)}명)")
        st.caption("계산서 발행 금액을 입력하세요. 별도 세금 공제 없이 지급 처리됩니다.")

        h1, h2, h3, h4 = st.columns([2, 2, 2, 2])
        for col, hdr in zip([h1,h2,h3,h4], ["상호명","지점","구분","계산서 금액"]):
            col.markdown(f"**{hdr}**")

        for emp in business_emps:
            default = stage["business"].get(emp["id"], 0)
            c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
            c1.markdown(emp["name"])
            c2.markdown(emp["branch"])
            c3.markdown("일반사업자" if emp["emp_type"] == "business" else "면세사업자")
            c4.number_input("", min_value=0, value=default, step=10000,
                            key=_wkey("biz", emp["id"], year, month),
                            label_visibility="collapsed")

    # ── 급여 확정 ─────────────────────────────────────────────
    st.divider()
    st.markdown("#### ✅ 급여 확정")
    st.info(
        "입력 내용을 모두 확인한 후 아래 버튼을 누르세요. "
        "기존 저장된 데이터는 삭제 후 재저장됩니다."
    )

    if st.button("✅ 급여 확정 (저장)", type="primary",
                  use_container_width=True, key="confirm_payroll"):
        _confirm_and_save(year, month, insured_emps, freelance_emps, business_emps)


def _confirm_and_save(year, month, insured_emps, freelance_emps, business_emps):
    """급여 확정: 기존 데이터 삭제 → 전체 계산 → 저장"""
    # 기존 데이터 삭제
    delete_payroll_entries(year, month)

    ok = 0
    actual_applied = 0
    errors = []

    # 4대보험
    for emp in insured_emps:
        gross = st.session_state.get(_wkey("ins", emp["id"], year, month), 0)
        if gross <= 0:
            continue
        try:
            entry  = calc_insured(emp, year, month, override_gross=gross)
            actual = get_insurance_actual(year, month, emp["id"])
            if actual:
                entry = apply_insurance_actuals(entry, actual)
                actual_applied += 1
            if save_payroll_entry(entry):
                ok += 1
            else:
                errors.append(f"{emp['name']} 저장 실패")
        except Exception as e:
            errors.append(f"{emp['name']}: {e}")

    # 사업소득자
    for emp in freelance_emps:
        gross = st.session_state.get(_wkey("frl", emp["id"], year, month), 0)
        if gross <= 0:
            continue
        try:
            entry = calc_freelance(emp, year, month, gross)
            if save_payroll_entry(entry):
                ok += 1
            else:
                errors.append(f"{emp['name']} 저장 실패")
        except Exception as e:
            errors.append(f"{emp['name']}: {e}")

    # 사업자
    for emp in business_emps:
        gross = st.session_state.get(_wkey("biz", emp["id"], year, month), 0)
        if gross <= 0:
            continue
        try:
            entry = calc_business(emp, year, month, gross)
            if save_payroll_entry(entry):
                ok += 1
            else:
                errors.append(f"{emp['name']} 저장 실패")
        except Exception as e:
            errors.append(f"{emp['name']}: {e}")

    if errors:
        st.error("저장 오류: " + " / ".join(errors))

    msg = f"✅ {ok}명 급여 확정 완료"
    if actual_applied:
        msg += f" (공단 실납부액 적용 {actual_applied}명)"
    st.success(msg)
    st.cache_data.clear()
    st.rerun()


# ── 계산 결과 탭 ──────────────────────────────────────────────
def _render_result():
    c1, c2, c3 = st.columns([1, 1, 2])
    r_year  = c1.selectbox("연도", list(range(_now.year, _now.year - 3, -1)), key="res_yr")
    r_month = c2.selectbox("월", list(range(1, 13)), index=_now.month - 1, key="res_mn",
                            format_func=lambda m: f"{m}월")
    r_br    = c3.selectbox("지점", ["전체"] + BRANCH_LIST, key="res_br")

    entries = get_payroll_entries(r_year, r_month, None if r_br == "전체" else r_br)
    if not entries:
        st.info("저장된 급여 데이터가 없습니다. '급여 입력' 탭에서 확정하세요.")
        return

    df = pd.DataFrame(entries)
    show_cols = {
        "name": "이름/상호", "branch": "지점", "emp_type": "유형",
        "gross_pay": "지급액(세전)", "meal_allowance": "식대", "transport": "교통비",
        "income_tax": "소득세", "local_tax": "지방세",
        "pension_emp": "국민연금", "health_emp": "건강보험", "employ_emp": "고용보험",
        "total_deduction": "공제합계", "net_pay": "실수령액",
        "company_pension": "연금(회사)", "company_health": "건강(회사)",
        "company_employ": "고용(회사)", "company_accident": "산재",
    }
    show_df = df[[c for c in show_cols if c in df.columns]].copy()
    show_df = show_df.rename(columns=show_cols)
    show_df["유형"] = show_df["유형"].map(EMP_TYPE_LABELS).fillna(show_df["유형"])
    for col in [v for k, v in show_cols.items() if k not in ("name","branch","emp_type")]:
        if col in show_df.columns:
            show_df[col] = show_df[col].apply(
                lambda v: f"{int(v):,}" if pd.notna(v) and str(v) != "" else "0"
            )
    st.dataframe(show_df, use_container_width=True, hide_index=True, height=500)

    total_gross = sum(e.get("gross_pay", 0) for e in entries)
    total_net   = sum(e.get("net_pay", 0)   for e in entries)
    total_co    = sum(
        e.get("company_pension",0) + e.get("company_health",0) +
        e.get("company_employ",0)  + e.get("company_accident",0)
        for e in entries
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("총 지급액 (세전)", f"{total_gross:,}원")
    c2.metric("총 실수령 합계",   f"{total_net:,}원")
    c3.metric("본사 부담 4대보험", f"{total_co:,}원")
    c4.metric("인원 수",         f"{len(entries)}명")

    # 잠금
    st.divider()
    locked = is_payroll_locked(r_year, r_month)
    if not locked:
        if st.button("🔒 급여 잠금", type="primary", key="lock_res_btn"):
            uname = st.session_state.get("auth_user", {}).get("username", "admin")
            lock_payroll(r_year, r_month, uname)
            st.success(f"🔒 {r_year}년 {r_month}월 급여 잠금 완료")
            st.rerun()
    else:
        st.success("🔒 이 급여는 확정(잠금) 상태입니다.")
        if st.session_state.get("auth_user", {}).get("role") == "admin":
            if st.button("🔓 잠금 해제", key="unlock_res_btn"):
                unlock_payroll(r_year, r_month)
                st.rerun()


# ── 요율/세액 설정 탭 ─────────────────────────────────────────
def _render_settings():
    sec("4대보험 요율 설정")
    rates = get_insurance_rates(_now.year)

    with st.form("insurance_rates_form"):
        c1, c2 = st.columns(2)
        r_year = c1.number_input("적용 연도", min_value=2020, max_value=2035,
                                  value=rates["year"], step=1)
        c2.markdown(" ")
        c3, c4, c5 = st.columns(3)
        pension    = c3.number_input("국민연금 (직원)", 0.0, 0.1,
                                      float(rates["pension_rate"]),    format="%.4f")
        health     = c4.number_input("건강보험 (직원)", 0.0, 0.1,
                                      float(rates["health_rate"]),     format="%.5f")
        employ_emp = c5.number_input("고용보험 (직원)", 0.0, 0.05,
                                      float(rates["employ_rate_emp"]), format="%.4f")
        c6, c7 = st.columns(2)
        employ_co  = c6.number_input("고용보험 (회사)", 0.0, 0.05,
                                      float(rates["employ_rate_co"]),  format="%.4f")
        accident   = c7.number_input("산재보험 (회사)", 0.0, 0.1,
                                      float(rates["accident_rate"]),   format="%.4f")
        if st.form_submit_button("요율 저장", type="primary"):
            ok = save_insurance_rates({
                "year": int(r_year), "pension_rate": pension, "health_rate": health,
                "employ_rate_emp": employ_emp, "employ_rate_co": employ_co,
                "accident_rate": accident,
            })
            st.success("✅ 저장 완료") if ok else st.error("저장 실패")

    st.divider()
    sec("간이세액표 업로드")
    t1, t2 = st.columns([1, 3])
    tax_year_sel = t1.number_input("적용 연도", 2020, 2035, _now.year, step=1)
    tax_file     = t2.file_uploader("간이세액표.xlsx (국세청 원본)", type=["xlsx"])
    if tax_file and st.button("간이세액표 업로드", type="primary"):
        rows, err = parse_tax_brackets(tax_file, int(tax_year_sel))
        if err:
            st.error(f"파싱 오류: {err}")
        elif not rows:
            st.warning("파싱된 데이터가 없습니다.")
        else:
            if upsert_tax_brackets(rows, int(tax_year_sel)):
                st.success(f"✅ {len(rows)}개 구간 저장 완료 ({int(tax_year_sel)}년)")
            else:
                st.error("저장 실패")

    brackets = get_tax_brackets(_now.year)
    if brackets:
        st.caption(f"현재 등록된 간이세액표: {_now.year}년 기준 {len(brackets)}개 구간")
    else:
        st.info("간이세액표가 없습니다. 업로드하거나 기본 계산식이 사용됩니다.")

    st.divider()
    sec("📅 공휴일 관리 (시급제 급여 할증 기준)")
    import pandas as pd
    hol_c1, hol_c2 = st.columns([1, 3])
    hol_year = hol_c1.number_input("연도", min_value=2020, max_value=2035,
                                    value=_now.year, step=1, key="hol_yr")
    holidays = get_public_holidays(int(hol_year))

    if holidays:
        hol_df = pd.DataFrame(holidays)[["id", "holiday_date", "name"]]
        hol_df.columns = ["ID", "날짜", "공휴일명"]
        st.dataframe(hol_df, use_container_width=True, hide_index=True)
        del_id = st.number_input("삭제할 공휴일 ID", min_value=1, step=1, key="hol_del_id")
        if st.button("🗑️ 공휴일 삭제", key="hol_del_btn"):
            delete_public_holiday(int(del_id))
            st.success("삭제 완료")
            st.rerun()
    else:
        st.info(f"{int(hol_year)}년 등록된 공휴일이 없습니다.")

    st.markdown("##### 공휴일 추가")
    with st.form("hol_add_form"):
        ha1, ha2 = st.columns([1, 2])
        new_hdate = ha1.text_input("날짜 (YYYY-MM-DD)", placeholder="2025-10-03")
        new_hname = ha2.text_input("공휴일명", placeholder="개천절")
        if st.form_submit_button("추가", type="primary"):
            if new_hdate and new_hname:
                try:
                    from datetime import date as _d
                    yr = _d.fromisoformat(new_hdate).year
                    if upsert_public_holiday(new_hdate, new_hname, yr):
                        st.success(f"✅ {new_hdate} {new_hname} 추가 완료")
                        st.rerun()
                except ValueError:
                    st.error("날짜 형식이 잘못됐습니다. YYYY-MM-DD로 입력하세요.")
            else:
                st.error("날짜와 공휴일명 모두 입력하세요.")

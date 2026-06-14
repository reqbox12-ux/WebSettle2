"""
domains/payroll/employee/service.py — 직원 마스터 비즈니스 로직
"""
import pandas as pd
from domains.payroll.db import upsert_employee


def _get_name(row_keys: dict) -> str:
    """컬럼명 변형 무관하게 이름 추출"""
    return str(
        row_keys.get("직원명", "") or row_keys.get("이름", "") or
        row_keys.get("상호명", "") or row_keys.get("성명", "")
    ).strip()


def import_employees_from_excel(file) -> tuple[int, list[str]]:
    """
    엑셀 파일에서 직원 초기 데이터 일괄 임포트.
    시트1: 4대보험가입자 / 시트2: 사업소득자 / 시트3: 사업자(일반/면세)
    반환: (저장 수, 오류 목록)
    """
    xl     = pd.ExcelFile(file)
    saved  = 0
    errors = []

    # ── 시트1: 4대보험가입자
    insured_sheets = [s for s in xl.sheet_names if any(k in s for k in ("보험", "4대", "가입자"))]
    if not insured_sheets:
        insured_sheets = xl.sheet_names[:1]

    for sheet in insured_sheets:
        try:
            df = xl.parse(sheet, dtype=str).fillna("")
            for _, row in df.iterrows():
                rk   = {str(k).strip(): v for k, v in row.items()}
                name = _get_name(rk)
                if not name or name == "nan":
                    continue
                upsert_employee({
                    "name":           name,
                    "branch":         str(rk.get("소속지점", "") or rk.get("지점", "")).strip(),
                    "emp_type":       "insured",
                    "dependents":     max(1, int(str(rk.get("부양가족수", 1)).replace(",", "") or 1)),
                    "base_salary":    int(str(rk.get("세전기본급", 0)).replace(",", "") or 0),
                    "meal_allowance": int(str(rk.get("식대", 0)).replace(",", "") or 0),
                    "transport":      int(str(rk.get("교통비", 0)).replace(",", "") or 0),
                    "email":          str(rk.get("이메일", "")).strip(),
                    "id_number":      str(rk.get("주민번호", "") or rk.get("주민등록번호", "")).strip(),
                    "join_date":      str(rk.get("입사일", "")).strip(),
                    "note":           str(rk.get("비고", "")).strip(),
                    "is_active":      1,
                })
                saved += 1
        except Exception as e:
            errors.append(f"[4대보험가입자] {e}")

    # ── 시트2: 사업소득자
    freelance_sheets = [s for s in xl.sheet_names if any(k in s for k in ("사업소득", "프리", "소득자"))]
    if not freelance_sheets and len(xl.sheet_names) > 1:
        freelance_sheets = xl.sheet_names[1:2]

    for sheet in freelance_sheets:
        try:
            df = xl.parse(sheet, dtype=str).fillna("")
            for _, row in df.iterrows():
                rk   = {str(k).strip(): v for k, v in row.items()}
                name = _get_name(rk)
                if not name or name == "nan":
                    continue
                upsert_employee({
                    "name":           name,
                    "branch":         str(rk.get("소속지점", "") or rk.get("지점", "")).strip(),
                    "emp_type":       "freelance",
                    "dependents":     0,
                    "base_salary":    0,
                    "meal_allowance": 0,
                    "transport":      0,
                    "email":          str(rk.get("이메일", "")).strip(),
                    "id_number":      str(rk.get("주민등록번호", "") or rk.get("주민번호", "")).strip(),
                    "join_date":      str(rk.get("등록일", "") or rk.get("입사일", "")).strip(),
                    "note":           str(rk.get("비고", "")).strip(),
                    "is_active":      1,
                })
                saved += 1
        except Exception as e:
            errors.append(f"[사업소득자] {e}")

    # ── 시트3: 사업자 (일반/면세)
    biz_sheets = [s for s in xl.sheet_names if any(k in s for k in ("사업자", "일반", "면세"))]
    if not biz_sheets and len(xl.sheet_names) > 2:
        biz_sheets = xl.sheet_names[2:3]

    for sheet in biz_sheets:
        try:
            df = xl.parse(sheet, dtype=str).fillna("")
            for _, row in df.iterrows():
                rk   = {str(k).strip(): v for k, v in row.items()}
                name = _get_name(rk)
                if not name or name == "nan":
                    continue
                biz_type_raw = str(rk.get("사업자구분", "일반")).strip()
                emp_type     = "tax_exempt" if "면세" in biz_type_raw else "business"
                upsert_employee({
                    "name":           name,
                    "branch":         str(rk.get("소속지점", "") or rk.get("지점", "")).strip(),
                    "emp_type":       emp_type,
                    "dependents":     0,
                    "base_salary":    0,
                    "meal_allowance": 0,
                    "transport":      0,
                    "email":          str(rk.get("이메일", "")).strip(),
                    "id_number":      str(rk.get("사업자등록번호", "") or rk.get("사업자번호", "")).strip(),
                    "join_date":      str(rk.get("등록일", "")).strip(),
                    "note":           str(rk.get("비고", "")).strip(),
                    "is_active":      1,
                })
                saved += 1
        except Exception as e:
            errors.append(f"[사업자] {e}")

    return saved, errors

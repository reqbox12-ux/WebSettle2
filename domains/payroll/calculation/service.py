"""
domains/payroll/calculation/service.py — 급여 계산 엔진
"""
from domains.payroll.db import get_insurance_rates, get_tax_brackets


def _lookup_income_tax(taxable: int, dependents: int, tax_year: int = 2026) -> int:
    """간이세액표 조회. 해당 연도 없으면 가장 최근 연도로 fallback, 그것도 없으면 계산식."""
    brackets = get_tax_brackets(tax_year)
    if not brackets:
        # fallback: 직전 연도 시도
        brackets = get_tax_brackets(tax_year - 1)
    dep_col  = f"dependents_{min(dependents, 7)}"
    for b in brackets:
        if b["salary_from"] <= taxable <= b["salary_to"]:
            return int(b.get(dep_col, 0))

    # 간이세액표 미등록 시 간략 계산 (국세청 2025 기준 근사치)
    if taxable <= 1_060_000:
        return 0
    elif taxable <= 1_500_000:
        return int((taxable - 1_060_000) * 0.06)
    elif taxable <= 3_000_000:
        return int(26_400 + (taxable - 1_500_000) * 0.15)
    elif taxable <= 4_500_000:
        return int(251_400 + (taxable - 3_000_000) * 0.24)
    elif taxable <= 8_800_000:
        return int(611_400 + (taxable - 4_500_000) * 0.35)
    else:
        return int(2_116_400 + (taxable - 8_800_000) * 0.38)


def calc_insured(employee: dict, year: int, month: int,
                 override_gross: int = None) -> dict:
    """
    4대보험 가입자 급여 계산.
    override_gross: 해당 월 실지급 기본급 오버라이드 (없으면 employee.base_salary 사용)
    """
    rates   = get_insurance_rates(year)
    gross   = override_gross if override_gross is not None else employee.get("base_salary", 0)
    meal    = employee.get("meal_allowance", 0)
    trans   = employee.get("transport", 0)
    dep     = employee.get("dependents", 1)

    # 과세 기준: 비과세(식대 월 20만, 교통비 월 20만) 제외
    taxable = gross + max(0, meal - 200_000) + max(0, trans - 200_000)

    # 소득세 (간이세액표 — 해당 연도, 없으면 최근 연도 fallback)
    income_tax = _lookup_income_tax(taxable, dep, tax_year=year)
    local_tax  = round(income_tax * 0.1)

    # 4대보험 직원 부담분
    pension_emp = round(gross * rates["pension_rate"])
    health_emp  = round(gross * rates["health_rate"])
    employ_emp  = round(gross * rates["employ_rate_emp"])
    total_ded   = income_tax + local_tax + pension_emp + health_emp + employ_emp
    net_pay     = gross + meal + trans - total_ded

    # 본사 부담분
    company_pension  = pension_emp
    company_health   = health_emp
    company_employ   = round(gross * rates["employ_rate_co"])
    company_accident = round(gross * rates["accident_rate"])

    return {
        "year": year, "month": month,
        "employee_id": employee["id"],
        "branch": employee["branch"],
        "emp_type": "insured",
        "gross_pay": gross,
        "meal_allowance": meal,
        "transport": trans,
        "taxable_base": taxable,
        "income_tax": income_tax,
        "local_tax": local_tax,
        "pension_emp": pension_emp,
        "health_emp": health_emp,
        "employ_emp": employ_emp,
        "total_deduction": total_ded,
        "net_pay": net_pay,
        "company_pension": company_pension,
        "company_health": company_health,
        "company_employ": company_employ,
        "company_accident": company_accident,
        "status": "draft",
    }


def calc_business(employee: dict, year: int, month: int, payment: int) -> dict:
    """
    일반사업자/면세사업자 지급 처리.
    계산서 발행 기준 — 별도 세금 공제 없음.
    """
    return {
        "year": year, "month": month,
        "employee_id": employee["id"],
        "branch": employee["branch"],
        "emp_type": employee["emp_type"],
        "gross_pay": payment,
        "meal_allowance": 0,
        "transport": 0,
        "taxable_base": 0,
        "income_tax": 0,
        "local_tax": 0,
        "pension_emp": 0,
        "health_emp": 0,
        "employ_emp": 0,
        "total_deduction": 0,
        "net_pay": payment,
        "company_pension": 0,
        "company_health": 0,
        "company_employ": 0,
        "company_accident": 0,
        "status": "draft",
    }


def calc_freelance(employee: dict, year: int, month: int, payment: int) -> dict:
    """
    사업소득자 급여 계산.
    payment: 지급 금액 (세전)
    소득세 3% + 지방소득세 0.3% = 3.3% 원천징수
    """
    income_tax = round(payment * 0.03)
    local_tax  = round(payment * 0.003)
    total_ded  = income_tax + local_tax
    net_pay    = payment - total_ded

    return {
        "year": year, "month": month,
        "employee_id": employee["id"],
        "branch": employee["branch"],
        "emp_type": "freelance",
        "gross_pay": payment,
        "meal_allowance": 0,
        "transport": 0,
        "taxable_base": payment,
        "income_tax": income_tax,
        "local_tax": local_tax,
        "pension_emp": 0,
        "health_emp": 0,
        "employ_emp": 0,
        "total_deduction": total_ded,
        "net_pay": net_pay,
        "company_pension": 0,
        "company_health": 0,
        "company_employ": 0,
        "company_accident": 0,
        "status": "draft",
    }

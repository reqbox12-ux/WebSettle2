"""
domains/dashboard/service.py — 대시보드 데이터 집계 서비스
"""
import pandas as pd
import streamlit as st
from shared.db import (
    get_card_by_branch, get_branch_cash_revenue, get_payroll_summary,
    get_expense_by_category, get_revenue_by_category, get_insurance_summary,
)
from shared.config import BRANCH_LIST
from domains.branch.db import get_branch_monthly_revenue
from domains.payroll.db import get_insurance_actuals_by_branch

# 월별 수동입력 매출 컬럼 (카페인건비 포함 — 아파트에서 받는 매출)
_BMR_REVENUE_COLS = ["dogeub", "pt_sales", "gx_sales", "cafe_sales",
                     "golf_sales", "facility_fee", "cafe_labor", "other_sales"]


# ── 캐시 래퍼 ───────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def c_card(y, m):
    return get_card_by_branch(y, m)


@st.cache_data(ttl=300, show_spinner=False)
def c_cash(y, m):
    return get_branch_cash_revenue(y, m)


@st.cache_data(ttl=300, show_spinner=False)
def c_pay(y, m):
    return get_payroll_summary(y, m)


@st.cache_data(ttl=300, show_spinner=False)
def c_exp(y, m):
    return get_expense_by_category(y, m)


@st.cache_data(ttl=300, show_spinner=False)
def c_rev(y, m):
    return get_revenue_by_category(y, m)


@st.cache_data(ttl=300, show_spinner=False)
def c_ins(y, m):
    return get_insurance_summary(y, m)


@st.cache_data(ttl=300, show_spinner=False)
def c_ins_actual(y, m):
    """공단 고지내역 기반 지점별 4대보험 집계 (insurance_actuals)"""
    rows = get_insurance_actuals_by_branch(y, m)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


@st.cache_data(ttl=300, show_spinner=False)
def c_bmr(y, m):
    """월별 수동입력 매출 (branch_monthly_revenue)"""
    rows = get_branch_monthly_revenue(y, m)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def build_summary(year: int, month: int) -> pd.DataFrame:
    """모든 지점의 월별 매출/지출/손익 집계"""
    card_df       = c_card(year, month)
    cash_df       = c_cash(year, month)
    pay_df        = c_pay(year, month)
    exp_df        = c_exp(year, month)
    ins_actual_df = c_ins_actual(year, month)
    bmr_df        = c_bmr(year, month)

    def s(df, col):
        return df.set_index("branch")[col] if not df.empty else pd.Series(dtype=float)

    card_sup = s(card_df, "card_supply")
    card_fee = s(card_df, "card_fee")
    card_vat = s(card_df, "card_vat")
    card_net = s(card_df, "card_net")
    cash_sup = s(cash_df, "cash_supply")
    cash_vat = s(cash_df, "cash_vat")

    if not pay_df.empty:
        ins   = pay_df[pay_df.type == "insured"].groupby("branch")["net_pay"].sum()
        ins_t = pay_df[pay_df.type == "insured"].groupby("branch")["income_tax"].sum()
        _ext  = pay_df.type.isin(["freelance", "business", "tax_exempt"])
        frl   = pay_df[_ext].groupby("branch")["net_pay"].sum()
        frl_t = pay_df[pay_df.type == "freelance"].groupby("branch")["income_tax"].sum()
        frl_l = pay_df[pay_df.type == "freelance"].groupby("branch")["local_tax"].sum()
    else:
        ins = ins_t = frl = frl_t = frl_l = pd.Series(dtype=float)

    # 4대보험: 공단 고지내역(insurance_actuals) 기준 → 고지내역 저장 즉시 반영
    ins_co  = s(ins_actual_df, "company_insurance")  if not ins_actual_df.empty else pd.Series(dtype=float)
    ins_emp = s(ins_actual_df, "employee_insurance") if not ins_actual_df.empty else pd.Series(dtype=float)
    ins4    = ins_emp  # 직원 부담 4대보험료 = 고지내역 기준

    pc = {"급여", "4대보험료", "소득세·지방세 합계", "프리랜서", "퇴직금"}
    other = (
        exp_df[~exp_df.category.isin(pc)].groupby("branch")["amount"].sum()
        if not exp_df.empty
        else pd.Series(dtype=float)
    )

    # ── 월별 수동입력 매출 집계 ─────────────────────────────
    if not bmr_df.empty and "branch" in bmr_df.columns:
        bmr_idx = bmr_df.set_index("branch")
        bmr_rev = sum(
            bmr_idx[c].fillna(0) if c in bmr_idx.columns else pd.Series(dtype=float)
            for c in _BMR_REVENUE_COLS
        )
        bmr_vat = (bmr_rev / 11).apply(lambda v: int(v))   # 직접입력매출 VAT (÷11)
    else:
        bmr_rev = pd.Series(dtype=float)
        bmr_vat = pd.Series(dtype=float)

    r = pd.DataFrame({"branch": BRANCH_LIST}).set_index("branch")
    r["카드공급가액"] = card_sup
    r["카드VAT"]     = card_vat
    r["카드수수료"]   = card_fee
    r["카드실수령"]   = card_net   # 참고용 (공급가액 – 수수료)
    r["현금VAT"]     = cash_vat
    r["현금공급가액"] = cash_sup
    r["수동입력매출"] = bmr_rev    # 직접 입력 현금매출 (도급비·시설상환비 등)
    r["직접입력VAT"]  = bmr_vat    # 직접입력매출 VAT (수동입력매출 ÷ 11)

    # ── 총매출 = 카드공급가액 + 카드수수료 + 카드VAT + 현금공급가액 + 현금VAT + 수동입력매출
    #    ※ 통장의 도급비 항목은 계정과목 검토에서 '제외' 처리 후 업로드할 것
    r["총매출"] = (
        r["카드공급가액"].fillna(0)
        + r["카드수수료"].fillna(0)
        + r["카드VAT"].fillna(0)
        + r["현금공급가액"].fillna(0)
        + r["현금VAT"].fillna(0)
        + r["수동입력매출"].fillna(0)
    )
    # 부가세합계 = 카드VAT + 현금VAT + 직접입력매출VAT
    r["부가세합계"] = (
        r["카드VAT"].fillna(0)
        + r["현금VAT"].fillna(0)
        + r["직접입력VAT"].fillna(0)
    )
    r["급여"]         = ins
    r["4대보험료_직원"] = ins4
    r["소득세지방세"]  = ins_t
    r["4대보험_본사"]  = ins_co
    r["4대보험_직원"]  = ins_emp
    r["프리랜서"]     = frl
    r["프리랜서세금"]  = frl_t + frl_l
    r["기타지출"]     = other
    r = r.fillna(0)
    r["인건비합계"] = (
        r["급여"] + r["4대보험료_직원"] + r["소득세지방세"]
        + r["프리랜서"] + r["프리랜서세금"] + r["4대보험_본사"]
    )
    # ── 총지출 = 인건비합계 + 기타지출 + 부가세합계 + 카드수수료
    r["총지출"] = (
        r["인건비합계"]
        + r["기타지출"]
        + r["부가세합계"]
        + r["카드수수료"].fillna(0)
    )
    r["손익"]   = r["총매출"] - r["총지출"]
    # ── 이익률 = 손익 ÷ 총매출 × 100
    r["이익률"] = r.apply(
        lambda x: round(x["손익"] / x["총매출"] * 100, 1) if x["총매출"] > 0 else 0,
        axis=1,
    )
    return r.reset_index()


@st.cache_data(ttl=300, show_spinner=False)
def build_trend(year: int, up_to_month: int) -> pd.DataFrame:
    """연간 추이용: 1~up_to_month 각 월 집계를 branch·month 컬럼 포함해 반환"""
    frames = []
    for m in range(1, up_to_month + 1):
        df = build_summary(year, m)
        if not df.empty:
            tmp = df[["branch", "총매출", "총지출", "손익", "인건비합계"]].copy()
            tmp["month"] = m
            frames.append(tmp)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)

"""
domains/upload/ui.py — 데이터 업로드 페이지
"""
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from shared.config import BRANCH_LIST, ALL_CATEGORIES
from shared.db import (
    upsert_card_sales, upsert_bank_transactions,
    delete_card_sales, delete_bank_transactions,
)
from shared.utils import sec
from modules.parser import (
    parse_card_aggregate, parse_credit_card,
    parse_hana, parse_shinhan, recalc_vat,
    parse_payroll_insured, parse_payroll_freelance,
)
from shared.db import upsert_payroll
from modules.classifier import classify_transactions
from modules.ai_classifier import ai_classify_batch, load_api_key

_now        = datetime.now()
_DB_PATH    = Path(__file__).parent.parent.parent / "data" / "settlement.db"
_BACKUP_DIR = Path(__file__).parent.parent.parent / "backups"


# ── 은행 데이터 처리 공통 ─────────────────────────────────────
def _process_and_save(df: pd.DataFrame, bank: str, year: int, month: int,
                      api_key, bank_label: str):
    """분류 → AI → VAT 재계산 → 저장"""
    if df.empty:
        st.warning(f"⚠️ {bank_label} 시트를 찾지 못했습니다.")
        return

    df = classify_transactions(df, bank)
    if api_key:
        unclf = df[df["needs_review"] == 1]
        if not unclf.empty:
            tx_list = unclf[["description", "counterpart", "deposit", "withdrawal"]].to_dict("records")
            ai_res  = ai_classify_batch(tx_list, BRANCH_LIST, ALL_CATEGORIES, api_key)
            for item in ai_res:
                try:
                    idx  = unclf.index[item["id"]]
                    br   = item.get("branch", "")
                    cat  = item.get("category", "")
                    conf = float(item.get("confidence", 0))
                    if br or cat:
                        df.at[idx, "branch"]   = br
                        df.at[idx, "category"] = cat
                        df.at[idx, "classification_source"] = "ai"
                        df.at[idx, "is_excluded"] = 1 if cat == "제외" else 0
                        if conf >= 0.75 and br and cat:
                            df.at[idx, "needs_review"] = 0
                except Exception:
                    pass

    df = recalc_vat(df)
    upsert_bank_transactions(df, bank, year, month)
    total    = len(df)
    auto_ok  = int((df.needs_review == 0).sum())
    need_rev = int(df.needs_review.sum())
    ai_cnt   = int((df.get("classification_source", "") == "ai").sum()) \
               if "classification_source" in df.columns else 0
    st.success(
        f"✅ {bank_label}: 총 {total}건 저장 "
        f"(자동분류 {auto_ok}건 / AI {ai_cnt}건 / 미분류 {need_rev}건)"
    )
    if need_rev > 0:
        st.info(f"📋 미분류 {need_rev}건은 '규칙 관리 → 계정과목 검토'에서 확인하세요.")
    st.cache_data.clear()


def _sheet_preview(fb):
    """업로드 파일 시트 구조 미리보기"""
    xl = pd.ExcelFile(fb)
    with st.expander(f"📋 파일 구조 확인 ({len(xl.sheet_names)}개 시트)", expanded=True):
        for sn in xl.sheet_names:
            try:
                raw  = xl.parse(sn, header=None, nrows=4, dtype=str)
                hrow = 0
                for ri, row in raw.iterrows():
                    vals = [str(v).strip() for v in row
                            if pd.notna(v) and str(v).strip() not in ("nan", "")]
                    if "No" in vals:
                        hrow = ri
                        break
                headers = [str(v).strip() for v in raw.iloc[hrow]
                           if pd.notna(v) and str(v).strip() not in ("nan", "")]
                if any("전체선택" in v for v in headers):
                    kind = "🟦 신한통장"
                elif any("의뢰인" in v or "수취인" in v for v in headers):
                    kind = "🟩 하나통장"
                else:
                    kind = "❓ 미감지"
                st.markdown(f"**{sn}** → {kind}")
                st.caption("헤더: " + " | ".join(headers[:10]))
            except Exception as e:
                st.caption(f"{sn}: 읽기 실패 ({e})")


def render_page():
    st.markdown(
        '<div class="ph"><div class="ph-title">데이터 업로드</div>'
        '<div class="ph-sub">엑셀 파일을 업로드하면 자동으로 파싱·저장됩니다</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="al al-info">ℹ️&nbsp; 같은 연월을 다시 올리면 기존 데이터가 교체됩니다. '
        '업로드 전 백업을 권장합니다.</div>',
        unsafe_allow_html=True,
    )

    _api_key = load_api_key()
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["카드 매출", "통장 내역", "💰 급여", "🏥 4대보험 고지내역", "🗄️ 백업/복원"])

    # ── 카드 매출 ─────────────────────────────────────────────
    with tab1:
        st.subheader("카드 매출 업로드")
        c1, c2 = st.columns(2)
        uy = c1.number_input("연도", value=_now.year, min_value=2020, max_value=2030, key="uy")
        um = c2.selectbox("월", list(range(1, 13)), index=_now.month - 1, key="um",
                          format_func=lambda m: f"{m}월")

        sec("① 카드사 결과 집계 조회")
        f1 = st.file_uploader("카드사 결과 집계 조회.xlsx", type=["xlsx"], key="agg")
        if f1 and st.button("저장", key="b_agg"):
            with st.spinner("처리 중..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    tmp.write(f1.read())
                    tp = tmp.name
                try:
                    df = parse_card_aggregate(tp, uy, um)
                    upsert_card_sales(df, "card_aggregate", uy, um)
                    st.cache_data.clear()
                    un = (df.branch == "미매핑").sum()
                    st.success(f"✅ {len(df)}건 저장 완료 (미매핑 {un}건)")
                    if un:
                        st.dataframe(df[df.branch == "미매핑"][["raw_merchant", "total_amount"]])
                except Exception as e:
                    st.error(f"❌ 오류: {e}")
                finally:
                    os.unlink(tp)

        sec("② 신용카드")
        f2 = st.file_uploader("신용카드.xlsx", type=["xlsx"], key="cc")
        if f2 and st.button("저장", key="b_cc"):
            with st.spinner("처리 중..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    tmp.write(f2.read())
                    tp = tmp.name
                try:
                    df = parse_credit_card(tp, uy, um)
                    upsert_card_sales(df, "credit_card", uy, um)
                    st.cache_data.clear()
                    st.success(f"✅ {len(df)}건 저장 완료")
                except Exception as e:
                    st.error(f"❌ 오류: {e}")
                finally:
                    os.unlink(tp)

        st.divider()
        st.caption("⚠️ 해당 월 카드매출 전체 삭제 (재업로드 또는 초기화 시 사용)")
        cd1, cd2, cd3 = st.columns([1, 1, 2])
        cl_card_y = cd1.number_input("연도", value=_now.year, min_value=2020, max_value=2030,
                                     key="cl_card_y")
        cl_card_m = cd2.selectbox("월", list(range(1, 13)), index=_now.month - 1,
                                   key="cl_card_m", format_func=lambda m: f"{m}월")
        cd3.markdown("<br>", unsafe_allow_html=True)
        if cd3.button("🗑️ 카드매출 데이터 삭제", key="cl_card_btn", use_container_width=True):
            delete_card_sales(int(cl_card_y), int(cl_card_m))
            st.cache_data.clear()
            st.success(f"✅ {cl_card_y}년 {cl_card_m}월 카드매출 데이터 삭제 완료")
            st.rerun()

    # ── 통장 내역 ─────────────────────────────────────────────
    with tab2:
        st.subheader("통장 내역 업로드")
        c1, c2 = st.columns(2)
        by = c1.number_input("연도", value=_now.year, min_value=2020, max_value=2030, key="by")
        bm = c2.selectbox("월", list(range(1, 13)), index=_now.month - 1, key="bm",
                          format_func=lambda m: f"{m}월")

        # ── 하나은행 ─────────────────────────────────────────
        sec("🟩 하나은행 통장")
        st.caption("하나은행 파일만 업로드 → 하나 데이터만 교체됩니다. 신한은행은 영향 없음.")
        f_hana = st.file_uploader("하나통장.xlsx", type=["xlsx"], key="bank_hana")

        if f_hana:
            _sheet_preview(f_hana)

        if f_hana and st.button("🟩 하나은행 저장", type="primary", key="b_bank_hana"):
            with st.spinner("하나은행 처리 중..."):
                try:
                    f_hana.seek(0)
                    xl = pd.ExcelFile(f_hana)
                    df = parse_hana(xl, by, bm)
                    _process_and_save(df, "hana", by, bm, _api_key, "하나은행")
                except Exception as e:
                    st.error(f"❌ 하나은행 저장 실패: {e}")

        st.divider()

        # ── 신한은행 ─────────────────────────────────────────
        sec("🟦 신한은행 통장")
        st.caption("신한은행 파일만 업로드 → 신한 데이터만 교체됩니다. 하나은행은 영향 없음.")
        f_shinhan = st.file_uploader("신한통장.xlsx", type=["xlsx"], key="bank_shinhan")

        if f_shinhan:
            _sheet_preview(f_shinhan)

        if f_shinhan and st.button("🟦 신한은행 저장", type="primary", key="b_bank_shinhan"):
            with st.spinner("신한은행 처리 중..."):
                try:
                    f_shinhan.seek(0)
                    xl = pd.ExcelFile(f_shinhan)
                    df = parse_shinhan(xl, by, bm)
                    _process_and_save(df, "shinhan", by, bm, _api_key, "신한은행")
                except Exception as e:
                    st.error(f"❌ 신한은행 저장 실패: {e}")

        # ── 통장 데이터 클리어 ────────────────────────────────
        st.divider()
        st.caption("⚠️ 해당 월 통장내역 삭제 (재업로드 또는 초기화 시 사용)")
        bd1, bd2, bd3, bd4 = st.columns([1, 1, 1, 1])
        cl_bank_y = bd1.number_input("연도", value=_now.year, min_value=2020, max_value=2030,
                                     key="cl_bank_y")
        cl_bank_m = bd2.selectbox("월", list(range(1, 13)), index=_now.month - 1,
                                   key="cl_bank_m", format_func=lambda m: f"{m}월")
        cl_bank_t = bd3.selectbox("통장", ["전체", "하나(hana)", "신한(shinhan)"],
                                   key="cl_bank_t")
        bd4.markdown("<br>", unsafe_allow_html=True)
        if bd4.button("🗑️ 통장내역 삭제", key="cl_bank_btn", use_container_width=True):
            bank_code = None
            if "하나" in cl_bank_t:
                bank_code = "hana"
            elif "신한" in cl_bank_t:
                bank_code = "shinhan"
            delete_bank_transactions(int(cl_bank_y), int(cl_bank_m), bank_code)
            st.cache_data.clear()
            lbl = cl_bank_t if cl_bank_t != "전체" else "전체"
            st.success(f"✅ {cl_bank_y}년 {cl_bank_m}월 통장내역({lbl}) 삭제 완료")
            st.rerun()

    # ── 급여 ──────────────────────────────────────────────────
    with tab3:
        st.subheader("급여 데이터 업로드")
        st.markdown(
            '<div class="al al-info">ℹ️&nbsp; 급여 집계 엑셀을 업로드합니다. '
            '<b>지점별집계</b> 시트(4대보험) 및 <b>사업소득자</b> 시트(프리랜서)가 있어야 합니다.<br>'
            '상세 급여 계산(개인별 급여명세서)은 <b>인사/급여 → 급여계산</b> 탭을 이용하세요.</div>',
            unsafe_allow_html=True,
        )
        py1, py2 = st.columns(2)
        pay_year  = py1.number_input("연도", value=_now.year, min_value=2020, max_value=2030, key="pay_y")
        pay_month = py2.selectbox("월", list(range(1, 13)), index=_now.month - 1, key="pay_m",
                                   format_func=lambda m: f"{m}월")

        pay_file = st.file_uploader("급여_집계.xlsx", type=["xlsx", "xls"], key="pay_xl")

        if pay_file and st.button("📥 급여 데이터 저장", type="primary", key="pay_save"):
            with st.spinner("처리 중..."):
                try:
                    pay_file.seek(0)
                    xl = pd.ExcelFile(pay_file)
                    sheets = xl.sheet_names
                    insured_ok   = False
                    freelance_ok = False

                    if "지점별집계" in sheets:
                        df_ins = parse_payroll_insured(xl, int(pay_year), int(pay_month))
                        if not df_ins.empty:
                            upsert_payroll(df_ins, int(pay_year), int(pay_month), "insured")
                            insured_ok = True

                    if "사업소득자" in sheets:
                        df_free = parse_payroll_freelance(xl, int(pay_year), int(pay_month))
                        if not df_free.empty:
                            upsert_payroll(df_free, int(pay_year), int(pay_month), "freelance")
                            freelance_ok = True

                    if insured_ok or freelance_ok:
                        parts = []
                        if insured_ok:   parts.append("4대보험")
                        if freelance_ok: parts.append("프리랜서")
                        st.success(f"✅ {pay_year}년 {pay_month}월 급여 저장 완료 ({' · '.join(parts)})")
                        st.cache_data.clear()
                    else:
                        st.warning(
                            "⚠️ 인식된 시트가 없습니다. "
                            "'지점별집계' 또는 '사업소득자' 시트가 있어야 합니다. "
                            f"현재 시트: {', '.join(sheets)}"
                        )
                except Exception as e:
                    st.error(f"❌ 오류: {e}")

        st.divider()
        st.caption("💡 개인별 급여명세서·세금 등 상세 급여 처리는 인사/급여 탭을 이용하세요.")
        st.page_link("http://localhost:8501/?page=payroll", label="→ 인사/급여 페이지로 이동", icon="💼")

    # ── 4대보험 고지내역 ──────────────────────────────────────
    with tab4:
        st.subheader("4대보험 고지내역")
        from domains.payroll.insurance.ui import render as _ins_render
        _ins_render()

    # ── 백업 / 복원 ───────────────────────────────────────────
    with tab5:
        st.subheader("백업 / 복원")
        st.markdown(
            '<div class="al al-info">ℹ️&nbsp; DB 전체(모든 데이터)를 백업합니다. '
            '최근 7개가 자동 유지됩니다. '
            '복원 후에는 반드시 앱을 새로고침(F5)하세요.</div>',
            unsafe_allow_html=True,
        )

        # 백업 생성
        sec("백업 생성")
        if st.button("💾 지금 백업 생성", type="primary", key="do_backup"):
            try:
                from backup import create_backup
                create_backup()
                ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.success(f"✅ 백업 완료 — {ts_now}")
                st.rerun()
            except Exception as e:
                st.error(f"❌ 백업 실패: {e}")

        # 백업 목록 & 복원
        sec("백업 목록 / 복원")
        _BACKUP_DIR.mkdir(exist_ok=True)
        backups = sorted(_BACKUP_DIR.glob("settlement_*.db"), reverse=True)

        if not backups:
            st.info("저장된 백업이 없습니다. 위에서 먼저 백업을 생성하세요.")
        else:
            st.caption(f"총 {len(backups)}개 백업 (최대 7개 유지)")
            for i, bp in enumerate(backups):
                size_mb = bp.stat().st_size / (1024 * 1024)
                ts      = bp.stem.replace("settlement_", "")
                try:
                    dt    = datetime.strptime(ts, "%Y%m%d_%H%M%S")
                    label = dt.strftime("%Y년 %m월 %d일  %H:%M:%S")
                except Exception:
                    label = ts

                col_a, col_b, col_c = st.columns([5, 1, 1])
                col_a.markdown(f"📦 **{label}** &nbsp; `{size_mb:.1f} MB`")

                if col_b.button("🗑️", key=f"del_bk_{i}", use_container_width=True,
                                help="이 백업 삭제"):
                    bp.unlink()
                    st.success(f"삭제 완료: {bp.name}")
                    st.rerun()

                if col_c.button("🔄 복원", key=f"restore_{i}", use_container_width=True):
                    try:
                        # 복원 전 현재 DB를 broken_ 으로 보존
                        if _DB_PATH.exists():
                            broken = _BACKUP_DIR / f"broken_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                            shutil.copy2(_DB_PATH, broken)
                        shutil.copy2(bp, _DB_PATH)
                        st.cache_data.clear()
                        st.success(
                            f"✅ **{label}** 복원 완료  \n"
                            "앱을 새로고침(F5)해야 변경사항이 반영됩니다."
                        )
                    except Exception as e:
                        st.error(f"❌ 복원 실패: {e}")

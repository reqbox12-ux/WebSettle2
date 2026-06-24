"""
domains/settings/ui.py — 통합 설정 페이지
규칙 관리(계정과목 검토 + 키워드 규칙 + AI) + 계정 관리(admin)
"""
from datetime import datetime
import streamlit as st

from shared.config import BRANCH_LIST, ALL_CATEGORIES
from shared.utils import sec
from shared.db import (
    get_all_bank_transactions, get_keyword_rules,
    update_transaction_classification,
    delete_keyword_rule, update_keyword_rule,
)
from modules.classifier import add_rule
from modules.ai_classifier import ai_classify_batch, ai_extract_keyword, load_api_key, save_api_key
from domains.auth.service import get_all_users, add_user, delete_user, change_password

_now = datetime.now()


def render_page(auth_user: dict = None):
    if auth_user is None:
        auth_user = st.session_state.get("auth_user", {})

    st.markdown(
        '<div class="ph"><div class="ph-title">설정</div>'
        '<div class="ph-sub">규칙 관리 · AI 분류 설정 · 계정 관리</div></div>',
        unsafe_allow_html=True,
    )

    is_admin = auth_user.get("role") == "admin"

    # 탭 구성: 일반 3개 + admin 1개
    if is_admin:
        tab1, tab2, tab3, tab4 = st.tabs(["계정과목 검토", "규칙 목록 · 추가", "⚙️ AI 설정", "👤 계정 관리"])
    else:
        tab1, tab2, tab3 = st.tabs(["계정과목 검토", "규칙 목록 · 추가", "⚙️ AI 설정"])

    _api_key = load_api_key()

    # ── 탭1: 계정과목 검토 ──────────────────────────────────────
    with tab1:
        _yr_list = list(range(2024, _now.year + 2))
        fa1, fa2, fa3 = st.columns([1, 1, 1])
        rv_year  = fa1.selectbox("연도", _yr_list,
                                 index=_yr_list.index(_now.year) if _now.year in _yr_list else len(_yr_list) - 1,
                                 key="rv_year")
        rv_month = fa2.selectbox("월", list(range(1, 13)), index=_now.month - 1, key="rv_month",
                                 format_func=lambda m: f"{m}월")
        rv_bank  = fa3.selectbox("통장", ["전체", "hana", "신한(shinhan)"], key="rv_bank")

        bank_filter = None if rv_bank == "전체" else ("shinhan" if "신한" in rv_bank else "hana")

        df_all = get_all_bank_transactions(rv_year, rv_month, bank_filter)
        if df_all.empty:
            st.info("📭 해당 기간에 통장 데이터가 없습니다.")
        else:
            # 미분류 필터
            show_only_unclassified = st.checkbox("미분류(검토필요)만 보기", value=True, key="rv_unclf")
            df_view = df_all[df_all["needs_review"] == 1] if show_only_unclassified else df_all
            st.caption(f"표시 {len(df_view)}건 / 전체 {len(df_all)}건 (미분류 {int(df_all['needs_review'].sum())}건)")

            if df_view.empty:
                st.success("✅ 미분류 거래가 없습니다.")
            else:
                for _, row in df_view.iterrows():
                    tx_id   = int(row["id"])
                    date_   = row.get("tx_date", "")
                    desc_   = row.get("description", "")
                    amt_dep = int(row.get("deposit", 0))
                    amt_wdr = int(row.get("withdrawal", 0))
                    cur_br  = row.get("branch", "") or ""
                    cur_cat = row.get("category", "") or ""
                    src     = row.get("classification_source", "")

                    with st.expander(
                        f"{'🔴' if row['needs_review'] else '🟢'} [{date_}] {desc_} "
                        f"{'입금 {:,}'.format(amt_dep) if amt_dep else '출금 {:,}'.format(amt_wdr)}",
                        expanded=bool(row["needs_review"])
                    ):
                        c1, c2 = st.columns(2)
                        new_br  = c1.selectbox("지점", [""] + BRANCH_LIST,
                                               index=([""] + BRANCH_LIST).index(cur_br) if cur_br in BRANCH_LIST else 0,
                                               key=f"br_{tx_id}")
                        new_cat = c2.selectbox("계정과목", [""] + ALL_CATEGORIES,
                                               index=([""] + ALL_CATEGORIES).index(cur_cat) if cur_cat in ALL_CATEGORIES else 0,
                                               key=f"cat_{tx_id}")

                        save_col, rule_col, _ = st.columns([1, 1, 2])
                        if save_col.button("💾 저장", key=f"sv_{tx_id}"):
                            update_transaction_classification(tx_id, new_br, new_cat, "manual")
                            st.success("저장 완료")
                            st.rerun()

                        if rule_col.button("➕ 규칙 추가", key=f"rl_{tx_id}"):
                            if new_br and new_cat:
                                bank_code = row.get("bank", "")
                                kw = ai_extract_keyword(desc_, _api_key) if _api_key else desc_[:10]
                                add_rule(bank_code, kw, new_br, new_cat)
                                update_transaction_classification(tx_id, new_br, new_cat, "manual")
                                st.success(f"규칙 추가: '{kw}' → {new_br} / {new_cat}")
                                st.rerun()
                            else:
                                st.warning("지점과 계정과목을 모두 선택하세요.")

                        if src:
                            st.caption(f"분류 출처: {src}")

    # ── 탭2: 규칙 목록 · 추가 ─────────────────────────────────
    with tab2:
        sec("키워드 규칙 목록")
        bank_sel = st.selectbox("통장 필터", ["전체", "hana", "신한(shinhan)"], key="rl_bank")
        bank_code_f = None if bank_sel == "전체" else ("shinhan" if "신한" in bank_sel else "hana")

        rules_df = get_keyword_rules(bank_code_f)
        if rules_df is None or len(rules_df) == 0:
            st.info("등록된 규칙이 없습니다.")
        else:
            for _, r in rules_df.iterrows():
                rid  = int(r["id"])
                cols = st.columns([2, 2, 2, 1, 1])
                cols[0].markdown(f"`{r['keyword']}`")
                edit_br  = cols[1].selectbox("지점", [""] + BRANCH_LIST,
                                              index=([""] + BRANCH_LIST).index(r["branch"]) if r["branch"] in BRANCH_LIST else 0,
                                              key=f"rl_br_{rid}", label_visibility="collapsed")
                edit_cat = cols[2].selectbox("계정", [""] + ALL_CATEGORIES,
                                              index=([""] + ALL_CATEGORIES).index(r["category"]) if r["category"] in ALL_CATEGORIES else 0,
                                              key=f"rl_cat_{rid}", label_visibility="collapsed")
                if cols[3].button("수정", key=f"rl_up_{rid}"):
                    update_keyword_rule(rid, edit_br, edit_cat)
                    st.success("수정 완료")
                    st.rerun()
                if cols[4].button("🗑️", key=f"rl_del_{rid}"):
                    delete_keyword_rule(rid)
                    st.success("삭제 완료")
                    st.rerun()

        sec("새 규칙 추가")
        nc1, nc2, nc3, nc4 = st.columns([2, 2, 2, 1])
        new_bank = nc1.selectbox("통장", ["hana", "shinhan"], key="nr_bank")
        new_kw   = nc2.text_input("키워드", key="nr_kw")
        new_br   = nc3.selectbox("지점", [""] + BRANCH_LIST, key="nr_br")
        new_cat  = nc4.selectbox("계정과목", [""] + ALL_CATEGORIES, key="nr_cat",
                                  label_visibility="collapsed")
        if st.button("➕ 규칙 추가", key="nr_add"):
            if new_kw and new_br and new_cat:
                add_rule(new_bank, new_kw, new_br, new_cat)
                st.success(f"규칙 추가: [{new_bank}] '{new_kw}' → {new_br} / {new_cat}")
                st.rerun()
            else:
                st.warning("키워드, 지점, 계정과목을 모두 입력하세요.")

    # ── 탭3: AI 설정 ───────────────────────────────────────────
    with tab3:
        sec("OpenAI API 설정")
        st.markdown(
            '<div class="al al-info">ℹ️&nbsp; API 키를 입력하면 미분류 거래를 AI가 자동으로 분류합니다. '
            '데이터 업로드 시 자동 적용됩니다.</div>',
            unsafe_allow_html=True,
        )
        current_key = _api_key or ""
        masked = f"sk-...{current_key[-4:]}" if len(current_key) > 8 else ("설정됨" if current_key else "미설정")
        st.caption(f"현재 API 키: **{masked}**")
        new_key = st.text_input("새 API 키 (sk-...)", type="password", key="ai_new_key",
                                 placeholder="sk-proj-...")
        if st.button("💾 API 키 저장", key="ai_save_key"):
            if new_key.startswith("sk-"):
                save_api_key(new_key)
                st.success("✅ API 키 저장 완료")
                st.rerun()
            else:
                st.error("올바른 OpenAI API 키 형식이 아닙니다 (sk- 로 시작해야 합니다).")

    # ── 탭4: 계정 관리 (admin 전용) ────────────────────────────
    if is_admin:
        with tab4:
            st.markdown(
                '<div class="al al-warn">⚠️&nbsp; 관리자 전용 메뉴입니다. '
                '사용자 계정 추가 · 삭제 · 비밀번호 변경이 가능합니다.</div>',
                unsafe_allow_html=True,
            )
            at1, at2, at3 = st.tabs(["사용자 목록", "새 계정 추가", "비밀번호 변경"])

            with at1:
                sec("전체 사용자")
                users = get_all_users()
                for u in users:
                    c1, c2, c3, c4 = st.columns([1.5, 1.5, 1, 1])
                    c1.markdown(f"**{u['username']}**")
                    c2.markdown(u["name"])
                    c3.markdown("🔴 관리자" if u["role"] == "admin" else "🔵 사용자")
                    if u["username"] != "admin":
                        if c4.button("삭제", key=f"del_u_{u['id']}"):
                            delete_user(u["id"])
                            st.success(f"'{u['username']}' 삭제 완료")
                            st.rerun()
                    else:
                        c4.markdown("―")
                st.caption(f"총 {len(users)}명")

            with at2:
                sec("새 계정 추가")
                nu1, nu2 = st.columns(2)
                new_uname = nu1.text_input("아이디", key="nu_uname")
                new_uname_k = nu2.text_input("이름(한글)", key="nu_name")
                new_pw    = nu1.text_input("비밀번호", type="password", key="nu_pw")
                new_role  = nu2.selectbox("권한", ["user", "admin"], key="nu_role",
                                           format_func=lambda r: "관리자" if r == "admin" else "사용자")
                if st.button("➕ 계정 생성", key="nu_create"):
                    if new_uname and new_pw:
                        ok, msg = add_user(new_uname, new_uname_k, new_pw, new_role)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                    else:
                        st.warning("아이디와 비밀번호를 입력하세요.")

            with at3:
                sec("비밀번호 변경")
                cp1, cp2 = st.columns(2)
                cp_uname = cp1.text_input("아이디", key="cp_uname")
                cp_new   = cp2.text_input("새 비밀번호", type="password", key="cp_new")
                if st.button("🔑 비밀번호 변경", key="cp_change"):
                    if cp_uname and cp_new:
                        ok, msg = change_password(cp_uname, cp_new)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                    else:
                        st.warning("아이디와 새 비밀번호를 입력하세요.")

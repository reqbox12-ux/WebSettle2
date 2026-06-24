"""
domains/rules/ui.py — 규칙 관리 페이지
"""
from datetime import datetime
import streamlit as st

from shared.config import BRANCH_LIST, ALL_CATEGORIES
from shared.utils import sec
from shared.db import (
    get_all_bank_transactions, get_keyword_rules, update_transaction_classification,
    delete_keyword_rule, update_keyword_rule,
)
from modules.classifier import add_rule
from modules.ai_classifier import ai_classify_batch, ai_extract_keyword, load_api_key, save_api_key

_now = datetime.now()


def render_page():
    st.markdown(
        '<div class="ph"><div class="ph-title">규칙 관리</div>'
        '<div class="ph-sub">계정과목 검토 및 키워드 자동분류 규칙</div></div>',
        unsafe_allow_html=True,
    )

    _api_key = load_api_key()
    tab1, tab2, tab3 = st.tabs(["계정과목 검토", "규칙 목록 · 추가", "⚙️ AI 설정"])

    # ── 탭1: 계정과목 검토 ──────────────────────────────────
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
        rv_df_all   = get_all_bank_transactions(rv_year, rv_month, bank_filter)

        fb1, fb2, fb3 = st.columns([1, 1, 1])
        exist_branches   = ["전체"] + sorted([b for b in (rv_df_all["branch"].dropna().unique().tolist()
                                               if not rv_df_all.empty else []) if b])
        exist_categories = ["전체"] + sorted([c for c in (rv_df_all["category"].dropna().unique().tolist()
                                               if not rv_df_all.empty else []) if c])
        rv_branch   = fb1.selectbox("지점", exist_branches, key="rv_branch")
        rv_category = fb2.selectbox("계정과목", exist_categories, key="rv_category")
        rv_status   = fb3.selectbox("상태", ["전체", "미분류만", "AI분류", "자동분류", "제외"], key="rv_status")

        rv_df = rv_df_all.copy() if not rv_df_all.empty else rv_df_all
        if not rv_df.empty:
            if rv_branch != "전체":
                rv_df = rv_df[rv_df["branch"] == rv_branch]
            if rv_category != "전체":
                rv_df = rv_df[rv_df["category"] == rv_category]
            if rv_status == "미분류만":
                rv_df = rv_df[rv_df["needs_review"] == 1]
            elif rv_status == "AI분류":
                rv_df = rv_df[rv_df.get("classification_source", "") == "ai"] if "classification_source" in rv_df.columns else rv_df
            elif rv_status == "자동분류":
                rv_df = rv_df[rv_df.get("classification_source", "").isin(["rule", "smart"])] if "classification_source" in rv_df.columns else rv_df
            elif rv_status == "제외":
                rv_df = rv_df[rv_df["is_excluded"] == 1] if "is_excluded" in rv_df.columns else rv_df

        if rv_df_all.empty:
            st.markdown('<div class="al al-ok">✅&nbsp; 해당 월의 거래 내역이 없습니다.</div>',
                        unsafe_allow_html=True)
        else:
            total  = len(rv_df)
            unrev  = int(rv_df_all["needs_review"].sum()) if "needs_review" in rv_df_all.columns else 0
            ai_cnt = int((rv_df_all.get("classification_source", "") == "ai").sum()) if "classification_source" in rv_df_all.columns else 0

            ai_col1, ai_col2 = st.columns([3, 1])
            ai_col1.caption(f"표시 {total}건 · 전체 미분류 {unrev}건 · AI분류 {ai_cnt}건")
            if _api_key:
                if unrev > 0 and ai_col2.button("🤖 AI 일괄분류", type="primary", key="ai_bulk"):
                    unclf_rows = rv_df_all[rv_df_all["needs_review"] == 1]
                    tx_list    = unclf_rows[["description", "counterpart", "deposit", "withdrawal"]].to_dict("records")
                    with st.spinner(f"🤖 AI가 {len(tx_list)}건 분류 중..."):
                        ai_res = ai_classify_batch(tx_list, BRANCH_LIST, ALL_CATEGORIES, _api_key)
                    applied = 0
                    for item in ai_res:
                        try:
                            loc_idx = unclf_rows.index[item["id"]]
                            tx_id   = int(rv_df_all.loc[loc_idx, "id"])
                            br   = item.get("branch", "")
                            cat  = item.get("category", "제외" if not item.get("branch") else "")
                            conf = float(item.get("confidence", 0))
                            if cat:
                                update_transaction_classification(tx_id, br or "본사", cat, "ai")
                                applied += 1
                        except Exception:
                            pass
                    st.success(f"✅ {applied}건 AI 분류 완료!")
                    st.cache_data.clear()
                    st.rerun()
            else:
                ai_col2.caption("🔑 API 키 없음")

            st.divider()

            def _status_label(row):
                src = str(row.get("classification_source", "") or "")
                if row.get("is_excluded", 0) == 1:  return "⛔ 제외"
                if src == "rule":                     return "✅ 자동"
                if src == "smart":                    return "🔵 스마트"
                if src == "ai":                       return "🤖 AI"
                if src == "manual":                   return "✏️ 수동"
                if row.get("needs_review", 0) == 1:  return "❓ 미분류"
                return "✅ 분류됨"

            import pandas as pd

            # 표시용 DataFrame 구성
            disp_rows = []
            id_map = []   # row 순서 → 실제 tx id, bank 매핑
            for _, row in rv_df.iterrows():
                amt = int(row.get("deposit", 0) or 0) or -int(row.get("withdrawal", 0) or 0)
                disp_rows.append({
                    "상태":    _status_label(row),
                    "날짜":    str(row.get("tx_date", ""))[:10],
                    "통장":    str(row.get("bank", "")).upper(),
                    "적요":    str(row.get("description", ""))[:40],
                    "금액":    amt,
                    "지점":    str(row.get("branch", "") or ""),
                    "계정과목": str(row.get("category", "") or ""),
                })
                id_map.append({"id": int(row["id"]), "bank": str(row.get("bank", ""))})

            rv_edit_df = pd.DataFrame(disp_rows)
            cat_opts = [""] + ALL_CATEGORIES

            edited_rv = st.data_editor(
                rv_edit_df,
                use_container_width=True,
                hide_index=True,
                height=520,
                num_rows="fixed",
                key="rv_editor_table",
                column_config={
                    "상태":    st.column_config.TextColumn("상태", disabled=True, width="small"),
                    "날짜":    st.column_config.TextColumn("날짜", disabled=True, width="small"),
                    "통장":    st.column_config.TextColumn("통장", disabled=True, width="small"),
                    "적요":    st.column_config.TextColumn("적요", disabled=True, width="large"),
                    "금액":    st.column_config.NumberColumn("금액", disabled=True, format="%d",
                                                              width="medium"),
                    "지점":    st.column_config.SelectboxColumn("지점", options=BRANCH_LIST,
                                                                width="medium"),
                    "계정과목": st.column_config.SelectboxColumn("계정과목", options=cat_opts,
                                                                  width="medium"),
                },
            )
            st.caption("지점·계정과목 셀을 클릭해 수정 → 저장 버튼 한 번으로 일괄 반영")

            if st.button("💾 변경사항 저장", key="rv_bulk_save", type="primary"):
                changes = st.session_state.get("rv_editor_table", {}).get("edited_rows", {})
                if not changes:
                    st.info("변경된 내용이 없습니다.")
                else:
                    saved_rv = 0
                    errs_rv  = []
                    for row_idx_str, row_changes in changes.items():
                        idx  = int(row_idx_str)
                        info = id_map[idx]
                        # 변경 후 현재 값 (변경 없으면 원본 유지)
                        cur_br  = row_changes.get("지점",    disp_rows[idx]["지점"])
                        cur_cat = row_changes.get("계정과목", disp_rows[idx]["계정과목"])
                        if not cur_br or not cur_cat:
                            errs_rv.append(f"행 {idx + 1}: 지점·계정과목 모두 필요합니다.")
                            continue
                        update_transaction_classification(info["id"], cur_br, cur_cat, "manual")
                        saved_rv += 1
                    if saved_rv:
                        st.success(f"✅ {saved_rv}건 저장 완료")
                        st.cache_data.clear()
                        st.rerun()
                    for e in errs_rv:
                        st.warning(e)

    # ── 탭2: 규칙 목록 · 추가 ─────────────────────────────
    with tab2:
        sec("규칙 목록")
        bf  = st.selectbox("통장 필터", ["전체", "hana", "shinhan"], key="rule_bank_filter")
        rdf = get_keyword_rules(None if bf == "전체" else bf)

        if rdf.empty:
            st.info("등록된 규칙이 없습니다.")
        else:
            # 편집용 df: 삭제체크박스 + 지점·계정과목 편집 가능
            edit_rdf = rdf[["id", "bank", "keyword", "branch", "category", "hit_count"]].copy()
            edit_rdf.insert(0, "삭제", False)

            edited_rules = st.data_editor(
                edit_rdf,
                use_container_width=True,
                hide_index=True,
                height=460,
                num_rows="fixed",
                key="rules_editor",
                column_config={
                    "삭제":       st.column_config.CheckboxColumn("🗑️ 삭제", width="small"),
                    "id":         st.column_config.NumberColumn("ID", disabled=True, width="small"),
                    "bank":       st.column_config.TextColumn("통장", disabled=True, width="small"),
                    "keyword":    st.column_config.TextColumn("키워드", disabled=True, width="large"),
                    "branch":     st.column_config.SelectboxColumn("지점", options=BRANCH_LIST,
                                                                    width="medium"),
                    "category":   st.column_config.SelectboxColumn("계정과목", options=ALL_CATEGORIES,
                                                                    width="medium"),
                    "hit_count":  st.column_config.NumberColumn("적용횟수", disabled=True, width="small"),
                },
            )
            st.caption(f"총 {len(rdf)}개 규칙 · 지점·계정과목 수정 가능 · 🗑️ 체크 후 저장하면 삭제")

            if st.button("💾 변경사항 저장 (수정·삭제)", key="rules_save_btn", type="primary"):
                changes  = st.session_state.get("rules_editor", {}).get("edited_rows", {})
                del_count = 0
                upd_count = 0
                for row_idx_str, row_ch in changes.items():
                    idx     = int(row_idx_str)
                    rule_id = int(rdf.iloc[idx]["id"])

                    # 삭제 체크된 경우
                    if row_ch.get("삭제", False):
                        delete_keyword_rule(rule_id)
                        del_count += 1
                    else:
                        # 지점 또는 계정과목 변경
                        new_br  = row_ch.get("branch",   rdf.iloc[idx]["branch"])
                        new_cat = row_ch.get("category", rdf.iloc[idx]["category"])
                        update_keyword_rule(rule_id, new_br, new_cat)
                        upd_count += 1

                msgs = []
                if del_count:
                    msgs.append(f"{del_count}개 삭제")
                if upd_count:
                    msgs.append(f"{upd_count}개 수정")
                if msgs:
                    st.success(f"✅ {' / '.join(msgs)} 완료")
                    st.rerun()
                else:
                    st.info("변경된 내용이 없습니다.")

        sec("새 규칙 추가")
        c1, c2 = st.columns(2)
        nb = c1.selectbox("통장", ["hana", "shinhan"], key="nb")
        nk = c2.text_input("키워드 (적요에 포함된 문자)")
        c3, c4 = st.columns(2)
        nbr = c3.selectbox("지점", BRANCH_LIST, key="nbr")
        nct = c4.selectbox("계정과목", ALL_CATEGORIES, key="nct")
        if st.button("규칙 추가", type="primary"):
            if nk:
                add_rule(nb, nk, nbr, nct)
                st.success(f"✅ [{nb}] '{nk}' → {nbr} / {nct}")
            else:
                st.error("키워드를 입력하세요.")

    # ── 탭3: AI 설정 ──────────────────────────────────────
    with tab3:
        sec("Anthropic API 키 설정")
        st.markdown("""
        **Google Gemini API 키 발급 방법**
        1. [aistudio.google.com](https://aistudio.google.com) 접속 (구글 계정으로 로그인)
        2. 좌측 **Get API key** → **Create API key**
        3. 생성된 키(`AIza`로 시작)를 아래에 입력 후 저장
        """)

        cur_key = _api_key
        masked  = ("sk-ant-..." + cur_key[-6:]) if len(cur_key) > 10 else ("미설정" if not cur_key else cur_key)
        if cur_key:
            st.markdown(f'<div class="al al-ok">✅&nbsp; API 키 등록됨: <code>{masked}</code></div>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<div class="al al-warn">⚠️&nbsp; API 키가 없습니다. 아래에 입력해주세요.</div>',
                        unsafe_allow_html=True)

        new_key = st.text_input("API 키 입력", type="password", placeholder="AIza...", key="new_api_key")
        if st.button("저장", type="primary", key="save_api_key_btn"):
            if new_key.startswith("AIza") or new_key.startswith("sk-"):
                save_api_key(new_key)
                st.success("✅ API 키가 저장되었습니다.")
                st.rerun()
            else:
                st.error("올바른 API 키 형식이 아닙니다.")
        if cur_key:
            st.divider()
            if st.button("🗑️ API 키 삭제", key="del_api_key_btn"):
                save_api_key("")
                st.success("삭제되었습니다.")
                st.rerun()

        st.divider()
        sec("AI 기능 현황")
        ai_status = "✅ 활성화" if _api_key else "❌ 비활성화 (API 키 필요)"
        st.markdown(f"""
        | 기능 | 상태 |
        |---|---|
        | 업로드 시 AI 자동분류 (미분류 fallback) | {ai_status} |
        | 저장 시 AI 핵심 키워드 추출 | {ai_status} |
        | 계정과목 검토 AI 일괄분류 버튼 | {ai_status} |
        """)

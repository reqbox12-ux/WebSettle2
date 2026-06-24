"""
domains/accounts/ui.py — 계정 관리 페이지 (관리자 전용)
"""
import streamlit as st
from shared.utils import sec
from domains.auth.service import get_all_users, add_user, delete_user, change_password


def render_page(auth_user: dict):
    if auth_user.get("role") != "admin":
        st.error("관리자만 접근할 수 있습니다.")
        st.stop()

    st.markdown(
        '<div class="ph"><div class="ph-title">계정 관리</div>'
        '<div class="ph-sub">사용자 추가 · 삭제 · 비밀번호 변경</div></div>',
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs(["사용자 목록", "새 계정 추가", "비밀번호 변경"])

    with tab1:
        sec("전체 사용자")
        users = get_all_users()
        for u in users:
            c1, c2, c3, c4 = st.columns([1.5, 1.5, 1, 1])
            c1.markdown(f"**{u['username']}**")
            c2.markdown(u["name"])
            c3.markdown("🔴 관리자" if u["role"] == "admin" else "🔵 사용자")
            if u["username"] != "admin":
                if c4.button("삭제", key=f"del_{u['id']}"):
                    delete_user(u["id"])
                    st.success(f"'{u['username']}' 삭제 완료")
                    st.rerun()
            else:
                c4.markdown("―")
        st.caption(f"총 {len(users)}명")

    with tab2:
        sec("새 계정 추가")
        a1, a2 = st.columns(2)
        new_username = a1.text_input("아이디", key="new_uname")
        new_name     = a2.text_input("이름", key="new_name")
        a3, a4 = st.columns(2)
        new_pw   = a3.text_input("비밀번호", type="password", key="new_upw")
        new_role = a4.selectbox("권한", ["user", "admin"],
                                format_func=lambda x: "관리자" if x == "admin" else "사용자",
                                key="new_urole")
        if st.button("계정 추가", type="primary", key="add_user_btn"):
            if new_username and new_name and new_pw:
                if len(new_pw) < 6:
                    st.error("비밀번호는 6자 이상이어야 합니다.")
                elif add_user(new_username, new_name, new_pw, new_role):
                    st.success(f"✅ '{new_username}' 계정이 추가되었습니다.")
                    st.rerun()
                else:
                    st.error("이미 존재하는 아이디입니다.")
            else:
                st.error("모든 항목을 입력하세요.")

    with tab3:
        sec("비밀번호 변경")
        users  = get_all_users()
        unames = [u["username"] for u in users]
        target = st.selectbox(
            "계정 선택", unames, key="chpw_user",
            format_func=lambda x: next(
                (f"{x} ({u['name']})" for u in users if u["username"] == x), x
            ),
        )
        new_pw1 = st.text_input("새 비밀번호", type="password", key="chpw1")
        new_pw2 = st.text_input("새 비밀번호 확인", type="password", key="chpw2")
        if st.button("변경", type="primary", key="chpw_btn"):
            if not new_pw1 or not new_pw2:
                st.error("비밀번호를 입력하세요.")
            elif new_pw1 != new_pw2:
                st.error("비밀번호가 일치하지 않습니다.")
            elif len(new_pw1) < 6:
                st.error("비밀번호는 6자 이상이어야 합니다.")
            else:
                change_password(target, new_pw1)
                st.success(f"✅ '{target}' 비밀번호가 변경되었습니다.")

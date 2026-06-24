"""
domains/auth/ui.py — 로그인 페이지 UI
"""
import base64
from pathlib import Path
import streamlit as st
from domains.auth.service import verify_login, create_session


def _get_logo_login() -> str:
    """로그인 왼쪽 패널용 로고"""
    lp = Path(__file__).parent.parent.parent / "assets" / "logo.png"
    if lp.exists():
        b64 = base64.b64encode(lp.read_bytes()).decode()
        return f'<img src="data:image/png;base64,{b64}" style="height:80px;width:auto;display:block" alt="LAON SPORTS">'
    return (
        '<svg viewBox="0 0 210 80" xmlns="http://www.w3.org/2000/svg" style="height:96px;width:auto;display:block">'
        '<text x="2" y="56" fill="#E60028" font-size="62" font-weight="900" '
        'font-family="Arial Black,Impact,system-ui" letter-spacing="-3">LAON</text>'
        '<text x="7" y="74" fill="#E60028" font-size="13.5" font-weight="700" '
        'font-family="Arial,Helvetica,system-ui" letter-spacing="10">SPORTS</text>'
        '</svg>'
    )


def show_login() -> None:
    """로그인 페이지 렌더링 (split two-panel)"""
    ll_logo = _get_logo_login()

    st.markdown("""<style>
    #MainMenu,header,footer{display:none!important}
    [data-testid="stDecoration"],[data-testid="stStatusWidget"],
    [data-testid="stToolbar"],[data-testid="stAppDeployButton"],
    [data-testid="stHeader"]{display:none!important}

    .stApp [data-testid="stMain"]{margin-left:0!important;width:100%!important;padding:0!important}
    .stApp [data-testid="stAppViewContainer"]{padding-left:0!important;background:linear-gradient(to right,#171210 50%,#FAF8F6 50%)!important}
    .stApp [data-testid="stMainBlockContainer"]{padding:0!important;max-width:100%!important}
    .stApp .block-container{padding:0!important;max-width:100%!important}

    .stApp [data-testid="stVerticalBlock"]{min-height:100vh}
    .stApp [data-testid="stHorizontalBlock"]{gap:0!important;min-height:100vh;align-items:stretch!important}
    .stApp [data-testid="stColumn"]{padding:0!important;min-height:100vh}

    .stApp [data-testid="stColumn"]:first-child{
        background:
            radial-gradient(ellipse at 28% 72%, rgba(190,12,30,.30) 0%,transparent 54%),
            radial-gradient(ellipse at 72% 20%, rgba(120,8,20,.18) 0%,transparent 40%),
            #171210;
    }
    .stApp [data-testid="stColumn"]:last-child{background:#FAF8F6!important}
    .stApp [data-testid="stColumn"]:last-child>div{padding:0 64px!important}

    .ll-wrap{
        display:flex;align-items:flex-start;justify-content:flex-start;
        min-height:100vh;padding:44px 52px;
    }
    .lr-hdr{max-width:420px;margin-bottom:28px;font-family:'Pretendard Variable',system-ui,sans-serif}
    .lr-sign{font-size:10px;font-weight:700;letter-spacing:2.5px;color:#E60028!important;
        margin:0 0 14px;text-transform:uppercase;display:block}
    .lr-headline{font-size:28px;font-weight:800;color:#1F1B1B!important;
        margin:0 0 8px;line-height:1.3;letter-spacing:-.3px}
    .lr-sub{font-size:14px;color:#9A918C!important;margin:0}

    .stApp [data-testid="stColumn"]:last-child [data-testid="stTextInput"],
    .stApp [data-testid="stColumn"]:last-child [data-testid="stCheckbox"],
    .stApp [data-testid="stColumn"]:last-child .stButton,
    .stApp [data-testid="stColumn"]:last-child [data-baseweb="notification"]{max-width:420px}

    .stApp [data-testid="stColumn"]:last-child label{
        font-size:13px!important;font-weight:600!important;color:#1F1B1B!important}

    .stApp [data-testid="stColumn"]:last-child [data-baseweb="input"]{
        background:#FFFFFF!important;border:1.5px solid #E5E0DB!important;
        border-radius:10px!important;box-shadow:none!important;outline:none!important}
    .stApp [data-testid="stColumn"]:last-child [data-baseweb="input"]:focus-within{
        border-color:#E60028!important;box-shadow:0 0 0 3px rgba(230,0,40,.10)!important}
    .stApp [data-testid="stColumn"]:last-child [data-baseweb="input"] input{
        font-size:15px!important;color:#1F1B1B!important;height:48px!important;
        padding:0 14px!important;background:transparent!important;
        border:none!important;box-shadow:none!important}
    .stApp [data-testid="stColumn"]:last-child [data-baseweb="input"] input::placeholder{
        color:#C3BAB4!important}
    .stApp [data-testid="stColumn"]:last-child [data-baseweb="input"] button{
        background:#FFFFFF!important;border:none!important;
        color:#9A918C!important;height:48px!important;padding:0 14px!important}
    .stApp [data-testid="stColumn"]:last-child [data-baseweb="input"] button:hover{
        background:#F5F0EC!important;color:#5B5450!important}
    .stApp [data-testid="stColumn"]:last-child [data-baseweb="base-input"]{
        background:#FFFFFF!important;border:none!important;box-shadow:none!important}

    .stApp [data-testid="stColumn"]:last-child .stButton>button{
        background:#E60028!important;color:#fff!important;border:none!important;
        border-radius:10px!important;font-size:15px!important;font-weight:700!important;
        height:50px!important;margin-top:8px!important;letter-spacing:-.2px;
        font-family:'Pretendard Variable',system-ui,sans-serif!important;
        transition:background .18s!important;box-shadow:0 2px 12px rgba(230,0,40,.25)!important}
    .stApp [data-testid="stColumn"]:last-child .stButton>button:hover{
        background:#C00022!important;box-shadow:0 4px 16px rgba(230,0,40,.35)!important}

    .stApp [data-testid="stColumn"]:last-child [data-testid="stCheckbox"] label,
    .stApp [data-testid="stColumn"]:last-child [data-testid="stCheckbox"] label p,
    .stApp [data-testid="stColumn"]:last-child [data-testid="stCheckbox"] p{
        font-size:13px!important;color:#5B5450!important;font-weight:500!important}

    .stApp [data-testid="stColumn"]:last-child [data-testid="stNotification"]{
        background:#FFF3F5!important;border-color:#E60028!important}

    @media(max-width:700px){
        .stApp [data-testid="stColumn"]:first-child{display:none!important}
        .stApp [data-testid="stColumn"]:last-child{background:#171210!important}
        .stApp [data-testid="stColumn"]:last-child>div{padding:0 28px!important}
        .lr-headline{color:#EDE8E5!important}
        .lr-sub{color:rgba(237,232,229,.55)!important}
        .stApp [data-testid="stColumn"]:last-child label{color:#EDE8E5!important}
        .stApp [data-testid="stColumn"]:last-child [data-baseweb="input"]{
            background:rgba(255,255,255,.07)!important;border-color:rgba(255,255,255,.14)!important}
        .stApp [data-testid="stColumn"]:last-child [data-baseweb="input"] input{
            color:#EDE8E5!important}
        .stApp [data-testid="stColumn"]:last-child [data-baseweb="input"] button{
            background:transparent!important}
        .stApp [data-testid="stColumn"]:last-child [data-testid="stCheckbox"] label,
        .stApp [data-testid="stColumn"]:last-child [data-testid="stCheckbox"] p{
            color:rgba(237,232,229,.7)!important}
    }
    </style>""", unsafe_allow_html=True)

    left, right = st.columns([1, 1])

    with left:
        st.markdown(f'<div class="ll-wrap">{ll_logo}</div>', unsafe_allow_html=True)

    with right:
        st.markdown("<div style='height:20vh'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div class="lr-hdr">
          <p class="lr-sign">Sign In</p>
          <h2 class="lr-headline">안녕하세요,<br>다시 만나요.</h2>
          <p class="lr-sub">사내 계정으로 로그인하세요.</p>
        </div>
        """, unsafe_allow_html=True)

        username = st.text_input("사번 또는 이메일", placeholder="아이디를 입력하세요", key="login_user")
        password = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요", key="login_pw")
        remember = st.checkbox("로그인 상태 유지", value=True, key="login_remember")

        if st.button("로그인", type="primary", use_container_width=True, key="login_btn"):
            if username and password:
                user = verify_login(username, password)
                if user:
                    tok = create_session(user["username"], remember=remember)
                    st.session_state.authenticated = True
                    st.session_state.auth_user = user
                    st.session_state.session_token = tok
                    st.query_params.update({"page": "dashboard", "t": tok})
                    st.rerun()
                else:
                    st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
            else:
                st.warning("아이디와 비밀번호를 입력해주세요.")

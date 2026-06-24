"""
공통 유틸리티 — 포맷터, 차트 기본 설정, UI 헬퍼
"""
import base64
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go

# ── 숫자 포맷터 ────────────────────────────────────────────────
def fw(n, unit="auto") -> str:
    """큰 숫자를 억/만 단위로 축약"""
    try:
        v = int(n)
        if unit == "auto":
            if abs(v) >= 100_000_000:
                return f"{v / 100_000_000:.1f}억"
            if abs(v) >= 10_000:
                return f"{v / 10_000:.0f}만"
        return f"{v:,}"
    except Exception:
        return "—"


def fn(n) -> str:
    """정수 콤마 포맷"""
    try:
        return f"{int(n):,}"
    except Exception:
        return "—"


def tone(v) -> str:
    """양수/음수/0에 따른 CSS 클래스"""
    if v > 0:
        return "c-pos"
    if v < 0:
        return "c-red"
    return "c-ink"


# ── Streamlit UI 헬퍼 ─────────────────────────────────────────
def sec(label: str):
    """구분선 + 섹션 레이블"""
    st.markdown(
        f'<div class="sec"><span class="sec-t">{label}</span>'
        f'<span class="sec-l"></span></div>',
        unsafe_allow_html=True,
    )


# ── 로고 HTML ─────────────────────────────────────────────────
def get_logo_html(mobile: bool = False) -> str:
    logo_path = Path(__file__).parent.parent / "assets" / "logo.png"
    if logo_path.exists():
        b64 = base64.b64encode(logo_path.read_bytes()).decode()
        w = "160" if mobile else "148"
        return (
            f'<img src="data:image/png;base64,{b64}" '
            f'style="width:{w}px;height:auto;display:block" alt="LAON SPORTS">'
        )
    w = "160" if mobile else "140"
    return (
        f'<svg viewBox="0 0 210 80" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:{w}px;height:auto;display:block">'
        f'<text x="2" y="56" fill="#E60028" font-size="62" font-weight="900" '
        f'font-family="Arial Black,Impact,system-ui,sans-serif" letter-spacing="-3">LAON</text>'
        f'<text x="7" y="74" fill="#E60028" font-size="13.5" font-weight="700" '
        f'font-family="Arial,Helvetica,system-ui,sans-serif" letter-spacing="10">SPORTS</text>'
        f'</svg>'
    )


# ── Plotly 기본 레이아웃 ──────────────────────────────────────
PLOT_BASE = dict(
    font=dict(family="Pretendard Variable,sans-serif", size=12, color="#1F1B1B"),
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    margin=dict(t=16, b=36, l=10, r=10),
    legend=dict(
        orientation="h", yanchor="bottom", y=1.02,
        xanchor="right", x=1,
        font=dict(size=12, color="#1F1B1B"),
    ),
    hoverlabel=dict(
        bgcolor="#fff",
        bordercolor="rgba(31,27,27,.12)",
        font=dict(family="Pretendard Variable,sans-serif", size=13, color="#1F1B1B"),
    ),
)

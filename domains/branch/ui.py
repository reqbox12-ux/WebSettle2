"""
domains/branch/ui.py — 지점 상세 페이지 (전월 대비 + 손익계산서 통합 뷰)
"""
import base64
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from shared.config import BRANCH_LIST as _JSON_BRANCH_LIST
from shared.utils import fn, fw, sec, PLOT_BASE
from domains.dashboard.service import build_summary, c_rev, c_exp
from domains.branch.db import (
    get_active_branch_names, get_all_branches, upsert_branch,
    get_branch_monthly_revenue, upsert_branch_monthly_revenue,
)

_now = datetime.now()

# ── 유틸 ─────────────────────────────────────────────────────
def _prev_ym(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _delta_badge(curr: float, prev: float) -> str:
    if prev == 0:
        return '<span style="font-size:11px;color:var(--ink3)">—</span>'
    diff = curr - prev
    pct  = diff / abs(prev) * 100
    sign = "▲" if diff >= 0 else "▼"
    col  = "var(--pos)" if diff >= 0 else "var(--red)"
    bg   = "var(--poss)" if diff >= 0 else "var(--reds)"
    return (
        f'<span style="display:inline-flex;align-items:center;gap:3px;'
        f'padding:2px 8px;border-radius:999px;background:{bg};'
        f'color:{col};font-size:11px;font-weight:700">'
        f'{sign} {abs(pct):.1f}%</span>'
    )


# ── 전월 대비 KPI 카드 ────────────────────────────────────────
def _render_mom_kpi(curr: dict, prev: dict):
    card_curr = curr.get("카드공급가액", 0) + curr.get("카드VAT", 0) + curr.get("카드수수료", 0)
    card_prev = prev.get("카드공급가액", 0) + prev.get("카드VAT", 0) + prev.get("카드수수료", 0)
    cash_curr = curr.get("현금공급가액", 0) + curr.get("현금VAT", 0) + curr.get("수동입력매출", 0)
    cash_prev = prev.get("현금공급가액", 0) + prev.get("현금VAT", 0) + prev.get("수동입력매출", 0)
    items = [
        ("총 매출",   curr["총매출"],  prev["총매출"],  "c-ink"),
        ("카드 매출", card_curr,       card_prev,       "c-ink"),
        ("현금 매출", cash_curr,       cash_prev,       "c-ink"),
        ("총 지출",   curr["총지출"],  prev["총지출"],  "c-red"),
        ("순 손익",   curr["손익"],    prev["손익"],
         "c-pos" if curr["손익"] >= 0 else "c-red"),
    ]
    html = '<div class="kpi-grid">'
    for lbl, c_val, p_val, cls in items:
        delta = _delta_badge(c_val, p_val)
        html += (
            f'<div class="kpi">'
            f'<div class="kpi-lbl">{lbl}</div>'
            f'<div class="kpi-val {cls}">{fw(abs(int(c_val)))}'
            f'<span class="kpi-unit">원</span></div>'
            f'<div class="kpi-sub" style="display:flex;align-items:center;gap:6px">'
            f'전월 {fw(abs(int(p_val)))} &nbsp;{delta}</div>'
            f'</div>'
        )
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


# ── 전월 대비 비교 차트 ──────────────────────────────────────
def _render_mom_chart(curr: dict, prev: dict, year: int, month: int, key: str):
    p_year, p_month = _prev_ym(year, month)
    labels   = ["총 매출", "총 지출", "순 손익"]
    c_vals   = [curr["총매출"], curr["총지출"], curr["손익"]]
    p_vals   = [prev["총매출"], prev["총지출"], prev["손익"]]

    bar_colors_c = ["#3D3835", "#E60028", "#2E7D5B" if curr["손익"] >= 0 else "#E60028"]
    bar_colors_p = ["rgba(61,56,53,.35)", "rgba(230,0,40,.35)",
                    "rgba(46,125,91,.35)" if prev["손익"] >= 0 else "rgba(230,0,40,.35)"]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=f"{year}년 {month}월 (이번달)",
        x=labels, y=c_vals,
        marker_color=bar_colors_c,
        text=[fw(abs(int(v))) for v in c_vals],
        textposition="outside",
        textfont=dict(size=11),
    ))
    fig.add_trace(go.Bar(
        name=f"{p_year}년 {p_month}월 (전월)",
        x=labels, y=p_vals,
        marker_color=bar_colors_p,
        text=[fw(abs(int(v))) for v in p_vals],
        textposition="outside",
        textfont=dict(size=11, color="#9A918C"),
    ))
    fig.update_layout(**{
        **PLOT_BASE,
        "barmode": "group",
        "height": 340,
        "margin": dict(t=30, b=20, l=10, r=10),
        "yaxis": dict(tickformat=",", gridcolor="rgba(31,27,27,.07)", zeroline=True,
                      zerolinecolor="rgba(31,27,27,.15)"),
        "legend": dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                       font=dict(size=11)),
        "bargap": 0.25, "bargroupgap": 0.1,
    })
    st.plotly_chart(fig, use_container_width=True, key=key,
                    config={"staticPlot": True, "displayModeBar": False})


# ── 손익계산서 통합 패널 ─────────────────────────────────────
def _render_pnl_panel(row: dict, year: int, month: int):
    b = row["branch"]

    rev_df = c_rev(year, month)
    rev_by_cat: dict = {}
    if not rev_df.empty:
        br_rev = rev_df[rev_df.branch == b]
        rev_by_cat = br_rev.set_index("category")["supply_amount"].to_dict()

    exp_df = c_exp(year, month)
    exp_by_cat: dict = {}
    if not exp_df.empty:
        br_exp = exp_df[exp_df.branch == b]
        exp_by_cat = br_exp.groupby("category")["amount"].sum().to_dict()

    # 월별 수동입력 매출 (해당 지점)
    from domains.branch.db import get_branch_monthly_revenue as _get_bmr
    _bmr_list = _get_bmr(year, month)
    bmr_data: dict = next((r for r in _bmr_list if r.get("branch") == b), {})

    CARD_CATS = ["PT매출(카드)", "GX매출(카드)", "골프매출(카드)", "키즈매출(카드)", "기타매출(카드)"]
    CASH_CATS = ["PT매출(현금)", "GX매출(현금)", "골프매출(현금)", "키즈매출(현금)", "기타매출(현금)",
                 "도급비", "시설상환비", "카페매출"]
    BMR_LABELS = [
        ("dogeub",       "도급비(입력)"),
        ("pt_sales",     "PT매출(입력)"),
        ("gx_sales",     "GX매출(입력)"),
        ("cafe_sales",   "카페매출(입력)"),
        ("golf_sales",   "골프매출(입력)"),
        ("facility_fee", "시설상환비(입력)"),
        ("cafe_labor",   "카페인건비(입력)"),
        ("other_sales",  "기타매출(입력)"),
    ]

    def _row(lbl, amt, indent=False, bold=False, cls=""):
        style_lbl = "color:var(--ink3);padding-left:20px" if indent else "color:var(--ink);font-weight:600" if bold else "color:var(--ink2)"
        style_amt = f"font-feature-settings:'tnum' 1;font-weight:{'700' if bold else '500'};{f'color:{cls}' if cls else ''}"
        border    = "border-top:2px solid var(--bds);margin-top:4px;padding-top:10px" if bold else "border-bottom:1px solid var(--bd)"
        return (
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:{"10px" if bold else "6px"} 0;{border}">'
            f'<span style="font-size:{"14px" if bold else "12.5px"};{style_lbl}">{lbl}</span>'
            f'<span style="font-size:{"14px" if bold else "12.5px"};{style_amt}">{fn(int(amt))}원</span>'
            f'</div>'
        )

    # 수익 섹션 — 카드(공급가액+VAT+수수료) + 현금(총입금) + 직접입력
    rev_html = '<div style="font-size:10px;font-weight:700;color:var(--ink3);letter-spacing:.07em;text-transform:uppercase;padding-bottom:8px;border-bottom:1px solid var(--bd);margin-bottom:2px">수 익</div>'

    # 카드 매출: 공급가액 + VAT + 수수료 = 총액
    card_supply_v = int(row.get("카드공급가액", 0))
    card_vat_v    = int(row.get("카드VAT", 0))
    card_fee_v    = int(row.get("카드수수료", 0))
    card_total_v  = card_supply_v + card_vat_v + card_fee_v
    if card_total_v > 0:
        if card_supply_v > 0:
            rev_html += _row("카드 공급가액", card_supply_v, indent=True)
        if card_vat_v > 0:
            rev_html += _row("카드 VAT", card_vat_v, indent=True)
        if card_fee_v > 0:
            rev_html += _row("카드 수수료", card_fee_v, indent=True)
        rev_html += _row("카드 소계", card_total_v, bold=True)

    # 현금 매출: 카테고리별 공급가액 + VAT = 총입금
    cash_supply_v = int(row.get("현금공급가액", 0))
    cash_vat_v    = int(row.get("현금VAT", 0))
    cash_total_v  = cash_supply_v + cash_vat_v
    if cash_total_v > 0:
        for cat in CASH_CATS:
            v = int(rev_by_cat.get(cat, 0))
            if v > 0:
                rev_html += _row(cat, v, indent=True)
        if cash_vat_v > 0:
            rev_html += _row("현금 VAT", cash_vat_v, indent=True)
        rev_html += _row("현금 소계", cash_total_v, bold=True)

    # 수동입력 현금매출 (도급비·시설상환비 등 직접 입력)
    bmr_total = int(row.get("수동입력매출", 0))
    bmr_vat   = int(row.get("직접입력VAT", 0))
    if bmr_total > 0:
        for db_col, label in BMR_LABELS:
            v = int(bmr_data.get(db_col, 0) or 0)
            if v > 0:
                rev_html += _row(label, v, indent=True)
        if bmr_vat > 0:
            rev_html += _row("직접입력매출 VAT (÷11)", bmr_vat, indent=True)
        rev_html += _row("직접입력 현금매출 (VAT 포함)", bmr_total, bold=True)

    # 총매출 합계
    rev_html += (
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:12px 0;border-top:2px solid var(--ink);margin-top:6px">'
        f'<span style="font-size:15px;font-weight:800;color:var(--ink)">총 매출</span>'
        f'<span style="font-size:15px;font-weight:800;color:var(--ink);font-feature-settings:\'tnum\' 1">'
        f'{fn(int(row["총매출"]))}원</span></div>'
    )

    # 비용 섹션
    exp_html = '<div style="font-size:10px;font-weight:700;color:var(--ink3);letter-spacing:.07em;text-transform:uppercase;padding-bottom:8px;border-bottom:1px solid var(--bd);margin-bottom:2px;margin-top:8px">비 용</div>'
    PAY_ITEMS = [
        ("급여 (실수령)",        "급여"),
        ("4대보험료 (직원부담)", "4대보험료_직원"),
        ("4대보험료 (본사부담)", "4대보험_본사"),
        ("소득세·지방세",        "소득세지방세"),
        ("프리랜서",             "프리랜서"),
        ("프리랜서 세금",        "프리랜서세금"),
    ]
    for lbl, key in PAY_ITEMS:
        v = int(row.get(key, 0))
        if v > 0:
            exp_html += _row(lbl, v, indent=True)
    exp_html += _row("인건비 합계", row["인건비합계"], bold=True)

    for cat, amt in sorted(exp_by_cat.items(), key=lambda x: -x[1]):
        if amt > 0:
            exp_html += _row(cat, int(amt), indent=True)
    if int(row.get("기타지출", 0)) > 0:
        exp_html += _row("기타지출 합계", row["기타지출"], bold=True)

    # 부가세 세부 항목
    if int(row.get("카드VAT", 0)) > 0:
        exp_html += _row("카드 VAT", row["카드VAT"], indent=True)
    if int(row.get("현금VAT", 0)) > 0:
        exp_html += _row("현금 VAT", row["현금VAT"], indent=True)
    if int(row.get("직접입력VAT", 0)) > 0:
        exp_html += _row("직접입력매출 VAT", row["직접입력VAT"], indent=True)
    if int(row.get("부가세합계", 0)) > 0:
        exp_html += _row("부가세합계 (카드VAT + 현금VAT + 직접입력VAT)", row["부가세합계"], bold=True)
    if int(row.get("카드수수료", 0)) > 0:
        exp_html += _row("카드수수료", row["카드수수료"], bold=True)

    # 총지출 합계
    exp_html += (
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:12px 0;border-top:2px solid var(--ink);margin-top:6px">'
        f'<span style="font-size:15px;font-weight:800;color:var(--red)">총 지출</span>'
        f'<span style="font-size:15px;font-weight:800;color:var(--red);font-feature-settings:\'tnum\' 1">'
        f'{fn(int(row["총지출"]))}원</span></div>'
    )

    pnl     = int(row["손익"])
    rate    = row["이익률"]
    pnl_col = "var(--pos)" if pnl >= 0 else "var(--red)"
    sign    = "▲" if pnl >= 0 else "▼"

    pnl_html = (
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:16px 20px;background:{"var(--poss)" if pnl >= 0 else "var(--reds)"};'
        f'border-radius:var(--rs);margin-top:16px">'
        f'<span style="font-size:16px;font-weight:800;color:{pnl_col}">순 손익</span>'
        f'<div style="text-align:right">'
        f'<div style="font-size:20px;font-weight:800;color:{pnl_col};font-feature-settings:\'tnum\' 1">'
        f'{sign} {fn(abs(pnl))}원</div>'
        f'<div style="font-size:13px;font-weight:600;color:{pnl_col}">'
        f'이익률 {"+" if rate >= 0 else ""}{rate:.1f}% (손익÷총매출)</div>'
        f'</div></div>'
    )

    st.markdown(
        f'<div style="background:var(--sf);border:1px solid var(--bd);border-radius:var(--r);'
        f'padding:24px;box-shadow:var(--shm)">'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:32px">'
        f'<div>{rev_html}</div>'
        f'<div>{exp_html}</div>'
        f'</div>'
        f'{pnl_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── 연간 월별 추이 차트 ──────────────────────────────────────
def _render_yearly_trend(br_sel: str, year: int, month: int):
    months_data = []
    for m in range(1, 13):
        r     = build_summary(year, m)
        row_m = r[r.branch == br_sel]
        if not row_m.empty:
            months_data.append({
                "월": f"{m}월",
                "총매출": row_m.iloc[0]["총매출"],
                "총지출": row_m.iloc[0]["총지출"],
                "손익":   row_m.iloc[0]["손익"],
            })
        else:
            months_data.append({"월": f"{m}월", "총매출": 0, "총지출": 0, "손익": 0})

    import pandas as pd
    mdf = pd.DataFrame(months_data)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="총매출", x=mdf["월"], y=mdf["총매출"],
        marker_color="#3D3835", opacity=0.8,
    ))
    fig.add_trace(go.Bar(
        name="총지출", x=mdf["월"], y=mdf["총지출"],
        marker_color="#E60028", opacity=0.72,
    ))
    fig.add_trace(go.Scatter(
        name="손익", x=mdf["월"], y=mdf["손익"],
        mode="lines+markers", yaxis="y2",
        line=dict(color="#2E7D5B", width=2.5),
        marker=dict(
            size=8,
            color=["#2E7D5B" if v >= 0 else "#E60028" for v in mdf["손익"]],
            line=dict(width=2, color="white"),
        ),
    ))
    # 현재 월 강조
    fig.add_vline(
        x=f"{month}월", line_width=1.5, line_dash="dot",
        line_color="rgba(230,0,40,.4)",
    )
    fig.update_layout(**{
        **PLOT_BASE,
        "barmode": "group",
        "height": 300,
        "margin": dict(t=16, b=20, l=10, r=10),
        "yaxis":  dict(tickformat=",", gridcolor="rgba(31,27,27,.07)", zeroline=False),
        "yaxis2": dict(overlaying="y", side="right", tickformat=",",
                       zeroline=True, zerolinecolor="rgba(31,27,27,.2)"),
        "xaxis":  dict(tickfont=dict(size=11)),
    })
    st.plotly_chart(fig, use_container_width=True,
                    config={"staticPlot": True, "displayModeBar": False})


# ── 지점 페이지 메인 ─────────────────────────────────────────
def render_page():
    year  = st.session_state.year
    month = st.session_state.month

    st.markdown(
        '<div class="ph"><div class="ph-title">지점 상세 내역</div>'
        '<div class="ph-sub">지점 상세 분석 · 지점 관리 · 월별 매출 직접 입력</div></div>',
        unsafe_allow_html=True,
    )

    tab_detail, tab_mgmt, tab_revenue, tab_reports = st.tabs(
        ["📊 지점 상세", "🏢 지점 관리", "📝 월별 매출 입력", "📬 지점 보고"]
    )

    with tab_detail:
        _render_detail(year, month)

    with tab_mgmt:
        _render_branch_mgmt()

    with tab_revenue:
        _render_monthly_revenue(year, month)

    with tab_reports:
        _render_branch_reports()


def _render_detail(year: int, month: int):
    """기존 지점 상세 뷰 (전월 대비 + 손익계산서 + 추이 + PDF)"""
    BRANCH_LIST = get_active_branch_names()

    st.markdown('<div class="filter-wrap">', unsafe_allow_html=True)
    fc1, fc2, fc3 = st.columns([1, 1, 2])
    yrs    = list(range(_now.year, _now.year - 3, -1))
    year   = fc1.selectbox("연도", yrs, index=yrs.index(year) if year in yrs else 0, key="br_yr")
    month  = fc2.selectbox("월", list(range(1, 13)), index=month - 1, key="br_mn",
                            format_func=lambda m: f"{m}월")
    br_sel = fc3.selectbox("지점 선택", BRANCH_LIST, key="br_sel")
    st.session_state.year  = year
    st.session_state.month = month
    st.markdown('</div>', unsafe_allow_html=True)

    with st.spinner("데이터 로드 중..."):
        full_df  = build_summary(year, month)
        p_year, p_month = _prev_ym(year, month)
        prev_df  = build_summary(p_year, p_month)

    br_row   = full_df[full_df.branch == br_sel]
    prev_row = prev_df[prev_df.branch == br_sel]

    has_data = (not br_row.empty and
                (br_row.iloc[0]["총매출"] != 0 or br_row.iloc[0]["총지출"] != 0))

    if not has_data:
        _rev_check = c_rev(year, month)
        _exp_check = c_exp(year, month)
        _has = ((not _rev_check.empty and br_sel in _rev_check.branch.values) or
                (not _exp_check.empty and br_sel in _exp_check.branch.values))
        if not _has:
            st.markdown('<div class="al al-warn">⚠️&nbsp; 해당 지점의 데이터가 없습니다.</div>',
                        unsafe_allow_html=True)
            return

    def _empty_row(branch: str) -> dict:
        r = {c: 0 for c in full_df.columns}
        r["branch"] = branch
        r["이익률"] = 0.0
        return r

    curr_d = br_row.iloc[0].to_dict() if not br_row.empty else _empty_row(br_sel)
    prev_d = prev_row.iloc[0].to_dict() if not prev_row.empty else _empty_row(br_sel)

    # ── 목표 매출 설정 & 달성률 ────────────────────────────────
    try:
        from modules.db import get_branch_goals, set_branch_goal
        goals = get_branch_goals(year, month)
        cur_goal = goals.get(br_sel, 0)
        actual_rev = int(curr_d.get("총매출", 0))

        with st.expander("🎯 목표 매출 설정", expanded=(cur_goal == 0 and actual_rev > 0)):
            g1, g2 = st.columns([3, 1])
            new_goal = g1.number_input(
                f"{year}년 {month}월 · {br_sel} 목표 매출 (원)",
                value=cur_goal,
                step=1_000_000,
                min_value=0,
                key=f"goal_{br_sel}_{year}_{month}",
                format="%d",
            )
            g2.markdown("<br>", unsafe_allow_html=True)
            if g2.button("💾 저장", key=f"goal_save_{br_sel}_{year}_{month}",
                          use_container_width=True):
                set_branch_goal(year, month, br_sel, int(new_goal))
                st.success("목표 저장 완료")
                st.rerun()

        if cur_goal > 0:
            achieve_rate = (actual_rev / cur_goal * 100) if cur_goal else 0
            color = "var(--pos)" if achieve_rate >= 100 else ("var(--warn)" if achieve_rate >= 70 else "var(--red)")
            st.markdown(
                f'<div style="background:var(--sf);border:1px solid var(--bd);border-radius:var(--rs);'
                f'padding:12px 18px;margin-bottom:16px;display:flex;align-items:center;gap:16px">'
                f'<span style="font-size:12px;color:var(--ink3)">🎯 목표 매출</span>'
                f'<span style="font-size:14px;font-weight:700;color:var(--ink)">'
                f'{cur_goal:,}원</span>'
                f'<span style="font-size:12px;color:var(--ink3)">달성률</span>'
                f'<span style="font-size:18px;font-weight:800;color:{color}">'
                f'{achieve_rate:.1f}%</span>'
                f'<div style="flex:1;background:var(--sf2);border-radius:999px;height:8px;overflow:hidden">'
                f'<div style="width:{min(achieve_rate,100):.1f}%;height:100%;'
                f'background:{color};transition:width .5s"></div></div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        pass

    # ── 전월 대비 KPI 카드
    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:16px">'
        f'<div style="font-size:13px;font-weight:600;color:var(--ink)">'
        f'{year}년 {month}월 &nbsp;·&nbsp; {br_sel}</div>'
        f'<div style="font-size:11px;color:var(--ink3)">전월({p_year}년 {p_month}월) 대비</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    _render_mom_kpi(curr_d, prev_d)

    # ── 전월 대비 비교 차트
    st.markdown(
        f'<div class="ch"><div class="ch-t">전월 대비 비교 — {br_sel}</div>'
        f'<div class="ch-s">{year}년 {month}월 vs {p_year}년 {p_month}월</div>',
        unsafe_allow_html=True,
    )
    _render_mom_chart(curr_d, prev_d, year, month, key="mom_chart")
    st.markdown('</div>', unsafe_allow_html=True)

    # ── 손익계산서
    sec("손익계산서")
    _render_pnl_panel(curr_d, year, month)

    # ── 연간 월별 추이
    sec(f"{year}년 월별 손익 추이")
    _render_yearly_trend(br_sel, year, month)

    # ── 정산서 내보내기
    _render_pdf_section(full_df, br_sel, year, month)


# ── Nominatim 지오코딩 (API 키 불필요) ───────────────────────
def _geocode_nominatim(address: str) -> tuple:
    """OpenStreetMap Nominatim으로 주소 → 위도/경도 변환"""
    import urllib.request, urllib.parse, json
    try:
        url = (
            "https://nominatim.openstreetmap.org/search"
            f"?q={urllib.parse.quote(address)}&format=json&limit=1&countrycodes=kr"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "WebSettle-LaonSports/1.0"})
        with urllib.request.urlopen(req, timeout=7) as resp:
            rows = json.loads(resp.read())
        if rows:
            return float(rows[0]["lat"]), float(rows[0]["lon"])
    except Exception:
        pass
    return None, None


# ── 카카오맵 미리보기 iframe ──────────────────────────────────
def _kakao_map_iframe(lat: float, lng: float, name: str = "") -> str:
    safe_name = name.replace("'", "").replace('"', "")
    return (
        f'<iframe src="https://map.kakao.com/link/map/{safe_name},{lat},{lng}" '
        f'style="width:100%;height:380px;border:1px solid #E8E2DE;border-radius:10px;" '
        f'allowfullscreen></iframe>'
    )


# ── Daum 주소 검색 임베드 HTML (팝업 아닌 인라인 임베드) ────
_DAUM_EMBED_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<script src="https://t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Apple SD Gothic Neo',sans-serif;background:#FAF7F5}
.rb{
  display:none;background:#fff;border:2px solid #E60028;
  border-radius:8px;padding:12px 16px;margin:0 0 6px;
}
.rl{font-size:10px;color:#9A918C;font-weight:700;letter-spacing:.06em}
.ra{font-size:15px;font-weight:800;color:#1F1B1B;margin:4px 0 2px;word-break:break-all;
    user-select:all;cursor:text}
.rj{font-size:11px;color:#9A918C}
.cs{font-size:12px;font-weight:700;color:#2E7D5B;margin-top:6px}
#wrap{width:100%;height:400px}
</style>
</head>
<body>
<div class="rb" id="rb">
  <div class="rl">📋 선택된 주소 — 왼쪽 필드에 Ctrl+V 붙여넣기</div>
  <div class="ra" id="ra"></div>
  <div class="rj" id="rj"></div>
  <div class="cs" id="cs"></div>
</div>
<div id="wrap"></div>
<script>
new daum.Postcode({
  width:'100%',
  height:'400px',
  oncomplete:function(d){
    var addr = d.roadAddress || d.jibunAddress;
    document.getElementById('ra').innerText = addr;
    document.getElementById('rj').innerText = d.jibunAddress ? '지번: '+d.jibunAddress : '';
    document.getElementById('rb').style.display = 'block';
    if(navigator.clipboard){
      navigator.clipboard.writeText(addr)
        .then(function(){ document.getElementById('cs').innerText='✅ 클립보드 복사 완료! 왼쪽 주소 필드에 Ctrl+V 하세요'; })
        .catch(function(){ document.getElementById('cs').innerText='위 주소를 드래그 선택 후 복사하세요'; });
    } else {
      document.getElementById('cs').innerText='위 주소를 드래그 선택 후 복사하세요';
    }
  }
}).embed(document.getElementById('wrap'),{autoClose:false});
</script>
</body>
</html>"""


# ── 지점 관리 탭 ──────────────────────────────────────────────
def _render_branch_mgmt():
    sec("지점 목록")
    st.caption("계약일·해지일·재계약 여부와 주소를 직접 수정하고 저장하세요. 비활성 지점은 드롭다운에서 자동으로 제외됩니다.")

    branches = get_all_branches(active_only=False)
    if not branches:
        st.info("등록된 지점이 없습니다.")
        return

    display_cols = {
        "id":               "ID",
        "name":             "지점명",
        "contract_date":    "계약일",
        "termination_date": "해지일",
        "is_active":        "재계약",
        "address":          "주소",
        "note":             "비고",
    }

    df = pd.DataFrame(branches)
    for col in ["address", "lat", "lng"]:
        if col not in df.columns:
            df[col] = "" if col == "address" else None

    edit_df = df[[c for c in display_cols if c in df.columns]].copy()
    edit_df = edit_df.rename(columns=display_cols)
    edit_df["재계약"] = edit_df["재계약"].apply(lambda v: bool(v))

    edited = st.data_editor(
        edit_df,
        use_container_width=True,
        hide_index=True,
        height=460,
        num_rows="fixed",
        key="branch_editor_table",
        column_config={
            "ID":    st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "지점명": st.column_config.TextColumn("지점명", width="medium"),
            "계약일": st.column_config.TextColumn("계약일", width="small", help="YYYY-MM-DD 형식"),
            "해지일": st.column_config.TextColumn("해지일", width="small", help="계약 해지일"),
            "재계약": st.column_config.CheckboxColumn("재계약", width="small",
                                                       help="체크 해제 시 드롭다운에서 제외"),
            "주소":   st.column_config.TextColumn("주소", width="large"),
            "비고":   st.column_config.TextColumn("비고", width="medium"),
        },
    )
    st.caption(f"총 {len(branches)}개 지점 · 위도/경도는 아래 '위치 상세 편집'에서 설정")

    if st.button("💾 변경사항 저장", key="branch_inline_save", type="primary"):
        changes = st.session_state.get("branch_editor_table", {}).get("edited_rows", {})
        if not changes:
            st.info("변경된 내용이 없습니다.")
        else:
            col_reverse = {v: k for k, v in display_cols.items()}
            saved_count = 0
            for row_idx_str, row_changes in changes.items():
                branch = dict(branches[int(row_idx_str)])
                for col_label, val in row_changes.items():
                    db_col = col_reverse.get(col_label)
                    if not db_col:
                        continue
                    if db_col == "is_active":
                        branch[db_col] = 1 if val else 0
                    else:
                        branch[db_col] = str(val or "").strip()
                upsert_branch(branch)
                saved_count += 1
            st.success(f"✅ {saved_count}개 지점 수정 완료")
            st.rerun()

    # ── 위치 상세 편집 ───────────────────────────────────────
    st.divider()
    sec("위치 상세 편집")
    st.markdown(
        '<div class="al al-info">ℹ️&nbsp; '
        '오른쪽 검색창에서 주소 클릭 → 자동 복사 → 왼쪽 주소 필드에 <b>Ctrl+V</b> → '
        '<b>위도/경도 자동 변환</b> 버튼 → 저장</div>',
        unsafe_allow_html=True,
    )

    branch_names = [b["name"] for b in branches]
    sel_br_name  = st.selectbox("편집할 지점 선택", branch_names, key="loc_edit_sel")
    sel_br       = next((b for b in branches if b["name"] == sel_br_name), {})

    lat_key = f"loc_lat_{sel_br_name}"
    lng_key = f"loc_lng_{sel_br_name}"

    # 처음 선택 시 DB값으로 초기화
    if lat_key not in st.session_state:
        st.session_state[lat_key] = float(sel_br["lat"]) if sel_br.get("lat") else 0.0
    if lng_key not in st.session_state:
        st.session_state[lng_key] = float(sel_br["lng"]) if sel_br.get("lng") else 0.0

    edit_col, search_col = st.columns([3, 2])

    with edit_col:
        addr_input = st.text_input(
            "주소",
            value=sel_br.get("address", "") or "",
            key=f"loc_addr_{sel_br_name}",
            placeholder="오른쪽 검색창에서 주소 클릭 후 Ctrl+V 붙여넣기",
        )

        if st.button("📍 입력 주소로 위도/경도 자동 변환", key="geocode_btn",
                     use_container_width=True, type="primary"):
            import re
            addr = st.session_state.get(f"loc_addr_{sel_br_name}", "").strip()
            if addr:
                # 괄호 건물명 제거 후 검색 (예: "황새울로14 (서현리더스빌딩)" → "황새울로14")
                clean_addr = re.sub(r'\(.*?\)', '', addr).strip()
                with st.spinner(f"🔍 '{clean_addr}' 좌표 변환 중..."):
                    lat, lng = _geocode_nominatim(clean_addr)
                if lat and lng:
                    st.session_state[lat_key] = lat
                    st.session_state[lng_key] = lng
                    st.success(f"✅ 좌표 변환 완료: {lat:.6f}, {lng:.6f}")
                    st.rerun()
                else:
                    st.error(f"⚠️ '{clean_addr}' 좌표를 찾지 못했습니다. 도로명 주소만 간략히 입력해보세요.")
            else:
                st.warning("주소를 먼저 입력하세요.")

        lat_input = st.number_input(
            "위도 (Latitude)",
            format="%.6f", step=0.000001,
            key=lat_key,
        )
        lng_input = st.number_input(
            "경도 (Longitude)",
            format="%.6f", step=0.000001,
            key=lng_key,
        )

        # 출퇴근 허용 반경
        radius_key = f"loc_radius_{sel_br_name}"
        if radius_key not in st.session_state:
            st.session_state[radius_key] = int(sel_br.get("attendance_radius") or 300)
        st.select_slider(
            "📡 출퇴근 허용 반경",
            options=list(range(100, 550, 50)),
            key=radius_key,
            format_func=lambda v: f"{v}m",
            help="지점 좌표 기준, 이 반경 안에서만 출퇴근 가능",
        )

        if st.button("💾 위치 정보 저장", key="loc_save_btn", use_container_width=True):
            updated = dict(sel_br)
            updated["address"]           = st.session_state.get(f"loc_addr_{sel_br_name}", "").strip()
            updated["lat"]               = float(lat_input) if abs(float(lat_input)) > 0.0001 else None
            updated["lng"]               = float(lng_input) if abs(float(lng_input)) > 0.0001 else None
            updated["attendance_radius"] = int(st.session_state.get(radius_key, 300))
            upsert_branch(updated)
            # 저장 후 session_state 초기화 (다음 번에 DB에서 새로 읽도록)
            st.session_state.pop(lat_key, None)
            st.session_state.pop(lng_key, None)
            st.session_state.pop(radius_key, None)
            st.success(f"✅ '{sel_br_name}' 위치 정보 저장 완료")
            st.rerun()

    with search_col:
        st.markdown("**📍 주소 검색**")
        st.caption("주소 클릭 시 자동 복사 → 왼쪽 주소 필드에 Ctrl+V")
        st.components.v1.html(_DAUM_EMBED_HTML, height=500, scrolling=False)

    # ── 지도 미리보기 (좌표 있을 때, 전체 너비) ─────────────
    lat_v = st.session_state.get(lat_key, float(sel_br["lat"]) if sel_br.get("lat") else 0.0)
    lng_v = st.session_state.get(lng_key, float(sel_br["lng"]) if sel_br.get("lng") else 0.0)
    if lat_v and lng_v and abs(float(lat_v)) > 0.001 and abs(float(lng_v)) > 0.001:
        sec("🗺️ 지도 미리보기")
        st.markdown(_kakao_map_iframe(float(lat_v), float(lng_v), sel_br_name),
                    unsafe_allow_html=True)

    # ── 전체 위치 현황 ────────────────────────────────────────
    st.divider()
    all_with_loc = [b for b in branches if b.get("lat") and b.get("lng")]
    sec(f"위치 등록 현황 ({len(all_with_loc)}/{len(branches)}개)")
    loc_rows = []
    for b in branches:
        loc_rows.append({
            "지점명": b["name"],
            "주소":   b.get("address", "") or "미입력",
            "위도":   f"{b['lat']:.6f}" if b.get("lat") else "—",
            "경도":   f"{b['lng']:.6f}" if b.get("lng") else "—",
            "상태":   "✅ 등록" if b.get("lat") else "❌ 미등록",
        })
    st.dataframe(pd.DataFrame(loc_rows), use_container_width=True, hide_index=True)

    # ── 지점 추가 ────────────────────────────────────────────
    st.divider()
    sec("지점 추가")
    c1, c2, c3 = st.columns(3)
    new_name     = c1.text_input("지점명 *", key="new_br_name")
    new_contract = c2.text_input("계약일 (YYYY-MM-DD)", key="new_br_contract")
    new_note     = c3.text_input("비고", key="new_br_note")
    if st.button("➕ 지점 추가", type="primary", key="new_br_save"):
        if not new_name.strip():
            st.error("지점명을 입력하세요.")
        else:
            upsert_branch({
                "name":          new_name.strip(),
                "contract_date": new_contract.strip(),
                "is_active":     1,
                "note":          new_note.strip(),
            })
            st.success(f"✅ '{new_name}' 지점 추가 완료")
            st.rerun()


# ── 월별 매출 입력 탭 ─────────────────────────────────────────
_REVENUE_COLS = {
    "dogeub":       "도급비",
    "pt_sales":     "PT매출",
    "gx_sales":     "GX매출",
    "cafe_sales":   "카페매출",
    "golf_sales":   "골프매출",
    "facility_fee": "시설상환비",
    "cafe_labor":   "카페인건비",
    "other_sales":  "기타매출",
}


def _render_monthly_revenue(year: int, month: int):
    sec("월별 매출 직접 입력")
    st.caption("💡 도급비·시설상환비 등 직접 입력한 금액이 총매출(현금매출)에 반영됩니다. 통장에서 같은 항목이 도급비로 분류된 경우 '계정과목 검토'에서 제외 처리 후 업로드하세요.")

    col1, col2 = st.columns(2)
    yrs   = list(range(_now.year, _now.year - 3, -1))
    year  = col1.selectbox("연도", yrs,
                            index=yrs.index(year) if year in yrs else 0,
                            key="bmr_yr")
    month = col2.selectbox("월", list(range(1, 13)), index=month - 1,
                            key="bmr_mn", format_func=lambda m: f"{m}월")

    BRANCH_LIST = get_active_branch_names()

    # 기존 저장값 불러오기
    saved = {r["branch"]: r for r in get_branch_monthly_revenue(year, month)}

    # 전체 지점 × 전체 컬럼 DataFrame 구성
    rows = []
    for br in BRANCH_LIST:
        s = saved.get(br, {})
        row = {"지점": br}
        for db_col, label in _REVENUE_COLS.items():
            row[label] = int(s.get(db_col, 0) or 0)
        row["비고"] = s.get("note", "")
        rows.append(row)

    df_input = pd.DataFrame(rows)

    edited = st.data_editor(
        df_input,
        use_container_width=True,
        hide_index=True,
        height=600,
        num_rows="fixed",
        key="bmr_editor",
        column_config={
            "지점": st.column_config.TextColumn("지점", disabled=True, width="large"),
            **{
                label: st.column_config.NumberColumn(label, format="%d", min_value=0, step=10000)
                for label in _REVENUE_COLS.values()
            },
            "비고": st.column_config.TextColumn("비고"),
        },
    )

    label_to_db = {v: k for k, v in _REVENUE_COLS.items()}

    if st.button("💾 저장", type="primary", key="bmr_save"):
        changes = st.session_state.get("bmr_editor", {}).get("edited_rows", {})
        if not changes:
            st.info("변경된 내용이 없습니다.")
        else:
            saved_count = 0
            for row_idx_str, row_changes in changes.items():
                br = BRANCH_LIST[int(row_idx_str)]
                # 기존값 + 변경값 병합
                existing = saved.get(br, {})
                data = {db_col: int(existing.get(db_col, 0) or 0)
                        for db_col in _REVENUE_COLS}
                data["note"] = existing.get("note", "")
                for col_label, val in row_changes.items():
                    if col_label == "비고":
                        data["note"] = str(val or "").strip()
                    elif col_label in label_to_db:
                        data[label_to_db[col_label]] = int(val or 0)
                upsert_branch_monthly_revenue(year, month, br, data)
                saved_count += 1
            st.success(f"✅ {year}년 {month}월 {saved_count}개 지점 매출 저장 완료")
            st.rerun()


def _render_pdf_section(full_df, br_sel: str, year: int, month: int):
    from domains.branch.pdf import gen_pdf_html
    import io
    _ALL_BRANCHES = get_active_branch_names()
    sec("정산서 내보내기")
    st.markdown(
        '<div class="al al-info">ℹ️&nbsp; 포함할 지점을 선택한 후 다운로드하세요. '
        'HTML은 브라우저에서 열고 Ctrl+P → PDF 저장, Excel은 바로 다운로드 가능합니다.</div>',
        unsafe_allow_html=True,
    )

    chk_all_br = st.checkbox("전체 지점 선택", value=False, key="pdf_all_br")
    if chk_all_br:
        available_br = [b for b in _ALL_BRANCHES
                        if not full_df[full_df.branch == b].empty
                        and full_df[full_df.branch == b].iloc[0]["총매출"] > 0]
        pdf_branches = available_br or [br_sel]
    else:
        available_br = [b for b in _ALL_BRANCHES if not full_df[full_df.branch == b].empty]
        rows_c = [st.columns(4) for _ in range((len(available_br) + 3) // 4)]
        flat   = [c for row_c in rows_c for c in row_c]
        pdf_branches = [b for b, col in zip(available_br, flat)
                        if col.checkbox(b, value=(b == br_sel), key=f"pdf_br_{b}")]

    exp_df_pdf = c_exp(year, month)
    rev_df_pdf = c_rev(year, month)

    if pdf_branches:
        html_content = gen_pdf_html(full_df, pdf_branches, year, month,
                                    exp_df=exp_df_pdf, rev_df=rev_df_pdf)
        html_b64 = base64.b64encode(html_content.encode("utf-8")).decode()
        btn_part = (
            f'<a href="data:text/html;base64,{html_b64}" '
            f'download="정산보고서_{year}년{month}월.html" '
            f'style="background:#E60028;color:#fff;border-radius:8px;font-weight:600;'
            f'font-size:14px;padding:10px 22px;text-decoration:none;'
            f'white-space:nowrap;display:inline-block;'
            f'box-shadow:0 2px 6px rgba(230,0,40,.3)">📄 HTML 정산서 다운로드</a>'
        )
    else:
        btn_part = (
            '<span style="background:#ccc;color:#fff;border-radius:8px;font-weight:600;'
            'font-size:14px;padding:10px 22px;white-space:nowrap;display:inline-block;'
            'cursor:not-allowed">정산서 다운로드</span>'
        )

    st.markdown(
        f'<div class="pdf-box" style="display:flex;align-items:center;'
        f'justify-content:space-between;flex-wrap:wrap;gap:14px">'
        f'<div><div class="pdf-t" style="margin-bottom:4px">📄 정산서 다운로드</div>'
        f'<div style="font-size:12px;color:#9A918C">선택 지점 {len(pdf_branches)}개 · {year}년 {month}월</div>'
        f'</div>{btn_part}</div>',
        unsafe_allow_html=True,
    )

    # ── Excel 손익계산서 다운로드 ──────────────────────────────
    if pdf_branches:
        try:
            xl_buf = io.BytesIO()
            with pd.ExcelWriter(xl_buf, engine="openpyxl") as writer:
                for br in pdf_branches:
                    br_row = full_df[full_df.branch == br]
                    if br_row.empty:
                        continue
                    d = br_row.iloc[0].to_dict()

                    # 지출 카테고리별 상세
                    exp_detail = {}
                    if not exp_df_pdf.empty:
                        br_exp = exp_df_pdf[exp_df_pdf.branch == br]
                        exp_detail = br_exp.set_index("category")["amount"].to_dict() if not br_exp.empty else {}

                    rows_xl = [
                        ("", "항목", "금액 (원)"),
                        ("매출", "카드 공급가액",    int(d.get("카드공급가액", 0))),
                        ("",     "카드 수수료",      -int(d.get("카드수수료", 0))),
                        ("",     "카드 실수령",       int(d.get("카드실수령", 0))),
                        ("",     "현금 공급가액",     int(d.get("현금공급가액", 0))),
                        ("",     "직접입력 매출",     int(d.get("수동입력매출", 0))),
                        ("",     "▶ 총매출",          int(d.get("총매출", 0))),
                        ("지출", "급여",              int(d.get("급여", 0))),
                        ("",     "4대보험(직원)",      int(d.get("4대보험료_직원", 0))),
                        ("",     "4대보험(본사)",      int(d.get("4대보험_본사", 0))),
                        ("",     "소득세·지방세",      int(d.get("소득세지방세", 0))),
                        ("",     "프리랜서",           int(d.get("프리랜서", 0))),
                        ("",     "인건비합계",         int(d.get("인건비합계", 0))),
                        ("",     "기타지출",           int(d.get("기타지출", 0))),
                        ("",     "부가세합계",         int(d.get("부가세합계", 0))),
                        ("",     "▶ 총지출",           int(d.get("총지출", 0))),
                        ("손익", "▶ 순손익",           int(d.get("손익", 0))),
                        ("",     "이익률",             f"{float(d.get('이익률', 0)):.1f}%"),
                    ]
                    df_xl = pd.DataFrame(rows_xl, columns=["구분", "항목", "금액"])
                    # 시트 이름 최대 31자 제한
                    sheet_name = br[:31]
                    df_xl.to_excel(writer, sheet_name=sheet_name, index=False)

                    # 숫자 열 서식
                    ws = writer.sheets[sheet_name]
                    for row_i in range(2, len(rows_xl) + 2):
                        cell = ws.cell(row=row_i, column=3)
                        if isinstance(cell.value, int):
                            cell.number_format = '#,##0'

            xl_buf.seek(0)
            fn_xl = f"손익계산서_{year}년{month:02d}월.xlsx"
            st.download_button(
                label="📊 Excel 손익계산서 다운로드",
                data=xl_buf.getvalue(),
                file_name=fn_xl,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_pnl_xl",
            )
        except Exception as e:
            st.caption(f"Excel 생성 오류: {e}")


# ── 지점 보고 뷰 (ERP ↔ 랜딩페이지 연동) ─────────────────────────────────────
def _render_branch_reports():
    """
    랜딩페이지(branch_server.py)에서 직원이 올린 보고를 ERP에서 확인.
    - AS 요청 / 비품 요청 / 오늘 출퇴근 현황
    공유 DB(settlement.db)를 직접 조회.
    """
    from shared.db import get_conn
    from datetime import date

    today = date.today().isoformat()
    conn  = get_conn()

    # ── 지점 포털 바로가기 ────────────────────────────────────
    sec("지점 포털 바로가기")
    st.markdown(
        '<div class="al al-info">🔗&nbsp; 최고관리자(admin) 계정으로 지점 포털에 로그인하면 '
        '<b>전체 지점</b>의 데이터를 조회·관리할 수 있습니다. '
        '일반 직원은 자기 지점만 접근 가능합니다.</div>',
        unsafe_allow_html=True,
    )
    pc1, pc2 = st.columns(2)
    pc1.markdown(
        '<a href="https://attend.laonfitness.com/login" target="_blank" '
        'style="display:block;text-align:center;background:#E60028;color:#fff;'
        'border-radius:10px;font-weight:700;font-size:14px;padding:14px;'
        'text-decoration:none;box-shadow:0 2px 6px rgba(230,0,40,.3)">'
        '🌐 지점 포털 접속 (attend.laonfitness.com)</a>',
        unsafe_allow_html=True,
    )
    pc2.markdown(
        '<a href="http://192.168.0.237:8502/login" target="_blank" '
        'style="display:block;text-align:center;background:var(--sf2);color:var(--ink);'
        'border:1px solid var(--bd);border-radius:10px;font-weight:700;font-size:14px;'
        'padding:14px;text-decoration:none">'
        '🏠 내부망 접속 (192.168.0.237:8502)</a>',
        unsafe_allow_html=True,
    )
    st.divider()

    # ── 포털 문의 / 비밀번호 초기화 요청 ──────────────────────
    sec("포털 문의 · 비밀번호 초기화 요청")
    try:
        inq_rows = conn.execute(
            "SELECT id, type, name, phone, branch, message, created_at "
            "FROM portal_inquiries WHERE status='open' ORDER BY created_at DESC"
        ).fetchall()
        if not inq_rows:
            st.caption("📭 처리 대기 중인 문의가 없습니다.")
        else:
            st.markdown(
                f'<div class="al al-warn">⚠️&nbsp; 처리 대기 문의 <b>{len(inq_rows)}건</b> — '
                '비밀번호 초기화는 <b>인사/급여 → 직원 마스터 → 직원 계정 관리</b>에서 '
                'PW초기화 버튼으로 처리하세요.</div>',
                unsafe_allow_html=True,
            )
            _type_lbl = {"pw_reset": "🔑 비밀번호 초기화", "account": "📨 계정 문의", "etc": "💬 기타"}
            for iq in inq_rows:
                iq_id, iq_type, iq_name, iq_phone, iq_branch, iq_msg, iq_at = iq
                ic1, ic2 = st.columns([5, 1])
                ic1.markdown(
                    f"**{_type_lbl.get(iq_type, iq_type)}** · {iq_name} ({iq_phone}) "
                    f"· {iq_branch or '지점 미입력'}  \n"
                    f"<span style='font-size:12px;color:var(--ink3)'>{iq_msg or '—'} · {iq_at}</span>",
                    unsafe_allow_html=True,
                )
                if ic2.button("✅ 처리완료", key=f"inq_done_{iq_id}", use_container_width=True):
                    conn.execute(
                        "UPDATE portal_inquiries SET status='done', "
                        "resolved_at=datetime('now','localtime') WHERE id=?", (iq_id,)
                    )
                    conn.commit()
                    st.rerun()
    except Exception:
        st.caption("포털 문의 테이블이 아직 없습니다. 포털 서버 재시작 후 생성됩니다.")
    st.divider()

    sec("랜딩페이지 연동 보고")
    st.caption("지점 포털에서 직원이 제출한 AS·비품 요청과 오늘 출퇴근 현황을 실시간으로 확인합니다.")

    col1, col2, col3 = st.columns(3)

    # ── AS 요청 현황
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM as_requests WHERE status='open'"
        )
        open_as = cur.fetchone()[0]
        cur2 = conn.execute(
            "SELECT COUNT(*) FROM as_requests WHERE status='open' AND priority='urgent'"
        )
        urgent_as = cur2.fetchone()[0]
        col1.metric("🔧 처리 대기 AS", f"{open_as}건", f"긴급 {urgent_as}건" if urgent_as else "정상")
    except Exception:
        col1.metric("🔧 AS 요청", "—", "테이블 없음")

    # ── 비품 요청 현황
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM supply_requests WHERE status='pending'"
        )
        pend_supply = cur.fetchone()[0]
        col2.metric("📦 승인 대기 비품", f"{pend_supply}건")
    except Exception:
        col2.metric("📦 비품 요청", "—", "테이블 없음")

    # ── 오늘 출퇴근
    try:
        cur = conn.execute(
            "SELECT COUNT(DISTINCT employee_id) FROM attendance WHERE work_date=?", (today,)
        )
        att_cnt = cur.fetchone()[0]
        col3.metric("🕐 오늘 출근", f"{att_cnt}명", today)
    except Exception:
        col3.metric("🕐 오늘 출근", "—", "테이블 없음")

    st.divider()

    # ── AS 요청 목록
    sec("AS 요청 목록")
    branch_filter = st.selectbox("지점 필터", ["전체"] + get_active_branch_names(), key="rpt_br_as")
    status_filter = st.selectbox("상태", ["전체", "open", "in_progress", "resolved"], key="rpt_st_as")

    try:
        q = "SELECT * FROM as_requests WHERE 1=1"
        params: list = []
        if branch_filter != "전체":
            q += " AND branch=?"; params.append(branch_filter)
        if status_filter != "전체":
            q += " AND status=?"; params.append(status_filter)
        q += " ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, created_at DESC"
        cur = conn.execute(q, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        if rows:
            PRIO_LABEL = {"urgent": "🔴 긴급", "normal": "🟡 보통", "low": "🟢 낮음"}
            STATUS_LABEL = {"open": "접수", "in_progress": "처리중", "resolved": "완료"}
            df_as = pd.DataFrame([{
                "ID": r["id"], "지점": r["branch"],
                "제목": r["title"], "우선순위": PRIO_LABEL.get(r["priority"], r["priority"]),
                "상태": STATUS_LABEL.get(r["status"], r["status"]),
                "담당자": r.get("assigned_to", ""), "접수일": r["created_at"][:16],
            } for r in rows])
            st.dataframe(df_as, use_container_width=True, hide_index=True)

            # 빠른 상태 변경
            with st.expander("⚡ 상태 일괄 변경"):
                sel_id  = st.number_input("AS 요청 ID", min_value=1, step=1, key="as_chg_id")
                new_st  = st.selectbox("새 상태", ["in_progress", "resolved"], key="as_chg_st")
                assigned = st.text_input("담당자 (선택)", key="as_chg_who")
                note_txt = st.text_input("처리 메모", key="as_chg_note")
                if st.button("변경 저장", key="as_chg_btn", type="primary"):
                    conn2 = get_conn()
                    conn2.execute(
                        "UPDATE as_requests SET status=?, assigned_to=?, note=? WHERE id=?",
                        (new_st, assigned, note_txt, int(sel_id))
                    )
                    conn2.commit(); conn2.close()
                    st.success("✅ 상태 변경 완료"); st.rerun()
        else:
            st.info("조건에 맞는 AS 요청이 없습니다.")
    except Exception as e:
        st.warning(f"AS 요청 조회 실패: {e}")

    st.divider()

    # ── 비품 요청 목록
    sec("비품 구매 요청")
    try:
        q2 = "SELECT * FROM supply_requests WHERE 1=1"
        p2: list = []
        if branch_filter != "전체":
            q2 += " AND branch=?"; p2.append(branch_filter)
        q2 += " ORDER BY created_at DESC LIMIT 50"
        cur2 = conn.execute(q2, p2)
        cols2 = [d[0] for d in cur2.description]
        rows2 = [dict(zip(cols2, r)) for r in cur2.fetchall()]

        if rows2:
            ST2 = {"pending": "대기", "approved": "승인", "rejected": "반려", "delivered": "납품완료"}
            df_sup = pd.DataFrame([{
                "ID": r["id"], "지점": r["branch"], "품목": r["item_name"],
                "수량": f'{r["quantity"]}{r["unit"]}', "사유": r.get("reason", ""),
                "상태": ST2.get(r["status"], r["status"]),
                "요청일": r["created_at"][:16],
            } for r in rows2])
            st.dataframe(df_sup, use_container_width=True, hide_index=True)

            with st.expander("⚡ 승인 / 반려"):
                sup_id  = st.number_input("비품 요청 ID", min_value=1, step=1, key="sup_chg_id")
                sup_act = st.radio("처리", ["approved", "rejected", "delivered"], horizontal=True, key="sup_chg_act")
                sup_by  = st.text_input("처리자", key="sup_chg_by")
                rej_rsn = st.text_input("반려 사유 (반려 시)", key="sup_rej_rsn")
                if st.button("처리 저장", key="sup_chg_btn", type="primary"):
                    conn3 = get_conn()
                    conn3.execute(
                        "UPDATE supply_requests SET status=?, approved_by=?, reject_reason=? WHERE id=?",
                        (sup_act, sup_by, rej_rsn, int(sup_id))
                    )
                    conn3.commit(); conn3.close()
                    st.success("✅ 처리 완료"); st.rerun()
        else:
            st.info("비품 요청이 없습니다.")
    except Exception as e:
        st.warning(f"비품 요청 조회 실패: {e}")

    st.divider()

    # ── 오늘 출퇴근 현황
    sec(f"오늘 출퇴근 현황 ({today})")
    try:
        cur3 = conn.execute("""
            SELECT a.employee_id, e.name, e.branch,
                   a.clock_in, a.clock_out, a.work_hours, a.is_late
            FROM attendance a
            LEFT JOIN employees e ON a.employee_id = e.id
            WHERE a.work_date = ?
            ORDER BY e.branch, a.clock_in
        """, (today,))
        cols3 = [d[0] for d in cur3.description]
        rows3 = [dict(zip(cols3, r)) for r in cur3.fetchall()]

        if rows3:
            df_att = pd.DataFrame([{
                "이름": r.get("name", "—"), "지점": r.get("branch", ""),
                "출근": (r.get("clock_in") or "")[:5],
                "퇴근": (r.get("clock_out") or "근무중")[:5] if r.get("clock_out") else "근무중",
                "근무시간": f'{r.get("work_hours") or 0:.1f}h',
                "지각": "⚠️" if r.get("is_late") else "✅",
            } for r in rows3])
            st.dataframe(df_att, use_container_width=True, hide_index=True)
        else:
            st.info("오늘 출퇴근 기록이 없습니다.")
    except Exception as e:
        st.warning(f"출퇴근 현황 조회 실패: {e}")

    conn.close()

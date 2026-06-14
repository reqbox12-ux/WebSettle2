"""
domains/dashboard/ui.py — 전체 집계 대시보드 페이지
"""
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from shared.config import BRANCH_LIST
from shared.utils import fw, fn, sec, PLOT_BASE
from domains.dashboard.service import build_summary, build_trend, c_rev, c_exp


_now = datetime.now()


# ── KPI 카드 (전월 대비 델타 + 인건비 비율 포함) ────────────────
def render_kpi(df, prev_df=None):
    tot_rev  = df["총매출"].sum()
    card_rev = (df["카드공급가액"].fillna(0) + df["카드VAT"].fillna(0) + df["카드수수료"].fillna(0)).sum()
    cash_rev = (df["현금공급가액"].fillna(0) + df["현금VAT"].fillna(0) + df["수동입력매출"].fillna(0)).sum()
    tot_exp  = df["총지출"].sum()
    tot_pnl  = df["손익"].sum()
    rate     = round(tot_pnl / tot_rev * 100, 1) if tot_rev else 0
    labor    = df["인건비합계"].fillna(0).sum()
    labor_rt = round(labor / tot_rev * 100, 1) if tot_rev else 0
    pc       = (df["손익"] > 0).sum()
    tc       = len(df[df["총매출"] > 0])
    sign_pnl = "▲" if tot_pnl >= 0 else "▼"
    sign_rt  = "+" if rate >= 0 else ""

    def _d_amt(curr, prev_val):
        if prev_val is None:
            return ""
        diff = curr - prev_val
        if diff == 0:
            return '<div style="font-size:10px;color:#9A918C;margin-top:2px">전월 동일</div>'
        pct   = round(diff / abs(prev_val) * 100, 1) if prev_val else 0
        arrow = "▲" if diff >= 0 else "▼"
        color = "#2E7D5B" if diff >= 0 else "#E60028"
        sign  = "+" if diff >= 0 else ""
        return (
            f'<div style="font-size:10.5px;color:{color};margin-top:2px">'
            f'{arrow} {fw(abs(int(diff)))} ({sign}{pct}%)'
            f'<span style="color:#9A918C;font-size:9.5px"> 전월比</span></div>'
        )

    def _d_pct(curr, prev_val):
        if prev_val is None:
            return ""
        diff  = round(curr - prev_val, 1)
        if diff == 0:
            return '<div style="font-size:10px;color:#9A918C;margin-top:2px">전월 동일</div>'
        arrow = "▲" if diff >= 0 else "▼"
        color = "#2E7D5B" if diff >= 0 else "#E60028"
        sign  = "+" if diff >= 0 else ""
        return (
            f'<div style="font-size:10.5px;color:{color};margin-top:2px">'
            f'{arrow} {sign}{diff}%p'
            f'<span style="color:#9A918C;font-size:9.5px"> 전월比</span></div>'
        )

    if prev_df is not None and not prev_df.empty:
        p_tot_rev  = prev_df["총매출"].sum()
        p_card_rev = (prev_df["카드공급가액"].fillna(0) + prev_df["카드VAT"].fillna(0) + prev_df["카드수수료"].fillna(0)).sum()
        p_cash_rev = (prev_df["현금공급가액"].fillna(0) + prev_df["현금VAT"].fillna(0) + prev_df["수동입력매출"].fillna(0)).sum()
        p_tot_exp  = prev_df["총지출"].sum()
        p_tot_pnl  = prev_df["손익"].sum()
        p_rate     = round(p_tot_pnl / p_tot_rev * 100, 1) if p_tot_rev else 0
        p_labor    = prev_df["인건비합계"].fillna(0).sum()
        p_labor_rt = round(p_labor / p_tot_rev * 100, 1) if p_tot_rev else 0
    else:
        p_card_rev = p_cash_rev = p_tot_exp = p_tot_pnl = p_rate = p_labor_rt = None

    cards = [
        ("카드 매출",   fw(card_rev),                     "원", "공급가액+VAT+수수료",            "c-ink", _d_amt(card_rev, p_card_rev)),
        ("현금 매출",   fw(cash_rev),                     "원", "공급가액+VAT+직접입력 (총입금)",  "c-ink", _d_amt(cash_rev, p_cash_rev)),
        ("총 지출",     fw(tot_exp),                      "원", "인건비+기타+부가세+수수료",        "c-red", _d_amt(tot_exp,  p_tot_exp)),
        ("순 손익",     f"{sign_pnl} {fw(abs(tot_pnl))}", "원", "총매출 – 총지출",
         "c-pos" if tot_pnl >= 0 else "c-red", _d_amt(tot_pnl, p_tot_pnl)),
        ("이익률",      f"{sign_rt}{rate}",               "%",  f"손익÷총매출 · 흑자 {pc} / {tc} 지점",
         "c-pos" if rate >= 0 else "c-red", _d_pct(rate, p_rate)),
        ("인건비 비율", f"{labor_rt}",                    "%",  "인건비합계 ÷ 총매출",
         "c-pos" if labor_rt <= 50 else "c-red", _d_pct(labor_rt, p_labor_rt)),
    ]
    html = '<div class="kpi-grid">'
    for lbl, val, unit, sub, cls, delta_html in cards:
        html += (
            f'<div class="kpi"><div class="kpi-lbl">{lbl}</div>'
            f'<div class="kpi-val {cls}">{val}<span class="kpi-unit">{unit}</span></div>'
            f'<div class="kpi-sub">{sub}</div>'
            f'{delta_html}</div>'
        )
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


# ── 막대 + 손익 차트 ─────────────────────────────────────────
def render_chart(df, key="ch"):
    dc = df[df["총매출"] > 0].sort_values("총매출", ascending=False)
    if dc.empty:
        st.info("차트 데이터가 없습니다.")
        return
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="총매출", x=dc.branch, y=dc.총매출,
        marker_color="#3D3835", opacity=0.85,
        text=dc.총매출.apply(fw), textposition="outside",
        textfont=dict(size=10, color="#1F1B1B", family="Pretendard Variable,sans-serif"),
    ))
    fig.add_trace(go.Bar(
        name="총지출", x=dc.branch, y=dc.총지출,
        marker_color="#E60028", opacity=0.75,
    ))
    fig.add_trace(go.Scatter(
        name="손익", x=dc.branch, y=dc.손익,
        mode="lines+markers", yaxis="y2",
        line=dict(color="#2E7D5B", width=2.5),
        marker=dict(
            size=7,
            color=["#2E7D5B" if v >= 0 else "#E60028" for v in dc.손익],
            line=dict(width=2, color="white"),
        ),
    ))
    _tf = dict(size=11, color="#1F1B1B", family="Pretendard Variable,sans-serif")
    fig.update_layout(**{
        **PLOT_BASE, "barmode": "group", "height": 380,
        "yaxis":  dict(tickformat=",", gridcolor="rgba(31,27,27,.08)", zeroline=False, tickfont=_tf, color="#1F1B1B"),
        "yaxis2": dict(overlaying="y", side="right", tickformat=",", zeroline=True,
                       zerolinecolor="rgba(31,27,27,.2)", tickfont=_tf, color="#1F1B1B"),
        "xaxis":  dict(tickangle=-30, tickfont=_tf, color="#1F1B1B"),
        "margin": dict(t=16, b=70, l=10, r=10),
    })
    st.plotly_chart(fig, use_container_width=True, key=key,
                    config={"staticPlot": True, "displayModeBar": False})


# ── 지출 구성 도넛 차트 ───────────────────────────────────────
def render_donut_chart(df, key="donut"):
    labor = df["인건비합계"].fillna(0).sum()
    other = df["기타지출"].fillna(0).sum()
    vat   = df["부가세합계"].fillna(0).sum()
    fee   = df["카드수수료"].fillna(0).sum()
    total = labor + other + vat + fee
    if total <= 0:
        st.info("지출 데이터가 없습니다.")
        return
    labels = ["인건비", "기타지출", "부가세", "카드수수료"]
    values = [labor, other, vat, fee]
    colors = ["#4A6FA5", "#C8A87E", "#E8C96B", "#E60028"]
    _tf = dict(size=11.5, color="#1F1B1B", family="Pretendard Variable,sans-serif")
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.55,
        marker=dict(colors=colors, line=dict(color="white", width=2.5)),
        textinfo="label+percent",
        textposition="outside",
        textfont=_tf,
        hovertemplate="%{label}: %{value:,.0f}원 (%{percent})<extra></extra>",
    ))
    fig.update_layout(**{
        **PLOT_BASE, "height": 310, "showlegend": False,
        "margin": dict(t=10, b=10, l=10, r=10),
        "annotations": [dict(
            text=f"<b>{fw(int(total))}</b><br>총지출",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=12, family="Pretendard Variable,sans-serif", color="#1F1B1B"),
        )],
    })
    st.plotly_chart(fig, use_container_width=True, key=key,
                    config={"staticPlot": True, "displayModeBar": False})


# ── 연간 추이 꺾은선 차트 ─────────────────────────────────────
def render_trend_chart(year, month, sel_branches, key="trend"):
    trend_raw = build_trend(year, month)
    if trend_raw.empty:
        st.info("추이 데이터가 없습니다.")
        return
    flt = trend_raw[trend_raw.branch.isin(sel_branches)]
    if flt.empty:
        st.info("추이 데이터가 없습니다.")
        return
    monthly = (
        flt.groupby("month")
        .agg(총매출=("총매출", "sum"), 손익=("손익", "sum"))
        .reset_index()
    )
    xlabels = [f"{m}월" for m in monthly.month]
    _tf = dict(size=11, color="#1F1B1B", family="Pretendard Variable,sans-serif")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        name="총매출", x=xlabels, y=monthly.총매출,
        mode="lines+markers",
        line=dict(color="#3D3835", width=2.5),
        marker=dict(size=7, color="#3D3835", line=dict(width=2, color="white")),
        hovertemplate="%{x}: %{y:,.0f}원<extra>총매출</extra>",
    ))
    fig.add_trace(go.Scatter(
        name="손익", x=xlabels, y=monthly.손익,
        mode="lines+markers",
        line=dict(color="#2E7D5B", width=2),
        marker=dict(
            size=7,
            color=["#2E7D5B" if v >= 0 else "#E60028" for v in monthly.손익],
            line=dict(width=2, color="white"),
        ),
        hovertemplate="%{x}: %{y:,.0f}원<extra>손익</extra>",
    ))
    fig.update_layout(**{
        **PLOT_BASE, "height": 310,
        "yaxis": dict(tickformat=",", gridcolor="rgba(31,27,27,.08)", zeroline=True,
                      zerolinecolor="rgba(31,27,27,.2)", tickfont=_tf, color="#1F1B1B"),
        "xaxis": dict(tickfont=_tf, color="#1F1B1B"),
        "margin": dict(t=16, b=40, l=10, r=10),
        "legend": dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                       font=dict(size=11, family="Pretendard Variable,sans-serif")),
    })
    st.plotly_chart(fig, use_container_width=True, key=key,
                    config={"staticPlot": True, "displayModeBar": False})


# ── 손익 순위 카드 ────────────────────────────────────────────
def render_rank_cards(df):
    active  = df[df["총매출"] > 0].sort_values("손익", ascending=False)
    if active.empty:
        st.info("데이터 없음")
        return
    top3    = active.head(3)
    bottom3 = active.tail(3).sort_values("손익")

    def card_row(row, rank, is_top):
        pnl  = int(row["손익"])
        rate = row["이익률"]
        sign = "▲" if pnl >= 0 else "▼"
        pnl_col  = "var(--pos)" if is_top else "var(--red)"
        bg       = "var(--poss)" if is_top else "var(--reds)"
        rate_col = "var(--pos)" if is_top else "var(--red)"
        return (
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'padding:10px 14px;border-radius:var(--rs);background:{bg};margin-bottom:6px">'
            f'<div style="display:flex;align-items:center;gap:10px">'
            f'<span style="font-size:12px;font-weight:800;color:{pnl_col};width:18px;text-align:center">{rank}</span>'
            f'<span style="font-size:13px;font-weight:600;color:var(--ink)">{row["branch"]}</span>'
            f'</div><div style="text-align:right">'
            f'<div style="font-size:13px;font-weight:700;color:{pnl_col}">{sign} {fw(abs(pnl))}</div>'
            f'<div style="font-size:11px;font-weight:600;color:{rate_col}">{rate:.1f}%</div>'
            f'</div></div>'
        )

    html = '<div style="display:flex;flex-direction:column;gap:16px">'
    html += '<div><div style="font-size:10px;font-weight:700;color:var(--pos);letter-spacing:.07em;text-transform:uppercase;margin-bottom:8px">🏆 흑자 TOP 3</div>'
    for i, (_, row) in enumerate(top3.iterrows()):
        html += card_row(row, i + 1, True)
    html += '</div>'
    html += '<div><div style="font-size:10px;font-weight:700;color:var(--red);letter-spacing:.07em;text-transform:uppercase;margin-bottom:8px">⚠️ 적자 BOTTOM 3</div>'
    for i, (_, row) in enumerate(bottom3.iterrows()):
        html += card_row(row, i + 1, False)
    html += '</div></div>'
    st.markdown(html, unsafe_allow_html=True)


# ── 대시보드 페이지 메인 ─────────────────────────────────────
def render_page():
    year  = st.session_state.get("year", _now.year)
    month = st.session_state.get("month", _now.month)

    st.markdown(
        '<div class="ph"><div class="ph-title">대시보드</div>'
        '<div class="ph-sub">연도 · 월 · 지점을 선택하면 데이터가 필터링됩니다</div></div>',
        unsafe_allow_html=True,
    )

    # ── 필터 ─────────────────────────────────────────────────
    st.markdown('<div class="filter-wrap">', unsafe_allow_html=True)
    fc1, fc2 = st.columns([1, 1])
    yrs   = list(range(_now.year, _now.year - 3, -1))
    year  = fc1.selectbox("연도", yrs, index=yrs.index(year) if year in yrs else 0, key="f_yr")
    month = fc2.selectbox("월", list(range(1, 13)), index=month - 1, key="f_mn",
                           format_func=lambda m: f"{m}월")
    st.session_state.year  = year
    st.session_state.month = month

    # 지점 멀티셀렉 (체크박스 그리드)
    prev_was_all = st.session_state.get("_f_br_all_prev", True)
    chk_all = st.checkbox("전체 지점", value=True, key="f_br_all")
    st.session_state["_f_br_all_prev"] = chk_all

    if chk_all:
        sel_branches = BRANCH_LIST[:]
        # 전체→개별 전환 준비: 버전 리셋 + 캐시 초기화
        st.session_state["_br_grid_ver"] = 0
        st.session_state["_sel_br_cache"] = []
    else:
        # 전체(True) → 개별(False) 전환 시 버전 올림 → 위젯 키가 바뀌어 모두 미선택으로 초기화
        if prev_was_all:
            st.session_state["_br_grid_ver"]  = st.session_state.get("_br_grid_ver", 0) + 1
            st.session_state["_sel_br_cache"] = []
        ver      = st.session_state.get("_br_grid_ver", 0)
        prev_sel = st.session_state.get("_sel_br_cache", [])
        n_col    = 5
        n_rows_g = (len(BRANCH_LIST) + n_col - 1) // n_col
        grid     = [st.columns(n_col) for _ in range(n_rows_g)]
        flat     = [c for row in grid for c in row]
        sel_branches = [
            br for br, col in zip(BRANCH_LIST, flat)
            if col.checkbox(br, value=(br in prev_sel), key=f"f_br_{br}_v{ver}")
        ]
        st.session_state["_sel_br_cache"] = sel_branches
        if not sel_branches:
            st.caption("⚠️ 지점을 하나 이상 선택하세요.")
    st.session_state["_sel_br_cache"] = sel_branches
    # 하위 호환 (branch/ui.py 등에서 sel_br 참조)
    st.session_state.sel_br = sel_branches[0] if len(sel_branches) == 1 else "전체"
    st.markdown('</div>', unsafe_allow_html=True)

    if not sel_branches:
        st.markdown('</div>', unsafe_allow_html=True)
        st.info("📌 지점을 하나 이상 선택하세요.")
        return

    # ── 데이터 로드 ───────────────────────────────────────────
    with st.spinner("데이터 로드 중..."):
        full_df = build_summary(year, month)

    prev_year  = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    prev_full  = build_summary(prev_year, prev_month)

    # 전년 동월
    yoy_full = build_summary(year - 1, month)

    view_df = full_df[full_df.branch.isin(sel_branches)].copy() if not full_df.empty else full_df.copy()
    prev_df = prev_full[prev_full.branch.isin(sel_branches)].copy() if not prev_full.empty else pd.DataFrame()
    yoy_df  = yoy_full[yoy_full.branch.isin(sel_branches)].copy() if not yoy_full.empty else pd.DataFrame()

    # ── KPI ──────────────────────────────────────────────────
    render_kpi(view_df, prev_df if not prev_df.empty else None)

    # ── 전년 동월 비교 ────────────────────────────────────────
    if not yoy_df.empty:
        cur_rev = int(view_df["총매출"].sum()) if not view_df.empty else 0
        yoy_rev = int(yoy_df["총매출"].sum())
        cur_pnl = int(view_df["손익"].sum()) if not view_df.empty else 0
        yoy_pnl = int(yoy_df["손익"].sum())
        diff_rev = cur_rev - yoy_rev
        diff_pnl = cur_pnl - yoy_pnl
        rev_sign = "▲" if diff_rev >= 0 else "▼"
        pnl_sign = "▲" if diff_pnl >= 0 else "▼"
        rev_col  = "var(--pos)" if diff_rev >= 0 else "var(--red)"
        pnl_col  = "var(--pos)" if diff_pnl >= 0 else "var(--red)"
        st.markdown(
            f'<div class="al al-info" style="display:flex;gap:32px;flex-wrap:wrap">'
            f'<span>📅 <b>전년 동월 비교</b> ({year-1}년 {month}월 대비)</span>'
            f'<span>총매출 <b style="color:{rev_col}">{rev_sign} {abs(diff_rev):,}원</b> '
            f'({"+{:,}".format(diff_rev) if diff_rev>=0 else "{:,}".format(diff_rev)}원)</span>'
            f'<span>손익 <b style="color:{pnl_col}">{pnl_sign} {abs(diff_pnl):,}원</b> '
            f'({"+{:,}".format(diff_pnl) if diff_pnl>=0 else "{:,}".format(diff_pnl)}원)</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── 테이블 섹션 ───────────────────────────────────────────
    br_label = "전체 지점" if len(sel_branches) == len(BRANCH_LIST) else f"선택 {len(sel_branches)}개 지점"
    sec(f"{year}년 {month}월 · {br_label}")
    view_mode = st.radio("보기 방식", ["요약", "상세"], horizontal=True, key="tbl_mode")

    if view_mode == "상세":
        detail_cols = {
            "branch": "지점", "카드공급가액": "카드공급가액", "카드수수료": "카드수수료",
            "카드VAT": "카드VAT", "카드실수령": "카드실수령", "현금공급가액": "현금공급가액",
            "현금VAT": "현금VAT", "수동입력매출": "직접입력매출", "총매출": "총매출", "급여": "급여",
            "4대보험료_직원": "4대보험(직원)", "4대보험_본사": "4대보험(본사)",
            "소득세지방세": "소득세·지방세", "프리랜서": "프리랜서", "프리랜서세금": "프리랜서세금",
            "인건비합계": "인건비합계", "기타지출": "기타지출", "부가세합계": "부가세합계",
            "총지출": "총지출", "손익": "손익", "이익률": "이익률(%)",
        }
        disp = view_df[[c for c in detail_cols if c in view_df.columns]].copy()
        disp = disp.rename(columns=detail_cols)

        def _color_pnl(val):
            try:
                v = float(str(val).replace(",", ""))
                if v > 0:
                    return "color:#2E7D5B;font-weight:700"
                if v < 0:
                    return "color:#E60028;font-weight:700"
            except Exception:
                pass
            return ""

        int_cols_det = [c for c in disp.columns if c not in ("지점", "이익률(%)")]
        for c in int_cols_det:
            disp[c] = disp[c].apply(lambda v: f"{int(v):,}" if pd.notna(v) else "0")
        disp["이익률(%)"] = disp["이익률(%)"].apply(lambda v: f"{float(v):.1f}%" if pd.notna(v) else "0%")

        st.dataframe(
            disp.style
            .map(_color_pnl, subset=["손익"])
            .set_properties(**{"text-align": "right"}, subset=int_cols_det)
            .set_properties(**{"font-weight": "700", "text-align": "left"}, subset=["지점"]),
            use_container_width=True, hide_index=True, height=600,
        )
    else:
        table_html = (
            '<div class="bt"><table>'
            '<thead><tr>'
            '<th style="text-align:left">지점</th>'
            '<th>카드매출</th><th>현금매출</th><th>총지출</th><th>손익 / 이익률</th>'
            '</tr></thead><tbody>'
        )
        for _, row in view_df.iterrows():
            pnl      = int(row["손익"])
            rt       = row["이익률"]
            sign     = "▲" if pnl >= 0 else "▼"
            bdg_cls  = "bdg-pos" if pnl >= 0 else "bdg-neg"
            rate_col = "color:var(--pos)" if rt >= 0 else "color:var(--red)"
            rate_sign = "+" if rt >= 0 else ""
            sel_cls  = "sel" if st.session_state.get("drill") == row.branch else ""
            card_tot = int(row.get("카드공급가액", 0) + row.get("카드VAT", 0) + row.get("카드수수료", 0))
            cash_tot = int(row.get("현금공급가액", 0) + row.get("현금VAT", 0) + row.get("수동입력매출", 0))
            table_html += (
                f'<tr class="{sel_cls}">'
                f'<td>{row.branch}</td>'
                f'<td>{fw(card_tot)}</td>'
                f'<td>{fw(cash_tot)}</td>'
                f'<td>{fw(row["총지출"])}</td>'
                f'<td style="text-align:center">'
                f'<span class="bdg {bdg_cls}">{sign} {fw(abs(pnl))}</span>'
                f'&nbsp;<span style="font-size:11.5px;{rate_col}">'
                f'{rate_sign}{rt}%</span></td>'
                f'</tr>'
            )
        table_html += '</tbody></table></div>'
        st.markdown(table_html, unsafe_allow_html=True)

    # ── Excel 내보내기 ────────────────────────────────────────
    try:
        import io
        xl_buf = io.BytesIO()
        # 전체 상세 데이터 준비
        export_cols = {
            "branch": "지점", "카드공급가액": "카드공급가액", "카드수수료": "카드수수료",
            "카드실수령": "카드실수령", "현금공급가액": "현금공급가액", "현금VAT": "현금VAT",
            "총매출": "총매출", "인건비합계": "인건비합계", "기타지출": "기타지출",
            "부가세합계": "부가세합계", "총지출": "총지출", "손익": "손익", "이익률": "이익률(%)",
        }
        xl_df = view_df[[c for c in export_cols if c in view_df.columns]].copy()
        xl_df = xl_df.rename(columns=export_cols)
        with pd.ExcelWriter(xl_buf, engine="openpyxl") as writer:
            xl_df.to_excel(writer, sheet_name=f"{year}년{month:02d}월", index=False)
        xl_buf.seek(0)
        st.download_button(
            label="📥 Excel 내보내기",
            data=xl_buf.getvalue(),
            file_name=f"손익현황_{year}년{month:02d}월.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_summary_xl",
        )
    except Exception:
        pass

    # ── 차트: 매출·지출 비교 + 손익 순위 ────────────────────────
    sec("지점별 매출 · 지출 · 손익")
    col_ch1, col_ch2 = st.columns([3, 2])
    with col_ch1:
        st.markdown(
            '<div class="ch"><div class="ch-t">매출 · 지출 비교</div>'
            '<div class="ch-s">막대: 매출/지출 &nbsp;|&nbsp; 선: 손익 (우축)</div>',
            unsafe_allow_html=True,
        )
        render_chart(view_df, key="ch_main")
        st.markdown('</div>', unsafe_allow_html=True)
    with col_ch2:
        st.markdown(
            '<div class="ch"><div class="ch-t">손익 순위</div>'
            '<div class="ch-s">흑자 TOP3 · 적자 BOTTOM3</div>',
            unsafe_allow_html=True,
        )
        render_rank_cards(view_df)
        st.markdown('</div>', unsafe_allow_html=True)

    # ── 차트: 지출 구성 도넛 + 연간 추이 ─────────────────────────
    sec("비용 구성 · 연간 추이")
    col_d, col_t = st.columns([2, 3])
    with col_d:
        st.markdown(
            '<div class="ch"><div class="ch-t">지출 구성</div>'
            '<div class="ch-s">인건비 · 기타 · 부가세 · 카드수수료</div>',
            unsafe_allow_html=True,
        )
        render_donut_chart(view_df, key="donut_main")
        st.markdown('</div>', unsafe_allow_html=True)
    with col_t:
        st.markdown(
            f'<div class="ch"><div class="ch-t">연간 추이</div>'
            f'<div class="ch-s">{year}년 1월 ~ {month}월 · 총매출 · 손익</div>',
            unsafe_allow_html=True,
        )
        render_trend_chart(year, month, sel_branches, key="trend_main")
        st.markdown('</div>', unsafe_allow_html=True)

"""
domains/attendance_erp/ui.py — ERP 출퇴근 현황 조회
직원들의 출퇴근 기록을 ERP에서 월별/지점별로 확인합니다.
"""
from datetime import datetime
import streamlit as st
import pandas as pd

from shared.utils import sec
from modules.db import get_conn

_now = datetime.now()


def _get_attendance_summary(year: int, month: int, branch: str = None) -> pd.DataFrame:
    """월별 출퇴근 요약 조회"""
    conn = get_conn()
    if not conn:
        return pd.DataFrame()

    year_str  = str(year)
    month_str = f"{month:02d}"
    prefix    = f"{year_str}-{month_str}"

    query = """
        SELECT
            e.name AS 이름,
            e.branch AS 지점,
            a.work_date AS 날짜,
            a.clock_in AS 출근,
            a.clock_out AS 퇴근,
            a.work_minutes AS 근무분,
            a.break_minutes AS 휴게분,
            a.status AS 상태,
            a.note AS 비고
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        WHERE a.work_date LIKE ?
    """
    params = [f"{prefix}%"]

    if branch and branch != "전체":
        query += " AND e.branch = ?"
        params.append(branch)

    query += " ORDER BY a.work_date DESC, e.branch, e.name"

    try:
        df = pd.read_sql_query(query, conn, params=params)
    except Exception as e:
        st.error(f"데이터 조회 오류: {e}")
        return pd.DataFrame()

    if df.empty:
        return df

    # 근무시간 계산 (분 → 시간:분)
    def _fmt_min(m):
        try:
            m = int(m)
            return f"{m // 60}h {m % 60:02d}m" if m > 0 else "-"
        except Exception:
            return "-"

    df["근무시간"] = df["근무분"].apply(_fmt_min)
    df["휴게시간"] = df["휴게분"].apply(_fmt_min)

    # 상태 표시
    status_map = {
        "present": "✅ 정상",
        "late":    "⏰ 지각",
        "absent":  "❌ 결근",
        "half":    "🕐 반차",
    }
    df["상태"] = df["상태"].map(lambda s: status_map.get(s, s or "―"))

    return df


def _get_monthly_stats(year: int, month: int, branch: str = None) -> dict:
    """월간 통계"""
    conn = get_conn()
    if not conn:
        return {}

    prefix = f"{year}-{month:02d}"

    query = """
        SELECT
            COUNT(DISTINCT e.id) AS 출근직원수,
            COUNT(a.id) AS 총출근일수,
            AVG(a.work_minutes) AS 평균근무분,
            COUNT(CASE WHEN a.status='absent' THEN 1 END) AS 결근수,
            COUNT(CASE WHEN a.status='late'   THEN 1 END) AS 지각수
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        WHERE a.work_date LIKE ?
    """
    params = [f"{prefix}%"]
    if branch and branch != "전체":
        query += " AND e.branch = ?"
        params.append(branch)

    try:
        row = conn.execute(query, params).fetchone()
        if row:
            return {
                "출근직원수": row[0] or 0,
                "총출근일수": row[1] or 0,
                "평균근무시간": f"{int((row[2] or 0)) // 60}h {int((row[2] or 0)) % 60:02d}m",
                "결근수": row[3] or 0,
                "지각수": row[4] or 0,
            }
    except Exception:
        pass
    return {}


def _get_branch_list() -> list:
    """DB에서 지점 목록 조회"""
    conn = get_conn()
    if not conn:
        return []
    try:
        rows = conn.execute("SELECT DISTINCT branch FROM employees WHERE branch IS NOT NULL ORDER BY branch").fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def render_page():
    st.markdown(
        '<div class="ph"><div class="ph-title">출퇴근 현황</div>'
        '<div class="ph-sub">직원 출퇴근 기록을 월별·지점별로 조회합니다</div></div>',
        unsafe_allow_html=True,
    )

    # ── 필터 ─────────────────────────────────────────────────
    st.markdown('<div class="filter-wrap">', unsafe_allow_html=True)
    fc1, fc2, fc3 = st.columns([1, 1, 2])

    yrs   = list(range(_now.year, _now.year - 3, -1))
    year  = fc1.selectbox("연도", yrs, key="att_yr",
                           index=yrs.index(st.session_state.get("year", _now.year))
                                 if st.session_state.get("year", _now.year) in yrs else 0)
    month = fc2.selectbox("월", list(range(1, 13)), index=_now.month - 1, key="att_mn",
                           format_func=lambda m: f"{m}월")

    branch_list = ["전체"] + _get_branch_list()
    branch = fc3.selectbox("지점", branch_list, key="att_br")
    st.markdown('</div>', unsafe_allow_html=True)

    # ── 월간 통계 KPI ─────────────────────────────────────────
    stats = _get_monthly_stats(year, month, branch if branch != "전체" else None)

    if stats:
        sec(f"{year}년 {month}월 · {'전체 지점' if branch == '전체' else branch} 요약")
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("출근 직원 수",   f"{stats['출근직원수']}명")
        k2.metric("총 출근 일수",   f"{stats['총출근일수']}일")
        k3.metric("평균 근무시간",  stats["평균근무시간"])
        k4.metric("결근",          f"{stats['결근수']}건",
                   delta=f"-{stats['결근수']}" if stats["결근수"] > 0 else None,
                   delta_color="inverse")
        k5.metric("지각",          f"{stats['지각수']}건",
                   delta=f"-{stats['지각수']}" if stats["지각수"] > 0 else None,
                   delta_color="inverse")
    else:
        st.info(f"📭 {year}년 {month}월 출퇴근 데이터가 없습니다.")

    # ── 상세 테이블 ───────────────────────────────────────────
    sec("출퇴근 상세 내역")

    df = _get_attendance_summary(year, month, branch if branch != "전체" else None)

    if df.empty:
        st.info("📭 해당 기간에 출퇴근 기록이 없습니다.")
        return

    # 표시 컬럼 선택
    disp_cols = ["날짜", "지점", "이름", "출근", "퇴근", "근무시간", "휴게시간", "상태", "비고"]
    disp_cols = [c for c in disp_cols if c in df.columns]
    df_disp   = df[disp_cols].copy()

    # 비고 빈값 처리
    if "비고" in df_disp.columns:
        df_disp["비고"] = df_disp["비고"].fillna("").replace("None", "")

    st.dataframe(
        df_disp,
        use_container_width=True,
        hide_index=True,
        column_config={
            "날짜": st.column_config.TextColumn("날짜", width="small"),
            "지점": st.column_config.TextColumn("지점", width="small"),
            "이름": st.column_config.TextColumn("이름", width="small"),
            "출근": st.column_config.TextColumn("출근", width="small"),
            "퇴근": st.column_config.TextColumn("퇴근", width="small"),
            "근무시간": st.column_config.TextColumn("근무시간", width="small"),
            "휴게시간": st.column_config.TextColumn("휴게시간", width="small"),
            "상태": st.column_config.TextColumn("상태", width="small"),
        },
    )

    st.caption(f"총 {len(df_disp)}건")

    # ── Excel 다운로드 ────────────────────────────────────────
    try:
        import io
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_disp.to_excel(writer, sheet_name="출퇴근현황", index=False)
        buf.seek(0)
        fn = f"출퇴근현황_{year}년{month:02d}월_{branch}.xlsx"
        st.download_button(
            "📥 Excel 다운로드",
            data=buf.getvalue(),
            file_name=fn,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="att_dl",
        )
    except Exception as e:
        st.caption(f"다운로드 준비 중 오류: {e}")

"""
domains/branch_app/testmode.py
테스트 모드: 가상 '오늘' 날짜 오버라이드 + 테스트 데이터 격리(is_test).
- 모든 날짜 판단은 today_str()/today_dt() 를 거치게 한다.
- 테스트 모드가 켜져 있으면 설정된 가상 날짜를 반환.
"""
from datetime import datetime, date
from shared.db import get_conn


def _get(k: str, default: str = "") -> str:
    try:
        conn = get_conn()
        row = conn.execute("SELECT v FROM app_state WHERE k=?", (k,)).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def _set(k: str, v: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO app_state (k, v) VALUES (?,?)", (k, str(v)))
    conn.commit()
    conn.close()


# ── 테스트 모드 상태 ──────────────────────────────────────────
def is_test_mode() -> bool:
    return _get("test_mode", "0") == "1"


def virtual_date() -> str:
    """테스트모드면 가상 날짜, 아니면 빈 문자열."""
    if is_test_mode():
        return _get("virtual_date", "")
    return ""


def set_test_mode(on: bool, vdate: str = ""):
    _set("test_mode", "1" if on else "0")
    if vdate:
        _set("virtual_date", vdate)


def get_test_state() -> dict:
    return {
        "test_mode": is_test_mode(),
        "virtual_date": _get("virtual_date", ""),
        "real_today": date.today().isoformat(),
    }


# ── 현재 날짜 (오버라이드 적용) ───────────────────────────────
def today_str() -> str:
    v = virtual_date()
    if v:
        return v
    return date.today().isoformat()


def today_dt() -> datetime:
    """가상 날짜면 그 날 현재시각, 아니면 진짜 now."""
    v = virtual_date()
    if v:
        try:
            y, m, d = map(int, v.split("-"))
            now = datetime.now()
            return datetime(y, m, d, now.hour, now.minute, now.second)
        except Exception:
            pass
    return datetime.now()


def is_test_flag() -> int:
    """현재 생성하는 데이터에 붙일 is_test 값."""
    return 1 if is_test_mode() else 0


# ── 테스트 데이터 정리 ────────────────────────────────────────
def purge_test_data() -> dict:
    """is_test=1 인 모든 데이터 삭제 (운영 복구)."""
    conn = get_conn()
    counts = {}
    for tbl in ("sales", "payment_orders", "gx_enrollments", "gx_applications",
                "lesson_enrollments", "gx_sessions", "gx_class_status", "refunds"):
        try:
            cur = conn.execute(f"DELETE FROM {tbl} WHERE is_test=1")
            counts[tbl] = cur.rowcount
        except Exception:
            pass
    conn.commit()
    conn.close()
    return counts
